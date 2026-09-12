#!/bin/sh
# Manual launcher for the Force Acid web control panel, for use over SSH while
# developing. Not yet wired into MockbaMod's AddOns autolaunch — see
# ../addon/README.txt and DESIGN.md for the plan to fold this into the addon
# lifecycle once it's proven out.
#
#   ssh root@<force-ip> '/media/662522/AddOns/ForceAcid/web/run.sh &'
#   http://<force-ip>:8303

mmPath=$(cat /dev/shm/.mmPath 2>/dev/null || echo /media/662522)
cd "$(dirname "$0")"

export LD_LIBRARY_PATH="$mmPath/AddOns/Python/libjack:$LD_LIBRARY_PATH"
exec python3 server.py "$@"
