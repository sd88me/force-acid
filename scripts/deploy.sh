#!/usr/bin/env bash
# Deploy + enable Force Acid on a live MockbaMod Force in one command.
# Usage: scripts/deploy.sh user@force-ip
#
# Standard MockbaMod deploy.sh pattern - see
# ~/.claude/skills/mockbamod-module-creator/references/deploy-debug.md
# ("Standard deploy.sh pattern") for the template this was generated from.
# Supersedes scripts/install.sh (which only handles the engine's own
# manage.sh ENABLE, not the web panel) -- this does both in one command.
set -euo pipefail
cd "$(dirname "$0")/.."

APP_DIR="ForceAcid"        # device-side AddOns/<APP_DIR> folder name
HAS_WEB=1                  # 1 if addon/web/manage.sh exists and needs its own ENABLE

HOST="${1:?usage: scripts/deploy.sh user@force-ip}"

if [ ! -d addon ]; then
  echo "addon/ not found - run scripts/build.sh first." >&2
  exit 1
fi

mmPath="$(ssh "$HOST" 'cat /dev/shm/.mmPath')"
echo "== remote mmPath: $mmPath =="

# scp -r into an existing destination NESTS rather than merges - remove first.
ssh "$HOST" "rm -rf '$mmPath/AddOns/$APP_DIR'"
scp -r addon "$HOST:$mmPath/AddOns/$APP_DIR"

ssh "$HOST" "'$mmPath/AddOns/$APP_DIR/manage.sh' ENABLE"
if [ "$HAS_WEB" = 1 ]; then
  ssh "$HOST" "'$mmPath/AddOns/$APP_DIR/web/manage.sh' ENABLE"
fi

cat <<EOF

== $APP_DIR deployed and enabled (auto-launches at boot - force-acid is a
plain MIDI process, no LD_PRELOAD/acvs involvement at all, so this is safe
to run unattended). ==

On the Force: Preferences -> MIDI, enable Sync+Track on "Mockba Acid In"
and Track on "Mockba Acid Out". Full routing/track-template setup is in
../README.md's "Using Force Acid" section.
EOF
