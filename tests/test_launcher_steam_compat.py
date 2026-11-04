"""Add to Steam removes a Proton chosen before for the shortcut (launcher/uncharted_linux.py
clear_compat_tool, issue #73). Run: python3 -m unittest discover -s tests"""
import sys
import tempfile
import unittest
from pathlib import Path

from paths import ROOT

if str(ROOT / 'launcher') not in sys.path:
    sys.path.insert(0, str(ROOT / 'launcher'))
import uncharted_linux as linux

CONFIG = '''"InstallConfigStore"
{
\t"Software"
\t{
\t\t"Valve"
\t\t{
\t\t\t"Steam"
\t\t\t{
\t\t\t\t"CompatToolMapping"
\t\t\t\t{
\t\t\t\t\t"0"
\t\t\t\t\t{
\t\t\t\t\t\t"name"\t\t"proton_experimental"
\t\t\t\t\t\t"priority"\t\t"75"
\t\t\t\t\t}
\t\t\t\t\t"3166847744"
\t\t\t\t\t{
\t\t\t\t\t\t"name"\t\t"proton_10"
\t\t\t\t\t\t"config"\t\t"a \\"quoted\\" {brace}"
\t\t\t\t\t\t"priority"\t\t"250"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t\t"3166847744"\t\t"not a mapping"
\t\t\t}
\t\t}
\t}
}
'''


class SteamCompatToolTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.steam = Path(self.folder.name)
        (self.steam / 'config').mkdir()
        self.config = self.steam / 'config' / 'config.vdf'
        self.config.write_text(CONFIG, encoding='utf-8')

    def tearDown(self):
        self.folder.cleanup()

    def test_the_shortcuts_entry_goes_the_rest_stays(self):
        self.assertTrue(linux.clear_compat_tool(self.steam, 3166847744))
        text = self.config.read_text(encoding='utf-8')
        self.assertNotIn('proton_10', text)
        self.assertIn('proton_experimental', text)        # Steam's default for its own games
        self.assertIn('"3166847744"\t\t"not a mapping"', text)
        self.assertEqual(text.count('{'), text.count('}'))
        self.assertEqual((self.steam / 'config' / 'config.vdf.bak').read_text(encoding='utf-8'), CONFIG)

    def test_nothing_to_remove(self):
        self.assertFalse(linux.clear_compat_tool(self.steam, 12345))
        self.assertEqual(self.config.read_text(encoding='utf-8'), CONFIG)
        self.assertFalse(linux.clear_compat_tool(self.steam / 'missing', 3166847744))


if __name__ == '__main__':
    unittest.main()
