// SPDX-License-Identifier: GPL-2.0-or-later
// Linux fork: BB_WAIT_SITES=1 — where the GPU threads wait for the GPU (Scheduler::Wait, Finish,
// WaitSubmitted), by the caller's file and line: calls and milliseconds per 5 s, printed with
// the frame stats ("GPU ticks" there is the total). After MediEvil's wait diagnostics.
#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>

namespace BbWaitSites {
struct Entry {
    const char* file = nullptr;
    unsigned line = 0, calls = 0;
    std::uint64_t ns = 0, max_ns = 0;
};

inline bool Enabled() {
    static const bool enabled = [] {
        const char* env = std::getenv("BB_WAIT_SITES");
        return env && env[0] == '1';
    }();
    return enabled;
}

inline std::mutex& Mutex() {
    static std::mutex mutex;
    return mutex;
}
inline std::array<Entry, 48>& Table() {
    static std::array<Entry, 48> table;
    return table;
}

inline void Add(const char* file, unsigned line, std::uint64_t ns) {
    std::scoped_lock lock{Mutex()};
    auto& table = Table();
    Entry* entry = &table.back(); // the last row collects whatever does not fit
    for (unsigned i = 0; i + 1 < table.size(); ++i) {
        if (!table[i].calls || (table[i].line == line && std::strcmp(table[i].file, file) == 0)) {
            entry = &table[i];
            break;
        }
    }
    if (!entry->calls) {
        entry->file = entry == &table.back() ? "other" : file;
        entry->line = entry == &table.back() ? 0 : line;
    }
    ++entry->calls;
    entry->ns += ns;
    entry->max_ns = std::max(entry->max_ns, ns);
}

/// The busiest sites of the last window, then cleared (driver.cpp, every 5 s).
inline void Report() {
    if (!Enabled()) {
        return;
    }
    std::array<Entry, 48> rows;
    {
        std::scoped_lock lock{Mutex()};
        rows = Table();
        Table() = {};
    }
    std::sort(rows.begin(), rows.end(), [](const Entry& a, const Entry& b) { return a.ns > b.ns; });
    std::printf("GPU waits by site (5 s):");
    for (unsigned i = 0; i < 8 && rows[i].calls; ++i) {
        const char* name = std::strrchr(rows[i].file, '/');
        std::printf(" %s:%u %u calls %.1f ms (max %.1f)", name ? name + 1 : rows[i].file,
                    rows[i].line, rows[i].calls, rows[i].ns / 1e6, rows[i].max_ns / 1e6);
    }
    std::printf("\n");
}
} // namespace BbWaitSites
