#!/usr/bin/env bash
# =============================================================================
# Build force-acid for the Akai Force (armhf) inside a QEMU-emulated armhf
# container and assemble the MockbaMod addon folder + tarball under dist/.
#
#   dist/force-acid                 the armhf binary
#   dist/ForceAcid/                 the addon folder (drop into AddOns/)
#   dist/force-acid-addon.tar.gz    the same, packed
#
# Requires Docker with armhf emulation. Docker Desktop has it out of the box;
# on a bare Linux dockerd run this once first:
#   docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

IMG=force-acid-builder
PLATFORM=linux/arm/v7

echo "== build armhf toolchain image ($PLATFORM) =="
docker build --platform "$PLATFORM" -t "$IMG" scripts

echo "== compile + package (native armhf under QEMU — slow, be patient) =="
docker run --rm --platform "$PLATFORM" \
  -u "$(id -u):$(id -g)" -v "$PWD":/build -w /build "$IMG" bash -euxc '
  COMMON="-O2 -Wall -Wextra -Wno-unused-parameter -Isrc"
  rm -rf dist && mkdir -p dist/ForceAcid obj

  # acid generator — C, upstream logic untouched
  gcc $COMMON -std=c11   -c src/acid_core.c        -o obj/acid_core.o

  # vendored RtMidi (ALSA backend) + our host shim — C++
  g++ $COMMON -std=c++14 -D__LINUX_ALSA__ -c src/rtmidi/RtMidi.cpp -o obj/RtMidi.o
  g++ $COMMON -std=c++14 -c src/host_shim.cpp      -o obj/host_shim.o

  g++ obj/acid_core.o obj/RtMidi.o obj/host_shim.o \
      -lasound -lpthread \
      -o dist/force-acid

  strip dist/force-acid
  file dist/force-acid
  echo "-- shared libs the Force must provide --"
  readelf -d dist/force-acid | grep NEEDED
  echo "-- highest glibc symbol version required (want <= 2.28) --"
  { readelf -V dist/force-acid | grep -o "GLIBC_[0-9.]*" | sort -uV | tail -3; } || true

  rm -rf obj
  cp dist/force-acid               dist/ForceAcid/force-acid
  cp addon/NSMODULE.json           dist/ForceAcid/
  cp addon/manage.sh               dist/ForceAcid/
  cp addon/run_force-acid.sh       dist/ForceAcid/
  cp addon/VERSION                 dist/ForceAcid/
  cp addon/README.txt              dist/ForceAcid/
  cp addon/help.json               dist/ForceAcid/
  cp addon/shadow_page.conf        dist/ForceAcid/
  cp addon/force-acid.conf.example dist/ForceAcid/
  chmod 0755 dist/ForceAcid/force-acid dist/ForceAcid/manage.sh dist/ForceAcid/run_force-acid.sh

  ( cd dist && tar -czf force-acid-addon.tar.gz ForceAcid )
  ls -la dist dist/ForceAcid
'
echo "== done -> dist/force-acid-addon.tar.gz =="
