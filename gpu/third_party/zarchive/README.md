# ZArchive (vendored)

Source: https://github.com/Exzap/ZArchive
Pinned commit: 965b66c8d67b6b7e30fd63b3b75aa91a99ff303b
License: MIT No Attribution (see LICENSE)

The reader (`zarchivereader.cpp`) mounts a packed game (.zar) as /app0; the writer
(`zarchivewriter.cpp`, `sha_256.c`) packs a game folder (`bb-probe --zar-pack`). The command line
tool (`main.cpp`) is not used. Reader taken from R-V-L's SpartanPort fork (feat/zar), the writer
added by the Linux fork of the Uncharted port (issue #70).
