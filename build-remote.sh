#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
source ./remote-build-config.sh
rsync -az --exclude=.git eden/ "$EDGLANTINE_BUILD_HOST:$EDGLANTINE_REMOTE_ROOT/eden/"
ssh "$EDGLANTINE_BUILD_HOST" bash -s -- "$EDGLANTINE_REMOTE_ROOT" <<'REMOTE'
set -euo pipefail
build_root=$1
docker run --rm --name edglantine-ps5-build -v "$build_root:/work" -w /work/eden \
  -e XDG_CACHE_HOME=/work/cache -e EDEN_BUILD_JOBS=6 -e EDEN_PS5_VULKAN=ON \
  -e EDEN_VULKAN_DRIVER=RADV botty-standalone-build bash -lc \
  'bash tools/prepare-build.sh && bash tools/build-headless-native.sh --graphics' \
  > "$build_root/build.log" 2>&1
REMOTE
