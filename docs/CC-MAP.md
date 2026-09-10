# Force Acid — CC map

Control channel: **1** by default (`control_channel` in `force-acid.conf`, or
`--control-channel`). Output channel: **1** (`output_channel` / `--out-channel`).

CC numbers are chosen to sit clear of the ranges MockbaMod's MidiLoop docs warn
about (0, 1, 32, 64, 121+). Three contiguous blocks, one per page of the Move
version's UI, eight controls each.

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
| **Seq B** | 40 | `b_generate` | ≥64 fires | |
| | 41 | `b_mutate` | ≥64 fires | |
| | 42 | `b_density` | 0–127 → 0.00–1.00 | |
| | 43 | `b_accent` | 0–127 → 0.00–1.00 | |
| | 44 | `b_slide` | 0–127 → 0.00–1.00 | |
| | 45 | `b_octaves` | 0–127 → 1–3 | |
| | 46 | `b_length` | 0–127 → 2–32 | |
| | 47 | `b_gate` | 0–127 → 0.05–1.00 | |
| **Global** | 50 | `scale` | 0–127 → 0–5 | Minor, Phrygian, HarmMinor, MinPent, Dorian, Major |
| | 51 | `root` | 0–127 → 0–11 | C … B |
| | 52 | `b_tune` | 0–127 → −24…+24 | Seq B interval from Seq A, semitones |
| | 53 | `blend` | 0–127 → −63…+64 | −63 = A only, 0 = both, +64 = B only |
| | 54 | `a_algo` | 0–127 → 1–16 | 1 = pure primary, 16 = mostly secondary |
| | 55 | `b_algo` | 0–127 → 1–16 | |
| | 56 | `reset_bars` | 0–127 → 0–4 | 1 / 2 / 4 / 8 bars, Off |
| | 57 | `swing` | 0–127 → 50–75 | 50 straight, 66 triplet, 75 max |

## Enum landing points

For the enum params the wire value is quantised to the nearest option index, so
the useful CC values are:

- **scale** (6): 0, 25, 51, 76, 102, 127
- **root** (12): 0, 12, 23, 35, 46, 58, 69, 81, 92, 104, 115, 127
- **reset_bars** (5): 0, 32, 64, 95, 127  (127 = Off)

## Note input

Note-on on the control channel **transposes** both sequencers, C4 (note 60) =
no shift, clamped ±48 semitones. Note-off is swallowed. Acid does not pass
played notes through to the synth — it only generates.

## Not mapped yet

- parameter feedback (surface ← generator): planned on channel 16, v0.2
- preset save/recall: not in this port
