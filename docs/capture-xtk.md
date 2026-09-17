# The `.xtk` track template

**Update:** the original version of this doc assumed `.xtk` was "an
undocumented Akai binary" that had to be captured by hand on real hardware.
That was wrong — it's inspectable and directly authorable. Kept below for
the real format, how it was reverse-engineered, and what's still unverified.

## What it actually is

`.xtk` = a 5-line ASCII header, then a **gzip-compressed JSON document**:

```
ACVS
3.3.0.0
SerialisableTrackData
json
Linux
<gzip-compressed JSON follows>
```

Confirmed by pulling a real one off a live MockbaMod Force over SSH
(`Harpie4T/Harpie 4T Control.xtk`) and running it through `gunzip`/
`python3 -m json.tool` — it decompresses cleanly to `{"data": {...}}`, a large
JSON tree (track/mixer/pad-bank state) whose relevant part for a control
template is `data.program.customQLinks`: a **flat 16-entry array**, one per
Force Q-Link knob (Force's physical knob bank — 16 knobs, not "3 pages of 8"
like Move's UI; the Move-era plan in this file's earlier draft assumed the
wrong shape). Each entry:

```json
{
  "name": "DENSITY A",
  "controlType": 0,
  "targetData": [{
    "version": 1,
    "parameter": 22,
    "track": "ACID CTRL",
    "insertParamIndex": {"initialized": false},
    "instrumentIndex": 257,
    "paramType": 1,
    "controlInputRange": {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 2.0, "skew": 1.0},
    "parameterRange":    {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 0.0, "skew": 1.0},
    "behaviour": 0
  }],
  "momentary": 0,
  "controlValue": 0.0
}
```

- `parameter` — the CC number.
- `track` — the **name** of the destination MIDI track. Binding is by
  string match against the track's name in the Force session, not by track
  index/ID — the loaded template only works if a track is named exactly
  this.
- `instrumentIndex: 257` — constant across every entry in the one real file
  inspected. Meaning unconfirmed; left untouched.
- `paramType` — `1` on every continuous-knob entry seen; `0` on one
  momentary-style entry in the reference file. Not confirmed whether that's
  meaningful or incidental (see below).
- `momentary` — `1` on some entries (not consistently on what looked like
  the obvious "trigger" CCs in the reference file). Set to `1` for our own
  Generate/Mutate knobs on the theory that's clearly the intent; unconfirmed
  against real hardware behavior.

## How our template was built

`scripts/build_xtk.py` + `scripts/xtk-seed.json` (the decompressed JSON body
of that real Harpie4T template, used purely as a structural skeleton —
mixer/pad-bank/sample boilerplate we don't understand or need to change is
left byte-identical, on the theory that a file structurally identical to one
a real Force is known to load is far more likely to also load than a
hand-built minimal skeleton). The script rewrites `customQLinks` to our own
16 knobs (Seq A + Seq B's `generate/mutate/density/accent/slide/octaves/
length/gate`, CC 20-27 and 40-47) and the self-referential template name
fields, and re-emits the gzip+header framing.

```bash
python3 scripts/build_xtk.py                        # -> addon/Force Acid Control.xtk (+ .xtk.json)
python3 scripts/build_xtk.py --track-name "MY TRACK" # if you don't use "ACID CTRL"
```

Regenerate it (same command) if `docs/CC-MAP.md`'s CC assignments ever
change — the two need to stay in sync by hand, same convention as
`host_shim.cpp`'s `PARAMS[]` table.

### Leftover donor-addon data (found, fixed)

`customQLinks` was always fully overwritten, but on-device inspection found
the seed carried real, un-scrubbed state from whatever addon it was actually
captured controlling — not just Harpie4T's own chrome:

- `data.program.customisable.mapping` (127 entries) is a *different*
  addon's own generator-engine automation-parameter names (e.g. `"1 Mode
  0-25 (1 Cluster 0-59)"`, `"1 Rand Rotate (CC 86)"`) — would have leaked
  into the Force's automation-parameter picker for this track. Fixed by
  `blank_mapping()`: every entry reset to the same `{"automationIndex":
  2147483647, "value": 0.0, "name": ""}` shape real "unused" slots already
  use elsewhere in the same file (not a guess — 30 of the original 127
  entries already looked exactly like this).
- `data.midiInputRoute`/`midiOutputRoute` pointed at `"Mockba Harpie 4T"` —
  a literally different ALSA client than force-acid's own (`"Mockba Acid"`,
  see `host_shim.cpp`'s `--client` default). Fixed by `fix_midi_routes()`,
  same naming convention, our own client name and `--control-channel`.
  **Still unconfirmed on real hardware**: the cached `deviceId` fields
  (e.g. `"137-0"`) look like stale per-boot ALSA client:port numbers reset
  here to a `"0-0"` placeholder on the assumption Force re-resolves by
  `deviceName` when the id doesn't match — not verified. If Q-Link changes
  don't reach force-acid after loading the template, re-point the track's
  MIDI I/O by hand once in the Force UI and report back.

`audit()` now scans every build for leftover donor-addon strings
(`"RiffMaker"`, `"Harpie"`) and refuses to write a `.xtk` if any survive, so
a future seed re-capture can't silently reintroduce this same leak.

### Review / hand-edit / rebuild loop

Every build now always writes a second file next to the `.xtk`: the same
JSON body, pretty-printed, at `<out>.json` (e.g. `addon/Force Acid
Control.xtk.json`). That's the reviewable form — diff it, hand-edit it
after a real-hardware finding, then repack it straight back into `.xtk`
framing without touching the generation script:

```bash
python3 scripts/build_xtk.py --pack "addon/Force Acid Control.xtk.json"
```

**Only Seq A + Seq B's 8 core knobs each are covered (16 total = one full
Q-Link bank).** Global (scale/root/blend/swing/...) and the newer Advanced
controls (channel/offset/dir/jitter/auto_gen) aren't in this template —
they're reachable via plain MIDI-learn on any Force track, or from the web
control panel (`web/`), which covers every CC. A second template for a
second Q-Link bank is possible later if that turns out to matter in
practice.

## Status: NOT YET visually confirmed on a real screen

The file is structurally valid (round-trips through gzip/JSON correctly,
matches the real reference file's shape) and has been copied onto the test
Force. What hasn't been confirmed: actually loading it onto a MIDI track
named `ACID CTRL` in the Force UI and looking at whether the 16 knobs show
up with the right names/ranges, and whether Generate/Mutate feel like
momentary triggers rather than sticky positions. That needs someone at the
touchscreen — SSH/text tooling can't drive it. Report back either way (works
as-is / knob names missing / momentary feels wrong / wouldn't load at all) so
this doc and the `momentary`/`paramType` open questions above can be
corrected with a real answer instead of a guess.

## Fallback: skip the template

MIDI-learn works with no template at all — assign any Force track's knobs to
the CCs directly. The template is a convenience, not a requirement.
