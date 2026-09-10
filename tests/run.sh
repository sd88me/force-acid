#!/usr/bin/env bash
# Native (host-arch) build + run of the acid_core smoke test. No Docker, no
# cross toolchain — this only checks the ported generator logic still behaves.
set -euo pipefail
cd "$(dirname "$0")/.."

CC="${CC:-cc}"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

$CC -O2 -Wall -Wextra -Isrc -std=c11 \
    tests/test_smoke.c src/acid_core.c -lm \
    -o "$OUT/test_smoke"

"$OUT/test_smoke" | tail -n 20
