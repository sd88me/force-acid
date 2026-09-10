/* Host-side smoke test for acid_core.c — links the natively-built core (NOT
 * the armhf cross build) and drives it the way host_shim.cpp / the Schwung
 * chain host would: start transport, tick ~8 s, twiddle params, confirm no
 * crash and that the output is sane MIDI (note ranges, on/off balance, root
 * moving on note-in, Blend muting Seq B). Local build-time check only.
 *
 *   tests/run.sh          # builds and runs this
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include "acid_core.h"

static float mock_get_bpm(void) { return 120.0f; }
static int   mock_get_clock_status(void) { return MOVE_CLOCK_STATUS_RUNNING; }

static int g_note_on = 0, g_note_off = 0, g_cc = 0;
static int g_min_note = 200, g_max_note = -1;

static void observe(const uint8_t msg[3], int len, long tick_idx) {
    if (len < 1) return;
    uint8_t type = msg[0] & 0xF0;
    if (type == 0x90 && msg[2] > 0) {
        g_note_on++;
        if (msg[1] < g_min_note) g_min_note = msg[1];
        if (msg[1] > g_max_note) g_max_note = msg[1];
        printf("[%6ld] note-on  note=%3d vel=%3d\n", tick_idx, msg[1], msg[2]);
    } else if (type == 0x80 || (type == 0x90 && msg[2] == 0)) {
        g_note_off++;
        printf("[%6ld] note-off note=%3d\n", tick_idx, msg[1]);
    } else if (type == 0xB0) {
        g_cc++;
        printf("[%6ld] cc       cc=%3d val=%3d\n", tick_idx, msg[1], msg[2]);
    } else {
        printf("[%6ld] other    %02x %02x %02x\n", tick_idx, msg[0], msg[1], msg[2]);
    }
}

int main(void) {
    host_api_v1_t host = { mock_get_bpm, mock_get_clock_status };
    midi_fx_api_v1_t *api = move_midi_fx_init(&host);
    if (!api) { fprintf(stderr, "init returned NULL\n"); return 1; }
    printf("api_version = %u (expect %u)\n", api->api_version, (unsigned)MIDI_FX_API_VERSION);

    void *inst = api->create_instance(".", NULL);
    if (!inst) { fprintf(stderr, "create_instance returned NULL\n"); return 1; }
    printf("instance created OK\n\n");

    api->set_param(inst, "a_length", "5");
    api->set_param(inst, "b_length", "7");
    api->set_param(inst, "a_algo", "1");
    api->set_param(inst, "b_algo", "12");
    api->set_param(inst, "b_tune", "7");
    api->set_param(inst, "blend", "0");
    api->set_param(inst, "reset_bars", "4"); /* Off */

    char buf[512];
    int n = api->get_param(inst, "b_tune", buf, sizeof(buf));
    printf("b_tune readback = %.*s (expect 7)\n\n", n, buf);

    uint8_t start_msg[1] = { 0xFA };
    uint8_t out_msgs[MIDI_FX_MAX_OUT_MSGS][3];
    int out_lens[MIDI_FX_MAX_OUT_MSGS];
    int count = api->process_midi(inst, start_msg, 1, out_msgs, out_lens, MIDI_FX_MAX_OUT_MSGS);
    printf("process_midi(START) -> %d messages\n\n", count);

    long total_blocks = (long)((44100.0 / 128.0) * 8.0);
    for (long i = 0; i < total_blocks; i++) {
        if (i == total_blocks / 4) {
            printf("\n--- note-in C3 (60) at block %ld ---\n\n", i);
            uint8_t note_msg[3] = { 0x90, 60, 100 };
            count = api->process_midi(inst, note_msg, 3, out_msgs, out_lens, MIDI_FX_MAX_OUT_MSGS);
            for (int m = 0; m < count; m++) observe(out_msgs[m], out_lens[m], i);
        }
        if (i == total_blocks / 2) {
            printf("\n--- Reset Both = 1 bar at block %ld ---\n\n", i);
            api->set_param(inst, "reset_bars", "0");
        }
        if (i == (3 * total_blocks) / 4) {
            printf("\n--- Blend hard left (Seq A alone) at block %ld ---\n\n", i);
            api->set_param(inst, "blend", "-63");
        }
        if (i == total_blocks - 200) { printf("\n--- A Generate ---\n\n"); api->set_param(inst, "a_generate", "go"); }
        if (i == total_blocks - 100) { printf("\n--- A Mutate ---\n\n");   api->set_param(inst, "a_mutate", "go"); }

        count = api->tick(inst, 128, 44100, out_msgs, out_lens, MIDI_FX_MAX_OUT_MSGS);
        for (int m = 0; m < count; m++) observe(out_msgs[m], out_lens[m], i);
    }

    api->destroy_instance(inst);

    printf("\n=== summary ===\n");
    printf("note-on=%d note-off=%d cc(portamento)=%d\n", g_note_on, g_note_off, g_cc);
    printf("note range: %d..%d\n", g_min_note, g_max_note);

    int ok = 1;
    if (g_note_on == 0) { fprintf(stderr, "FAIL: no note-on events\n"); ok = 0; }
    if (g_min_note < 0 || g_max_note > 127) { fprintf(stderr, "FAIL: note out of range\n"); ok = 0; }
    if (g_note_off < g_note_on - 4) { fprintf(stderr, "FAIL: leaked notes\n"); ok = 0; }

    printf(ok ? "\nSMOKE TEST PASSED\n" : "\nSMOKE TEST FAILED\n");
    return ok ? 0 : 1;
}
