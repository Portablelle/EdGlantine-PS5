#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
[[ $(uname -s) == Linux ]] || { echo 'Run on build-server only' >&2; exit 1; }
cd "$(dirname "$0")/.."
scratch=$(cat .local/headless-cache)
out=build/nx2-tests/shader-pool-policy
mkdir -p "$(dirname "$out")"
clang++-18 -std=c++20 -O1 -g -fsanitize=address,undefined \
    -I "$scratch/source/src" tests-nx2/shader-pool-policy.cpp -o "$out"
env -u EDEN_NX2_UNDEF_ZERO ASAN_OPTIONS=detect_leaks=1 "$out" 1
EDEN_NX2_UNDEF_ZERO=0 ASAN_OPTIONS=detect_leaks=1 "$out" 0
EDEN_NX2_UNDEF_ZERO=1 ASAN_OPTIONS=detect_leaks=1 "$out" 1
echo 'PASS: shader pool ownership and both AMD policy/cache modes (ASan/UBSan/LSan)'
