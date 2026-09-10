# force-acid — porting `schwung-acid` to the Akai Force (MockbaMod)

Status: **scaffold + first shim written, not yet built or hardware-tested.**

## Goal

Run the exact generator from
[`schwung-acid`](https://github.com/sd88me/schwung-acid) on a MockbaMod-modded
Akai Force, driven by the Force's transport and by CC from a Force MIDI track,
with as little change to the generator code as possible.

## What ports unchanged

`src/acid_core.c` is `schwung-acid/src/acid/dsp/acid.c` **verbatim** apart from
one hunk: the two Schwung headers are swapped for `src/acid_core.h`. All of the
following come across with zero edits:

- both generators (`gen_primary` = tb3po model, `gen_secondary` = Sting-style),
  the Algo 1–16 blend, `mutate_pattern`
- step→note mapping, scales, octave handling, C4-anchored live transpose
- Blend velocity crossfade, per-seq accent/normal ratio
- Swing (internal free-run **and** the 24-PPQN follow path)
- Reset Both / polymeter, gate-off accounting, slide/portamento (CC 65)
- the whole `set_param` / `get_param` string interface

`acid.c` already contains an external-MIDI-clock path (`0xF8/0xFA/0xFB/0xFC`
handling in `process_midi`, plus `get_bpm` / `get_clock_status` polling in
`tick`). That path was secondary on Move; on the Force it becomes the primary
sync. No new code in the core to make that happen.

## The host gap, and how the shim fills it

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
| `get_param` for UI repaint | not used yet (no control-surface feedback in v0.1) |
| `host->get_bpm()` | EMA of 0xF8 inter-pulse interval (`note_clock_pulse`) |
| `host->get_clock_status()` | `RUNNING` on 0xFA/0xFB, `STOPPED` on 0xFC, auto-demote to `STOPPED` after 500 ms of clock silence |
| output forced to the slot's one channel (`chain_midi.c` nibble rewrite) | `send_out()` rewrites the channel nibble to `--out-channel` — same single-stream model, so Blend-as-B-mute still holds |
| everything on one audio thread | one `std::mutex` serialises every call into the core (input callback vs. timer) |

### Threading

Move's contract is "there is no control thread, everything is the audio
callback." The shim keeps the spirit: **one mutex, every core call under it.**
Contention is a handful of 3-byte messages per 16th note plus one `tick` every
2.9 ms — nil. The core does its own `malloc` only in `create_instance` (once,
before the threads start), so the RT-safety rules that dominate the Move build
don't constrain us here.

## Semantic deltas from the Move version

1. **No knob feedback.** Move re-reads `get_param` to redraw knob values; a
   Force track's knobs are one-way. Turning a physical knob sends CC and the
   value takes effect, but nothing pushes the generator's current value back to
   the surface. Planned for v0.2 (send CC back on ch 16, the way Euclidier
   does).
2. **Generate / Mutate are CC buttons.** `access:"write"` enums on Move; here a
   CC ≥ 64 fires the trigger, CC < 64 (the release) is ignored, so a latching
   pad or a knob detent both work as a one-shot.
3. **Length / Swing** arrive as 0–127 and are rescaled to 2–32 / 50–75. On Move
   they ride a range-normalised knob curve; the CC rescale is the linear
   equivalent. `acid.c` already rounds these (declared `float`, used as `int`).
4. **BPM is estimated, not told.** Move hands the core an exact host BPM. Here
   it's derived from clock pulses, so `samples_per_step` (used for gate length
   and for free-run between clocks) can lag a fast tempo ramp by a few EMA
   steps. Stepping itself rides the clock directly and is unaffected.
5. **Transport = MIDI transport.** The Force must be set to send Sync + Clock to
   `Mockba Acid:In`. Without clock the shim free-runs at `--bpm` (default 120)
   and never advances `RUNNING` — matches `acid.c`'s "no transport" behaviour.
6. **One output channel**, exactly like the Move slot. Splitting A and B to two
   channels/ports is a possible v0.2 flag but changes the Blend-mutes-B model,
   so it's deliberately not the default.

## Control surface — the open piece

The Move version's UI (`ui_hierarchy` in `module.json`: three pages of eight
knobs) has **no direct Force equivalent**. Options, roughly in order of effort:

1. **MIDI-learn / a plain CC map (this is v0.1).** Any Force MIDI track: assign
   its 8 knobs per page to the CC blocks in `CC-MAP.md`. Zero extra tooling.
2. **A Force track template (`.xtk`)** with the three pages pre-named and
   pre-mapped, shipped in the addon — this is what Euclidier / RiffMaker do.
   `.xtk` is an undocumented Akai binary; we can't author it blind. Plan:
   build it once on a real Force from the CC map, pull it off over SSH, commit
   it. See `docs/capture-xtk.md`.
3. **A NodeServer web panel** (phone/laptop UI), like RiffMaker4T's remote
   editor. Most work; best UX; needs the NodeServer addon installed.

v0.1 ships option 1 and the map; option 2 is the intended "real" surface once
there's hardware to capture it on.

## Toolchain

Force userland: `ELF 32-bit LSB, ARM EABI5, /lib/ld-linux-armhf.so.3`,
"for GNU/Linux 3.2.0". Euclidier and the other addons top out at `GLIBC_2.4` /
`GLIBCXX_3.4.21` (≈ GCC 5.1).

`scripts/Dockerfile` uses **Debian Buster** (glibc 2.28, GCC 8) cross
(`g++-arm-linux-gnueabihf`) and **statically links libstdc++ / libgcc**, so the
compiler's C++ runtime never has to match the device. `libasound`, `libc`,
`libpthread` stay dynamic and resolve on-device.

Fallbacks if a glibc-version link/run error appears:
- build armhf-native on Raspberry Pi OS 32-bit (this is how Euclidier is built —
  `compile_pi.sh`), or
- `apt`-install `g++` on the Force itself over SSH (writable `/usr` overlay) and
  build there.

## Dependencies

- **RtMidi 6** — vendored in `src/rtmidi/` (`RtMidi.cpp` + `RtMidi.h`), ALSA
  backend (`-D__LINUX_ALSA__`). Same library Euclidier/RiffMaker link (their
  binaries show `../RtMidi/RtMidi.cpp`, `libasound.so.2`).
- **ALSA** (`libasound.so.2`) — present on the Force.

## Build / install / run

```bash
./scripts/build.sh                                  # -> dist/ForceAcid/ + tarball
FORCE_HOST=root@<force-ip> ./scripts/install.sh      # scp to /media/662522/AddOns/ForceAcid
FORCE_HOST=root@<force-ip> ./scripts/install.sh --enable   # + autolaunch at boot
```

Force IP: wifi screen, Shift + the info button. SSH user/pass `root` / `force`.

## TODO before calling it v1

- [ ] `build.sh` actually produces a runnable armhf binary (Docker not available
      in this environment yet — untested)
- [ ] hardware smoke test: ports appear, clock starts/stops it, a CC moves a param
- [ ] capture a real `.xtk` template, commit it, reference from `README.txt`
- [ ] control-surface feedback (CC out on ch 16)
- [ ] decide A/B split-channel mode (flag) vs. keep merged-only
- [ ] licensing note — inherits `schwung-acid`'s (tb3po = GPL-3.0); keep the
      `VEL_PYRAMID` attribution question from the upstream README in view
