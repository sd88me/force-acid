# force-acid

Port of [`schwung-acid`](https://github.com/sd88me/schwung-acid) — the dual
generative acid-bassline MIDI-FX for Ableton Move — to the **Akai Force**
running [MockbaMod](https://github.com/MockbaTheBorg/MockbaMod).

**Status: v0.2 in progress, hardware-verified.** The generator tracks
upstream `schwung-acid` (currently v1.1.1 — Jitter, per-sequencer Offset/
Direction, Auto Gen, 12-scale set, all ported); the Move chain-host is
reimplemented as a headless ALSA/RtMidi process, plus one Force-only
addition upstream can't have: **independent Seq A / Seq B output MIDI
channels** (`a_channel`/`b_channel`, like the original tb3po's two separate
outputs — Move's chain host forces one channel for the whole slot, Force's
host doesn't). All of the above is confirmed working end-to-end on a real
Force. A browser control panel (`web/`) and a Force track template
(`addon/Force Acid Control.xtk`) also exist — see below. See
[`DESIGN.md`](DESIGN.md) for what's still open before v1 (control-surface
feedback, confirming the `.xtk` template actually looks right on a real
screen).

## How the port works

| Layer | Move | Force |
|---|---|---|
| Generator | `dsp.so` (`acid.c`) | `src/acid_core.c` — **same file**, only the `#include` swapped |
| Host | Schwung chain, on the audio thread | `src/host_shim.cpp` — standalone process, RtMidi + a timer thread |
| Params | `module.json` knobs → `set_param("0.42")` | MIDI **CC** on a control channel → rescale → `set_param` |
| Clock | host `get_bpm` / `get_clock_status` | Force transport: MIDI clock + Start/Stop into the virtual port |
| UI | `ui_hierarchy`, knobs on the display | CC map ([`docs/CC-MAP.md`](docs/CC-MAP.md)); a Force track template ([`docs/capture-xtk.md`](docs/capture-xtk.md)); a browser panel (`web/`) |
| Output | one slot channel (forced by the chain host) | **independent channel per sequencer** (`a_channel`/`b_channel`, FORCE-ONLY — see `src/acid_core.c`'s header) |

## Layout

```
src/
  acid_core.c        schwung-acid's acid.c, verbatim but for the include line
  acid_core.h        the ~6 host symbols acid_core.c needs, re-declared
  host_shim.cpp      RtMidi virtual ports, CC→set_param, clock/BPM, timer, main()
  rtmidi/            vendored RtMidi 6 (ALSA backend)
addon/               MockbaMod addon: NSMODULE.json, manage.sh, run/conf, README,
                     Force Acid Control.xtk (Q-Link track template)
scripts/             Dockerfile (armhf-native under QEMU), build.sh, install.sh,
                     build_xtk.py + xtk-seed.json (generates the .xtk template)
docs/                CC-MAP.md, capture-xtk.md
tests/               native smoke test for the generator logic
web/                 browser control panel (TD-3-MO styled), server.py + static/,
                     manage.sh + run_forceacidweb.sh (autolaunches on boot,
                     independent of the engine's own manage.sh) — web/README.md
```

## Force track template + web panel + nodeServer link

- `addon/Force Acid Control.xtk` — 16 Q-Link knobs (Seq A + Seq B's core
  controls) pre-named and pre-ranged. Load it onto a MIDI track named
  exactly `ACID CTRL`. Reverse-engineered format, structurally valid but not
  yet visually confirmed on a real screen — see
  [`docs/capture-xtk.md`](docs/capture-xtk.md).
- `web/` — a standalone browser control panel covering every CC (including
  Global/Advanced, not just the 16 in the template), plus engine start/stop.
  See [`web/README.md`](web/README.md).
- If you have the **nodeServer** AddOn installed, its home page now has a
  "Force Acid" link straight to the panel (see nodeServer's `ENDPOINTS.js` —
  points at a small redirect endpoint, `forceacid.js`, rather than a plain
  link, because nodeServer's own link renderer mangles absolute URLs).

## Web control panel

`web/` is a standalone browser UI for the CC map — knobs, Generate/Mutate
buttons, and Scale/Root/Reset selectors, styled after the Behringer TD-3-MO,
plus start/stop control of the engine itself. Runs its own tiny Python server
directly on the Force (port 8303). See [`web/README.md`](web/README.md).

## Build & deploy

```bash
./tests/run.sh                                          # logic check, no Docker

./scripts/build.sh                                      # -> dist/ForceAcid/ + tarball  (needs Docker)
FORCE_HOST=root@<force-ip> ./scripts/install.sh --enable
```

Then on the Force: Preferences → MIDI, enable Sync+Track on `Mockba Acid In` and
Track on `Mockba Acid Out`; a MIDI track named `ACID CTRL` → `Mockba Acid In`
ch 1 for CC + note transpose (load `Force Acid Control.xtk` onto it for
pre-named knobs); one or two instrument tracks ← `Mockba Acid Out`, on
whichever channel(s) you set `a_channel`/`b_channel` to (both default to 1);
press Play.

## License

Inherits `schwung-acid`'s terms — the primary generator (Algo 1) is adapted
from `schwung-tb3po` (GPL-3.0). See the upstream README for the full
attribution chain and the `VEL_PYRAMID` table's status.
