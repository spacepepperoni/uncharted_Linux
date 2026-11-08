"""The entries of a packed game (.zar, issue #70) without unpacking anything: the launcher asks which
executables a .zar holds. Only the uncompressed name table and file tree are read.

ZArchive format (https://github.com/Exzap/ZArchive, big-endian): ... name table, file tree, ... and a
144-byte footer of six (offset, size) sections, an integrity hash, the total size, version and magic.
A tree entry is 16 bytes: the name offset with the file flag in its top bit, then for a file its
offset and size (48 bits each), for a directory the index of its first child and the child count.
"""
from pathlib import Path
import struct

MAGIC = 0x169F52D6
VERSION = 0x61BF3A01
FOOTER = 144


def _name(table, offset):
    """As ZArchiveReader::GetName."""
    if offset == 0x7FFFFFFF or offset > len(table):
        return ''
    length = table[offset] & 0x7F
    if table[offset] & 0x80:
        length |= table[offset] << 7
        offset += 2
    else:
        offset += 1
    return table[offset:offset + length].decode('cp1252', 'replace')


def root_entries(path):
    """{lower-case name: (name, is_file, size)} of the archive's root, or None if not a .zar."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            total = f.tell()
            if total < FOOTER:
                return None
            f.seek(total - FOOTER)
            footer = f.read(FOOTER)
            sections = struct.unpack('>12Q', footer[:96])
            version, magic = struct.unpack('>II', footer[136:144])
            if magic != MAGIC or version != VERSION:
                return None
            (names_at, names_size), (tree_at, tree_size) = sections[4:6], sections[6:8]
            if names_at + names_size > total or tree_at + tree_size > total or tree_size < 16:
                return None
            f.seek(names_at)
            names = f.read(names_size)
            f.seek(tree_at)
            tree = f.read(tree_size)
    except OSError:
        return None

    def entry(index):
        return struct.unpack_from('>IIII', tree, index * 16)

    _flag, first, count, _reserved = entry(0)
    found = {}
    for index in range(first, min(first + count, len(tree) // 16)):
        flag, low, size_low, high = entry(index)
        is_file = bool(flag & 0x80000000)
        name = _name(names, flag & 0x7FFFFFFF)
        size = size_low | ((high & 0xFFFF0000) << 16) if is_file else 0
        if name:
            found[name.lower()] = (name, is_file, size)
    return found


def is_zar(path):
    return bool(path) and Path(path).suffix.lower() == '.zar' and Path(path).is_file()
