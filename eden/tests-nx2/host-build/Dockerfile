FROM botty-standalone-build
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends libssl-dev libavcodec-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev libavfilter-dev libavdevice-dev libzstd-dev libvulkan-dev libudev-dev catch2 && rm -rf /var/lib/apt/lists/*
