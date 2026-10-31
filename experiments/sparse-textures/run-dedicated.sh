#!/bin/bash
set -euo pipefail
[[ $(uname -s) == Linux ]] || { echo 'Dedicated Linux build only' >&2; exit 1; }
cd "$(dirname "$0")"
mesa=/work/mihawk-vulkan-review/.deps/work/radv-src
headers=/work/mihawk-vulkan-review/.deps/native/radv-release/include
sdk=/work/mihawk-vulkan-review/.deps/native/ps5-payload-sdk
mkdir -p out
python3 extract-driver.py "$mesa" out
clang-18 -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I. -I"$headers" out/driver-test.c -o out/driver-test
./out/driver-test
clang-18 -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined -I"$headers" probe.c probe-tests.c -o out/probe-test
./out/probe-test
"$sdk/bin/prospero-clang" -std=c11 -Wall -Wextra -Werror -I"$headers" -c probe.c -o out/nx2-sparse-probe.ps5.o
"$sdk/bin/prospero-ar" rcs out/libnx2-sparse-probe.ps5.a out/nx2-sparse-probe.ps5.o
(cd out && sha256sum libnx2-sparse-probe.ps5.a > SHA256SUMS)
printf '%s\n' 'PASS: PS5 cross-compiled diagnostic library; no console execution, no production integration'
