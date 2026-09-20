/* host_shim.cpp — Force/MockbaMod runtime host for the ported Acid generator.
 *
 * Plays the exact role the Schwung MIDI-FX chain host played for acid.c:
 *
 *   Schwung host                         this shim
 *   ------------------------------------ ----------------------------------------
 *   loads dsp.so, calls move_midi_fx_init  links acid_core.o, calls it directly
 *   process_midi() per incoming event    RtMidi input callback -> process_midi()
 *   tick(frames, sr) per audio block     wall-clock timer thread -> tick()
 *   set_param(key, "0.42") from knobs    CC on the control channel -> set_param()
 *   host->get_bpm()                      estimated from incoming 0xF8 clock
 *   host->get_clock_status()             transport state (0xFA/0xFC) + clock life
 *   one hard-wired output channel        a_channel/b_channel, set IN THE CORE now
 *
 * acid_core.c is verbatim from schwung-acid except for one small, clearly
 * marked (grep FORCE-ONLY) addition: independent a_channel/b_channel per
 * sequencer, since this shim -- unlike Move's chain host -- doesn't force
 * everything onto one channel. The shim no longer rewrites the channel
 * nibble on the way out (see send_out()) -- the core stamps the final
 * channel on every message it emits now.
 *
 * Build: see scripts/build.sh (native armhf under QEMU, links -lasound -lpthread).
 */

#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include "rtmidi/RtMidi.h"

extern "C" {
#include "acid_core.h"
}

/* ---------------------------------------------------------------------------
 * chain_param table — transcribed from schwung-acid/src/acid/module.json.
 * Keep in sync by hand; DESIGN.md explains why it is not read from JSON here.
 * kind: 'f' float, 'i' int, 'e' enum (value is option index), 'w' write-only
 *       momentary trigger (generate / mutate).
 * ------------------------------------------------------------------------- */
struct ParamSpec {
    const char *key;
    char        kind;
    double      lo, hi;   /* for f/i: value range. for e: 0 .. (n_options-1). */
    int         default_cc;
};

static const ParamSpec PARAMS[] = {
    /* key            kind   lo     hi     CC  */
    { "a_generate",   'w',   0,     1,     20 },
    { "a_mutate",     'w',   0,     1,     21 },
    { "a_density",    'f',   0.0,   1.0,   22 },
    { "a_accent",     'f',   0.0,   1.0,   23 },
    { "a_slide",      'f',   0.0,   1.0,   24 },
    { "a_octaves",    'i',   1,     3,     25 },
    { "a_length",     'f',   2,     32,    26 },
    { "a_gate",       'f',   0.05,  1.0,   27 },
    { "a_channel",    'i',   1,     16,    28 },   /* FORCE-ONLY: no Move equivalent */
    { "a_offset",     'f',   0,     31,    29 },
    { "a_dir",        'e',   0,     2,     30 },   /* 3 options: Fwd/Rev/Pendulum */
    { "a_auto_gen",   'e',   0,     6,     31 },   /* FORCE-ONLY: 7 options, Off + 6 bar counts */
    { "a_dump",       'w',   0,     1,     32 },   /* FORCE-ONLY: momentary, Export as MIDI Clip */

    { "b_generate",   'w',   0,     1,     40 },
    { "b_mutate",     'w',   0,     1,     41 },
    { "b_density",    'f',   0.0,   1.0,   42 },
    { "b_accent",     'f',   0.0,   1.0,   43 },
    { "b_slide",      'f',   0.0,   1.0,   44 },
    { "b_octaves",    'i',   1,     3,     45 },
    { "b_length",     'f',   2,     32,    46 },
    { "b_gate",       'f',   0.05,  1.0,   47 },
    { "b_channel",    'i',   1,     16,    48 },   /* FORCE-ONLY: no Move equivalent */
    { "b_offset",     'f',   0,     31,    49 },
    { "b_dir",        'e',   0,     2,     50 },   /* 3 options: Fwd/Rev/Pendulum */
    { "b_auto_gen",   'e',   0,     6,     51 },   /* FORCE-ONLY: 7 options, Off + 6 bar counts */
    { "b_dump",       'w',   0,     1,     52 },   /* FORCE-ONLY: momentary, Export as MIDI Clip */

    /* Global block moved to 70-79 (was 50-57) to make room for the two
     * per-seq Advanced blocks above without colliding -- see docs/CC-MAP.md.
     * cc 79 (old shared auto_gen) is retired -- replaced by a_auto_gen/
     * b_auto_gen above, and reused below for cv_mode. */
    { "scale",        'e',   0,     11,    70 },   /* 12 options (v1.1 curated set) */
    { "root",         'e',   0,     11,    71 },   /* 12 options */
    { "b_tune",       'i',  -24,    24,    72 },
    { "blend",        'i',  -63,    64,    73 },
    { "a_algo",       'i',   1,     16,    74 },
    { "b_algo",       'i',   1,     16,    75 },
    { "reset_bars",   'e',   0,     4,     76 },   /* 5 options  */
    { "swing",        'f',   50,    75,    77 },
    { "jitter",       'f',   0.0,   1.0,   78 },
    { "cv_mode",      'e',   0,     1,     79 },   /* FORCE-ONLY: 2 options, Off/On -- see acid_core.c's emit_step_for_seq() */
};
static const int N_PARAMS = (int)(sizeof(PARAMS) / sizeof(PARAMS[0]));

/* ---------------------------------------------------------------------------
 * Globals
 * ------------------------------------------------------------------------- */
static std::atomic<bool>  g_run{true};
static std::mutex         g_lock;          /* serialises every call into the core */
static midi_fx_api_v1_t  *g_api  = nullptr;
static void              *g_inst = nullptr;
static RtMidiOut         *g_out  = nullptr;

static int   g_ctrl_ch     = 0;            /* 0-based control channel (default 1) */
static bool  g_verbose     = false;
static bool  g_forward_unmapped = true;    /* pass CC/PB/PC we don't consume to the synth */

/* FORCE-ONLY: initial a_channel/b_channel (1-16, matches the wire convention),
 * from --a-channel/--b-channel or a_channel=/b_channel= in --config. Pushed
 * into the core via set_param right after create_instance() -- these are
 * core params (acid_seq_t.out_ch), not shim-level routing, so they can't be
 * applied until the instance exists. Default "1" for both matches the old
 * single-channel behaviour until a user explicitly separates them. */
static std::string g_init_a_channel = "1";
static std::string g_init_b_channel = "1";

/* CC -> param index, built at startup from PARAMS[].default_cc + config file. */
static std::unordered_map<int, int> g_cc2param;

/* BPM estimation from 24-PPQN clock. */
static std::atomic<float> g_bpm{120.0f};
static std::atomic<int>   g_clock_status{MOVE_CLOCK_STATUS_STOPPED};
static std::chrono::steady_clock::time_point g_last_pulse;
static bool   g_have_last_pulse = false;
static double g_pulse_ema_us   = 0.0;       /* EMA of inter-pulse interval, microseconds */
static std::chrono::steady_clock::time_point g_last_clock_seen;

/* ---------------------------------------------------------------------------
 * Host callbacks handed to acid_core.c
 * ------------------------------------------------------------------------- */
static float host_get_bpm(void) { return g_bpm.load(); }

static int host_get_clock_status(void) {
    /* Demote RUNNING->STOPPED if the clock has gone silent for >0.5 s. */
    if (g_clock_status.load() == MOVE_CLOCK_STATUS_RUNNING) {
        auto now = std::chrono::steady_clock::now();
        auto quiet = std::chrono::duration_cast<std::chrono::milliseconds>(now - g_last_clock_seen).count();
        if (quiet > 500) return MOVE_CLOCK_STATUS_STOPPED;
    }
    return g_clock_status.load();
}

/* ---------------------------------------------------------------------------
 * Output
 * ------------------------------------------------------------------------- */
/* No channel rewrite here anymore: acid_core.c now stamps the correct final
 * channel on every message it emits (a_channel/b_channel per sequencer, via
 * the FORCE-ONLY out_ch field -- see acid_core.c's file header), so the shim
 * just forwards bytes as given. */
static void send_out(const uint8_t (*msgs)[3], const int *lens, int n) {
    if (!g_out) return;
    for (int i = 0; i < n; i++) {
        std::vector<unsigned char> m(msgs[i], msgs[i] + lens[i]);
        try { g_out->sendMessage(&m); } catch (...) {}
    }
}

/* ---------------------------------------------------------------------------
 * v0.2: parameter feedback -- CC out on FEEDBACK_CHANNEL, same CC numbers as
 * input, so anything listening on Acid:Out (Mockba) (the web panel, a hardware
 * controller with motorized/LED feedback, another Force track) can display
 * the engine's TRUE current value instead of just "whatever this client last
 * sent". Sent after every CC-in that actually changes a param, and broadcast
 * in full periodically so a freshly-connected listener converges without
 * needing to ask for it. No Move equivalent -- FORCE-ONLY, like a_channel/
 * b_channel.
 * ------------------------------------------------------------------------- */
#define FEEDBACK_CHANNEL 15   /* 0-based -- MIDI channel 16 */

/* readback is what get_param returned: an index string for 'e', a numeric
 * value string for 'f'/'i'. Converts back to a 0-127 wire value. Caller
 * already excluded 'w' (no persistent value to report). */
static int wire_from_readback(const ParamSpec &p, const char *readback) {
    double wire;
    if (p.kind == 'e') {
        int idx = std::atoi(readback);
        int n = (int)(p.hi - p.lo) + 1;
        wire = (n > 1) ? (idx / (double)(n - 1)) * 127.0 : 0.0;
    } else {
        double val = std::atof(readback);
        double span = p.hi - p.lo;
        wire = (span > 0.0) ? ((val - p.lo) / span) * 127.0 : 0.0;
    }
    int w = (int)std::lround(wire);
    if (w < 0) w = 0;
    if (w > 127) w = 127;
    return w;
}

static void send_feedback_cc(int cc, int wire) {
    if (!g_out) return;
    std::vector<unsigned char> m = {
        (unsigned char)(0xB0 | FEEDBACK_CHANNEL), (unsigned char)cc, (unsigned char)wire
    };
    try { g_out->sendMessage(&m); } catch (...) {}
}

/* Full-state broadcast -- every non-momentary param, read fresh from the
 * core. Called once at startup (after the initial a_channel/b_channel push)
 * and periodically from the timer thread. */
static void send_all_feedback() {
    char readback[32];
    for (int i = 0; i < N_PARAMS; i++) {
        const ParamSpec &p = PARAMS[i];
        if (p.kind == 'w') continue;
        int n;
        { std::lock_guard<std::mutex> lk(g_lock);
          n = g_api->get_param(g_inst, p.key, readback, sizeof(readback)); }
        if (n <= 0) continue;
        send_feedback_cc(p.default_cc, wire_from_readback(p, readback));
    }
}

/* ---------------------------------------------------------------------------
 * CC -> set_param
 * ------------------------------------------------------------------------- */
static void apply_cc(int param_idx, int value /* 0..127 */) {
    const ParamSpec &p = PARAMS[param_idx];
    char buf[32];

    switch (p.kind) {
        case 'w':                                  /* generate / mutate */
            if (value < 64) return;                /* only the press, not the release */
            std::snprintf(buf, sizeof(buf), "go");
            break;
        case 'f': {
            double v = p.lo + (p.hi - p.lo) * (value / 127.0);
            std::snprintf(buf, sizeof(buf), "%.4f", v);
            break;
        }
        case 'i': {
            long v = std::lround(p.lo + (p.hi - p.lo) * (value / 127.0));
            std::snprintf(buf, sizeof(buf), "%ld", v);
            break;
        }
        case 'e': {
            int n = (int)(p.hi - p.lo) + 1;        /* option count */
            int idx = (int)std::lround((value / 127.0) * (n - 1));
            if (idx < 0) idx = 0;
            if (idx > n - 1) idx = n - 1;
            std::snprintf(buf, sizeof(buf), "%d", idx);
            break;
        }
        default: return;
    }

    char readback[32];
    int readback_len = -1;
    {
        std::lock_guard<std::mutex> lk(g_lock);
        g_api->set_param(g_inst, p.key, buf);
        if (p.kind != 'w') readback_len = g_api->get_param(g_inst, p.key, readback, sizeof(readback));
    }
    if (g_verbose) std::fprintf(stderr, "[acid] set %-11s = %s  (cc %d = %d)\n", p.key, buf, p.default_cc, value);
    if (readback_len > 0) send_feedback_cc(p.default_cc, wire_from_readback(p, readback));
}

/* ---------------------------------------------------------------------------
 * Control socket (force-shadow's on-device touchscreen page) -- plain
 * "SET <key> <value>" / "GET <key>" text lines over AF_UNIX, same protocol as
 * maze_host/dx7_host. Values are integers (the page uses int_values=1): enums
 * are option indices, and every float param whose range tops out at 1.0
 * (density/accent/slide/gate/jitter) is exchanged in PERCENT so the page can
 * round to an integer without losing resolution. Momentary keys (generate,
 * mutate) take any value. Reuses the exact set_param path apply_cc() does, then
 * re-broadcasts feedback so the web panel follows along.
 * ------------------------------------------------------------------------- */
static std::string g_ctrl_sock_path = "/tmp/acid_ctrl.sock";

static const ParamSpec *find_param(const char *key) {
    for (int i = 0; i < N_PARAMS; i++)
        if (!std::strcmp(PARAMS[i].key, key)) return &PARAMS[i];
    return nullptr;
}
static bool is_pct(const ParamSpec &p) { return p.kind == 'f' && p.hi <= 1.0; }

/* Display names for the enum params the page shows as steppers (option lists
 * too long for an enum row): GET <key>_txt -> name, GET <key>_n -> count.
 * Must mirror the web/params.json option lists. */
struct EnumNames { const char *key; int n; const char *const *names; };
static const char *const N_SCALE[] = { "MINOR", "PHRYGIAN", "HARM MIN", "MIN PENT", "DORIAN", "MAJOR",
                                       "PHRYG DOM", "LOCRIAN", "WHOLE TONE", "HUNG MIN", "MIN BLUES", "CHROMATIC" };
static const char *const N_ROOT[]  = { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" };
static const char *const N_REGEN[] = { "OFF", "1 BAR", "2 BARS", "4 BARS", "8 BARS", "16 BARS", "32 BARS" };
static const EnumNames ENUM_NAMES[] = {
    { "scale", 12, N_SCALE }, { "root", 12, N_ROOT },
    { "a_auto_gen", 7, N_REGEN }, { "b_auto_gen", 7, N_REGEN },
};

static bool enum_names_get(const char *key, std::string &out) {
    size_t kl = std::strlen(key);
    for (const EnumNames &e : ENUM_NAMES) {
        size_t el = std::strlen(e.key);
        if (kl < el || std::strncmp(key, e.key, el)) continue;
        const char *suffix = key + el;
        if (!std::strcmp(suffix, "_n")) { out = std::to_string(e.n) + "\n"; return true; }
        if (!std::strcmp(suffix, "_txt")) {
            const ParamSpec *p = find_param(e.key);
            char buf[32]; int n;
            { std::lock_guard<std::mutex> lk(g_lock);
              n = g_api->get_param(g_inst, p->key, buf, sizeof(buf) - 1); }
            if (n <= 0) return false;
            buf[n < 31 ? n : 31] = 0;
            int idx = std::atoi(buf);
            if (idx < 0) idx = 0;
            if (idx >= e.n) idx = e.n - 1;
            out = std::string(e.names[idx]) + "\n";
            return true;
        }
    }
    return false;
}

static void handle_ctrl_line(int fd, const std::string &line) {
    char cmd[16] = {0}, key[64] = {0}, val[64] = {0};
    if (std::sscanf(line.c_str(), "%15s", cmd) != 1) { send(fd, "ERR\n", 4, 0); return; }

    if (!std::strcmp(cmd, "SET") && std::sscanf(line.c_str(), "%*s %63s %63s", key, val) == 2) {
        const ParamSpec *p = find_param(key);
        if (!p) { send(fd, "ERR\n", 4, 0); return; }
        char buf[32];
        if (p->kind == 'w')      std::snprintf(buf, sizeof(buf), "go");
        else {
            double v = std::atof(val);
            if (is_pct(*p)) v /= 100.0;
            if (v < p->lo) v = p->lo;
            if (v > p->hi) v = p->hi;
            if (p->kind == 'f')  std::snprintf(buf, sizeof(buf), "%.4f", v);
            else                 std::snprintf(buf, sizeof(buf), "%ld", std::lround(v));
        }
        char readback[32]; int rn = -1;
        { std::lock_guard<std::mutex> lk(g_lock);
          g_api->set_param(g_inst, p->key, buf);
          if (p->kind != 'w') rn = g_api->get_param(g_inst, p->key, readback, sizeof(readback)); }
        if (g_verbose) std::fprintf(stderr, "[acid] ctrl set %-11s = %s\n", p->key, buf);
        if (rn > 0) send_feedback_cc(p->default_cc, wire_from_readback(*p, readback));
        send(fd, "OK\n", 3, 0);
        return;
    }
    if (!std::strcmp(cmd, "GET") && std::sscanf(line.c_str(), "%*s %63s", key) == 1) {
        std::string named;
        if (enum_names_get(key, named)) { send(fd, named.c_str(), named.size(), 0); return; }
        const ParamSpec *p = find_param(key);
        if (!p || p->kind == 'w') { send(fd, "ERR\n", 4, 0); return; }
        char buf[32]; int n;
        { std::lock_guard<std::mutex> lk(g_lock);
          n = g_api->get_param(g_inst, p->key, buf, sizeof(buf) - 1); }
        if (n <= 0) { send(fd, "ERR\n", 4, 0); return; }
        buf[n < 31 ? n : 31] = 0;
        char out[48];
        if (p->kind == 'e')       std::snprintf(out, sizeof(out), "%d\n", std::atoi(buf));
        else if (is_pct(*p))      std::snprintf(out, sizeof(out), "%ld\n", std::lround(std::atof(buf) * 100.0));
        else                      std::snprintf(out, sizeof(out), "%ld\n", std::lround(std::atof(buf)));
        send(fd, out, std::strlen(out), 0);
        return;
    }
    send(fd, "ERR\n", 4, 0);
}

static void ctrl_server_loop(int lfd) {
    while (g_run.load()) {
        int cfd = accept(lfd, nullptr, nullptr);
        if (cfd < 0) continue;
        char buf[256];
        ssize_t n = recv(cfd, buf, sizeof(buf) - 1, 0);
        if (n > 0) {
            buf[n] = 0;
            std::string line(buf);
            size_t nl = line.find('\n');
            if (nl != std::string::npos) line.resize(nl);
            handle_ctrl_line(cfd, line);
        }
        close(cfd);
    }
}

static int ctrl_socket_listen(const std::string &path) {
    unlink(path.c_str());
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }
    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, path.c_str(), sizeof(addr.sun_path) - 1);
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) { perror("bind"); close(fd); return -1; }
    chmod(path.c_str(), 0666);
    if (listen(fd, 8) != 0) { perror("listen"); close(fd); return -1; }
    return fd;
}

/* ---------------------------------------------------------------------------
 * Clock tracking
 * ------------------------------------------------------------------------- */
static void note_clock_pulse(void) {
    auto now = std::chrono::steady_clock::now();
    g_last_clock_seen = now;
    if (g_have_last_pulse) {
        double us = std::chrono::duration_cast<std::chrono::microseconds>(now - g_last_pulse).count();
        if (us > 200.0 && us < 200000.0) {              /* 5 BPM .. ~1250 BPM sanity */
            if (g_pulse_ema_us <= 0.0) g_pulse_ema_us = us;
            else g_pulse_ema_us += (us - g_pulse_ema_us) * 0.12;
            double bpm = 60.0e6 / (g_pulse_ema_us * 24.0);
            if (bpm > 20.0 && bpm < 400.0) g_bpm.store((float)bpm);
        }
    }
    g_last_pulse = now;
    g_have_last_pulse = true;
}

/* ---------------------------------------------------------------------------
 * RtMidi input callback
 * ------------------------------------------------------------------------- */
static void on_midi(double /*dt*/, std::vector<unsigned char> *msg, void * /*ud*/) {
    if (!msg || msg->empty()) return;
    const uint8_t *b = msg->data();
    int len = (int)msg->size();
    uint8_t status = b[0];
    uint8_t type   = status & 0xF0;
    uint8_t chan   = status & 0x0F;

    uint8_t out[MIDI_FX_MAX_OUT_MSGS][3];
    int     olen[MIDI_FX_MAX_OUT_MSGS];

    /* --- realtime / transport: hand straight to the core (it already knows
     *     0xF8/0xFA/0xFB/0xFC) and also update our BPM + status view. --- */
    if (status == 0xF8) {
        note_clock_pulse();
        int n;
        { std::lock_guard<std::mutex> lk(g_lock);
          n = g_api->process_midi(g_inst, b, len, out, olen, MIDI_FX_MAX_OUT_MSGS); }
        send_out(out, olen, n);
        return;
    }
    if (status == 0xFA || status == 0xFB) {          /* Start / Continue */
        g_clock_status.store(MOVE_CLOCK_STATUS_RUNNING);
        g_last_clock_seen = std::chrono::steady_clock::now();
        int n;
        { std::lock_guard<std::mutex> lk(g_lock);
          n = g_api->process_midi(g_inst, b, len, out, olen, MIDI_FX_MAX_OUT_MSGS); }
        send_out(out, olen, n);
        return;
    }
    if (status == 0xFC) {                            /* Stop */
        g_clock_status.store(MOVE_CLOCK_STATUS_STOPPED);
        g_have_last_pulse = false;
        int n;
        { std::lock_guard<std::mutex> lk(g_lock);
          n = g_api->process_midi(g_inst, b, len, out, olen, MIDI_FX_MAX_OUT_MSGS); }
        send_out(out, olen, n);
        return;
    }
    if (status >= 0xF0) return;                      /* other system msgs: ignore */

    /* --- channel voice messages: only the control channel matters --- */
    if (chan != (uint8_t)g_ctrl_ch) return;

    if (type == 0xB0 && len >= 3) {                  /* Control Change */
        auto it = g_cc2param.find(b[1]);
        if (it != g_cc2param.end()) { apply_cc(it->second, b[2]); return; }
        if (!g_forward_unmapped) return;
        /* fall through: forward unmapped CC to the synth */
    }

    /* Notes (transpose), plus any pass-through the core chooses to do. */
    int n;
    { std::lock_guard<std::mutex> lk(g_lock);
      n = g_api->process_midi(g_inst, b, len, out, olen, MIDI_FX_MAX_OUT_MSGS); }
    send_out(out, olen, n);
}

/* ---------------------------------------------------------------------------
 * Timer thread — stands in for the Schwung audio-block tick.
 * Feeds acid_tick() the real elapsed sample count so internal free-run tempo
 * stays accurate under scheduler jitter; when Force clock is present the
 * core's 0xF8 path drives stepping and this only does gate-off bookkeeping.
 * ------------------------------------------------------------------------- */
static void timer_loop() {
    using clock = std::chrono::steady_clock;
    auto prev = clock::now();
    auto last_feedback = clock::now();
    const auto period = std::chrono::microseconds(2902);   /* 128 / 44100 s */
    const auto feedback_period = std::chrono::seconds(2);

    while (g_run.load()) {
        std::this_thread::sleep_for(period);
        auto now = clock::now();
        double secs = std::chrono::duration_cast<std::chrono::duration<double>>(now - prev).count();
        prev = now;
        int frames = (int)std::lround(secs * MOVE_SAMPLE_RATE);
        if (frames < 1)    frames = 1;
        if (frames > 44100) frames = 44100;             /* clamp a huge stall */

        uint8_t out[MIDI_FX_MAX_OUT_MSGS][3];
        int     olen[MIDI_FX_MAX_OUT_MSGS];
        int n;
        { std::lock_guard<std::mutex> lk(g_lock);
          n = g_api->tick(g_inst, frames, MOVE_SAMPLE_RATE, out, olen, MIDI_FX_MAX_OUT_MSGS); }
        send_out(out, olen, n);

        /* v0.2: periodic full-state feedback broadcast, so a freshly-opened
         * web panel (or any other late-connecting listener) converges to the
         * true current state within a couple of seconds, not just on the
         * one-time startup broadcast in main(). */
        if (now - last_feedback >= feedback_period) {
            last_feedback = now;
            send_all_feedback();
        }
    }
}

/* ---------------------------------------------------------------------------
 * Config file: lines of "key = CC", '#' comments. Lets users re-map CCs and
 * a couple of options without a rebuild. Unknown keys are ignored.
 * ------------------------------------------------------------------------- */
static void load_config(const char *path) {
    FILE *f = std::fopen(path, "r");
    if (!f) return;
    char line[256];
    while (std::fgets(line, sizeof(line), f)) {
        char *hash = std::strchr(line, '#'); if (hash) *hash = 0;
        char key[64]; int val;
        if (std::sscanf(line, " %63[a-zA-Z_] = %d", key, &val) != 2) continue;
        if (!std::strcmp(key, "control_channel")) { g_ctrl_ch = (val - 1) & 0x0F; continue; }
        if (!std::strcmp(key, "a_channel")) {       /* FORCE-ONLY: pushed into the core after create_instance */
            int v = val < 1 ? 1 : (val > 16 ? 16 : val);
            g_init_a_channel = std::to_string(v); continue;
        }
        if (!std::strcmp(key, "b_channel")) {
            int v = val < 1 ? 1 : (val > 16 ? 16 : val);
            g_init_b_channel = std::to_string(v); continue;
        }
        if (!std::strcmp(key, "forward_unmapped")){ g_forward_unmapped = (val != 0); continue; }
        for (int i = 0; i < N_PARAMS; i++) {
            if (!std::strcmp(key, PARAMS[i].key)) {
                if (val >= 0 && val <= 127) g_cc2param[val] = i;
                break;
            }
        }
    }
    std::fclose(f);
}

/* ---------------------------------------------------------------------------
 * main
 * ------------------------------------------------------------------------- */
static void on_signal(int) { g_run.store(false); }

static void usage(const char *me) {
    std::fprintf(stderr,
        "usage: %s [options]\n"
        "  -v                    verbose (log every param change)\n"
        "  --client NAME         ALSA client name         (default: Acid)\n"
        "  --control-channel N   1-16, CC + note-in       (default: 1)\n"
        "  --a-channel N         1-16, Seq A note output   (default: 1)\n"
        "  --b-channel N         1-16, Seq B note output   (default: 1)\n"
        "  --bpm N               starting BPM before clock (default: 120)\n"
        "  --ctrl-sock PATH      control socket path       (default: /tmp/acid_ctrl.sock)\n"
        "  --config PATH         CC-map / channel overrides\n"
        "  --no-forward          drop unmapped CC instead of passing to the synth\n",
        me);
}

int main(int argc, char **argv) {
    std::string client = "Acid";
    const char *cfg = nullptr;
    float bpm0 = 120.0f;

    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        if      (a == "-v")                 g_verbose = true;
        else if (a == "--no-forward")       g_forward_unmapped = false;
        else if (a == "--client"          && i + 1 < argc) client   = argv[++i];
        else if (a == "--control-channel" && i + 1 < argc) g_ctrl_ch = (std::atoi(argv[++i]) - 1) & 0x0F;
        else if (a == "--a-channel"       && i + 1 < argc) g_init_a_channel = argv[++i];
        else if (a == "--b-channel"       && i + 1 < argc) g_init_b_channel = argv[++i];
        else if (a == "--bpm"             && i + 1 < argc) bpm0     = (float)std::atof(argv[++i]);
        else if (a == "--ctrl-sock"       && i + 1 < argc) g_ctrl_sock_path = argv[++i];
        else if (a == "--config"          && i + 1 < argc) cfg      = argv[++i];
        else { usage(argv[0]); return a == "-h" || a == "--help" ? 0 : 2; }
    }

    for (int i = 0; i < N_PARAMS; i++) g_cc2param[PARAMS[i].default_cc] = i;
    if (cfg) load_config(cfg);
    g_bpm.store(bpm0);

    /* --- core --- */
    static host_api_v1_t host = { host_get_bpm, host_get_clock_status };
    g_api = move_midi_fx_init(&host);
    if (!g_api || g_api->api_version != MIDI_FX_API_VERSION) {
        std::fprintf(stderr, "[acid] core init failed\n"); return 1;
    }
    g_inst = g_api->create_instance(".", nullptr);
    if (!g_inst) { std::fprintf(stderr, "[acid] create_instance failed\n"); return 1; }
    /* FORCE-ONLY: push the CLI/config initial channel selection now that the
     * instance exists -- see g_init_a_channel/g_init_b_channel above. */
    g_api->set_param(g_inst, "a_channel", g_init_a_channel.c_str());
    g_api->set_param(g_inst, "b_channel", g_init_b_channel.c_str());

    /* --- MIDI ports --- */
    RtMidiIn *in = nullptr;
    try {
        in = new RtMidiIn(RtMidi::UNSPECIFIED, client, 256);
        g_out = new RtMidiOut(RtMidi::UNSPECIFIED, client);
        in->openVirtualPort("In (Mockba)");
        g_out->openVirtualPort("Out (Mockba)");
        in->ignoreTypes(true, false, true);   /* sysex off, TIMING ON, sensing off */
        in->setCallback(&on_midi, nullptr);
    } catch (RtMidiError &e) {
        std::fprintf(stderr, "[acid] MIDI setup failed: %s\n", e.getMessage().c_str());
        return 1;
    }

    std::signal(SIGINT,  on_signal);
    std::signal(SIGTERM, on_signal);

    std::fprintf(stderr,
        "[acid] up. ports '%s:In (Mockba)' / '%s:Out (Mockba)'  ctrl ch %d  A ch %s  B ch %s\n"
        "[acid] connect Force transport SYNC+CLOCK to '%s:In (Mockba)', route a MIDI track\n"
        "[acid] to it on ch %d for CC control, and synth track(s) FROM '%s:Out (Mockba)'\n"
        "[acid] (Seq A and Seq B can share one channel or use two -- see a_channel/b_channel).\n",
        client.c_str(), client.c_str(), g_ctrl_ch + 1, g_init_a_channel.c_str(), g_init_b_channel.c_str(),
        client.c_str(), g_ctrl_ch + 1, client.c_str());

    /* v0.2: broadcast full initial state now that g_out exists, so a web
     * panel or controller connected at boot sees true defaults immediately
     * rather than waiting up to 2s for the first periodic broadcast. */
    send_all_feedback();

    std::thread timer(timer_loop);

    int ctrl_fd = ctrl_socket_listen(g_ctrl_sock_path);
    std::thread ctrl;
    if (ctrl_fd >= 0) ctrl = std::thread(ctrl_server_loop, ctrl_fd);

    while (g_run.load()) std::this_thread::sleep_for(std::chrono::milliseconds(100));

    /* --- shutdown: silence, then tear down --- */
    timer.join();
    if (ctrl_fd >= 0) {           /* unblock accept(), then reap */
        shutdown(ctrl_fd, SHUT_RDWR); close(ctrl_fd);
        ctrl.detach();
        unlink(g_ctrl_sock_path.c_str());
    }
    {
        std::lock_guard<std::mutex> lk(g_lock);
        /* FORCE-ONLY: A and B can each be on any of 16 channels and it can
         * change at runtime via CC, so the shim doesn't reliably know which
         * channel(s) are "live" at exit -- send note-off across all 16
         * rather than track/query it. One-time cost at shutdown only. */
        for (int ch = 0; ch < 16; ch++) {
            for (int note = 0; note < 128; note++) {
                std::vector<unsigned char> off = { (unsigned char)(0x80 | ch), (unsigned char)note, 0 };
                try { g_out->sendMessage(&off); } catch (...) {}
            }
        }
        g_api->destroy_instance(g_inst);
    }
    delete in;
    delete g_out;
    std::fprintf(stderr, "[acid] bye\n");
    return 0;
}
