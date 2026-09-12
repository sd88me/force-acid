# Force Acid — web control panel

A browser-based control surface for `force-acid`, styled after the Behringer
TD-3-MO (yellow chassis / black panels / red accent buttons). Runs as its own
process directly on the Force — no browser plugin, no app to install, just
open `http://<force-ip>:8303` from a phone or laptop on the same network.

**Status: v0.1, hardware-verified.** Built with `mockbamod-module-creator`'s
`references/web-gui.md` guidance: a standalone server (own port, own
process), not a nodeServer plugin — see `DESIGN.md` at the repo root for why.

## What it does

- Renders every CC-mapped parameter (see `docs/CC-MAP.md`) as a knob, a
  momentary button (Generate/Mutate), or an enum pill-selector (Scale/Root/
  Reset/Dir/Auto Gen), grouped into SEQ A / SEQ B / GLOBAL panels — all
  driven from `params.json`, the single source of truth for the CC map on
  this side (kept in sync by hand with `docs/CC-MAP.md` and
  `src/host_shim.cpp`'s `PARAMS` table, same convention `host_shim.cpp`
  itself documents). Covers the full CC map, Advanced controls included
  (Channel/Offset/Dir per sequencer, Jitter/Auto Gen global) — this is the
  only control surface that does; the `.xtk` track template only covers 16
  of the ~32 params (Seq A + B's core 8 each), see `docs/capture-xtk.md`.
- A TRANSPOSE slider sends a live note-on/off on the control channel, same as
  playing a note into the control track.
- An ENGINE button + status LED starts/stops the `force-acid` binary directly
  (the server runs on-device, so it can `Popen`/`killall` it locally) and
  polls `/status` every 2s to reflect whether its ALSA ports are actually
  present — this is the real signal, not just "did we launch a process".

## Known limitation

**No parameter feedback.** The knobs show whatever this browser session last
sent, not the engine's actual current value — there is no CC-out-on-ch16
telemetry yet (that's `DESIGN.md`'s v0.2 item). Opening the panel fresh, or
having another Force MIDI track also sending CCs, will desync the display
from reality. Don't treat the panel as a "read the current state" view yet.

## Run it

**Autolaunch (survives reboot):**
```sh
ssh root@<force-ip> '/media/662522/AddOns/ForceAcid/web/manage.sh ENABLE'
```
Copies `run_forceacidweb.sh` to the top-level `AddOns/` folder (MockbaMod's
boot loop kills+relaunches everything there on every boot — see
`~/.claude/skills/mockbamod-module-creator/references/architecture.md`) and
starts it immediately. `DISABLE`/`UNINSTALL` stop it and remove the
autolaunch entry. This is independent of the `force-acid` engine's own
`manage.sh` — enabling this does not enable the engine, and vice versa; the
panel's ENGINE button works either way once you open it.

The launcher tracks its PID in `.forceacidweb.pid` next to `server.py`
(there's no reliable way to `killall` a Python script by name without
risking unrelated `python3` processes on this device) — don't hand-manage
that file.

**Manual (dev loop, no autolaunch):**
```sh
ssh root@<force-ip> '/media/662522/AddOns/ForceAcid/web/run.sh &'
# then open http://<force-ip>:8303
```

`run.sh` sets `LD_LIBRARY_PATH` to the Python addon's bundled `libjack` before
exec'ing `server.py` — the bundled `python-rtmidi` wheel was built with JACK
support and won't import without `libjack.so.0` resolvable, even though we
never talk to JACK (we force `api='LINUX_ALSA'` on every `mido.open_*` call;
without that, port opens hang indefinitely trying a JACK connection that
never completes — this cost real debugging time, see the git history / ask
Claude if you hit the same hang again).

## Port

**8303.** Chosen to avoid nodeServer (8080, 443, historically 80) and
DrmVncServer (5900, VNC default) — see
`~/.claude/skills/mockbamod-module-creator/references/web-gui.md`.

## Gotcha: server.py loads params.json once at startup

Editing `params.json` (e.g. after a CC-MAP change) has no effect on an
already-running server — it's read once at import time, not per-request.
Restart the process (kill + re-run `run.sh`) after any `params.json` edit.

## Not yet done

- The **engine** (`force-acid` itself) is still manual-launch-only by
  choice — only this web panel autolaunches. Use the panel's own ENGINE
  button to start it after a reboot, or ask for `addon/manage.sh ENABLE`
  too if you want the engine persistent as well.
- No auth — anyone on the LAN who knows the IP:port can control it. Fine for
  a home studio, worth a look before exposing more broadly.
- No mobile home-screen icon / PWA manifest yet.
