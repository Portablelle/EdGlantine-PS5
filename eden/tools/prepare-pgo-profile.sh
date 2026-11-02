#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Convert through LLVM's lossless text representation for the pinned LLVM 18 reader.
# No training, fabricated counters, network access or compiler upgrade is involved.
set -euo pipefail
[[ $# == 2 ]] || { echo 'Usage: prepare-pgo-profile.sh INPUT OUTPUT' >&2; exit 2; }
input=$1
output=$2
[[ -f "$input" && ! -e "$output" ]] || { echo 'Input missing or output already exists' >&2; exit 2; }
command -v llvm-profdata-18 >/dev/null
mkdir -p "$(dirname "$output")"
work=$(mktemp -d "$(dirname "$output")/.pgo-convert.XXXXXX")
trap 'rm -rf "$work"' EXIT
if llvm-profdata-18 show "$input" > "$work/source-summary" 2>/dev/null; then
    cp -- "$input" "$work/profile"
    reader=llvm-profdata-18
else
    reader=${EDEN_PGO_READER:-llvm-profdata-21}
    "$reader" show "$input" > "$work/source-summary"
    "$reader" merge --text "$input" -o "$work/profile.txt"
    llvm-profdata-18 merge "$work/profile.txt" -o "$work/profile"
    "$reader" merge --text "$work/profile" -o "$work/roundtrip.txt"
    cmp "$work/profile.txt" "$work/roundtrip.txt"
fi
llvm-profdata-18 show "$work/profile" > "$work/converted-summary"
# The binary formats can have different metadata, but all function/counter totals
# and maxima in the ordinary summary must survive conversion unchanged.
for summary in source-summary converted-summary; do
    sed -n '/^Total functions:/p; /^Maximum function count:/p; /^Maximum internal block count:/p' \
        "$work/$summary" > "$work/$summary.common"
done
diff -u "$work/source-summary.common" "$work/converted-summary.common"
{
    printf 'input_sha256=%s\n' "$(sha256sum "$input" | cut -d' ' -f1)"
    printf 'output_sha256=%s\n' "$(sha256sum "$work/profile" | cut -d' ' -f1)"
    "$reader" --version
    cat "$work/converted-summary"
} > "$work/provenance"
mv -- "$work/profile" "$output"
mv -- "$work/provenance" "$output.provenance.txt"
printf 'PGO_PROFILE_READY %s\n' "$output"
