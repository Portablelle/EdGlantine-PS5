    if constexpr (std::is_same_v<Runtime, Vulkan::TextureCacheRuntime>) {
        // Keep independent copies in one submission, then publish guest writes
        // in modification order. A staging allocation stays busy until its tick.
        using Map = decltype(runtime.DownloadStagingBuffer(size_t{}));
        std::vector<std::pair<ImageId, Map>> pending;
        pending.reserve(16);
        constexpr size_t batch_limit = 32_MiB;
        size_t batch_bytes = 0;
        const auto finish_batch = [&] {
            if (pending.empty()) return;
            runtime.Finish();
            for (auto& [image_id, map] : pending) {
                Image& image = slot_images[image_id];
                const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));
                SwizzleImage(*gpu_memory, image.gpu_addr, image.info, copies, map.mapped_span,
                             swizzle_data_buffer);
                ClearStaleImage(image); // guest memory holds the image's data now (99zzzz3)
            }
            pending.clear();
            batch_bytes = 0;
        };
        for (size_t index = 0; index < images.size(); ++index) {
            const ImageId image_id = images[index];
            Image& image = slot_images[image_id];
            const size_t bytes = image.unswizzled_size_bytes;
            if (pending.size() == 16 || bytes > batch_limit - batch_bytes)
                finish_batch();
            auto refusable = runtime.TryDownloadStagingBuffer(bytes);
            if (!refusable) {
                // Refused even after the pool's retries (issue #20): what is already copied is
                // published, this image and the ones after it stay GPU-modified for a later read.
                finish_batch();
                DroppedReadbacks dropped;
                for (size_t rest = index; rest < images.size(); ++rest) {
                    Image& skipped = slot_images[images[rest]];
                    skipped.flags |= ImageFlagBits::GpuModified;
                    skipped.info.forced_flushed = false; // the next CPU read asks again
                    ++dropped.images;
                    dropped.bytes += skipped.unswizzled_size_bytes;
                }
                ReportDroppedReadbacks("sync", dropped);
                return;
            }
            auto map = std::move(*refusable);
            const auto copies = FixSmallVectorADL(FullDownloadCopies(image.info));
            image.DownloadMemory(map, copies);
            pending.emplace_back(image_id, std::move(map));
            // Oversized images retain the original one-image allocation/wait.
            if (bytes >= batch_limit) {
                finish_batch();
            } else {
                batch_bytes += bytes;
            }
        }
        finish_batch();
        return;
    }
