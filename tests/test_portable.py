import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.tools import utils
from scripts.build_windows import clean_config


class PortableTests(unittest.TestCase):
    def test_build_defaults_exclude_personal_coordinates(self):
        config = {'TT': {'regions': {'board': {'left': 123}}, 'board_coords': {'x': [45]}},
                  'JJ': {'regions': {'board': {}}, 'board_coords': {'x': [44]}}}
        clean = clean_config(copy.deepcopy(config))
        self.assertEqual(clean['TT']['regions'], {})
        self.assertEqual(clean['JJ']['regions'], {})
        self.assertEqual(clean['TT']['board_coords']['x'], [45])
        self.assertEqual(clean['engine_params']['goParam'], 'movetime')

    def test_frozen_config_is_writable_and_not_overwritten_on_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, user = Path(tmp) / 'default.json', Path(tmp) / 'user.json'
            source.write_text('{"theme":"light"}', encoding='utf-8')
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(utils, 'resource_path', return_value=str(source)), \
                    patch.object(utils, 'app_data_path', return_value=str(user)):
                self.assertEqual(utils.config_path(), str(user))
                self.assertEqual(json.loads(user.read_text())['theme'], 'light')
                user.write_text('{"theme":"dark"}', encoding='utf-8')
                self.assertEqual(utils.config_path(), str(user))
                self.assertEqual(json.loads(user.read_text())['theme'], 'dark')
                self.assertEqual(json.loads(source.read_text())['theme'], 'light')

    def test_source_config_still_uses_project_file(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(utils.config_path(), utils.resource_path('json', 'game_config.json'))

    def test_windows_engine_prefers_packaged_exe(self):
        from app.chess.engine import ChessEngine
        with patch('app.chess.engine.os.name', 'nt'), \
                patch('app.chess.engine.resource_path', return_value='C:/bundle/pikafish.exe'), \
                patch('app.chess.engine.os.path.isfile', return_value=True):
            self.assertEqual(ChessEngine().engine_path, 'C:/bundle/pikafish.exe')


if __name__ == '__main__':
    unittest.main()
