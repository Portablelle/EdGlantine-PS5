#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
[[ $(uname -s) == Linux ]] || { echo 'Run on build-server only' >&2; exit 1; }
cd "$(dirname "$0")/.."
scratch=$(cat .local/headless-cache)
mkdir -p build/nx2-tests
clang++-18 -std=c++20 -pthread -O1 -g -fsanitize=address,undefined \
    -Isrc -Iheadless -I"$scratch/source/src" tests-nx2/eglantine-three.cpp \
    -o build/nx2-tests/eglantine-three
ASAN_OPTIONS=detect_leaks=1 build/nx2-tests/eglantine-three
