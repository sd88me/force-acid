#!/bin/sh
############################################################
# Copy this file to $mmPath/AddOns to launch automatically
# at boot (manage.sh ENABLE does that for you).
############################################################
#
# Runs the Force Acid web control panel (server.py). Independent of the
# force-acid engine's own manage.sh/run_force-acid.sh -- the engine stays
# manual-launch-only by design; this one is what makes the *panel* survive a
# reboot, so it's there to press START from even if you haven't started the
# engine yet.

mmPath=$(cat /dev/shm/.mmPath)
. $mmPath/MockbaMod/env.sh

APPDIR="$mmPath/AddOns/ForceAcid/web"
LIBJACK="$mmPath/AddOns/Python/libjack"
PIDFILE="$APPDIR/.forceacidweb.pid"

if test "$1" = "kill"; then
    if [ -f "$PIDFILE" ]; then
        kill "$(cat "$PIDFILE")" 2>/dev/null
        rm -f "$PIDFILE"
    fi
else
    cd "$APPDIR" || exit 1
    export LD_LIBRARY_PATH="$LIBJACK:$LD_LIBRARY_PATH"
    python3 server.py >/tmp/forceacidweb.log 2>&1 &
    echo $! > "$PIDFILE"
fi
