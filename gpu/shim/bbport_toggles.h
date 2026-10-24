// bbport: optimizations that can be switched off while the game runs (BB_TOGGLE_FILE,
// see runtime_memory.c), to find which one changes rendering without restarting.
#pragma once
#include <atomic>
#include <csetjmp>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#ifdef _WIN32
// bbport (Windows): no signals. The loader's exception handler resumes the faulting thread
// in bb_longjmp (src/compat_win.c: no unwinding through the faulting frames).
typedef unsigned long long sigjmp_buf[32];
extern "C" __attribute__((returns_twice)) int bb_setjmp(sigjmp_buf buffer);
#define sigsetjmp(buffer, save) bb_setjmp(buffer)
extern "C" [[noreturn]] void bb_longjmp(sigjmp_buf buffer, int value);
#endif

extern "C" std::uint64_t runtime_disabled_optimizations;
/// Recovery point for speculative guest memory reads on this thread (runtime_memory.c).
extern "C" __thread sigjmp_buf* runtime_fault_recover;

namespace BbToggle {
enum : std::uint64_t {
    RegionCache = 1,
    FetchShaderCache = 2,
    PageTrackingEarlyExit = 4,
    PendingPollLimit = 8,
    ThreadedRecording = 16,
    ImageDescCache = 32,
    LockFreeUploadCheck = 64,
    FindImageCache = 128,
    DeferredUploads = 256,
    AccessMemo = 512,
    TextureBindingMemo = 1024,
    CoarseReadTracking = 2048,
    PreparedResources = 4096,
    DrawPreparation = 8192,
    DeferredStreamCopies = 16384,
    HotPages = 32768,
    FaultWindow = 65536,
    ParallelCopies = 131072,
    AsyncFences = 262144,
    PoolSmallCopies = 524288,
    RecordPrefetch = 1ull << 32,
    TextureViewMemo = 1ull << 33,
    TextureBindHelper = 1ull << 34,
    EarlyDrawInputs = 1ull << 35,
    ConstantRing = 1ull << 36,
    DrawPipeline = 1ull << 37,
    PipelinedTasks = 1ull << 38,
    PendingFenceWaits = 1ull << 39,
    PipelinedDispatch = 1ull << 40,
    RecorderFences = 1ull << 41,
    PipelinedMemoryWrites = 1ull << 42,
    MultiCopyShader = 1ull << 43,
    RenderStateMemo = 1ull << 44,
    TextureSetMemo = 1ull << 45,
    PipelinedIndirectDraws = 1ull << 46,
    SceneAttachmentsOnly = 1ull << 47,
    SampleSceneProxies = 1ull << 48,
    OrderedGuestWrites = 1ull << 49,
    SceneHalfRes = 1ull << 50, ///< live scaling also reduces the 960x540 post targets
    UpdateImageFastPath = 1u << 30,
    // TAA A/B in one run: optional techniques, off by default (no measured gain, 2026-10-02).
    TaaTonemapBlend = 1ull << 51,
    TaaClip = 1ull << 52,
    TaaVariance = 1ull << 53,
    TaaFilter = 1ull << 54,
    // On by default (bit set: off): history of a thin feature this jitter phase missed is kept
    // when nothing moves. Static-camera flicker of railings/window bars p99.9 -45% (2026-10-03).
    TaaKeepNearerHistory = 1ull << 55,
    SceneMipBias = 1ull << 57, ///< negative LOD bias of G-buffer samplers at reduced scene sizes
    /// One upscaler frame start per frame (Uncharted draws twice into its display buffer).
    OneFrameStart = 1ull << 59,
    // Bits 20-29 are used as raw debug toggles by the camera/object motion and the upscaler.
};
inline bool Disabled(std::uint64_t bit) {
    return (__atomic_load_n(&runtime_disabled_optimizations, __ATOMIC_RELAXED) & bit) != 0;
}
} // namespace BbToggle

namespace BbStats {
/// Guest writes caught by page protection, and pages currently left unprotected as hot.
inline std::atomic<std::uint64_t> tracker_faults{0};
/// Guest writes to pages holding GPU data: the data dropped as dead (BB_DEAD_GPU_FRAMES) or read
/// back first (waits for the GPU).
inline std::atomic<std::uint64_t> dead_gpu_drops{0}, gpu_read_backs{0};
/// ... or recent GPU data kept and merged at the next upload (BufferCache::ShadowGpuData).
inline std::atomic<std::uint64_t> gpu_merges{0};
/// ... or read back on the second queue (GPU work done; BufferCache::DownloadOnSideQueue).
inline std::atomic<std::uint64_t> gpu_side_downloads{0}, gpu_side_download_ns{0};
inline std::atomic<std::int64_t> hot_pages{0};
/// Stall diagnostics (BB_FRAME_STATS): per-frame deltas printed for frames over 40 ms.
inline std::atomic<std::uint64_t> images_registered{0};
inline std::atomic<std::uint64_t> image_upload_bytes{0};
inline std::atomic<std::uint64_t> buffer_upload_bytes{0};
inline std::atomic<int> gpu_thread_clock{-1}; ///< clockid_t of the GPU command thread
inline std::atomic<std::uint64_t> draws{0}, dispatches{0}, submissions{0};
/// Frames the GPU command thread has started (display pass), for per-frame diagnostics.
inline std::atomic<std::uint64_t> gpu_frames{0};
/// Wall time spent in operations suspected of stalls (ns, all threads).
inline std::atomic<std::uint64_t> t_resident{0}, t_protect{0}, t_image_create{0}, t_refresh{0},
    t_staging{0}, t_host_wait{0}, t_copy{0}, copy_bytes{0}, t_read_faults{0}, read_faults{0},
    t_write_faults{0}, t_copy_cpu{0}, copy_sys_us{0}, copy_minflt{0};
/// Diagnostics are collected only with BB_FRAME_STATS=1.
inline const bool enabled = [] {
    const char* env = std::getenv("BB_FRAME_STATS");
    return env && env[0] == '1';
}();
struct Timer {
    std::atomic<std::uint64_t>& total;
    std::chrono::steady_clock::time_point start =
        enabled ? std::chrono::steady_clock::now() : std::chrono::steady_clock::time_point{};
    ~Timer() {
        if (!enabled) {
            return;
        }
        total.fetch_add(std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now() - start)
                            .count(),
                        std::memory_order_relaxed);
    }
};
/// Wall time the GPU command thread waited for guest submissions (ns).
inline std::atomic<std::uint64_t> gpu_idle_ns{0};
/// Command queues waiting on memory (WaitRegMem, MemSemaphore): wall time (ns) and waits, the
/// graphics and compute queues apart; the longest single wait of the window and its address.
inline std::atomic<std::uint64_t> gfx_wait_ns{0}, gfx_waits{0}, asc_wait_ns{0}, asc_waits{0},
    longest_wait_ns{0}, longest_wait_addr{0};
/// Wall time the GPU command thread cycled through queues that were all waiting (ns), and the
/// part of it spent asleep (BB_GPU_WAIT_SLEEP_US).
inline std::atomic<std::uint64_t> queue_spin_ns{0}, queue_sleep_ns{0};
/// The last label writes the GPU emulation made (fences, WriteData) with their kind and order,
/// and the graphics queue's waits such a write ended, by kind (the rest the guest's CPU code ended).
enum FenceKind : std::uint32_t { FenceEop, FenceEos, FenceWriteData, FenceCompute, FenceKinds };
inline std::atomic<std::uint64_t> fence_writes[256];
inline std::atomic<std::uint32_t> fence_write_kinds[256];
inline std::atomic<std::uint64_t> fence_write_seqs[256];
inline std::atomic<std::uint64_t> fence_write_pos{0};
inline std::atomic<std::uint64_t> gfx_fence_wait_ns[FenceKinds], gfx_fence_waits[FenceKinds];
inline void NoteFenceWrite(std::uint64_t addr, FenceKind kind) {
    const std::uint64_t seq = fence_write_pos.fetch_add(1, std::memory_order_relaxed);
    fence_writes[seq & 255].store(addr, std::memory_order_relaxed);
    fence_write_kinds[seq & 255].store(kind, std::memory_order_relaxed);
    fence_write_seqs[seq & 255].store(seq, std::memory_order_release);
}
/// The kind of the latest recent write to the label at addr, or FenceKinds when there is none.
inline FenceKind RecentFenceWrite(std::uint64_t addr) {
    std::uint64_t newest = 0;
    FenceKind kind = FenceKinds;
    for (int i = 0; i < 256; ++i) {
        const std::uint64_t written = fence_writes[i].load(std::memory_order_relaxed);
        const std::uint64_t seq = fence_write_seqs[i].load(std::memory_order_acquire);
        if (written && addr >= written && addr < written + 8 && (kind == FenceKinds || seq > newest)) {
            newest = seq;
            kind = static_cast<FenceKind>(fence_write_kinds[i].load(std::memory_order_relaxed));
        }
    }
    return kind;
}
/// Whether the label at addr was written since write number `since` (or too long ago to tell).
inline bool FenceWrittenSince(std::uint64_t addr, std::uint64_t since) {
    if (fence_write_pos.load(std::memory_order_acquire) - since >= 256) {
        return true;
    }
    for (int i = 0; i < 256; ++i) {
        const std::uint64_t written = fence_writes[i].load(std::memory_order_relaxed);
        if (written && addr >= written && addr < written + 8 &&
            fence_write_seqs[i].load(std::memory_order_acquire) >= since) {
            return true;
        }
    }
    return false;
}
inline void NoteQueueWait(std::atomic<std::uint64_t>& total, std::atomic<std::uint64_t>& count,
                          std::chrono::steady_clock::time_point start, std::uint64_t addr) {
    const std::uint64_t ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
                                 std::chrono::steady_clock::now() - start).count();
    total.fetch_add(ns, std::memory_order_relaxed);
    count.fetch_add(1, std::memory_order_relaxed);
    if (ns > longest_wait_ns.load(std::memory_order_relaxed)) {
        longest_wait_ns.store(ns, std::memory_order_relaxed);
        longest_wait_addr.store(addr, std::memory_order_relaxed);
    }
}
/// Draws recorded into the reduced scene targets, and draws after the scene started.
inline std::atomic<std::uint64_t> reduced_draws{0}, scene_draws{0};
/// Wall time spent blocked in the scheduler (ns): waiting for the recording thread to drain,
/// for host copies before a submission or fence, and for GPU ticks.
inline std::atomic<std::uint64_t> sync_recording_ns{0}, host_copies_wait_ns{0}, tick_wait_ns{0},
    copy_threads_wait_ns{0}, host_copy_waits{0};
struct WaitTimer {
    std::atomic<std::uint64_t>& total;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    ~WaitTimer() {
        total.fetch_add(std::chrono::duration_cast<std::chrono::nanoseconds>(
                            std::chrono::steady_clock::now() - start).count(),
                        std::memory_order_relaxed);
    }
};
/// GPU thread rusage, refreshed after each graphics submission.
inline std::atomic<std::uint64_t> gpu_sys_us{0}, gpu_user_us{0}, gpu_invol_switches{0},
    gpu_vol_switches{0}, gpu_minor_faults{0};
/// Protection faults (signals) taken by the GPU thread itself.
inline std::atomic<std::uint64_t> gpu_signal_faults{0};
/// Protection changes: calls and pages, those removing write access (TLB shootdowns) apart.
inline std::atomic<std::uint64_t> protect_calls{0}, protect_pages{0}, protect_revoke_calls{0},
    protect_revoke_pages{0};
} // namespace BbStats
