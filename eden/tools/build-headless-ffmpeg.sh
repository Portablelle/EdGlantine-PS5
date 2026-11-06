#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
scratch=$(cat "$root/.local/headless-cache")
[[ "$(cat "$scratch/owner")" == "$root" ]]
export PS5_PAYLOAD_SDK="$scratch/sdk"
source="$scratch/source/.cache/cpm/ffmpeg/c7b5f1537d"
test -f "$source/configure"
mkdir -p "$scratch/ffmpeg-native"
cd "$scratch/ffmpeg-native"
# AV1 goes through dav1d (FFmpeg has no AV1 software decoder of its own): it decodes several
# frames at once, which NS2 movies need (OoT's 1080p menu movie). After viejunerd/Eglantine-PS5-
# 52c5d73.
dav1d="$scratch/ffmpeg-native/dav1d"
if [[ ! -f $dav1d/install/lib/libdav1d.a ]]; then
    rm -rf "$dav1d"
    mkdir -p "$dav1d"
    cat > "$dav1d/cross.ini" <<CROSS
[binaries]
c = ['bash', '$root/tools/ffmpeg-ps5-cc.sh']
ar = 'llvm-ar-18'
strip = 'llvm-strip-18'
nasm = 'nasm'
pkgconfig = 'false'
[properties]
needs_exe_wrapper = true
[host_machine]
system = 'freebsd'
cpu_family = 'x86_64'
cpu = 'x86_64'
endian = 'little'
CROSS
    meson setup "$dav1d/build" "$root/.deps/dav1d-54706fc6bc" --cross-file "$dav1d/cross.ini" \
        --prefix="$dav1d/install" --libdir=lib --buildtype=release --default-library=static \
        -Denable_tools=false -Denable_tests=false -Dlogging=false -Dxxhash_muxer=disabled
    ninja -C "$dav1d/build" -j"${EDEN_BUILD_JOBS:-$(nproc)}" install
fi
export PKG_CONFIG_LIBDIR="$dav1d/install/libdata/pkgconfig:$dav1d/install/lib/pkgconfig"
# Use the same pinned, minimal decoder set as the Linux core. Avoid the full
# prebuilt FFmpeg package's unrelated codec and C++ runtime dependencies.
bash "$source/configure" --prefix="$scratch/ffmpeg-native/install" \
    --enable-cross-compile --arch=x86_64 --target-os=freebsd \
    --cc="bash $root/tools/ffmpeg-ps5-cc.sh" --ld="bash $root/tools/ffmpeg-ps5-cc.sh" \
    --ar=llvm-ar-18 --ranlib=llvm-ranlib-18 --nm=llvm-nm-18 \
    --disable-autodetect --disable-everything --disable-programs --disable-doc \
    --disable-avdevice --disable-avformat --disable-network --disable-swresample \
    --enable-libdav1d --enable-decoder=h264,vp8,vp9,libdav1d --enable-filter=yadif,scale --enable-pic \
    --enable-pthreads --disable-shared --enable-static
make -j"${EDEN_BUILD_JOBS:-$(nproc)}"
make install
# The core links FFmpeg's libraries by name: dav1d goes inside libavcodec.a, which needs it.
llvm-ar-18 qLs "$scratch/ffmpeg-native/install/lib/libavcodec.a" "$dav1d/install/lib/libdav1d.a"
