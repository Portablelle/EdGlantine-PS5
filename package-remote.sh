#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
source ./remote-build-config.sh
version=$(python3 -c 'import json; print(json.load(open("eden/sce_sys/param.json"))["contentVersion"])')
[[ $version =~ ^[0-9]{2}\.[0-9]{3}\.[0-9]{3}$ ]]
ssh "$EDGLANTINE_BUILD_HOST" mkdir -p -- "$EDGLANTINE_REMOTE_ROOT/eden"
rsync -az --exclude=.git eden/ "$EDGLANTINE_BUILD_HOST:$EDGLANTINE_REMOTE_ROOT/eden/"
# Package the binary already built by build-remote.sh; do not prepare or compile again.
ssh "$EDGLANTINE_BUILD_HOST" bash -s -- "$version" "$EDGLANTINE_REMOTE_ROOT" <<'REMOTE'
set -euo pipefail
docker run --rm --name eden-nx2-package-20261030 \
  -v "$2:/work" -w /work/eden \
  -e XDG_CACHE_HOME=/work/cache -e EDEN_PACKAGE_DIR=/work/eden/build/release/PPSA99862 \
  -e NX2_PACKAGE_VERSION="$1" botty-standalone-build bash -lc \
  'bash tools/package-headless-native.sh --integration && python3 tests-nx2/check-isolation.py build/release/PPSA99862 && cd build/release && tar -czf "/work/Eden-NX2-PS5-prototype-${NX2_PACKAGE_VERSION}.tar.gz" PPSA99862' \
  > "$2/package.log" 2>&1
REMOTE
mkdir -p "artifacts/$version"
rsync -az "$EDGLANTINE_BUILD_HOST:$EDGLANTINE_REMOTE_ROOT/Eden-NX2-PS5-prototype-$version.tar.gz" "artifacts/$version/"
rsync -az "$EDGLANTINE_BUILD_HOST:$EDGLANTINE_REMOTE_ROOT/package.log" "artifacts/$version/"
(cd "artifacts/$version" && shasum -a 256 "Eden-NX2-PS5-prototype-$version.tar.gz" > SHA256SUMS)
