// A game folder and its title update packed into a .zar (zarchive_pack, gpu/shim/zarchive_bridge.cpp)
// and read back through the C API the guest file system uses (issue #70).
#include <cassert>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <strings.h>
#include <unistd.h>

#include "runtime_zarchive.h"

namespace fs = std::filesystem;

static void write(const fs::path& path, const std::string& data) {
    fs::create_directories(path.parent_path());
    std::ofstream(path, std::ios::binary) << data;
}

static std::string pattern(size_t size, unsigned seed) {
    std::string data(size, '\0');
    unsigned x = seed;
    for (char& c : data) {
        x = x * 1103515245u + 12345u;
        c = static_cast<char>(x >> 16);
    }
    return data;
}

int main() {
    const fs::path root = fs::temp_directory_path() / ("bbport-zar-" + std::to_string(::getpid()));
    fs::remove_all(root);
    const std::string big = pattern(300000, 1), updated = pattern(150001, 2);
    write(root / "game/eboot.bin", "BOOT");
    write(root / "game/sce_sys/param.sfo", "SFO");
    write(root / "game/U2Data/Big.pak", big);
    write(root / "game/U2Data/keep.pak", "keep");
    write(root / "game/Saves/Uncharted 2/SAVEDATA020/USR-DATA", "my save");
    write(root / "update/u2data/BIG.PAK", updated);
    write(root / "update/new.txt", "new");
    const std::string game = (root / "game").string(), update = (root / "update").string();
    const char* sources[] = {game.c_str(), update.c_str()};
    const char* skip[] = {"saves"};
    const std::string out = (root / "game.zar").string();
    assert(zarchive_pack(sources, 2, skip, 1, out.c_str()) == 0);
    assert(fs::is_regular_file(out) && !fs::exists(out + ".part"));

    ZArchive* archive = zarchive_open(out.c_str());
    assert(archive);
    char text[16] = {};
    assert(zarchive_read_all(archive, "EBOOT.BIN", text, sizeof(text)) == 4 && !std::strcmp(text, "BOOT"));
    assert(zarchive_find(archive, "Saves") == ZARCHIVE_NONE);
    assert(zarchive_find(archive, "new.txt") != ZARCHIVE_NONE);
    const int64_t pak = zarchive_find(archive, "u2data/big.pak");
    assert(pak != ZARCHIVE_NONE && zarchive_is_file(archive, pak));
    assert(zarchive_entry_size(archive, pak) == updated.size());   // the update's file replaced the game's
    std::vector<char> data(updated.size());
    assert(zarchive_read(archive, pak, 0, data.data(), data.size()) == updated.size());
    assert(std::string(data.data(), data.size()) == updated);
    assert(zarchive_read(archive, pak, 70000, data.data(), 100) == 100 &&
           !std::memcmp(data.data(), updated.data() + 70000, 100));   // a range across 64 KiB blocks
    assert(zarchive_read(archive, pak, updated.size() - 5, data.data(), 100) == 5);
    const int64_t dir = zarchive_find(archive, "U2Data");
    assert(dir != ZARCHIVE_NONE && !zarchive_is_file(archive, dir));
    int children = 0, is_file = 0;
    char name[64];
    for (uint32_t i = 0; zarchive_child(archive, dir, i, name, sizeof(name), &is_file); ++i) {
        assert(is_file && (!strcasecmp(name, "big.pak") || !std::strcmp(name, "keep.pak")));
        ++children;
    }
    assert(children == 2);
    zarchive_close(archive);
    assert(!zarchive_open((root / "game").string().c_str()));
    fs::remove_all(root);
    std::puts("ZArchive: game + update packed (Saves left out), read back by path, ranges and listing PASS");
}
