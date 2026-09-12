#!/usr/bin/env python3
"""Build addon/Force Acid Control.xtk -- a Force track template that
pre-assigns 16 Q-Link knobs (Force's physical knob bank) to the Seq A + Seq B
CCs from docs/CC-MAP.md, so loading it onto a MIDI track gets you named,
correctly-ranged knobs instead of hand MIDI-learning each one.

Background: .xtk was assumed to be "an undocumented Akai binary" (see
docs/capture-xtk.md's original plan: build one by hand on real hardware,
commit the result). It isn't -- pulling a real one off a live Force
(`Harpie4T/Harpie 4T Control.xtk`) and inspecting it showed:

    <5-line ASCII header>\n<gzip-compressed JSON>

    ACVS
    3.3.0.0
    SerialisableTrackData
    json
    Linux

The JSON's `data.program.customQLinks` is a flat 16-entry array (one Q-Link
knob bank), each entry roughly:

    {
      "name": "DENSITY A",             # shown as the knob's label; empty is legal
      "controlType": 0,
      "targetData": [{
        "version": 1,
        "parameter": 22,                # the CC number
        "track": "ACID CTRL",           # MUST match the MIDI track's name exactly
        "insertParamIndex": {"initialized": false},
        "instrumentIndex": 257,         # constant in every real sample seen -- meaning
                                         # unconfirmed, not touched
        "paramType": 1,                 # 1 = outbound MIDI CC (0 seen on one
                                         # momentary/trigger-style entry -- unconfirmed
                                         # whether that's meaningful or incidental)
        "controlInputRange": {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 2.0, "skew": 1.0},
        "parameterRange":    {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 0.0, "skew": 1.0},
        "behaviour": 0
      }],
      "momentary": 0,                   # 1 seen on some entries in the reference file,
                                         # 0 on others including its own Generate/Mutate --
                                         # semantics not confirmed; set to 1 here for our
                                         # Generate/Mutate since that's clearly the intent
      "controlValue": 0.0
    }

Everything else in the file (mixer/pad-bank/sample boilerplate) is left
byte-identical to the seed, on the theory that a file structurally identical
to one a real Force is known to load is far more likely to also load than a
hand-built minimal skeleton would be. `scripts/xtk-seed.json` is that seed --
the JSON body of `Harpie4T/Harpie 4T Control.xtk`, decompressed, pulled over
SSH from a live MockbaMod Force during development of this script. It's
structural/schema material (mixer defaults, empty pad banks), not anything
specific to Harpie4T's own generation logic.

CAVEAT: this is reverse-engineered from one sample file, not documented by
Akai/InMusic, and NOT YET CONFIRMED to load correctly in the Force's UI --
nobody has clicked through and looked at it on a real screen (that requires
touchscreen interaction this tooling can't perform). Load it once and check:
knob names show up, ranges look right, Generate/Mutate feel like triggers not
sticky values. Report back either way so this comment (and the momentary/
paramType question above) can be corrected.

Usage:
    python3 scripts/build_xtk.py [--track-name "ACID CTRL"] [--out "addon/Force Acid Control.xtk"]
"""
import argparse
import copy
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED_PATH = HERE / "xtk-seed.json"
HEADER = "ACVS\n3.3.0.0\nSerialisableTrackData\njson\nLinux\n"

# (key, label, cc, momentary)
KNOBS = [
    ("a_generate", "GENERATE A", 20, True),
    ("a_mutate",   "MUTATE A",   21, True),
    ("a_density",  "DENSITY A",  22, False),
    ("a_accent",   "ACCENT A",   23, False),
    ("a_slide",    "SLIDE A",    24, False),
    ("a_octaves",  "OCTAVES A",  25, False),
    ("a_length",   "LENGTH A",   26, False),
    ("a_gate",     "GATE A",     27, False),
    ("b_generate", "GENERATE B", 40, True),
    ("b_mutate",   "MUTATE B",   41, True),
    ("b_density",  "DENSITY B",  42, False),
    ("b_accent",   "ACCENT B",   43, False),
    ("b_slide",    "SLIDE B",    44, False),
    ("b_octaves",  "OCTAVES B",  45, False),
    ("b_length",   "LENGTH B",   46, False),
    ("b_gate",     "GATE B",     47, False),
]
assert len(KNOBS) == 16, "one Q-Link bank is 16 knobs -- trim/extend deliberately"

FULL_RANGE = {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 0.0, "skew": 1.0}
INPUT_RANGE = {"min": 0.0, "max": 1.0, "stride": 0.0, "deadspot": 2.0, "skew": 1.0}


def make_qlink(label, cc, track_name, momentary):
    return {
        "name": label,
        "controlType": 0,
        "targetData": [{
            "version": 1,
            "parameter": cc,
            "track": track_name,
            "insertParamIndex": {"initialized": False},
            "instrumentIndex": 257,
            "paramType": 1,
            "controlInputRange": dict(INPUT_RANGE),
            "parameterRange": dict(FULL_RANGE),
            "behaviour": 0,
        }],
        "momentary": 1 if momentary else 0,
        "controlValue": 0.0,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track-name", default="ACID CTRL",
                     help='must match the MIDI track name exactly once loaded on the Force (default: "ACID CTRL", matching addon/README.txt)')
    ap.add_argument("--out", default=str(HERE.parent / "addon" / "Force Acid Control.xtk"))
    ap.add_argument("--template-name", default="Force Acid Control")
    args = ap.parse_args()

    if not SEED_PATH.exists():
        sys.exit(f"seed file missing: {SEED_PATH}")

    doc = json.loads(SEED_PATH.read_text())

    program = doc["data"]["program"]
    program["customQLinks"] = [
        make_qlink(label, cc, args.track_name, momentary)
        for (_key, label, cc, momentary) in KNOBS
    ]

    # Self-referential name fields -- everywhere the seed said "Harpie 4T
    # Control" (its own template name), swap in ours. Leave targetData's
    # "track" fields alone -- those were just set above and mean something
    # different (the *destination* MIDI track name).
    def rename(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "name" and isinstance(v, str) and v.startswith("Harpie 4T Control"):
                    obj[k] = v.replace("Harpie 4T Control", args.template_name)
                else:
                    rename(v)
        elif isinstance(obj, list):
            for item in obj:
                rename(item)

    rename(doc)

    body = HEADER + json.dumps(doc, indent=4)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(out_path, "wb", mtime=0) as f:
        f.write(body.encode("utf-8"))

    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    print(f"Q-Link bank: {len(program['customQLinks'])} knobs, track name '{args.track_name}'")
    print("Load it on the Force onto a MIDI track literally named "
          f"'{args.track_name}' -- the CC targets are bound by track NAME, not by track index.")


if __name__ == "__main__":
    main()
