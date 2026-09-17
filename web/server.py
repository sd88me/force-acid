#!/usr/bin/env python3
"""Force Acid web control panel — serves the UI and bridges browser actions
to real MIDI CC sent straight into the "Mockba Acid:In" ALSA sequencer port,
and can start/stop the force-acid engine process itself.

Deliberately stdlib-only (http.server) + mido: no node-gyp / native-module
build step needed on-device. See ../DESIGN.md and
~/.claude/skills/mockbamod-module-creator/references/web-gui.md for why.

Run: LD_LIBRARY_PATH=<path-to>/Python/libjack python3 server.py [--port N]
(the LD_LIBRARY_PATH is only needed because the bundled python-rtmidi wheel
was built with JACK support and won't import without libjack.so.0 resolvable
-- we never actually talk to JACK, we force the ALSA API explicitly below.)
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import mido

WEB_DIR = Path(__file__).resolve().parent
ADDON_DIR = WEB_DIR.parent          # .../AddOns/ForceAcid on a deployed device
STATIC_DIR = WEB_DIR / "static"
PARAMS_PATH = WEB_DIR / "params.json"
ENGINE_BIN = ADDON_DIR / "force-acid"
ENGINE_CONF = ADDON_DIR / "force-acid.conf"

# "Export as MIDI Clip" -- see acid_core.c's process_dump_for_seq() for the
# engine side of this. Two destinations: the Force's own browsable
# "Sequences" folder (so it shows up in Force's own file browser/clip
# import), and a copy inside this addon's own folder for reference/backup.
FORCE_DOCS_SEQUENCES_DIR = Path("/media/az01-internal-sd/Force Documents/Sequences")
ADDON_EXPORTS_DIR = ADDON_DIR / "exports"
LANE_DUMP_CC = {"a": 32, "b": 52}
LANE_LENGTH_KEY = {"a": "a_length", "b": "b_length"}
LANE_GATE_KEY = {"a": "a_gate", "b": "b_gate"}
# Must match acid_core.c's DUMP_STEP_MS exactly -- the dump player's fixed,
# tempo-independent per-step cadence, kept in sync by hand.
DUMP_STEP_SEC = 0.060
DUMP_DONE_CC = 3            # acid_core.c's process_dump_for_seq() completion marker
DUMP_SLIDE_CC = 65          # dump always uses plain CC65, regardless of cv_mode
# The dump player emits on a fixed channel (acid_core.c's DUMP_CHANNEL), not
# the lane's own a_channel/b_channel, specifically so a capture can't be
# corrupted by live playback happening concurrently on the same channel.
# Filter on this deliberately -- see DUMP_CHANNEL's own comment.
DUMP_CHANNEL0 = 15


# The client name passed to RtMidi ("Mockba Acid", see host_shim.cpp) is not
# what actually shows up in ALSA/mido's port list on this device -- observed
# live (mido.get_output_names()/get_input_names()) as "Acid:In (Mockba) N:0"
# / "Acid:Out (Mockba) N:0": MockbaMod (or this RtMidi/ALSA combination)
# reorders it into "<short name>:<In/Out> (Mockba)", same pattern seen for
# every other host_shim-style addon (DX7, JV880, Maze Seq all show
# "<Name>:In (Mockba)" too) -- not something specific to force-acid. The
# original ("Mockba Acid", "In") tuple never matches that string, which
# silently made /cc and /status always report the engine as not running.
IN_PORT_MATCH = ("Acid:In", "(Mockba)")
OUT_PORT_MATCH = ("Acid:Out", "(Mockba)")

PARAMS = json.loads(PARAMS_PATH.read_text())
# "spacer" entries are layout-only (empty grid cell to force a row break in
# the web UI, see static/app.js's makeSpacer) -- no "key", nothing to map.
PARAM_BY_KEY = {p["key"]: p for g in PARAMS["groups"] for p in g["params"] if "key" in p}
CTRL_CHANNEL0 = PARAMS.get("control_channel", 1) - 1

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

_lock = threading.Lock()
_midi_out = None

FEEDBACK_CHANNEL0 = 15    # v0.2: matches host_shim.cpp's FEEDBACK_CHANNEL (MIDI ch 16)
CC_TO_KEY = {p["cc"]: p["key"] for p in PARAM_BY_KEY.values() if p["kind"] not in ("momentary", "export")}
_state_lock = threading.Lock()
_state = {}               # key -> last-seen wire value (0-127), from engine feedback


def _find_port(names, needles):
    for n in names:
        if all(x in n for x in needles):
            return n
    return None


def _ensure_out():
    """(Re)open the output port to Mockba Acid:In. Returns the mido port or None."""
    global _midi_out
    with _lock:
        if _midi_out is not None:
            try:
                names = mido.get_output_names()
            except Exception:
                names = []
            if _midi_out.name in names:
                return _midi_out
            try:
                _midi_out.close()
            except Exception:
                pass
            _midi_out = None

        try:
            names = mido.get_output_names()
        except Exception:
            names = []
        target = _find_port(names, IN_PORT_MATCH)
        if not target:
            return None
        try:
            _midi_out = mido.open_output(target, api="LINUX_ALSA")
        except Exception as e:
            print(f"[acid-web] failed to open {target}: {e}", file=sys.stderr)
            _midi_out = None
        return _midi_out


def _feedback_listener():
    """v0.2: background thread -- keeps an input connection to Mockba
    Acid:Out, watches for the engine's own feedback CCs (channel 16, same CC
    numbers as input -- see host_shim.cpp's send_all_feedback/apply_cc) and
    updates _state. Runs for the life of the process; reconnects whenever
    the port disappears (engine not running yet / restarted)."""
    port = None
    while True:
        if port is None:
            try:
                names = mido.get_input_names()
            except Exception:
                names = []
            target = _find_port(names, OUT_PORT_MATCH)
            if target:
                try:
                    port = mido.open_input(target, api="LINUX_ALSA")
                except Exception:
                    port = None
            if port is None:
                time.sleep(1.0)
                continue
        try:
            for msg in port.iter_pending():
                if msg.type == "control_change" and msg.channel == FEEDBACK_CHANNEL0:
                    key = CC_TO_KEY.get(msg.control)
                    if key:
                        with _state_lock:
                            _state[key] = msg.value
        except Exception:
            try:
                port.close()
            except Exception:
                pass
            port = None
            continue
        time.sleep(0.02)


def engine_present():
    try:
        names = mido.get_output_names()
    except Exception:
        return False
    return _find_port(names, IN_PORT_MATCH) is not None and \
        _find_port(mido.get_input_names(), OUT_PORT_MATCH) is not None


def engine_start():
    if engine_present():
        return True, "already running"
    if not ENGINE_BIN.exists():
        return False, f"binary not found: {ENGINE_BIN}"
    args = [str(ENGINE_BIN)]
    if ENGINE_CONF.exists():
        args += ["--config", str(ENGINE_CONF)]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return False, str(e)
    # Reap it whenever it exits (killall from /engine stop, a crash, or the
    # process outliving this server) -- otherwise it zombies forever, since
    # nothing else waits on it.
    threading.Thread(target=proc.wait, daemon=True).start()
    for _ in range(20):  # up to ~2s for the port to register
        time.sleep(0.1)
        if engine_present():
            return True, "started"
    return False, "launched but ports did not register in time"


def engine_stop():
    subprocess.run(["killall", "force-acid"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    global _midi_out
    with _lock:
        if _midi_out is not None:
            try:
                _midi_out.close()
            except Exception:
                pass
            _midi_out = None
    return True, "stopped"


def send_cc(cc, value):
    port = _ensure_out()
    if port is None:
        return False, "engine not running / port not found"
    value = max(0, min(127, int(round(value))))
    port.send(mido.Message('control_change', channel=CTRL_CHANNEL0, control=cc, value=value))
    return True, None


def send_transpose(semitones):
    port = _ensure_out()
    if port is None:
        return False, "engine not running / port not found"
    note = max(0, min(127, 60 + int(semitones)))
    port.send(mido.Message('note_on', channel=CTRL_CHANNEL0, note=note, velocity=100))

    def _off():
        time.sleep(0.08)
        try:
            port.send(mido.Message('note_off', channel=CTRL_CHANNEL0, note=note, velocity=0))
        except Exception:
            pass
    threading.Thread(target=_off, daemon=True).start()
    return True, None


def _wire_to_value(spec, wire):
    """Same lo/hi scaling the web UI's own knob display uses (see
    static/app.js's displayValue()) -- _state only ever holds raw 0-127 wire
    values (the engine's own CC feedback), never the scaled parameter."""
    lo, hi = spec["lo"], spec["hi"]
    v = lo + (hi - lo) * (wire / 127.0)
    return round(v) if spec["kind"] == "int" else v


def _capture_dump(lane, timeout=6.0):
    """Trigger acid_core.c's per-lane Export dump (see process_dump_for_seq())
    and capture the resulting MIDI stream on a dedicated, temporary input
    connection -- separate from _feedback_listener's long-lived one, since
    that only looks at channel 16 CCs, not this lane's own note/CC stream.
    Returns ({step_index: {"pitch", "velocity", "slide"}}, None) or
    (None, error_message)."""
    names = mido.get_input_names()
    target = _find_port(names, OUT_PORT_MATCH)
    if not target:
        return None, "engine not running / port not found"

    try:
        cap = mido.open_input(target, api="LINUX_ALSA")
    except Exception as e:
        return None, f"failed to open capture port: {e}"

    try:
        list(cap.iter_pending())  # drain anything stale before triggering
        ok, err = send_cc(LANE_DUMP_CC[lane], 127)
        if not ok:
            return None, err

        t0 = time.time()
        steps = {}
        pending_slide = False
        done = False
        deadline = t0 + timeout
        while time.time() < deadline and not done:
            for msg in cap.iter_pending():
                if getattr(msg, "channel", None) != DUMP_CHANNEL0:
                    continue  # not the dump stream -- e.g. concurrent live playback
                if msg.type == "control_change" and msg.control == DUMP_SLIDE_CC and msg.value == 127:
                    pending_slide = True
                elif msg.type == "note_on" and msg.velocity > 0:
                    idx = round((time.time() - t0) / DUMP_STEP_SEC)
                    steps[idx] = {"pitch": msg.note, "velocity": msg.velocity, "slide": pending_slide}
                    pending_slide = False
                elif msg.type == "control_change" and msg.control == DUMP_DONE_CC and msg.value == 127:
                    done = True
                    break
            if not done:
                time.sleep(0.005)
        if not done:
            return None, "export timed out waiting for the engine"
        return steps, None
    finally:
        cap.close()


def _build_midi_file(steps, length, gate):
    """A clean, straight 16th-note-grid Standard MIDI File (type 0) from a
    _capture_dump() result -- one note (or rest) per step, note length from
    the lane's own current Gate (already known from /state, not re-derived
    from the dump's own fixed-cadence timing), slide preserved as a CC65
    on/off bracketing the note it leads into. Deliberately ignores swing/
    jitter -- this is meant to be a clean, quantised clip, not a recording
    of one specific live performance."""
    PPQ = 480
    TICKS_PER_STEP = PPQ // 4   # a straight 1/16 grid
    gate_ticks = max(1, round(TICKS_PER_STEP * gate))

    mid = mido.MidiFile(type=0, ticks_per_beat=PPQ)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(120), time=0))

    events = []  # (abs_tick, sort_key, message)
    for i in range(length):
        st = steps.get(i)
        if not st:
            continue
        start = i * TICKS_PER_STEP
        end = start + gate_ticks
        if st["slide"]:
            events.append((start, 0, mido.Message("control_change", control=DUMP_SLIDE_CC, value=127)))
        events.append((start, 1, mido.Message("note_on", note=st["pitch"], velocity=st["velocity"])))
        events.append((end, 0, mido.Message("note_off", note=st["pitch"], velocity=0)))
        if st["slide"]:
            events.append((end, 1, mido.Message("control_change", control=DUMP_SLIDE_CC, value=0)))
    events.sort(key=lambda e: (e[0], e[1]))

    last_tick = 0
    for tick, _key, msg in events:
        track.append(msg.copy(time=tick - last_tick))
        last_tick = tick
    track.append(mido.MetaMessage("end_of_track", time=0))
    return mid


def export_lane(lane):
    if lane not in ("a", "b"):
        return False, "lane must be a|b"

    with _state_lock:
        length_wire = _state.get(LANE_LENGTH_KEY[lane])
        gate_wire = _state.get(LANE_GATE_KEY[lane])
    length = _wire_to_value(PARAM_BY_KEY[LANE_LENGTH_KEY[lane]], length_wire) if length_wire is not None else 16
    gate = _wire_to_value(PARAM_BY_KEY[LANE_GATE_KEY[lane]], gate_wire) if gate_wire is not None else 0.5

    steps, err = _capture_dump(lane, timeout=length * DUMP_STEP_SEC + 3.0)
    if err:
        return False, err

    mid = _build_midi_file(steps, length, gate)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"Force Acid Seq {lane.upper()} {stamp}.mid"
    written = []
    for d in (FORCE_DOCS_SEQUENCES_DIR, ADDON_EXPORTS_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
            out_path = d / filename
            mid.save(str(out_path))
            written.append(str(out_path))
        except Exception as e:
            print(f"[acid-web] export to {d} failed: {e}", file=sys.stderr)
    if not written:
        return False, "failed to write to both export locations"
    return True, written


class Handler(BaseHTTPRequestHandler):
    server_version = "ForceAcidWeb/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[acid-web] " + (fmt % args) + "\n")

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, relpath, content_type):
        path = STATIC_DIR / relpath
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if relpath != "index.html":
            self.send_header("Cache-Control", "public, max-age=60")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in STATIC_FILES:
            relpath, ctype = STATIC_FILES[path]
            self._file(relpath, ctype)
        elif path == "/params.json":
            self._json(200, PARAMS)
        elif path == "/status":
            self._json(200, {"engine_running": engine_present()})
        elif path == "/state":
            with _state_lock:
                self._json(200, dict(_state))
        else:
            self.send_error(404, "not found")

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "bad json"})
            return

        if path == "/cc":
            key = body.get("key")
            value = body.get("value")
            spec = PARAM_BY_KEY.get(key)
            if spec is None or value is None:
                self._json(400, {"ok": False, "error": "unknown key or missing value"})
                return
            ok, err = send_cc(spec["cc"], value)
            self._json(200 if ok else 503, {"ok": ok, "error": err})

        elif path == "/transpose":
            semis = body.get("semitones", 0)
            ok, err = send_transpose(semis)
            self._json(200 if ok else 503, {"ok": ok, "error": err})

        elif path == "/engine":
            action = body.get("action")
            if action == "start":
                ok, msg = engine_start()
            elif action == "stop":
                ok, msg = engine_stop()
            else:
                self._json(400, {"ok": False, "error": "action must be start|stop"})
                return
            self._json(200 if ok else 503, {"ok": ok, "message": msg})

        elif path == "/export":
            lane = body.get("lane")
            ok, result = export_lane(lane)
            if ok:
                self._json(200, {"ok": True, "paths": result})
            else:
                self._json(400 if result == "lane must be a|b" else 503, {"ok": False, "error": result})

        else:
            self.send_error(404, "not found")


def main():
    port = 8303
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    threading.Thread(target=_feedback_listener, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[acid-web] serving on http://0.0.0.0:{port}  (engine dir: {ADDON_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
