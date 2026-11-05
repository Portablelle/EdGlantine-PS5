#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds build/stubs/libSceVideodec2.so, the libSceVideodec2 import facade the hardware video decoder
# links against (tools/stubs/libSceVideodec2.c), with the Payload SDK's compiler.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
sdk="$root/../ps5-native-app-boilerplate/.deps/native/ps5-payload-sdk"
source="$root/tools/stubs/libSceVideodec2.c"
out="$root/build/stubs/libSceVideodec2.so"
[[ -f $out && $out -nt $source ]] && exit 0
test -x "$sdk/bin/prospero-clang" || { echo "Missing the Payload SDK; run make deps" >&2; exit 1; }
mkdir -p "$root/build/stubs"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
PS5_PAYLOAD_SDK="$sdk" "$sdk/bin/prospero-clang" -fPIC -c "$source" -o "$work/libSceVideodec2.o"
"$sdk/bin/prospero-lld" --shared -soname libSceVideodec2.sprx -o "$work/libSceVideodec2.so" "$work/libSceVideodec2.o"
mv "$work/libSceVideodec2.so" "$out"
