"""Steam Deck mode's game environment (launcher/uncharted_linux.py deck_environment).
Run: python3 -m unittest discover -s tests"""
import sys
import unittest

from paths import ROOT

if str(ROOT / 'launcher') not in sys.path:
    sys.path.insert(0, str(ROOT / 'launcher'))
import uncharted_linux as linux


def environment(**settings):
    """The variables the launcher sets for these settings (the game's own ones first)."""
    env = {'BB_UPSCALER': settings.get('anti_aliasing', 'off'),
           'BB_FRAME_GEN': settings.get('frame_generation', 'off'),
           'BB_FRAME_GEN_MULTIPLIER': settings.get('frame_gen_multiplier', '2')}
    linux.deck_environment(settings, env)
    return env


class DeckModeTests(unittest.TestCase):
    def test_capped_at_30(self):
        self.assertEqual(linux.DECK_SETTINGS['frame_rate'], '30')
        self.assertEqual(environment(steam_deck=True)['BB_VBLANK_HZ'], '30')
        self.assertEqual(environment(steam_deck=True, frame_rate='60')['BB_VBLANK_HZ'], '30')
        self.assertFalse(linux.deck_allows('frame_rate', '60'))
        self.assertTrue(linux.deck_allows('frame_rate', '30'))

    def test_rates_above_60_fall_back_to_30(self):
        self.assertEqual(environment(steam_deck=True, frame_rate='144')['BB_VBLANK_HZ'], '30')

    def test_old_60_default_becomes_30_once(self):
        saved = {'steam_deck': True, 'frame_rate': '60'}
        self.assertTrue(linux.deck_frame_rate_30(saved))
        self.assertEqual(saved['frame_rate'], '30')
        saved['frame_rate'] = '60'  # chosen again afterwards: kept
        self.assertFalse(linux.deck_frame_rate_30(saved))
        self.assertEqual(saved['frame_rate'], '60')
        desktop = {'steam_deck': False, 'frame_rate': '60'}
        self.assertTrue(linux.deck_frame_rate_30(desktop))
        self.assertEqual(desktop['frame_rate'], '60')
        self.assertFalse(linux.deck_frame_rate_30({}))  # first start: nothing saved yet

    def test_update_highlights(self):
        notes = ('**Steam Deck**\nText.\n\n<!-- Update notes:\n- Steam Deck performance improvements\n'
                 '- Added support for more distributions\n\n* Launcher improvements\n-->\n')
        self.assertEqual(linux.update_highlights(notes), ['Steam Deck performance improvements',
                                                          'Added support for more distributions',
                                                          'Launcher improvements'])
        self.assertEqual(linux.update_highlights('No list here.\n- not this'), [])
        self.assertEqual(linux.update_highlights(None), [])

    def test_frame_rate_is_locked(self):
        self.assertEqual(set(linux.DECK_LOCKED), {'window_size', 'present_mode', 'fullscreen', 'frame_rate'})

    def test_options_the_deck_cannot_run_are_replaced(self):
        env = environment(steam_deck=True, anti_aliasing='dlss', frame_generation='dlss',
                          frame_gen_multiplier='4')
        self.assertEqual((env['BB_UPSCALER'], env['BB_FRAME_GEN'], env['BB_FRAME_GEN_MULTIPLIER']),
                         ('off', 'off', '2'))
        env = environment(steam_deck=True, anti_aliasing='fsr3', frame_generation='fsr3')
        self.assertEqual((env['BB_UPSCALER'], env['BB_FRAME_GEN']), ('fsr3', 'fsr3'))

    def test_deck_allows(self):
        self.assertTrue(linux.deck_allows('frame_rate', '30'))
        self.assertFalse(linux.deck_allows('frame_rate', '120'))
        self.assertFalse(linux.deck_allows('anti_aliasing', 'fsr4'))
        self.assertTrue(linux.deck_allows('anti_aliasing', 'taa'))
        self.assertTrue(linux.deck_allows('window_size', '1280x800'))

    def test_mode_off_changes_nothing(self):
        env = environment(steam_deck=False, frame_rate='144', anti_aliasing='dlss')
        self.assertNotIn('BB_VBLANK_HZ', env)
        self.assertEqual(env['BB_UPSCALER'], 'dlss')

    def test_unsaved_changes(self):
        saved = {'frame_rate': '60', 'fullscreen': True, 'pad_bindings': {'cross': 'a'}}
        self.assertEqual(linux.unsaved_changes(saved, dict(saved)), [])
        self.assertEqual(linux.unsaved_changes(saved, {**saved, 'frame_rate': '30'}), ['frame_rate'])
        self.assertEqual(linux.unsaved_changes(saved, {**saved, 'pad_bindings': {'cross': 'b'}}), ['pad_bindings'])
        self.assertEqual(linux.unsaved_changes(saved, {**saved, 'new_setting': True}), ['new_setting'])

    def test_saved_readbacks_ignored(self):
        # The GPU readbacks choice is gone: a value saved by an older launcher has no effect.
        for value in ('0', '1', '2'):
            self.assertNotIn('BB_READBACKS', environment(gpu_readbacks=value))
            self.assertNotIn('BB_READBACKS', environment(gpu_readbacks=value, steam_deck=True))


if __name__ == '__main__':
    unittest.main()
