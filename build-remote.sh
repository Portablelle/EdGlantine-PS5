#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
rsync -az --exclude=.git eden/ build-server:/tmp/ps5-nx2-prototype-20261030/eden/
ssh build-server 'docker run --rm --name eden-nx2-build-20261030 -v /tmp/ps5-nx2-prototype-20261030:/work -w /work/eden -e XDG_CACHE_HOME=/work/cache -e EDEN_BUILD_JOBS=6 -e EDEN_PS5_VULKAN=ON -e EDEN_VULKAN_DRIVER=RADV botty-standalone-build bash -lc "bash tools/prepare-build.sh && bash tools/build-headless-native.sh --graphics" > /tmp/ps5-nx2-prototype-20261030/build.log 2>&1'
