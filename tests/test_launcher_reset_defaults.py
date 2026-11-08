"""Reset to defaults (launcher/uncharted_linux.py default_settings, differs_from_defaults; issue #77).
Run: python3 -m unittest discover -s tests"""
import sys
import unittest

from paths import ROOT

if str(ROOT / 'launcher') not in sys.path:
    sys.path.insert(0, str(ROOT / 'launcher'))
import uncharted_linux as linux

DEFAULTS = {'game_dir': '', 'user_dir': '', 'player_name': '', 'ui_language': '', 'frame_rate': '60',
            'window_size': '1920x1080', 'present_mode': 'Mailbox', 'fullscreen': False,
            'anti_aliasing': 'off', 'frame_generation': 'off', 'mouse_sensitivity': '1.0',
            'check_updates': True, 'key_bindings': {}, 'pad_bindings': {}, 'steam_deck': False}
PAD = {'cross': 'a', 'circle': 'b'}


class ResetDefaultsTests(unittest.TestCase):
    def test_pc_gets_the_launcher_defaults_and_keeps_its_setup(self):
        target = linux.default_settings(DEFAULTS, PAD)
        self.assertEqual(target['frame_rate'], '60')
        self.assertEqual(target['window_size'], '1920x1080')
        self.assertFalse(target['steam_deck'])
        self.assertEqual(target['pad_bindings'], PAD)
        self.assertEqual(target['key_bindings'], {})
        for kept in ('game_dir', 'user_dir', 'player_name', 'ui_language'):
            self.assertNotIn(kept, target)

    def test_steam_deck_stays_in_steam_deck_mode_with_its_values(self):
        target = linux.default_settings({**DEFAULTS, 'steam_deck': True}, PAD)
        self.assertTrue(target['steam_deck'])
        for key, value in linux.DECK_SETTINGS.items():
            self.assertEqual(target[key], value)

    def test_the_defaults_are_copies(self):
        target = linux.default_settings(DEFAULTS, PAD)
        target['key_bindings']['cross'] = 'Space'
        self.assertEqual(DEFAULTS['key_bindings'], {})

    def test_differs_only_when_a_setting_is_not_its_default(self):
        target = linux.default_settings(DEFAULTS, PAD)
        current = {**DEFAULTS, 'game_dir': '/games/uncharted', 'pad_bindings': {}, 'key_bindings': None}
        self.assertFalse(linux.differs_from_defaults(current, target))
        self.assertTrue(linux.differs_from_defaults({**current, 'frame_rate': '30'}, target))
        self.assertTrue(linux.differs_from_defaults({**current, 'key_bindings': {'cross': 'Space'}}, target))
        self.assertTrue(linux.differs_from_defaults({**current, 'pad_bindings': {'cross': 'b'}}, target))
        self.assertFalse(linux.differs_from_defaults({**current, 'pad_bindings': dict(PAD)}, target))


if __name__ == '__main__':
    unittest.main()
