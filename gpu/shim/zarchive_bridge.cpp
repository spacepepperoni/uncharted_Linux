/* C bridge between the guest file system (src/runtime_file.c) and the vendored ZArchive reader.
 * The reader is C++ and lives in the GPU library; the runtime stays plain C. Every entry point is
 * serialised because guest threads read the archive concurrently. */
#include "runtime_zarchive.h"

#include <zarchive/zarchivereader.h>
#include <zarchive/zarchivewriter.h>

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <map>
#include <vector>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <new>
#include <string>
#include <string_view>

struct ZArchive {
    ZArchiveReader* reader{};
    uint64_t size{};
    mutable std::mutex mutex;
};

namespace {
thread_local std::string open_error;

void set_error(std::string message) {
    open_error = std::move(message);
}

std::string_view relative_path(const char* path) {
    std::string_view view = path ? path : "";
    while (!view.empty() && view.front() == '/') {
        view.remove_prefix(1);
    }
    return view;
}
} // namespace

extern "C" {

ZArchive* zarchive_open(const char* path) {
    open_error.clear();
    if (!path || !*path) {
        set_error("empty path");
        return nullptr;
    }
    std::error_code ec;
    const uint64_t size = std::filesystem::file_size(path, ec);
    if (ec) {
        set_error("cannot stat the archive: " + ec.message());
        return nullptr;
    }
    ZArchiveReader* reader = nullptr;
    try {
        reader = ZArchiveReader::OpenFromFile(std::filesystem::path(path));
    } catch (const std::exception& error) {
        set_error(std::string("not a ZArchive: ") + error.what());
        return nullptr;
    }
    if (!reader) {
        set_error("not a ZArchive (bad footer or tables)");
        return nullptr;
    }
    auto* archive = new (std::nothrow) ZArchive;
    if (!archive) {
        delete reader;
        set_error("out of memory");
        return nullptr;
    }
    archive->reader = reader;
    archive->size = size;
    return archive;
}

void zarchive_close(ZArchive* archive) {
    if (!archive) {
        return;
    }
    delete archive->reader;
    delete archive;
}

uint64_t zarchive_size(const ZArchive* archive) {
    return archive ? archive->size : 0;
}

const char* zarchive_error(void) {
    return open_error.c_str();
}

int64_t zarchive_find(ZArchive* archive, const char* path) {
    if (!archive || !archive->reader) {
        return ZARCHIVE_NONE;
    }
    std::lock_guard lock(archive->mutex);
    try {
        const auto node = archive->reader->LookUp(relative_path(path), true, true);
        return node == ZARCHIVE_INVALID_NODE ? ZARCHIVE_NONE : static_cast<int64_t>(node);
    } catch (const std::exception&) {
        return ZARCHIVE_NONE;
    }
}

int zarchive_is_file(const ZArchive* archive, int64_t node) {
    if (!archive || !archive->reader || node < 0) {
        return 0;
    }
    std::lock_guard lock(archive->mutex);
    return archive->reader->IsFile(static_cast<ZArchiveNodeHandle>(node)) ? 1 : 0;
}

uint64_t zarchive_entry_size(const ZArchive* archive, int64_t node) {
    if (!archive || !archive->reader || node < 0) {
        return 0;
    }
    std::lock_guard lock(archive->mutex);
    return archive->reader->GetFileSize(static_cast<ZArchiveNodeHandle>(node));
}

int zarchive_child(ZArchive* archive, int64_t node, uint32_t index, char* name, size_t size,
                   int* is_file) {
    if (!archive || !archive->reader || node < 0) {
        return 0;
    }
    std::lock_guard lock(archive->mutex);
    ZArchiveReader::DirEntry entry{};
    try {
        if (!archive->reader->GetDirEntry(static_cast<ZArchiveNodeHandle>(node), index, entry)) {
            return 0;
        }
    } catch (const std::exception&) {
        return 0;
    }
    if (name && size) {
        const size_t length = std::min(entry.name.size(), size - 1);
        std::memcpy(name, entry.name.data(), length);
        name[length] = '\0';
    }
    if (is_file) {
        *is_file = entry.isFile ? 1 : 0;
    }
    return 1;
}

uint64_t zarchive_read(ZArchive* archive, int64_t node, uint64_t offset, void* buffer,
                       uint64_t length) {
    if (!archive || !archive->reader || node < 0 || !buffer || !length) {
        return 0;
    }
    std::lock_guard lock(archive->mutex);
    try {
        return archive->reader->ReadFromFile(static_cast<ZArchiveNodeHandle>(node), offset, length,
                                            buffer);
    } catch (const std::exception&) {
        return 0;
    }
}

int64_t zarchive_read_all(ZArchive* archive, const char* path, void* buffer, uint64_t size) {
    if (!archive || !buffer) {
        return -1;
    }
    const int64_t node = zarchive_find(archive, path);
    if (node == ZARCHIVE_NONE || !zarchive_is_file(archive, node)) {
        return -1;
    }
    const uint64_t length = zarchive_entry_size(archive, node);
    if (length > size) {
        return -1;
    }
    std::lock_guard lock(archive->mutex);
    try {
        const uint64_t read =
            archive->reader->ReadFromFile(static_cast<ZArchiveNodeHandle>(node), 0, length, buffer);
        return read == length ? static_cast<int64_t>(length) : -1;
    } catch (const std::exception&) {
        return -1;
    }
}

// Linux fork (issue #70): packs folders into one .zar with Exzap's ZArchiveWriter (64 KiB blocks,
// zstd level 6). Later folders override earlier ones file by file, names compared without case
// (the game, then its title update). Root entries named in `skip` (the Saves folder that can
// live in the game folder) are left out. The archive is written as <out>.part and renamed at the
// end; progress lines "ZAR: packed <MB> of <MB> MB" go to stdout.
int zarchive_pack(const char* const* sources, int count, const char* const* skip, int skip_count,
                  const char* out) {
    namespace fs = std::filesystem;
    struct Entry {
        std::string path; // as first seen, '/' separated
        fs::path source;
        bool directory{};
        uint64_t size{};
    };
    std::map<std::string, Entry> entries;
    const auto lower = [](std::string text) {
        std::transform(text.begin(), text.end(), text.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return text;
    };
    uint64_t total = 0;
    for (int i = 0; i < count; ++i) {
        std::error_code ec;
        const fs::path root(sources[i]);
        if (!fs::is_directory(root, ec)) {
            std::fprintf(stderr, "ZAR: %s is not a folder\n", sources[i]);
            return 1;
        }
        for (auto it = fs::recursive_directory_iterator(root, fs::directory_options::follow_directory_symlink, ec);
             !ec && it != fs::recursive_directory_iterator(); it.increment(ec)) {
            const std::string relative = it->path().lexically_relative(root).generic_string();
            if (it.depth() == 0) {
                bool skipped = false;
                for (int k = 0; k < skip_count; ++k)
                    skipped |= lower(relative) == lower(skip[k]);
                if (skipped) {
                    it.disable_recursion_pending();
                    continue;
                }
            }
            const std::string key = lower(relative);
            const bool directory = it->is_directory(ec);
            const uint64_t size = directory ? 0 : it->file_size(ec);
            auto [found, added] = entries.try_emplace(key, Entry{relative, it->path(), directory, size});
            if (!added && !directory) {
                total -= found->second.size;
                found->second.source = it->path();
                found->second.directory = false;
                found->second.size = size;
            }
            total += added || !directory ? size : 0;
        }
        if (ec) {
            std::fprintf(stderr, "ZAR: cannot read %s: %s\n", sources[i], ec.message().c_str());
            return 1;
        }
    }
    struct Output {
        std::FILE* file{};
        bool failed{};
    } output;
    const std::string part = std::string(out) + ".part";
    output.file = std::fopen(part.c_str(), "wb");
    if (!output.file) {
        std::fprintf(stderr, "ZAR: cannot write %s\n", part.c_str());
        return 1;
    }
    {
        ZArchiveWriter writer([](const int32_t, void*) {},
                              [](const void* data, size_t length, void* context) {
                                  auto* o = static_cast<Output*>(context);
                                  if (!o->failed && std::fwrite(data, 1, length, o->file) != length)
                                      o->failed = true;
                              },
                              &output);
        std::vector<char> buffer(1 << 20);
        uint64_t done = 0;
        int shown = -1;
        for (const auto& [key, entry] : entries) {
            if (entry.directory) {
                writer.MakeDir(entry.path.c_str(), true);
                continue;
            }
            const auto slash = entry.path.rfind('/');
            if (slash != std::string::npos)
                writer.MakeDir(entry.path.substr(0, slash).c_str(), true);
            if (!writer.StartNewFile(entry.path.c_str())) {
                std::fprintf(stderr, "ZAR: cannot add %s\n", entry.path.c_str());
                output.failed = true;
                break;
            }
            std::FILE* in = std::fopen(entry.source.string().c_str(), "rb");
            if (!in) {
                std::fprintf(stderr, "ZAR: cannot read %s\n", entry.source.string().c_str());
                output.failed = true;
                break;
            }
            for (size_t n; (n = std::fread(buffer.data(), 1, buffer.size(), in)) > 0;) {
                writer.AppendData(buffer.data(), n);
                done += n;
                const int percent = total ? static_cast<int>(done * 100 / total) : 100;
                if (percent != shown) {
                    shown = percent;
                    std::printf("ZAR: packed %llu of %llu MB\n", static_cast<unsigned long long>(done >> 20),
                                static_cast<unsigned long long>(total >> 20));
                    std::fflush(stdout);
                }
            }
            const bool read_error = std::ferror(in);
            std::fclose(in);
            if (read_error || output.failed) {
                std::fprintf(stderr, "ZAR: %s while packing %s\n", read_error ? "read error" : "write error",
                             entry.path.c_str());
                output.failed = true;
                break;
            }
        }
        if (!output.failed)
            writer.Finalize();
    }
    const bool failed = std::fclose(output.file) != 0 || output.failed;
    std::error_code ec;
    if (failed) {
        fs::remove(part, ec);
        return 1;
    }
    fs::rename(part, out, ec);
    if (ec) {
        std::fprintf(stderr, "ZAR: cannot rename %s: %s\n", part.c_str(), ec.message().c_str());
        return 1;
    }
    return 0;
}

} // extern "C"
