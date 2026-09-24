#!/usr/bin/env bash
# Assemble AddOns/ForceAcid/ - addon/ + the engine (dist/force-acid) + web/ -
# the one folder the device needs.
#   scripts/package.sh [version]    -> dist-zip/ForceAcid-<version>.zip, to unzip
#                                      onto the SD card root. Leaves out
#                                      a local addon/force-acid.conf.
#   scripts/package.sh --stage DIR  -> DIR/AddOns/ForceAcid, local files included;
#                                      scripts/deploy.sh copies this to the device.
# The binary isn't committed, so this runs scripts/build.sh (Docker, armhf
# under QEMU) first unless dist/force-acid already exists.
# .github/workflows/release.yml runs this for every published release.
set -euo pipefail
cd "${PKG_ROOT:-$(dirname "$0")/..}"
if [ "${1:-}" = --stage ]; then
  STAGE="${2:?usage: scripts/package.sh --stage DIR}"; VER=
else
  VER="${1:-$(git describe --tags --always)}"
  STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
fi
[ -f dist/force-acid ] || scripts/build.sh
A="$STAGE/AddOns/ForceAcid"
rm -rf "$A"; mkdir -p "$STAGE/AddOns"
cp -r addon "$A"
cp dist/force-acid "$A/force-acid"
cp -r web "$A/web"
find "$A" \( -name __pycache__ -prune -o -name '*.pyc' -o -name .gitkeep \) -exec rm -rf {} +
chmod 0755 "$A"/*.sh "$A"/web/*.sh "$A/force-acid"
[ -n "$VER" ] || exit 0

rm -f "$A/force-acid.conf"
OUT="$PWD/dist-zip"; mkdir -p "$OUT"
rm -f "$OUT/ForceAcid-$VER.zip"
python3 -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'AddOns')" "$OUT/ForceAcid-$VER" "$STAGE"
python3 -m zipfile -l "$OUT/ForceAcid-$VER.zip"
