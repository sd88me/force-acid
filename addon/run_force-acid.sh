#!/bin/sh
############################################################
# Copy this file to $mmPath/AddOns to launch automatically
# at boot (manage.sh ENABLE does that for you).
############################################################

# Set up the MockbaMod environment
mmPath=$(cat /dev/shm/.mmPath)
. $mmPath/MockbaMod/env.sh

APPDIR="$mmPath/AddOns/ForceAcid"
CONF="$APPDIR/force-acid.conf"
CONF_ARG=""
[ -f "$CONF" ] && CONF_ARG="--config $CONF"

if test "$1" = "kill"; then
    killall force-acid 2>/dev/null
else
    "$APPDIR/force-acid" $CONF_ARG 2>/dev/null &
fi
