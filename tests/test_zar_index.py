"""A packed game (.zar, issue #70): its root listed without unpacking (scripts/zar_index.py), what the
launcher makes of it (game_info, game_available, the saves beside it).
Run: python3 -m unittest discover -s tests"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from paths import ROOT

for folder in ('scripts', 'launcher'):
    if str(ROOT / folder) not in sys.path:
        sys.path.insert(0, str(ROOT / folder))
import zar_index


def fake_zar(path, entries):
    """A .zar with only a name table, a file tree of the root's entries (name, is_file, size) and
    the footer: what zar_index reads."""
    names, offsets = b'', []
    for name, _f, _s in entries:
        offsets.append(len(names))
        names += bytes([len(name)]) + name.encode()
    root_name = len(names)
    names += b'\0'
    tree = struct.pack('>IIII', root_name, 1, len(entries), 0)
    for (name, is_file, size), offset in zip(entries, offsets):
        flag = offset | (0x80000000 if is_file else 0)
        tree += struct.pack('>IIII', flag, 0, size & 0xFFFFFFFF, (size >> 32) << 16) if is_file else \
            struct.pack('>IIII', flag, 0, 0, 0)
    data = b'\0' * 64
    names_at, tree_at = len(data), len(data) + len(names)
    total = tree_at + len(tree) + 144
    footer = struct.pack('>12Q', 0, 64, 64, 0, names_at, len(names), tree_at, len(tree), 0, 0, 0, 0)
    footer += b'\0' * 32 + struct.pack('>QII', total, zar_index.VERSION, zar_index.MAGIC)
    Path(path).write_bytes(data + names + tree + footer)


class ZarIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_root_entries_of_a_packed_collection(self):
        path = self.dir / 'CUSA02320.zar'
        fake_zar(path, [('eboot.bin', True, 1234), ('big2-ps4_Shipping.elf', True, 5 << 32), ('sce_sys', False, 0)])
        root = zar_index.root_entries(path)
        self.assertEqual(root['eboot.bin'], ('eboot.bin', True, 1234))
        self.assertEqual(root['big2-ps4_shipping.elf'], ('big2-ps4_Shipping.elf', True, 5 << 32))
        self.assertEqual(root['sce_sys'], ('sce_sys', False, 0))
        self.assertTrue(zar_index.is_zar(path))

    def test_other_files_are_not_archives(self):
        other = self.dir / 'notes.zar'
        other.write_bytes(b'x' * 300)
        self.assertIsNone(zar_index.root_entries(other))
        self.assertIsNone(zar_index.root_entries(self.dir / 'missing.zar'))
        self.assertFalse(zar_index.is_zar(self.dir))

    def test_the_launcher_sees_the_games_in_a_zar(self):
        import uncharted_launcher as launcher
        path = self.dir / 'CUSA02320.zar'
        fake_zar(path, [('eboot.bin', True, 1), ('big2-ps4_Shipping.elf', True, 1), ('sce_sys', False, 0)])
        info = launcher.game_info(str(path))
        self.assertEqual(info['games'], ['u1', 'u2'])
        self.assertEqual(info['id'], 'CUSA02320')
        settings = {'game_dir': str(path)}
        self.assertTrue(launcher.game_available(settings, 'u2'))
        self.assertFalse(launcher.game_available(settings, 'u3'))

    def test_saves_of_a_zar_stay_in_the_folder_it_was_packed_from(self):
        import uncharted_linux as linux
        self.assertEqual(linux.saves_for('/games/CUSA02320.zar'), '/games/CUSA02320/Saves')
        self.assertEqual(linux.saves_for('/games/CUSA02320'), '/games/CUSA02320/Saves')


if __name__ == '__main__':
    unittest.main()
