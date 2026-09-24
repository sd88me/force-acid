#!/usr/bin/env bash
# Build the SD-card release zip: dist-zip/ForceAcid-<version>.zip, unpacking to
#   AddOns/ForceAcid/        addon/ + the force-acid binary + web/
# Unzip it onto the SD card root. The binary isn't committed, so this runs
# scripts/build.sh (Docker, armhf under QEMU) first unless dist/force-acid
# already exists. .github/workflows/release.yml runs this for every
# published release.
set -euo pipefail
cd "${PKG_ROOT:-$(dirname "$0")/..}"
VER="${1:-$(git describe --tags --always)}"
[ -f dist/force-acid ] || scripts/build.sh
OUT="$PWD/dist-zip"
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
A="$STAGE/AddOns/ForceAcid"
mkdir -p "$STAGE/AddOns" "$OUT"
cp -r addon "$A"
cp dist/force-acid "$A/force-acid"
cp -r web "$A/web"
find "$STAGE" \( -name __pycache__ -prune -o -name '*.pyc' -o -name .gitkeep \) -exec rm -rf {} +
chmod 0755 "$A"/*.sh "$A"/web/*.sh "$A/force-acid"
rm -f "$OUT/ForceAcid-$VER.zip"
python3 -c "import shutil,sys; shutil.make_archive(sys.argv[1], 'zip', sys.argv[2], 'AddOns')" "$OUT/ForceAcid-$VER" "$STAGE"
python3 -m zipfile -l "$OUT/ForceAcid-$VER.zip"
