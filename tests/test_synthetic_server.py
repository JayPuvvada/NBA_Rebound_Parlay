import unittest
from unittest.mock import Mock, patch
from scripts.synthetic_server import synthetic_board


class SyntheticBoardTests(unittest.TestCase):
    def test_quotes_are_explicitly_synthetic_and_not_fresh(self):
        loader = Mock()
        loader.get_team_id.side_effect = lambda team: {'CLE': 1, 'BOS': 2}[team]
        loader.get_games_for_date.return_value = [{'home_id':1,'away_id':2,'game_id':'real-game'}]
        with patch('scripts.synthetic_server.subjects', return_value=[('Jarrett Allen','CLE')]):
            board = synthetic_board(loader, '', 'CLE', 'BOS', '2026-10-08', 'basketball_nba_preseason')
        self.assertEqual(len(board['quotes']), 6)
        self.assertTrue(all(q['source'] == 'synthetic-local-test' and q['updated_at'] is None
                            and q['freshness'] == 'unknown' for q in board['quotes']))

    def test_unmatched_game_never_gets_quotes(self):
        loader = Mock()
        loader.get_games_for_date.return_value = []
        board = synthetic_board(loader, '', 'CLE', 'BOS', '2026-10-08', 'basketball_nba_preseason')
        self.assertEqual(board['status'], 'event_missing')
        self.assertEqual(board['quotes'], [])
