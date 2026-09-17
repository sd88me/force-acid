# Force Acid — CC map

Control channel: **1** by default (`control_channel` in `force-acid.conf`, or
`--control-channel`). Output is now **two independent channels**, one per
sequencer (`a_channel`/`b_channel`, default **1** for both — see "Per-sequence
output channel" below) — this replaces the old single `output_channel`/
`--out-channel` concept entirely.

CC numbers are chosen to sit clear of the ranges MockbaMod's MidiLoop docs warn
about (0, 1, 32, 64, 121+). Four contiguous blocks: Seq A (20-31), Seq B
(40-51), and Global (70-79, split into the original 8 knobs plus an Advanced
block moved out to make room for each sequencer's own Advanced controls,
including each seq's own Auto Regen at 31/51).

| Page | CC | Param | Wire range → value | Notes |
|---|---|---|---|---|
| **Seq A** | 20 | `a_generate` | ≥64 fires | momentary; re-roll Seq A |
| | 21 | `a_mutate` | ≥64 fires | momentary; nudge ~25% of Seq A |
| | 22 | `a_density` | 0–127 → 0.00–1.00 | |
| | 23 | `a_accent` | 0–127 → 0.00–1.00 | |
| | 24 | `a_slide` | 0–127 → 0.00–1.00 | |
| | 25 | `a_octaves` | 0–127 → 1–3 | |
| | 26 | `a_length` | 0–127 → 2–32 | takes effect immediately |
| | 27 | `a_gate` | 0–127 → 0.05–1.00 | live |
| | 28 | `a_channel` | 0–127 → 1–16 | **FORCE-ONLY**, no Move equivalent |
| | 29 | `a_offset` | 0–127 → 0–31 | read-side rotation, clamped to `< a_length` |
| | 30 | `a_dir` | 0–127 → 0–2 | Fwd / Rev / Pendulum |
| | 31 | `a_auto_gen` | 0–127 → 0–6 | **FORCE-ONLY**; Off / 1 / 2 / 4 / 8 / 16 / 32 bars — periodic auto re-Generate, Seq A only |
| **Seq B** | 40 | `b_generate` | ≥64 fires | |
| | 41 | `b_mutate` | ≥64 fires | |
| | 42 | `b_density` | 0–127 → 0.00–1.00 | |
| | 43 | `b_accent` | 0–127 → 0.00–1.00 | |
| | 44 | `b_slide` | 0–127 → 0.00–1.00 | |
| | 45 | `b_octaves` | 0–127 → 1–3 | |
| | 46 | `b_length` | 0–127 → 2–32 | |
| | 47 | `b_gate` | 0–127 → 0.05–1.00 | |
| | 48 | `b_channel` | 0–127 → 1–16 | **FORCE-ONLY**, no Move equivalent |
| | 49 | `b_offset` | 0–127 → 0–31 | read-side rotation, clamped to `< b_length` |
| | 50 | `b_dir` | 0–127 → 0–2 | Fwd / Rev / Pendulum |
| | 51 | `b_auto_gen` | 0–127 → 0–6 | **FORCE-ONLY**; Off / 1 / 2 / 4 / 8 / 16 / 32 bars — periodic auto re-Generate, Seq B only |
| **Global** | 70 | `scale` | 0–127 → 0–11 | 12 options, see below |
| | 71 | `root` | 0–127 → 0–11 | C … B |
| | 72 | `b_tune` | 0–127 → −24…+24 | Seq B interval from Seq A, semitones |
| | 73 | `blend` | 0–127 → −63…+64 | −63 = A only, 0 = both, +64 = B only. Still applies on top of per-channel output — it's a velocity crossfade, not a routing switch |
| | 74 | `a_algo` | 0–127 → 1–16 | 1 = pure primary, 16 = mostly secondary |
| | 75 | `b_algo` | 0–127 → 1–16 | |
| | 76 | `reset_bars` | 0–127 → 0–4 | 1 / 2 / 4 / 8 bars, Off (default) |
| | 77 | `swing` | 0–127 → 50–75 | 50 straight, 66 triplet, 75 max |
| | 78 | `jitter` | 0–127 → 0.00–1.00 | per-tick chance of perturbing *which* step plays, never *when* |
| | 79 | `cv_mode` | 0–127 → 0–1 | **FORCE-ONLY**; Off / On — see "CV Mode" below |

## Per-sequence output channel (FORCE-ONLY)

Move's chain host forces every MIDI FX slot onto one output channel — that's
why upstream schwung-acid has Blend instead of real A/B routing. Force's own
host (`host_shim.cpp`, a standalone process, not a chain slot) has no such
restriction, so `a_channel`/`b_channel` give each sequencer its own
independently-selectable MIDI output channel, same as the original tb3po's
two separate Tool-slot outputs. Point Seq A and Seq B at two different Force
instrument tracks and mix them with the Force's own mixer, and/or keep them
on one channel and use Blend as before — both work together, Blend doesn't
go away.

Startup defaults (before any CC arrives) come from `--a-channel`/`--b-channel`
or `a_channel =`/`b_channel =` in `force-acid.conf` — both default to **1**,
matching the old single-channel behaviour until you separate them.

## Enum landing points

For the enum params the wire value is quantised to the nearest option index,
so the useful CC values are:

- **scale** (12): 0, 12, 23, 35, 46, 58, 69, 81, 92, 104, 115, 127 —
  Minor, Phrygian, HarmMinor, MinPent, Dorian, Major, PhrygDom, Locrian,
  WholeTone, HungMinor, MinBlues, Chromatic
- **root** (12): 0, 12, 23, 35, 46, 58, 69, 81, 92, 104, 115, 127
- **reset_bars** (5): 0, 32, 64, 95, 127 (127 = Off, the default)
- **a_dir / b_dir** (3): 0, 64, 127 — Fwd, Rev, Pendulum
- **a_auto_gen / b_auto_gen** (7): 0, 21, 42, 64, 85, 106, 127 — Off, 1, 2, 4, 8, 16, 32 bars
- **cv_mode** (2): 0, 127 — Off, On

## CV Mode (FORCE-ONLY)

For routing the two sequencers to a Force **CV track** driving external
CV/Gate hardware (e.g. a Behringer TD-3-MO's CV inputs) instead of a MIDI
synth. Force's own CV-track CC convention expects specific standard CCs on
specific rows (pitch from the note itself, Gate from note-on/off, Velocity
and Mod Wheel as the assignable continuous rows) — `cv_mode` retargets both
sequencers' output to fit that, without changing anything else:

- **Accent → Velocity.** Every note already carried its accent as a
  velocity difference (72 non-accented / 118 accented, scaled by Blend) for
  a velocity-sensitive synth's own dynamics. In CV Mode the swing widens to
  the full range instead — **1 for a normal note, 127 for an accented
  one** — so a CV row assigned to Velocity reads a clean near-0V/full-scale
  step rather than a subtle synth-dynamics nudge, and **Blend's scaling is
  bypassed entirely** for this: Blend crossfades two sequencers sharing one
  audio destination, which doesn't apply when each sequencer is instead
  routed to its own separate CV/Gate output — scaling the accent-CV level
  by an unrelated mix control would silently report "full accent" as
  something less than full-scale at any Blend setting other than that
  sequencer's own extreme.
- **Slide → Mod Wheel (CC1), not Portamento (CC65).** Same on/off (127/0)
  semantics as before, just a different destination CC, matching what a
  Force CV track's own row-assignment menu expects for this kind of
  continuous/switched control rather than a synth-specific portamento
  switch.
- Everything else (note pitch, gate/note-on-off timing, per-sequencer
  channel) is unaffected — set `a_channel`/`b_channel` to route each
  sequencer to its own CV track as usual.

## Note input

Note-on on the control channel **transposes** both sequencers, C4 (note 60) =
no shift, clamped ±48 semitones. Note-off is swallowed. Acid does not pass
played notes through to the synth — it only generates. Transpose is a single
shared control, unaffected by `a_channel`/`b_channel` — it moves both
sequencers together regardless of which channel(s) they're on.

## Not mapped yet

- parameter feedback (surface ← generator): planned on channel 16, v0.2
- preset save/recall: not in this port
