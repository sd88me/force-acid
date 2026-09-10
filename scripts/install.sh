#!/usr/bin/env bash
# Install force-acid onto a MockbaMod Force over SSH.
#
#   FORCE_HOST=root@192.168.1.50 ./scripts/install.sh          # copy only
#   FORCE_HOST=root@192.168.1.50 ./scripts/install.sh --enable  # + autolaunch now
#
# Default host is root@force.local (rarely resolvable — usually pass the IP,
# shown on the Force wifi screen under Shift + info).
set -euo pipefail
cd "$(dirname "$0")/.."

FORCE_HOST="${FORCE_HOST:-root@force.local}"
SRC="dist/ForceAcid"
DEST="/media/662522/AddOns"

[ -d "$SRC" ] || { echo "run scripts/build.sh first ($SRC missing)"; exit 1; }

echo "== copy $SRC -> $FORCE_HOST:$DEST/ForceAcid =="
ssh "$FORCE_HOST" "mkdir -p '$DEST/ForceAcid'"
scp -r "$SRC"/* "$FORCE_HOST:$DEST/ForceAcid/"
ssh "$FORCE_HOST" "chmod +x '$DEST/ForceAcid/force-acid' '$DEST/ForceAcid/manage.sh' '$DEST/ForceAcid/run_force-acid.sh'"

if [ "${1:-}" = "--enable" ]; then
    echo "== enable autolaunch =="
    ssh "$FORCE_HOST" "'$DEST/ForceAcid/manage.sh' ENABLE"
else
    echo "Not enabled for autolaunch. To start it now:"
    echo "  ssh $FORCE_HOST '$DEST/ForceAcid/run_force-acid.sh'"
    echo "or run with --enable to copy run_force-acid.sh into AddOns/ for boot."
fi
