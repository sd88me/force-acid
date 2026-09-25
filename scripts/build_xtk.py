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

LEFTOVER-DATA FIX (found by on-device inspection): the seed's `customQLinks`
was fully overwritten already, but `data.program.customisable.mapping` (a
127-entry automation-parameter-name table) was NOT -- it's a leftover
catalog of a *different* addon's own generator engine (its `name` fields
read like "1 Mode 0-25 (1 Cluster 0-59)", "1 Rand Rotate (CC 86)" etc, and
one of its own `customQLinks[].targetData[].track` fields literally says
"RiffMaker 4T" -- so this seed's mixer/pad-bank chrome came from Harpie4T,
but this particular mapping table reflects whatever RiffMaker-generator
track that Harpie4T instance happened to be controlling when it was
captured). None of that belongs to force-acid and would leak into the
Force's own automation-parameter picker for this track. `blank_mapping()`
below zeroes every entry to the same shape real "unused" slots already use
elsewhere in the same file (`{"automationIndex": 2147483647, "value": 0.0,
"name": ""}` -- 30 of the original 127 entries already look exactly like
this, so it's not a guess, it's the file's own "empty" convention), keeping
`parameterIndex` untouched since that's positional/structural, not a label.

Usage:
    python3 scripts/build_xtk.py                          # seed + our KNOBS -> .xtk + .json
    python3 scripts/build_xtk.py --track-name "MY TRACK"
    python3 scripts/build_xtk.py --pack path/to/edited.json --out "addon/Force Acid Control.xtk"
        # skip seed/KNOBS generation entirely -- just re-pack an already-assembled
        # (and possibly hand-edited) JSON dump back into .xtk framing. Use this to
        # review/tweak a previous build's .json output on real hardware findings
        # and rebuild without touching this script.
"""
import argparse
import copy
import gzip
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED_PATH = HERE / "xtk-seed.json"
HOST_PARAMS_PATH = HERE.parent / "src" / "host_shim.cpp"
HEADER = "ACVS\n3.3.0.0\nSerialisableTrackData\njson\nLinux\n"

PARAMS_LINE_RE = re.compile(r'\{\s*"(\w+)"\s*,.*,\s*(-?\d+)\s*\}')


def parse_host_params(host_path):
    """Parse (key, cc) pairs straight out of the host's own PARAMS[] table
    -- so the mapping table below can never silently drift from what the
    host actually listens for, the same principle as KNOBS but for every CC
    the host has, not just the 16 that fit on the Q-Link bank. Returns
    [(key, cc), ...] in table order.
    """
    text = Path(host_path).read_text()
    m = re.search(r"static const ParamSpec PARAMS\[\]\s*=\s*\{(.*?)\n\};", text, re.DOTALL)
    if not m:
        sys.exit(f"couldn't find PARAMS[] table in {host_path}")
    entries = []
    for line in m.group(1).splitlines():
        em = PARAMS_LINE_RE.match(line.strip())
        if em:
            entries.append((em.group(1), int(em.group(2))))
    return entries


def label_from_key(key):
    """Auto-derived display label for CCs outside the curated KNOBS list --
    everything the web GUI exposes that the 16-knob Q-Link bank has no room
    for. Deliberately not hand-maintained (unlike KNOBS's labels), so it
    can't drift from the host's own key names either."""
    return key.upper().replace("_", " ")

# Sentinel automationIndex the file's own schema already uses for "this slot
# has no automation target" -- see LEFTOVER-DATA FIX above.
UNUSED_AUTOMATION_INDEX = 2147483647

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

# Strings that must never survive into the built .xtk -- anything from a
# donor addon's own captured state that isn't ours. Checked by audit() after
# every build so a future seed swap/re-capture can't silently reintroduce
# this same leak.
FORBIDDEN_SUBSTRINGS = ["RiffMaker", "Harpie"]


def display_order(items):
    """Force lays a Q-Link bank's 16 slots into an on-screen 4x4 grid
    bottom-up: array index 0 renders bottom-left, index 15 top-right
    (confirmed on real hardware -- both the Q-Link assign editor and the
    track overview page agree on this). To make the grid read top-to-bottom
    in the same order KNOBS lists them, reverse the array in blocks of 4
    (one block per display row); columns within a row keep their order.

    Side effect, unavoidable: this also changes which physical Q-Link knob
    number is bound to which parameter (whatever ends up at array index 0
    becomes hardware Q-Link knob 1), since screen position and array index
    are the same thing on this device. There's no way to change the visual
    order without also changing that binding.
    """
    cols = 4
    rows = 4  # a Q-Link bank is always 16 physical slots / 4 rows
    slots = [None] * (rows * cols)
    for d, item in enumerate(items):
        row, col = divmod(d, cols)
        slots[(rows - 1 - row) * cols + col] = item
    return [x for x in slots if x is not None]


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


def fix_midi_routes(doc, control_channel):
    """Point data.midiInputRoute/midiOutputRoute at force-acid's own ALSA
    ports instead of the leftover "Mockba Harpie 4T" one -- see
    LEFTOVER-DATA FIX.

    CORRECTED (previous version of this function used the wrong name -- see
    below): host_shim.cpp passes "Mockba Acid" as the RtMidi client name,
    but that is NOT what actually shows up in ALSA/mido's port list on real
    hardware. Confirmed live (mido.get_output_names()/get_input_names(),
    same investigation that fixed web/server.py's identical bug --
    web/server.py's IN_PORT_MATCH/OUT_PORT_MATCH comment has the full
    story): MockbaMod reorders it into "Acid:In (Mockba)" /
    "Acid:Out (Mockba)" (an ephemeral numeric client:port suffix follows,
    e.g. "... 141:0", which is NOT included here since it's assigned fresh
    every boot). The previous version of this function used the seed's own
    "Mockba Harpie 4T" / "Mockba Harpie 4T - CH:13" convention verbatim
    with force-acid's name substituted in, which was never actually
    correct on this device -- that donor sample was very likely captured
    against a different RtMidi/MockbaMod version's naming behavior.

    STILL UNCONFIRMED: whether Force's own route-matching needs the literal
    "(Mockba)" suffix, does prefix matching, or something else; whether the
    "- CH:N" suffix the donor sample had on its output route matters at all
    here (dropped -- no evidence it's part of this device's real
    convention, unlike the base name which is now directly observed).
    `deviceId` (e.g. "137-0") looks like a cached, per-boot-ephemeral ALSA
    client:port number -- reset to "0-0" here as a clearly-unresolved
    placeholder on the assumption Force re-resolves routes by deviceName
    when the cached id doesn't match anything live -- not verified. If
    Q-Link changes don't reach force-acid after loading this template,
    re-pointing the track's MIDI I/O by hand once in the Force UI should
    also fix the deviceId going forward; report back either way.
    """
    ch0 = control_channel - 1  # host_shim.cpp/force-acid.conf are 1-based; the numeric
                                # outputChannel field itself is 0-based.
    client = "Acid"

    in_route = doc["data"]["midiInputRoute"]
    in_route["inputPort"]["deviceName"] = f"{client}:In (Mockba)"
    in_route["inputPort"]["deviceId"] = "0-0"
    in_route["inputChannel"] = ch0

    out_route = doc["data"]["midiOutputRoute"]
    out_route["outputPort"]["deviceName"] = f"{client}:Out (Mockba)"
    out_route["outputPort"]["deviceId"] = "0-0"
    out_route["outputChannel"] = ch0


def blank_mapping(doc):
    """Rebuild data.program.customisable.mapping from KNOBS -- see
    LEFTOVER-DATA FIX.

    REAL-HARDWARE FINDING: this table, not customQLinks, is what the
    Force's on-screen custom-knob page actually renders. automationIndex is
    a MIDI CC number (RiffMaker4T's own real CC scheme, e.g. CC 24 ->
    "1 DIV 0-10"), and `name` is that CC's display label. Confirmed by
    comparing a live screenshot of the unmodified RiffMaker4T track
    (correct custom names) against ours (showing "CC 24", "CC 29" etc. with
    RiffMaker's own leftover *values* like 0.007874015718698502 -> "1") --
    Force falls back to a built-in MIDI-standard name (CC 11 = "Expression")
    or a bare "CC <n>" label whenever `name` is empty, which is what merely
    blanking `name` on every entry produced.

    The only correct fix is to actually populate this table with our own CC
    numbers and labels, and blank every other slot to the file's own
    "unused slot" shape (automationIndex sentinel, name/value empty) so no
    RiffMaker/Harpie CCs or names survive either.

    COVERAGE: this table has 127 slots and isn't limited to one Q-Link
    bank's 16 knobs the way customQLinks is -- the web GUI exposes every CC
    the host listens to (see docs/CC-MAP.md), so this on-screen page should
    too, not just the 16 that fit on a physical Q-Link bank. The first 16
    slots get the Q-Link-covered CCs in KNOBS, reordered for correct
    top-to-bottom reading on page 1 (hardware-confirmed -- see
    display_order()); every other CC the host has (parsed straight out of
    its own PARAMS[] table via parse_host_params(), never hand-copied, so
    it can't drift) fills the remaining slots after that, in the host's own
    table order. Whether the same bottom-up-per-page quirk applies to pages
    beyond the first isn't hardware-confirmed -- if page 2+ reads bottom-up
    on a real screen too, apply display_order() to chunks of those as well.
    """
    mapping = doc["data"]["program"]["customisable"]["mapping"]
    for entry in mapping:
        entry["automationIndex"] = UNUSED_AUTOMATION_INDEX
        entry["value"] = 0.0
        entry["name"] = ""
    for slot, (_key, label, cc, _momentary) in zip(mapping, display_order(KNOBS)):
        slot["automationIndex"] = cc
        slot["name"] = label
        slot["value"] = 0.0

    knob_ccs = {k[2] for k in KNOBS}
    extra = [(key, cc) for key, cc in parse_host_params(HOST_PARAMS_PATH) if cc not in knob_ccs]
    for slot, (key, cc) in zip(mapping[len(KNOBS):], extra):
        slot["automationIndex"] = cc
        slot["name"] = label_from_key(key)
        slot["value"] = 0.0


def rename(obj, template_name):
    """Self-referential name fields -- everywhere the seed said "Harpie 4T
    Control" (its own template name), swap in ours. Leave targetData's
    "track" fields alone -- those are the *destination* MIDI track name and
    get fully replaced by make_qlink() already."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "name" and isinstance(v, str) and v.startswith("Harpie 4T Control"):
                obj[k] = v.replace("Harpie 4T Control", template_name)
            else:
                rename(v, template_name)
    elif isinstance(obj, list):
        for item in obj:
            rename(item, template_name)


def audit(doc):
    """Scan the final doc for leftover donor-addon strings. Returns a list of
    JSON-path strings where something forbidden was found (empty = clean)."""
    hits = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}/{k}")
        elif isinstance(o, list):
            for i, item in enumerate(o):
                walk(item, f"{path}[{i}]")
        elif isinstance(o, str):
            for bad in FORBIDDEN_SUBSTRINGS:
                if bad in o:
                    hits.append(f"{path} = {o!r}")
    walk(doc, "")
    return hits


def build_doc(track_name, template_name, control_channel):
    if not SEED_PATH.exists():
        sys.exit(f"seed file missing: {SEED_PATH}")
    doc = json.loads(SEED_PATH.read_text())

    program = doc["data"]["program"]
    program["customQLinks"] = [
        make_qlink(label, cc, track_name, momentary)
        for (_key, label, cc, momentary) in KNOBS
    ]
    blank_mapping(doc)
    fix_midi_routes(doc, control_channel)
    rename(doc, template_name)
    return doc


def write_xtk(doc, out_path):
    body = HEADER + json.dumps(doc, indent=4)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(out_path, "wb", mtime=0) as f:
        f.write(body.encode("utf-8"))


def write_json(doc, out_path):
    """Always emitted alongside the .xtk -- the human-reviewable form. Edit
    this file and re-run with --pack to rebuild without touching this
    script's generation logic."""
    out_path.write_text(json.dumps(doc, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track-name", default="ACID CTRL",
                     help='must match the MIDI track name exactly once loaded on the Force (default: "ACID CTRL", matching addon/README.txt)')
    ap.add_argument("--out", default=str(HERE.parent / "addon" / "Force Acid Control.xtk"))
    ap.add_argument("--template-name", default=None,
                     help="self-referential name Force gives the NEW track it creates when "
                          "loading this .xtk (Force's track-template loader always creates a "
                          "new track, never merges onto one you already have) -- defaults to "
                          "--track-name so the created track is already correctly named and "
                          "self-targets without a manual rename step; override only if you "
                          "want the loaded track to have a different display name than the "
                          "Q-Link targets bind to")
    ap.add_argument("--control-channel", type=int, default=1,
                     help="1-16, must match force-acid's control_channel (default 1) -- "
                          "used for this track's MIDI I/O route, not the Q-Link CC targets")
    ap.add_argument("--pack", metavar="JSON_PATH",
                     help="skip seed/KNOBS generation -- wrap this already-assembled "
                          "JSON file (e.g. a previous build's --out .json, hand-edited) "
                          "into .xtk framing instead")
    args = ap.parse_args()

    out_path = Path(args.out)
    json_path = out_path.with_suffix(out_path.suffix + ".json")

    if args.pack:
        pack_path = Path(args.pack)
        if not pack_path.exists():
            sys.exit(f"--pack file missing: {pack_path}")
        doc = json.loads(pack_path.read_text())
        print(f"packing {pack_path} (skipping seed/KNOBS generation)")
    else:
        template_name = args.template_name or args.track_name
        doc = build_doc(args.track_name, template_name, args.control_channel)

    hits = audit(doc)
    if hits:
        print("WARNING: leftover donor-addon strings survived into the build:", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        sys.exit(1)

    write_xtk(doc, out_path)
    write_json(doc, json_path)

    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")
    print(f"wrote {json_path} (reviewable JSON -- edit + --pack it to rebuild)")
    if not args.pack:
        program = doc["data"]["program"]
        print(f"Q-Link bank: {len(program['customQLinks'])} knobs, track name '{args.track_name}'")
        print("Load it on the Force onto a MIDI track literally named "
              f"'{args.track_name}' -- the CC targets are bound by track NAME, not by track index.")


if __name__ == "__main__":
    main()
