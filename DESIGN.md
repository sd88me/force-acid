# force-acid — porting `schwung-acid` to the Akai Force (MockbaMod)

Status: **v0.1.0 — built and hardware-verified.** Native armhf binary built
(Debian stretch/QEMU toolchain — see "Toolchain" below for why buster doesn't
work) and confirmed working end-to-end on a real Force: virtual ports register
correctly (`aconnect -l` shows client `Mockba Acid` with `In`/`Out` ports),
real Force MIDI clock (0xF8/0xFA/0xFC) drives stepping, and generated
note-on/off + slide CC(65) reach `Mockba Acid:Out` with correct
accent/normal velocities. Remaining v0.2 items are listed in "TODO before
calling it v1" below.

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

`scripts/Dockerfile` + `scripts/build.sh` build **natively for armhf inside a
QEMU-emulated container** (`--platform linux/arm/v7`) — `apt install g++
libasound2-dev`, plain `gcc`/`g++`, dynamic link. Same shape as Euclidier's
`compile_pi.sh`, just on emulated hardware instead of a real Pi. Chosen over a
cross toolchain because the cross package ships no armhf ALSA and RtMidi's
ALSA backend needs `<alsa/asoundlib.h>` + `-lasound`; native armhf gets both
from one `apt` line, and glibc/GLIBCXX are automatically the device's ABI
family.

**Base image is `arm32v7/debian:stretch`, not `buster`.** Buster was the
original choice but its archived apt repo (`archive.debian.org`, since buster
is EOL) fails to resolve `g++`'s dependency on `g++-8` — "held broken
packages" — once the security/updates suites are stripped out (they have to
be: their Release files are expired and archive.debian.org doesn't mirror the
point-release fixups buster's g++-8 needs). Stretch's package set doesn't hit
this; the build works cleanly. Verified against the real device with
`strings /usr/lib/libstdc++.so.6.0.32` over SSH: the Force ships
`GLIBCXX_3.4.32` — comfortably newer than anything this or the other RtMidi
addons need — so stretch's older/lower symbol requirements are not a
compatibility risk, only a "furthest safely-old baseline" choice.

`build.sh` prints the highest `GLIBC_*` symbol version the binary actually
needs. This build: `GLIBC_2.4`, `GLIBCXX_3.4.22` — both well under the
device's actual ceiling (confirmed live: `libc.so.6` and
`libstdc++.so.6.0.32` on the Force satisfy both with room to spare).

Emulation: Docker Desktop registers binfmt automatically. On a bare Linux
dockerd, run once:
`docker run --rm --privileged multiarch/qemu-user-static --reset -p yes`.

Fallbacks if a future toolchain bump ever produces a binary that won't run on
the Force (`GLIBC_2.xx not found` / `GLIBCXX_3.4.xx not found`):
- build on a real Raspberry Pi OS 32-bit (`compile_pi.sh` style), or
- `apt`-install `g++`/`libasound2-dev` on the Force itself over SSH (the `/usr`
  overlay is writable) and compile there.

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

- [x] `build.sh` actually produces a runnable armhf binary — fixed (stretch
      base, see "Toolchain"), built successfully, `dist/force-acid-addon.tar.gz`
- [x] hardware smoke test: ports appear (`aconnect -l` shows `Mockba Acid`
      client with `In`/`Out`), clock starts it (real Force-clock-driven test:
      19 note-on/19 note-off + slide CC65 observed on `Mockba Acid:Out` over
      ~4s of injected 0xF8/0xFA/0xFC), a CC moves a param (verified via `-v`
      log during manual testing; the `a_generate` trigger (CC20) was also
      sent mid-run without disrupting the note stream)
- [x] capture a real `.xtk` template, commit it, reference from `README.txt`
      — turned out not to need real-hardware capture at all: `.xtk` is a
      5-line header + gzip-compressed JSON, reverse-engineered from a real
      Harpie4T template pulled over SSH. `scripts/build_xtk.py` generates
      `addon/Force Acid Control.xtk` (16 Q-Link knobs, Seq A+B's core
      controls) from `scripts/xtk-seed.json`. Structurally valid
      (round-trips through gzip/JSON, matches the real file's shape) but
      **not yet visually confirmed on a real screen** — see
      `docs/capture-xtk.md` for exactly what's unconfirmed (`momentary`/
      `paramType` semantics) and what to check.
- [x] fix leftover donor-addon data in the `.xtk` seed, found by on-device
      inspection: `customisable.mapping` (127 entries) carried a different
      addon's own generator-parameter names, and `midiInputRoute`/
      `midiOutputRoute` pointed at `"Mockba Harpie 4T"` instead of
      force-acid's own `"Mockba Acid"` ALSA client. Both scrubbed in
      `build_xtk.py` (`blank_mapping()`/`fix_midi_routes()`); an `audit()`
      pass now refuses to build if any donor-addon string survives. Also
      added: every build always emits a reviewable `<out>.json` alongside
      the `.xtk`, and `--pack` repacks a (possibly hand-edited) JSON dump
      straight back into `.xtk` framing. See `docs/capture-xtk.md`.
- [x] decide A/B split-channel mode (flag) vs. keep merged-only — went with
      always-available independent `a_channel`/`b_channel` (not a flag),
      since Force's host has no reason to force one-channel-only the way
      Move's chain host does. Blend is unchanged and still applies on top.
      Hardware-verified: A/B note streams land on distinct MIDI channels,
      each carrying its own slide CC65.
- [x] port the current schwung-acid upstream (v1.1.1) forward: Jitter,
      per-sequencer Offset/Direction (Fwd/Rev/Pendulum), Auto Gen, and the
      expanded 12-scale set — all hardware-verified (CCs 28-30/48-50/78-79,
      see `docs/CC-MAP.md`). `acid_core.c` is upstream verbatim plus the
      channel patch above, both marked `FORCE-ONLY`.
- [x] split the single shared Auto Gen into independent per-sequencer
      `a_auto_gen`/`b_auto_gen` (CCs 31/51, relabeled "Auto Regen"/"REGEN" on
      the web panel) — another `FORCE-ONLY` divergence from upstream's one
      shared control, same pattern as `a_channel`/`b_channel`. `auto_gen_idx`/
      `auto_gen_step_count` moved from the shared instance struct onto each
      `acid_seq_t`. Hardware-verified: A and B hold independent Auto Regen
      values simultaneously and echo back correctly via `/state`.
- [x] CV Mode (`cv_mode`, CC 79, reusing the retired shared Auto Gen slot) --
      `FORCE-ONLY`, for routing both sequencers to a Force CV track driving
      external CV/Gate hardware (e.g. a Behringer TD-3-MO) instead of a MIDI
      synth. In `emit_step_for_seq()`: accent becomes velocity-only at the
      widest swing (1 normal / 127 accented) for a Velocity CV row, and is
      NOT scaled by Blend (Blend crossfades two sequencers sharing one
      audio destination, which doesn't apply when each is routed to its own
      separate CV hardware); Slide moves from CC65 (Portamento) to CC1 (Mod
      Wheel) for a Mod Wheel CV row. See docs/CC-MAP.md's "CV Mode" section.
- [ ] control-surface feedback (CC out on ch 16)
- [ ] licensing note — inherits `schwung-acid`'s (tb3po = GPL-3.0); keep the
      `VEL_PYRAMID` attribution question from the upstream README in view
- [ ] not yet enabled for autolaunch on the test device (`manage.sh ENABLE`
      not run) — currently deploy-and-manually-run only, by design, pending a
      go-ahead to make it persistent

## Web control panel (`web/`)

v0.1 of a browser control surface exists and is hardware-verified: knobs +
buttons for the full CC map, TD-3-MO styling, engine start/stop from the
browser (the server runs on-device so it can `Popen`/`killall` the binary
directly). See `web/README.md` for details and known limitations (no
parameter feedback yet — same v0.2 gap as the CC-in-only control surface
generally). Not yet wired into `AddOns/` autolaunch.

**Gotcha worth recording**: the bundled `python-rtmidi` (via the `Python`
AddOn's `mido`) needs `LD_LIBRARY_PATH` pointed at that addon's `libjack`
folder just to *import* (it was built with JACK support), and separately,
opening a port via plain `mido.open_output(name)`/`open_input(name)` **hangs
forever** on this device unless you pass `api='LINUX_ALSA'` explicitly —
without it, rtmidi apparently tries JACK first and blocks waiting for a
server that isn't running. Cost real debugging time once; `web/server.py`
and any future Python-side MIDI tooling on this device should always pass
`api='LINUX_ALSA'`.
