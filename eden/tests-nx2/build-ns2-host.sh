#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(uname -s) == Linux ]] || exit 1
scratch=$(cat .local/headless-cache)
# Independent snapshot: native patch preparation can replace its source tree.
host_source=/work/cache/ns2-host-source
if [[ ! -f "$host_source/CMakeLists.txt" ]]; then
    mkdir -p "$host_source"
    cp -a "$scratch/source/." "$host_source/"
fi
# Refresh engine files before configuring; dependency downloads remain local to this snapshot.
# Run only after prepare-build.sh has completed, never during source extraction.
rsync -a --delete --exclude=.cache "$scratch/source/" "$host_source/"
cmake -S "$host_source" -B /work/cache/ns2-host-tests -G Ninja \
  -DCMAKE_C_COMPILER=clang-18 -DCMAKE_CXX_COMPILER=clang++-18 \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_LTO=OFF -DENABLE_WERROR=OFF \
  -DCMAKE_PROJECT_yuzu_INCLUDE="$PWD/headless/inject.cmake" \
  -DENABLE_QT=OFF -DYUZU_CMD=OFF -DYUZU_ROOM=OFF -DYUZU_ROOM_STANDALONE=OFF \
  -DYUZU_TESTS=ON -DBUILD_TESTING=OFF -DDYNARMIC_TESTS=OFF \
  -DENABLE_OPENGL=OFF -DENABLE_CUBEB=OFF -DENABLE_WEB_SERVICE=OFF \
  -DENABLE_LIBUSB=OFF -DYUZU_CRASH_DUMPS=OFF -DYUZU_USE_EXTERNAL_FFMPEG=OFF \
  -DVulkanHeaders_FORCE_BUNDLED=ON -DVulkanUtilityLibraries_FORCE_BUNDLED=ON \
  -Dzstd_FORCE_BUNDLED=ON -DBoost_FORCE_BUNDLED=ON -Dfmt_FORCE_BUNDLED=ON \
  -DDYNARMIC_ENABLE_NO_EXECUTE_SUPPORT=ON -DDYNARMIC_IGNORE_ASSERTS=OFF \
  -DSDL_UNIX_CONSOLE_BUILD=ON -DSDL_X11=OFF -DSDL_WAYLAND=OFF \
  -DSDL_OPENGL=OFF -DSDL_OPENGLES=OFF -DSDL_RENDER=OFF -DSDL_GPU=OFF
cmake --build /work/cache/ns2-host-tests --target tests -j "${EDEN_BUILD_JOBS:-3}"
/work/cache/ns2-host-tests/bin/tests --reporter compact '[native-gather]'
# Generic upstream host-memory/fiber tests assume a desktop fastmem backend;
# the prototype's sparse-memory and JIT tests live in tests-nx2/run.sh instead.
/work/cache/ns2-host-tests/bin/tests --reporter compact \
  '[pauth],[native-gpu],[native-shader],[native-swizzle],[graphics-supervisor],[guest-clock],[address-space],[audio-revision],[builtin-font],[applet],[exefs],[loader],[npdm],[storage-ranges],[texture-download],[texture-overlap],[video_core],MemoryTracker*' 
