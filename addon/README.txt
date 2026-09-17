*******************************************************************
 Force Acid  -  dual generative acid-bassline sequencer
 Port of the "Acid" MIDI-FX module for Ableton Move (Schwung)
*******************************************************************

WHAT IT IS
  Two independent generative sequencers (Seq A / Seq B), 2-32 steps each,
  blended into one MIDI output stream. Same generator, swing, blend and
  transpose behaviour as the Move version - only the control surface and
  the runtime host are new. There is NO on-screen GUI: you drive it from a
  Force MIDI track using CC messages, and (optionally) play notes into it
  to transpose both sequencers live (C4 = no shift).

RUNTIME
  Headless background process. Creates two ALSA MIDI ports:
      Mockba Acid:In      Mockba Acid:Out
  Autolaunch: use the addon-manager, or run  manage.sh ENABLE .

SETUP ON THE FORCE
  1. Preferences > MIDI:
       - "Mockba Acid In"  : enable Sync + Track (so clock + your CC track reach it)
       - "Mockba Acid Out" : enable Track
  2. Make a MIDI track named exactly "ACID CTRL" (the included template
     binds by track name), output = Mockba Acid In, channel 1.
     Load "Force Acid Control.xtk" (included alongside this file) onto that
     track to get 16 pre-named Q-Link knobs for Seq A + Seq B's core
     controls (Generate/Mutate/Density/Accent/Slide/Octaves/Length/Gate x2)
     -- or skip it and MIDI-learn any knob to any CC in the map below by
     hand. NOTE: the template is reverse-engineered and not yet confirmed to
     look right on a real screen -- see docs/capture-xtk.md. Global and the
     newer Advanced controls (Channel/Offset/Dir/Jitter/AutoGen) aren't in
     the template yet; reach them via MIDI-learn or the web control panel
     (web/, see web/README.md).
     Play notes on the control track to transpose (moves both sequencers
     together, regardless of their output channels).
  3. Make an instrument track (plugin, or MIDI to external gear), input =
     Mockba Acid Out. Seq A and Seq B each have their OWN output channel
     (a_channel/b_channel, both default to 1) -- either point one instrument
     track at channel 1 to hear both blended together (classic behaviour),
     or give A and B different channels and use two instrument tracks, one
     per channel, like the original tb3po's two separate outputs.
  4. Press Play. Seq A starts; dial Blend up from -63 to bring Seq B in
     (Blend still works even when A and B are on separate channels -- it's
     a velocity balance, not a routing switch).

CC MAP  (control channel 1 by default; edit force-acid.conf to change; full
table with enum landing points in docs/CC-MAP.md)
  SEQUENCE A            SEQUENCE B            GLOBAL
   20  Generate A        40  Generate B        70  Scale      (12 values)
   21  Mutate A          41  Mutate B          71  Root       (12 keys)
   22  Density A         42  Density B         72  Tune B     (-24..+24)
   23  Accent A          43  Accent B          73  Blend      (-63..+64)
   24  Slide A           44  Slide B           74  Algo A     (1..16)
   25  Octaves A (1-3)   45  Octaves B (1-3)   75  Algo B     (1..16)
   26  Length A (2-32)   46  Length B (2-32)   76  Reset Both (1/2/4/8/Off)
   27  Gate A            47  Gate B            77  Swing      (50..75)
   28  Channel A (1-16)  48  Channel B (1-16)  78  Jitter     (0..100%)
   29  Offset A (0-31)   49  Offset B (0-31)   79  CV Mode    (Off/On)
   30  Dir A (Fwd/Rev/Pendulum)  50  Dir B (Fwd/Rev/Pendulum)
   31  Auto Regen A (Off/1/2/4/8/16/32 bars)
                        51  Auto Regen B (Off/1/2/4/8/16/32 bars)
   32  Dump A (momentary, Export as MIDI Clip)
                        52  Dump B (momentary, Export as MIDI Clip)

  Generate / Mutate trigger on CC value >= 64 (treat as a momentary button).
  All other CCs are the full 0-127 range scaled to the parameter.
  Channel A/B, Offset A/B, Dir A/B, Auto Regen A/B, CV Mode and Dump A/B
  have no Move equivalent -- see DESIGN.md. Auto Regen A/B replaces the old
  single shared Auto Gen with an independent per-sequencer bar counter.

  CV Mode retargets both sequencers for a Force CV track driving external
  CV/Gate hardware (e.g. a Behringer TD-3-MO) instead of a MIDI synth:
  accent becomes a velocity-only signal (1 normal / 127 accented, NOT scaled
  by Blend) for a Velocity CV row, and Slide moves from CC65 (Portamento) to
  CC1 (Mod Wheel) for a Mod Wheel CV row. See docs/CC-MAP.md's "CV Mode"
  section.

  Dump A/B trigger the web panel's "Export sequence as MIDI clip" button --
  a Standard MIDI File is written to /media/az01-internal-sd/Force
  Documents/Sequences and to this addon's own exports/ folder. The dump
  replays the current pattern on its own fixed cadence over a dedicated
  channel, independent of live playback, so exporting never interrupts
  whatever's currently playing. See docs/CC-MAP.md's "Export as MIDI Clip"
  section.

OPTIONS (in run_force-acid.sh or on the command line)
   -v                     log every parameter change to stderr
   --control-channel N    1-16
   --a-channel N          1-16, Seq A's output channel (default 1)
   --b-channel N          1-16, Seq B's output channel (default 1)
   --config PATH          CC-map / channel overrides (see force-acid.conf.example)

STATUS
  v0.2 in progress - jitter, per-step Offset/Direction, per-seq Auto Regen,
  expanded scale set (12), and independent Seq A/Seq B output channels have all been
  ported from the current schwung-acid and verified on real Force hardware
  (ports register, transport clock drives stepping, notes/slide reach the
  right channel per sequencer, CC changes take effect live). No parameter
  feedback to the control surface yet, no preset save. See DESIGN.md.
