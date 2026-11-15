"""Save slots (scripts/save_slots.py, issue #71).
Run: python3 -m unittest discover -s tests"""
import sys
import tempfile
import unittest
from pathlib import Path

from paths import ROOT

if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))
import save_slots


def make_save(folder, prefix='SAVEDATA02', detail='Campaign 75% Complete - The Monastery\nPlayed for 6 hours'):
    for name in (prefix + '0', prefix + 'P'):
        (folder / name).mkdir(parents=True)
        (folder / name / 'USR-DATA').write_bytes(b'data ' + name.encode())
        (folder / (name + '.sce_sys')).mkdir()
    param = bytearray(1328)
    raw = detail.encode()
    param[256:256 + len(raw)] = raw
    (folder / (prefix + '0.sce_sys') / 'param.bin').write_bytes(bytes(param))


class SaveSlotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.saves = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_without_slots_every_game_uses_its_folder_as_before(self):
        self.assertEqual(save_slots.mapping(self.saves),
                         'SAVEDATA01=Uncharted 1;SAVEDATA02=Uncharted 2;SAVEDATA03=Uncharted 3')
        self.assertEqual(save_slots.slots(self.saves, 'Uncharted 2'), [1])

    def test_existing_saves_are_slot_one_with_their_description(self):
        make_save(self.saves / 'Uncharted 2')
        text, when = save_slots.details(self.saves, 'Uncharted 2', 1)
        self.assertEqual(text, 'Campaign 75% Complete - The Monastery · Played for 6 hours')
        self.assertIsNotNone(when)

    def test_a_selected_slot_is_what_the_game_sees(self):
        save_slots.select(self.saves, 'Uncharted 2', 3)
        self.assertIn('SAVEDATA02=Save slots/Uncharted 2/Slot 3', save_slots.mapping(self.saves))
        self.assertIn('SAVEDATA01=Uncharted 1', save_slots.mapping(self.saves))
        self.assertEqual(save_slots.slots(self.saves, 'Uncharted 2'), [1, 3])

    def test_copy_makes_an_independent_slot(self):
        make_save(self.saves / 'Uncharted 2')
        free = save_slots.first_free(self.saves, 'Uncharted 2')
        self.assertEqual(free, 2)
        save_slots.copy(self.saves, 'Uncharted 2', 1, free)
        copied = self.saves / 'Save slots' / 'Uncharted 2' / 'Slot 2'
        self.assertEqual((copied / 'SAVEDATA020' / 'USR-DATA').read_bytes(), b'data SAVEDATA020')
        self.assertTrue((copied / 'SAVEDATA020.sce_sys' / 'param.bin').is_file())
        (copied / 'SAVEDATA020' / 'USR-DATA').write_bytes(b'changed')
        self.assertEqual((self.saves / 'Uncharted 2' / 'SAVEDATA020' / 'USR-DATA').read_bytes(), b'data SAVEDATA020')
        self.assertEqual(save_slots.slots(self.saves, 'Uncharted 2'), [1, 2])

    def test_copy_replaces_what_the_target_held(self):
        make_save(self.saves / 'Uncharted 2', detail='first')
        make_save(self.saves / 'Save slots' / 'Uncharted 2' / 'Slot 2', detail='second')
        save_slots.copy(self.saves, 'Uncharted 2', 1, 2)
        self.assertEqual(save_slots.details(self.saves, 'Uncharted 2', 2)[0], 'first')
        self.assertFalse((self.saves / 'Save slots' / 'Uncharted 2' / 'Slot 2.copying').exists())

    def test_deleting_slot_one_keeps_the_game_folder_and_other_files(self):
        make_save(self.saves / 'Uncharted 2')
        (self.saves / 'Uncharted 2' / 'notes.txt').write_text('mine')
        save_slots.delete(self.saves, 'Uncharted 2', 1)
        self.assertEqual(save_slots.saves_in(self.saves / 'Uncharted 2'), [])
        self.assertTrue((self.saves / 'Uncharted 2' / 'notes.txt').is_file())

    def test_deleting_the_selected_slot_goes_back_to_slot_one(self):
        make_save(self.saves / 'Save slots' / 'Uncharted 3' / 'Slot 4', prefix='SAVEDATA03')
        save_slots.select(self.saves, 'Uncharted 3', 4)
        save_slots.rename(self.saves, 'Uncharted 3', 4, 'Crushing')
        save_slots.delete(self.saves, 'Uncharted 3', 4)
        self.assertEqual(save_slots.selected(self.saves, 'Uncharted 3'), 1)
        self.assertEqual(save_slots.name(self.saves, 'Uncharted 3', 4), '')
        self.assertFalse((self.saves / 'Save slots' / 'Uncharted 3' / 'Slot 4').exists())

    def test_names_and_a_broken_state_file(self):
        save_slots.rename(self.saves, 'Uncharted 1', 2, '  Main run  ')
        self.assertEqual(save_slots.name(self.saves, 'Uncharted 1', 2), 'Main run')
        (self.saves / save_slots.STATE).write_text('{not json')
        self.assertEqual(save_slots.selected(self.saves, 'Uncharted 1'), 1)
        self.assertEqual(save_slots.name(self.saves, 'Uncharted 1', 2), '')

    def test_no_free_slot_once_all_are_used(self):
        for n in range(2, save_slots.MOST + 1):
            make_save(self.saves / 'Save slots' / 'Uncharted 1' / f'Slot {n}', prefix='SAVEDATA01')
        self.assertIsNone(save_slots.first_free(self.saves, 'Uncharted 1'))


def make_sfo(game_dir, title):
    """A param.sfo with only TITLE_ID (as the PS4 lays it out)."""
    import struct
    key, value = b'TITLE_ID\0', title.encode() + b'\0'
    keys, values = 0x14 + 16, 0x14 + 16 + 12
    data = struct.pack('<IIIII', 0x46535000, 0x101, keys, values, 1)
    data += struct.pack('<HHIII', 0, 0x0204, len(value), 12, 0)
    data += key.ljust(12, b'\0') + value.ljust(12, b'\0')
    (Path(game_dir) / 'sce_sys').mkdir(parents=True)
    (Path(game_dir) / 'sce_sys' / 'param.sfo').write_bytes(data)


class WindowsLayoutTests(unittest.TestCase):
    """Issue #83: the saves as the Windows port keeps them (savedata/1/<title ID>)."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.saves = Path(self.temp.name) / 'Saves'
        self.game = Path(self.temp.name) / 'CUSA02320'
        make_sfo(self.game, 'CUSA02320')
        self.windows = self.saves / 'savedata' / '1' / 'CUSA02320'

    def tearDown(self):
        self.temp.cleanup()

    def test_title_id_from_the_game_folder(self):
        self.assertEqual(save_slots.title_id(self.game), 'CUSA02320')
        self.assertEqual(save_slots.title_id(self.saves), '')

    def test_saves_move_to_the_windows_folder_and_back(self):
        make_save(self.saves / 'Uncharted 1', prefix='SAVEDATA01')
        make_save(self.saves / 'Uncharted 2', prefix='SAVEDATA02')
        layout, _notes = save_slots.use_layout(self.saves, 'windows', self.game)
        self.assertEqual(layout, 'windows')
        self.assertTrue((self.windows / 'SAVEDATA010' / 'USR-DATA').is_file())
        self.assertTrue((self.windows / 'SAVEDATA02P.sce_sys').is_dir())
        self.assertEqual(save_slots.saves_in(self.saves / 'Uncharted 2'), [])
        self.assertEqual(save_slots.mapping(self.saves),
                         'SAVEDATA01=savedata/1/CUSA02320;SAVEDATA02=savedata/1/CUSA02320;'
                         'SAVEDATA03=savedata/1/CUSA02320')
        layout, _notes = save_slots.use_layout(self.saves, 'games')
        self.assertEqual(layout, 'games')
        self.assertTrue((self.saves / 'Uncharted 2' / 'SAVEDATA020' / 'USR-DATA').is_file())
        self.assertEqual(save_slots.saves_in(self.windows), [])
        self.assertIn('SAVEDATA02=Uncharted 2', save_slots.mapping(self.saves))

    def test_each_game_sees_only_its_saves_in_the_shared_folder(self):
        make_save(self.windows, prefix='SAVEDATA01')
        make_save(self.windows, prefix='SAVEDATA02', detail='Two')
        save_slots.use_layout(self.saves, 'windows', self.game)
        self.assertTrue(save_slots.used(self.saves, 'Uncharted 2', 1))
        self.assertFalse(save_slots.used(self.saves, 'Uncharted 3', 1))
        self.assertEqual(save_slots.details(self.saves, 'Uncharted 2', 1)[0], 'Two')
        save_slots.delete(self.saves, 'Uncharted 2', 1)
        self.assertEqual(sorted(d.name for d in save_slots.saves_in(self.windows)), ['SAVEDATA010', 'SAVEDATA01P'])
        save_slots.copy(self.saves, 'Uncharted 1', 1, 2)
        copied = self.saves / 'Save slots' / 'Uncharted 1' / 'Slot 2'
        self.assertEqual(sorted(d.name for d in copied.iterdir()),
                         ['SAVEDATA010', 'SAVEDATA010.sce_sys', 'SAVEDATA01P', 'SAVEDATA01P.sce_sys'])

    def test_a_save_in_both_places_is_not_overwritten(self):
        make_save(self.saves / 'Uncharted 3', prefix='SAVEDATA03', detail='linux')
        make_save(self.windows, prefix='SAVEDATA03', detail='windows')
        layout, notes = save_slots.use_layout(self.saves, 'windows', self.game)
        self.assertEqual(layout, 'windows')
        self.assertEqual(save_slots.details(self.saves, 'Uncharted 3', 1)[0], 'windows')
        self.assertTrue((self.saves / 'Uncharted 3' / 'SAVEDATA030').is_dir())
        self.assertTrue(any('left there' in note for note in notes))

    def test_without_a_title_id_the_existing_windows_folder_is_used(self):
        make_save(self.windows, prefix='SAVEDATA01')
        layout, _notes = save_slots.use_layout(self.saves, 'windows', '')
        self.assertEqual(layout, 'windows')
        self.assertIn('SAVEDATA01=savedata/1/CUSA02320', save_slots.mapping(self.saves))
        empty = Path(self.temp.name) / 'Empty'
        self.assertEqual(save_slots.use_layout(empty, 'windows', '')[0], 'games')


if __name__ == '__main__':
    unittest.main()
