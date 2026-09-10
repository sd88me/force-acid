# Capturing a Force track template (`.xtk`) for Force Acid

The Move version's UI is three pages of eight named knobs. The Force equivalent
that ships inside an addon (see Euclidier, RiffMaker4T) is a **track template**
— a `.xtk` file the user loads into a MIDI track, which pre-names and pre-maps
the eight control-surface knobs on each screen to our CCs.

`.xtk` is an undocumented Akai binary (zlib-ish container). We don't author it
by hand — we build it once on real hardware and commit the result.

## Procedure (needs a MockbaMod Force)

1. Install Force Acid and start it (`run_force-acid.sh`).
2. On the Force, create a **MIDI track**. Set its output to `Mockba Acid In`,
   channel 1.
3. Open the track's MIDI control / macro editor. Create **three screens**
   ("Seq A", "Seq B", "Global"). On each, assign the eight knobs to the CC
   numbers in `CC-MAP.md`, and set each knob's:
   - **name** (Generate, Mutate, Density, …)
   - **min / max** display range so the readout matches the real parameter
     (e.g. Octaves 1–3, Length 2–32, Blend −63…64, Swing 50–75)
   - for Generate / Mutate: a momentary / trigger knob type if the firmware
     offers one, else a 0/127 toggle
4. Save the track as a template. On MockbaMod the file lands under
   `Internal/Expansions/…` or the track-template folder as `*.xtk` (+ often a
   paired `*.xpm` MIDI map).
5. Pull it off over SSH:
   ```bash
   scp 'root@<force-ip>:/path/to/Force Acid Control.xtk' addon/
   ```
6. Commit it to `addon/`, add it to `scripts/build.sh`'s copy list, and mention
   it in `README.txt` ("load the included template into a MIDI track").

## Alternative: skip the template

MIDI-learn works with no template at all — assign any Force track's knobs to
the CCs directly. The template is a convenience, not a requirement, and v0.1
is usable without it.
