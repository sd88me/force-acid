# Force Acid

A dual generative acid-bassline MIDI-FX for the Akai Force, running
[MockbaMod](https://github.com/MockbaTheBorg/MockbaMod). It's a port of
[`schwung-acid`](https://github.com/sd88me/schwung-acid), a native module for
Ableton Move — the same generator, ported to run as a standalone process on
the Force rather than inside Move's chain host.

**Force Acid is a pure MIDI-FX/generator, not an audio synth.** It reads the
Force's MIDI clock/transport and writes generated notes to a virtual MIDI
output port for you to route to an instrument track (or to a CV track for
external hardware). There's no audio DSP here and nothing to route through
`force-audio-jack` — it's a MIDI-only addon, simpler to install and run than
the voice-synth addons in this family.

## Features

- **Two independent generators (Seq A / Seq B)**, 2–32 steps each, sharing
  one Root/Scale. Each has its own Algo knob (1–16) blending:
  - a **primary model** (density/accent/slide/octave probabilistic
    generation, ported from `schwung-tb3po` / the Phazerville `TB_3PO`
    applet) — Algo 1 is 100% primary;
  - a **secondary model** (urn-style non-repeating pitch draw, a
    density-modulated bounded random walk for gate/rest, and a fixed
    accent-permutation shape) — Algo 16 is mostly secondary.
- **Generate / Mutate** per sequencer, Jitter, per-sequencer Offset and
  Direction (Fwd/Rev/Pendulum), a 12-scale set, Swing (internal free-run and
  24-PPQN clock-follow), Reset Both / polymeter, slide/portamento, and a
  bipolar Blend crossfade between A and B.
- **Independent per-sequencer output MIDI channel** (`a_channel`/
  `b_channel`) — Force-only: point Seq A and Seq B at two different
  instrument tracks and mix them on the Force's own mixer, or keep them on
  one channel and use Blend as before. Both work together.
- **Independent per-sequencer Auto Regen** (`a_auto_gen`/`b_auto_gen`) —
  Force-only periodic auto re-Generate (Off / 1 / 2 / 4 / 8 / 16 / 32 bars),
  set separately for each sequencer.
- **CV Mode** (`cv_mode`) — Force-only. Retargets accent to a full-range
  Velocity row and slide to Mod Wheel (CC1) instead of Portamento, for
  routing either sequencer straight to a Force CV track driving external
  CV/Gate hardware (e.g. a Behringer TD-3-MO) instead of a MIDI synth.
- **Export as MIDI Clip** (`a_dump`/`b_dump`) — Force-only. A web-panel
  button per sequencer that writes the current pattern to a Standard MIDI
  File, on a dedicated channel and cadence that never disturbs live
  playback.
- **Live transpose** — a note-on on the control channel transposes both
  sequencers together, C4 = no shift.
- A full **CC map** ([`docs/CC-MAP.md`](docs/CC-MAP.md)) covering every
  parameter, a **Force track template** (`addon/Force Acid Control.xtk`,
  16 Q-Link knobs pre-named for Seq A/B's core controls), a **browser
  control panel** (`web/`, styled after the Behringer TD-3-MO, covering the
  entire CC map plus engine start/stop and Export), and a **touchscreen
  page** (see below).

## Using Force Acid

On the Force: **Preferences → MIDI**, enable **Sync + Track** on
`Mockba Acid In` (so clock and your CC track both reach it) and **Track** on
`Mockba Acid Out`. Then create a MIDI track named `ACID CTRL` → output
`Mockba Acid In` channel 1, for CC control and note transpose (load
`Force Acid Control.xtk` onto it for pre-named Q-Link knobs). Create one or
two instrument tracks ← `Mockba Acid Out`, on whichever channel(s) you set
`a_channel`/`b_channel` to (both default to 1). Press Play.

## Touchscreen GUI (shadow mode)

A full editor page for the Force's own touchscreen, rendered by
[`force-shadow`](https://github.com/sd88me/force-shadow): open it with
`SHIFT+SCENE-5`, start/stop the engine from the ENGINE cell in the top bar.
Yellow chassis / charcoal boxes / red accent buttons, matching the web
panel's TD-3-MO styling.

| Tab | Contents |
|-----|----------|
| SEQ A | Generate/Mutate, Auto Regen, Direction, Algorhythm/Density/Accent/Slide/Gate/Octaves/Length/Offset knobs, Blend A>B, plus a GLOBAL box (Scale, Root, Reset, Swing, Jitter, A/B Channel, CV Mode) |
| SEQ B | Same layout for Sequencer B (Tune Offset in place of Blend), plus the same GLOBAL box |

## Requirements

- **MockbaMod** on the Force — nothing else. No `force-audio-jack`, no
  ROMs, no additional firmware or addon dependencies. Force Acid is a plain
  MIDI process; it never touches `LD_PRELOAD`/`acvs` at all, unlike the
  audio-synth addons in this family.

## Installation

```bash
FORCE_HOST=user@force-ip ./scripts/deploy.sh user@force-ip
```

This copies `addon/` to the Force's `AddOns/ForceAcid`, runs
`manage.sh ENABLE` (engine autolaunch) and `web/manage.sh ENABLE` (web panel
autolaunch) in one command. It supersedes the manual steps in
`scripts/install.sh`, which only handles the engine's own `manage.sh
ENABLE` and leaves the web panel to be enabled separately — `install.sh` is
still valid for an engine-only install, but `deploy.sh` is now the
recommended one-command path.

## Building from source / testing

```bash
./tests/run.sh          # generator logic check, no Docker needed
./scripts/build.sh       # -> dist/ForceAcid/ + tarball (needs Docker; native
                          # armhf build under QEMU, see DESIGN.md)
```

## Project layout

```
src/
  acid_core.c        schwung-acid's acid.c, verbatim but for the include line
  acid_core.h         the ~6 host symbols acid_core.c needs, re-declared
  host_shim.cpp        RtMidi virtual ports, CC->set_param, clock/BPM, timer, main()
  rtmidi/               vendored RtMidi 6 (ALSA backend)
addon/                MockbaMod addon: NSMODULE.json, manage.sh, run/conf, README,
                       Force Acid Control.xtk (Q-Link track template),
                       shadow_page.conf (touchscreen page)
scripts/              Dockerfile (armhf-native under QEMU), build.sh, deploy.sh,
                       install.sh, build_xtk.py + xtk-seed.json, gen_shadow_page.py
docs/                 CC-MAP.md, capture-xtk.md
tests/                native smoke test for the generator logic
web/                  browser control panel (TD-3-MO styled), server.py + static/,
                       manage.sh + run_forceacidweb.sh (autolaunches on boot,
                       independent of the engine's own manage.sh) — web/README.md
```

If you have the **nodeServer** AddOn installed, its home page can link
straight to the web panel — see
[`nodeserver-integration/README.md`](nodeserver-integration/README.md).

## Related projects & credits

- [MockbaMod](https://github.com/MockbaTheBorg/MockbaMod) — the Akai Force
  addon platform this runs on.
- [`schwung-acid`](https://github.com/sd88me/schwung-acid) — the Ableton
  Move module this is ported from; see its README for the Move-side UI and
  parameter design this port follows.
- [`schwung-tb3po`](https://github.com/charlesvestal/schwung-tb3po) by
  Charles Vestal — the origin of the primary generator (Algo 1), itself a
  port of djphazer's `TB_3PO` applet for the
  [O_C-Phazerville Hemisphere Suite](https://github.com/djphazer/O_C-Phazerville).
- The secondary generator's mechanisms were independently reimplemented,
  inspired by the behaviour of a Max for Live device, "Sting.amxd" by Iftah
  Gabbai (released under CC BY-NC-ND) — no code or assets from that device
  were used; only its observed behaviour informed an original
  implementation, so its licence terms don't carry over to this repository.

## License

GPL-3.0, repository-wide. See [`LICENSE`](LICENSE) for the full text and
attribution chain (schwung-tb3po → djphazer's TB_3PO/O_C-Phazerville, plus
the Sting.amxd inspiration note above).
