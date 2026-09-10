# force-acid

Port of [`schwung-acid`](https://github.com/sd88me/schwung-acid) — the dual
generative acid-bassline MIDI-FX for Ableton Move — to the **Akai Force**
running [MockbaMod](https://github.com/MockbaTheBorg/MockbaMod).

**Status: v0.1.0 scaffold.** The generator is carried over byte-for-byte; the
Move chain-host is reimplemented as a headless ALSA/RtMidi process. Not yet
built with the real cross toolchain or tested on hardware. See
[`DESIGN.md`](DESIGN.md).

## How the port works

| Layer | Move | Force |
|---|---|---|
| Generator | `dsp.so` (`acid.c`) | `src/acid_core.c` — **same file**, only the `#include` swapped |
| Host | Schwung chain, on the audio thread | `src/host_shim.cpp` — standalone process, RtMidi + a timer thread |
| Params | `module.json` knobs → `set_param("0.42")` | MIDI **CC** on a control channel → rescale → `set_param` |
| Clock | host `get_bpm` / `get_clock_status` | Force transport: MIDI clock + Start/Stop into the virtual port |
| UI | `ui_hierarchy`, 3×8 knobs on the display | CC map ([`docs/CC-MAP.md`](docs/CC-MAP.md)); a `.xtk` template later |
| Output | one slot channel | one channel (`--out-channel`), same merged-stream model |

## Layout

```
src/
  acid_core.c        schwung-acid's acid.c, verbatim but for the include line
  acid_core.h        the ~6 host symbols acid_core.c needs, re-declared
  host_shim.cpp      RtMidi virtual ports, CC→set_param, clock/BPM, timer, main()
  rtmidi/            vendored RtMidi 6 (ALSA backend)
addon/               MockbaMod addon: NSMODULE.json, manage.sh, run/conf, README
scripts/             Dockerfile (armhf-native under QEMU), build.sh, install.sh
docs/                CC-MAP.md, capture-xtk.md
tests/               native smoke test for the generator logic
```

## Build & deploy

```bash
./tests/run.sh                                          # logic check, no Docker

./scripts/build.sh                                      # -> dist/ForceAcid/ + tarball  (needs Docker)
FORCE_HOST=root@<force-ip> ./scripts/install.sh --enable
```

Then on the Force: Preferences → MIDI, enable Sync+Track on `Mockba Acid In` and
Track on `Mockba Acid Out`; a MIDI track → `Mockba Acid In` ch 1 for CC + note
transpose; a synth track ← `Mockba Acid Out` ch 1; press Play.

## License

Inherits `schwung-acid`'s terms — the primary generator (Algo 1) is adapted
from `schwung-tb3po` (GPL-3.0). See the upstream README for the full
attribution chain and the `VEL_PYRAMID` table's status.
