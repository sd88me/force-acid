#!/usr/bin/env bash
# =============================================================================
# Cross-compile force-acid for the Akai Force (armhf) and assemble the
# MockbaMod addon folder + tarball under dist/.
#
#   dist/force-acid                 the binary
#   dist/ForceAcid/                 the addon folder (drop into AddOns/)
#   dist/force-acid-addon.tar.gz    the same, packed
#
# Requires Docker. See scripts/Dockerfile for the toolchain rationale.
# =============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

IMG=force-acid-builder

echo "== toolchain image =="
docker build -t "$IMG" scripts

echo "== cross-compile + package =="
docker run --rm -u "$(id -u):$(id -g)" -v "$PWD":/build -w /build "$IMG" bash -euxc '
  CXX=arm-linux-gnueabihf-g++
  CC=arm-linux-gnueabihf-gcc
  COMMON="-O2 -Wall -Wextra -Wno-unused-parameter -Isrc"

  rm -rf dist && mkdir -p dist/ForceAcid/build

  # acid generator (C, untouched upstream logic)
  $CC  $COMMON -std=c11   -c src/acid_core.c        -o dist/ForceAcid/build/acid_core.o

  # RtMidi (vendored) + our host shim (C++)
  $CXX $COMMON -std=c++14 -D__LINUX_ALSA__ -c src/rtmidi/RtMidi.cpp -o dist/ForceAcid/build/RtMidi.o
  $CXX $COMMON -std=c++14 -c src/host_shim.cpp      -o dist/ForceAcid/build/host_shim.o

  $CXX dist/ForceAcid/build/acid_core.o \
       dist/ForceAcid/build/RtMidi.o \
       dist/ForceAcid/build/host_shim.o \
       -static-libstdc++ -static-libgcc \
       -lasound -lpthread \
       -o dist/force-acid

  arm-linux-gnueabihf-strip dist/force-acid
  file dist/force-acid
  arm-linux-gnueabihf-readelf -d dist/force-acid | grep NEEDED || true

  rm -rf dist/ForceAcid/build
  cp dist/force-acid          dist/ForceAcid/force-acid
  cp addon/NSMODULE.json      dist/ForceAcid/
  cp addon/manage.sh          dist/ForceAcid/
  cp addon/run_force-acid.sh  dist/ForceAcid/
  cp addon/VERSION            dist/ForceAcid/
  cp addon/README.txt         dist/ForceAcid/
  cp addon/help.json          dist/ForceAcid/
  cp addon/force-acid.conf.example dist/ForceAcid/
  chmod 0755 dist/ForceAcid/force-acid dist/ForceAcid/manage.sh dist/ForceAcid/run_force-acid.sh

  ( cd dist && tar -czf force-acid-addon.tar.gz ForceAcid )
  ls -la dist dist/ForceAcid
'
echo "== done -> dist/force-acid-addon.tar.gz =="
