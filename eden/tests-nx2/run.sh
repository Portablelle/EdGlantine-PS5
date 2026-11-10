#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(uname -s) == Linux ]] || { echo 'Run on build-server'; exit 1; }
scratch=$(cat .local/headless-cache)
mkdir -p build/nx2-tests
clang++-18 -std=c++20 -pthread -O1 -g -fsanitize=address,undefined -Iheadless -I"$scratch/source/src" tests-nx2/six-core.cpp -o build/nx2-tests/six-core
build/nx2-tests/six-core
printf 'Six-core deferred writes: PASS\n'
clang++-18 -std=c++20 -O1 -g -fsanitize=address,undefined -I"$scratch/source/src" tests-nx2/qmd-cache.cpp -o build/nx2-tests/qmd-cache
build/nx2-tests/qmd-cache
printf 'QMD history preserves completion and live/deferred dependencies: PASS\n'

clang++-18 -std=c++20 -O1 -pthread -ffunction-sections -fdata-sections -Wl,--gc-sections src/memory_pages.cpp tests-nx2/memory-layout.cpp -o build/nx2-tests/memory-layout
build/nx2-tests/memory-layout
clang++-18 -std=c++20 -O1 -g -fsanitize=address,undefined -I"$scratch/source/src" -I/work/mihawk-vulkan-review/.deps/native/radv-release/include tests-nx2/sparse-layers.cpp -o build/nx2-tests/sparse-layers
build/nx2-tests/sparse-layers
python3 tests-nx2/check-sparse-owner.py
python3 tests-nx2/check-memory-ranges.py
python3 tests-nx2/check-eglantine.py
python3 tests-nx2/check-isolation.py
python3 tests-nx2/check-vulkan-port-anchors.py
python3 tests-nx2/check-generated-sources-built.py
python3 tests-nx2/check-staging-idle-trim.py
python3 tests-nx2/check-astc-per-layer-decode.py
python3 tests-nx2/check-converted-upload-chunks.py
python3 tests-nx2/check-graphics-usage-reserve.py
python3 tests-nx2/check-vram-reclaim.py
python3 tests-nx2/check-feedback-alias-copies.py
python3 tests-nx2/check-stale-texture-uploads.py
python3 tests-nx2/check-faster-shader-translation.py
python3 tests-nx2/check-native-hmma-lowering.py
python3 tests-nx2/check-suspended-channel-poll.py
python3 tests-nx2/check-inline-page-writes.py
python3 tests-nx2/check-mapped-upload-barrier.py
python3 tests-nx2/check-bound-compute-storage-writes.py
python3 tests-nx2/check-readback-refusal.py
python3 tests-nx2/check-memory-breakdown.py
python3 tests-nx2/check-native-spill-lut.py
python3 tests-nx2/check-native.py
python3 tests-nx2/run-mme.py
python3 tools/check-exclusive-monitor.py

bash tests-nx2/run-eglantine-three.sh
