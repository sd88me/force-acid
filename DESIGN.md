# Force Acid — architecture

Force Acid runs the exact generator from
[`schwung-acid`](https://github.com/sd88me/schwung-acid) on a MockbaMod-modded
Akai Force, driven by the Force's own transport and by CC from a Force MIDI
track, with as little change to the generator code as possible.

## What ports unchanged

`src/acid_core.c` is `schwung-acid/src/acid/dsp/acid.c` **verbatim** apart
from one hunk: the two Schwung headers are swapped for `src/acid_core.h`.
All of the following come across with zero edits:

- both generators (`gen_primary` = tb3po model, `gen_secondary` =
  Sting-style), the Algo 1–16 blend, `mutate_pattern`
- step→note mapping, scales, octave handling, C4-anchored live transpose
- Blend velocity crossfade, per-seq accent/normal ratio
- Swing (internal free-run **and** the 24-PPQN follow path)
- Reset Both / polymeter, gate-off accounting, slide/portamento (CC 65)
- the whole `set_param` / `get_param` string interface

`acid.c` already contains an external-MIDI-clock path (`0xF8/0xFA/0xFB/0xFC`
handling in `process_midi`, plus `get_bpm` / `get_clock_status` polling in
`tick`). That path was secondary on Move; on the Force it becomes the
primary sync. No new code in the core to make that happen.

## How the port works

| Layer | Move | Force |
|---|---|---|
| Generator | `dsp.so` (`acid.c`) | `src/acid_core.c` — **same file**, only the `#include` swapped |
| Host | Schwung chain, on the audio thread | `src/host_shim.cpp` — standalone process, RtMidi + a timer thread |
| Params | `module.json` knobs → `set_param("0.42")` | MIDI **CC** on a control channel → rescale → `set_param` |
| Clock | host `get_bpm` / `get_clock_status` | Force transport: MIDI clock + Start/Stop into the virtual port |
| UI | `ui_hierarchy`, knobs on the display | CC map ([`docs/CC-MAP.md`](docs/CC-MAP.md)); a Force track template; a touchscreen page (`shadow`); a browser panel (`web/`) |
| Output | one slot channel (forced by the chain host) | **independent channel per sequencer** (`a_channel`/`b_channel`, FORCE-ONLY) |

### The host gap, and how the shim fills it

On Move, a chain host owns the module: it calls the six entry points on the
audio thread, feeds MIDI in, collects MIDI out, and answers `get_bpm` /
`get_clock_status`. On the Force there is no such host. `src/host_shim.cpp`
reimplements exactly that contract as a standalone process:

| Schwung chain host did | `host_shim.cpp` does |
|---|---|
| `dlopen(dsp.so)`, `move_midi_fx_init(host)` | links `acid_core.o`, calls `move_midi_fx_init(&host)` directly |
| `create_instance(dir, cfg)` at slot load | once, at startup |
| `process_midi(msg,len,out[])` per event | RtMidi input callback → `process_midi` → send `out[]` on `Mockba Acid:Out` |
| `tick(frames, sample_rate, out[])` per 128-frame audio block | timer thread, ~2.9 ms, `frames` = **measured** elapsed samples so free-run tempo survives scheduler jitter |
| `set_param(key, "0.42")` from a knob edit | CC on the control channel → look up `key`, rescale 0–127 → range, format, `set_param` |
| `host->get_bpm()` | EMA of 0xF8 inter-pulse interval (`note_clock_pulse`) |
| `host->get_clock_status()` | `RUNNING` on 0xFA/0xFB, `STOPPED` on 0xFC, auto-demote to `STOPPED` after 500 ms of clock silence |
| output forced to the slot's one channel (`chain_midi.c` nibble rewrite) | `send_out()` rewrites the channel nibble per-sequencer (`a_channel`/`b_channel`) |
| everything on one audio thread | one `std::mutex` serialises every call into the core (input callback vs. timer) |

**Threading.** Move's contract is "there is no control thread, everything is
the audio callback." The shim keeps the spirit: one mutex, every core call
under it. Contention is a handful of 3-byte messages per 16th note plus one
`tick` every 2.9 ms — nil. The core does its own `malloc` only in
`create_instance` (once, before the threads start), so the RT-safety rules
that dominate the Move build don't constrain us here.

### Toolchain

Force userland: `ELF 32-bit LSB, ARM EABI5, /lib/ld-linux-armhf.so.3`, "for
GNU/Linux 3.2.0". `scripts/Dockerfile` + `scripts/build.sh` build **natively
for armhf inside a QEMU-emulated container** (`--platform linux/arm/v7`,
base image `arm32v7/debian:stretch` — buster's archived apt repo can't
resolve `g++`'s dependency chain once security/updates are stripped, stretch
doesn't hit that) — same shape as other MockbaMod addons' `compile_pi.sh`
pattern, just on emulated hardware instead of a real Pi. `build.sh` prints
the highest `GLIBC_*`/`GLIBCXX_*` symbol version the binary needs so it can
be checked against the device's actual libc/libstdc++ (comfortably ahead in
practice — verified live against `libstdc++.so.6.0.32` on the test device).

## Semantic deltas from the Move version

1. **No knob feedback yet.** Move re-reads `get_param` to redraw knob
   values; a Force track's knobs are one-way. Turning a physical knob sends
   CC and the value takes effect, but nothing pushes the generator's
   current value back to the surface (see Known limitations).
2. **Generate / Mutate are CC buttons.** `access:"write"` enums on Move;
   here a CC ≥ 64 fires the trigger, CC < 64 (the release) is ignored, so a
   latching pad or a knob detent both work as a one-shot.
3. **Length / Swing** arrive as 0–127 and are rescaled to 2–32 / 50–75. On
   Move they ride a range-normalised knob curve; the CC rescale is the
   linear equivalent.
4. **BPM is estimated, not told.** Move hands the core an exact host BPM.
   Here it's derived from clock pulses, so `samples_per_step` (used for
   gate length and free-run between clocks) can lag a fast tempo ramp by a
   few EMA steps. Stepping itself rides the clock directly and is
   unaffected.
5. **Transport = MIDI transport.** The Force must be set to send Sync +
   Clock to `Mockba Acid:In`. Without clock the shim free-runs at `--bpm`
   (default 120) and never advances `RUNNING` — matches `acid.c`'s
   "no transport" behaviour.

## Force-only additions

Move's chain host forces every MIDI FX slot onto one output channel, which
is why upstream `schwung-acid` has Blend instead of real A/B routing.
Force's own host (`host_shim.cpp`, a standalone process, not a chain slot)
has no such restriction, so several things become possible that Move can't
have:

- **Independent per-sequencer output channel** (`a_channel`/`b_channel`,
  CC 28/48) — the original tb3po's two-separate-outputs design, restored.
  Blend is unchanged and still applies on top; splitting to two channels
  doesn't retire it, it just means the two sides can *also* land on
  separate instrument tracks.
- **Independent per-sequencer Auto Regen** (`a_auto_gen`/`b_auto_gen`,
  CC 31/51) — replaces upstream's single shared Auto Gen; each sequencer's
  `auto_gen_idx`/`auto_gen_step_count` live on its own `acid_seq_t` rather
  than the shared instance struct.
- **CV Mode** (`cv_mode`, CC 79) — retargets both sequencers' output for a
  Force CV track: accent becomes velocity-only at the widest swing (1
  normal / 127 accented, not scaled by Blend, since Blend crossfades two
  sequencers sharing one *audio* destination — that doesn't apply once each
  is routed to its own separate CV/Gate hardware), and slide moves from CC65
  (Portamento) to CC1 (Mod Wheel) to match a CV track's row-assignment
  conventions. See `docs/CC-MAP.md`'s "CV Mode" section for the full
  behaviour.
- **Export as MIDI Clip** (`a_dump`/`b_dump`, CC 32/52) — a web-panel button
  per sequencer that writes the current pattern to a Standard MIDI File.
  Deliberately not a live capture: `process_dump_for_seq()` replays the
  seq's step buffer on its own fixed, tempo-independent 60 ms/step cadence,
  using entirely separate `dump_*` state from live playback, on a dedicated
  channel (16) that never carries live notes — so exporting can never
  disturb, or be corrupted by, live playback of either sequencer.
  `web/server.py` captures that stream and reconstructs a clean
  16th-note-grid clip.

All of the above is confirmed working end-to-end on a real Force. Search
`FORCE-ONLY` in `src/acid_core.c`/`src/host_shim.cpp` for every touch point.

## Known limitations

- **No control-surface feedback.** Move re-reads `get_param` to redraw
  knob positions; the Force host has no equivalent path yet — CC in only.
  Turning a physical knob or the web panel updates the generator, but
  nothing pushes the current value back to a knob, the web panel (opening
  it fresh, or another track also sending CC, will desync its display from
  reality), or the touchscreen page. Planned: CC-out on channel 16 (the
  channel already reserved for Export's own use, since Export and feedback
  never need to be live at once).
- **`.xtk` track template not yet visually confirmed on a real touchscreen
  track-template screen.** `addon/Force Acid Control.xtk` is structurally
  valid (round-trips through gzip/JSON, matches a real reference file's
  shape, and known donor-addon leftovers from the reverse-engineering
  process have been scrubbed — see `docs/capture-xtk.md`), but whether it
  actually loads with correct knob names/ranges and whether Generate/Mutate
  behave as momentary triggers rather than sticky positions still needs
  someone at the touchscreen to confirm.
- **`preset save/recall`** is not implemented — matches upstream
  `schwung-acid`, which also has none.
