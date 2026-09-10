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
  2. Make a MIDI track "ACID CTRL", output = Mockba Acid In, channel 1.
     Its knobs / pads send the CC map below. Play notes on it to transpose.
  3. Make an instrument track (plugin, or MIDI to external gear), input =
     Mockba Acid Out, input channel 1, monitor = In/Auto.
  4. Press Play. Seq A starts; dial Blend up from -63 to bring Seq B in.

CC MAP  (control channel 1 by default; edit force-acid.conf to change)
  SEQUENCE A            SEQUENCE B            GLOBAL
   20  Generate A        40  Generate B        50  Scale     (6 values)
   21  Mutate A          41  Mutate B          51  Root      (12 keys)
   22  Density A         42  Density B         52  Tune B    (-24..+24)
   23  Accent A          43  Accent B          53  Blend     (-63..+64)
   24  Slide A           44  Slide B           54  Algo A    (1..16)
   25  Octaves A (1-3)   45  Octaves B (1-3)   55  Algo B    (1..16)
   26  Length A (2-32)   46  Length B (2-32)   56  Reset Both(1/2/4/8/Off)
   27  Gate A            47  Gate B            57  Swing     (50..75)

  Generate / Mutate trigger on CC value >= 64 (treat as a momentary button).
  All other CCs are the full 0-127 range scaled to the parameter.

OPTIONS (in run_force-acid.sh or on the command line)
   -v                     log every parameter change to stderr
   --control-channel N    1-16
   --out-channel N        1-16
   --config PATH          CC-map / channel overrides (see force-acid.conf.example)

STATUS
  v0.1.0 - first port. Generator code is byte-for-byte the Move module's.
  Not yet verified on hardware. No parameter feedback to the control
  surface yet, no preset save. See DESIGN.md in the source repo.
