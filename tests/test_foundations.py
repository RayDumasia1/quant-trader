import importlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from quant_trader.data.repository import ResearchRepository
from quant_trader.data.validation import validate
from quant_trader.cli import file_hash, main
from quant_trader.features.market_regime import compute_market_regime
from quant_trader.research.scoring import compute_daily_scores


class FoundationTests(unittest.TestCase):
    def test_legacy_imports_do_not_open_database(self):
        with patch('duckdb.connect', side_effect=AssertionError('Import opened a database')):
            for path in Path('.').glob('*.py'):
                importlib.import_module(path.stem)

    def test_cli_refuses_to_overwrite_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'fixture.duckdb'
            with duckdb.connect(str(database)) as con:
                con.execute('CREATE TABLE marker(value INTEGER)')
            before = file_hash(database)
            with patch('sys.stderr'), self.assertRaises(SystemExit) as error:
                main(['validate', '--database', str(database), '--as-of', '2026-10-19',
                      '--output', str(database)])
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(file_hash(database), before)

    def test_repository_is_read_only_and_bounds_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'fixture.duckdb'
            with duckdb.connect(str(database)) as con:
                con.execute('CREATE TABLE price_history(symbol VARCHAR, date DATE, close DOUBLE)')
                con.execute("INSERT INTO price_history VALUES ('QQQ','2025-01-02',100),('QQQ','2025-01-03',101)")
            with ResearchRepository(database) as repository:
                prices = repository.prices(['QQQ'], as_of='2025-01-02')
                self.assertEqual(len(prices), 1)
                self.assertEqual(prices.iloc[0]['close'], 100)
                self.assertTrue(repository.prices(["QQQ'); DROP TABLE price_history;--"], as_of='2025-01-03').empty)
                with self.assertRaises(duckdb.InvalidInputException):
                    repository._connection.execute('DELETE FROM price_history')

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.duckdb'
            with self.assertRaises(FileNotFoundError):
                ResearchRepository(path)
            self.assertFalse(path.exists())

    def test_regime_readiness_and_prefix_invariance(self):
        index = pd.bdate_range('2023-01-01', periods=260)
        spy = pd.Series(np.arange(260) + 100.0, index=index)
        breadth = pd.Series(0.6, index=index)
        breadth.iloc[210] = np.nan
        full = compute_market_regime(spy, spy, spy * 0 + 15, breadth)
        self.assertTrue(pd.isna(full.iloc[210]['market_score']))
        self.assertTrue(pd.isna(full.iloc[210]['regime']))
        self.assertTrue(pd.isna(full.iloc[210]['max_exposure']))
        self.assertEqual(full.iloc[220]['market_score'], 15)
        legacy = compute_market_regime(spy, spy, spy * 0 + 15, breadth, require_breadth=False)
        self.assertEqual(legacy.iloc[210]['market_score'], 13)
        prefix = compute_market_regime(spy.iloc[:230], spy.iloc[:230],
                                       spy.iloc[:230] * 0 + 15, breadth.iloc[:230])
        assert_frame_equal(full.iloc[:230], prefix)

    def test_scoring_matches_stored_research_and_is_causal(self):
        database = Path('trading.duckdb')
        if not database.exists():
            self.skipTest('Existing research database not available')
        with duckdb.connect(str(database), read_only=True) as con:
            symbols = [row[0] for row in con.execute('SELECT DISTINCT symbol FROM daily_scores').fetchall()]
            prices = con.execute('SELECT * FROM price_history ORDER BY symbol,date').df()
            expected = con.execute('SELECT * FROM daily_scores ORDER BY symbol,date').df()
        prices = prices[prices.symbol.isin(symbols)]
        actual = compute_daily_scores(prices).sort_values(['symbol','date']).reset_index(drop=True)
        actual['date'] = pd.to_datetime(actual['date'])
        # Pandas 3 string inference mixes None/NaN across Python and DuckDB.
        for column in ['setup', 'structure', 'price_volume_confirm', 'accumulation']:
            actual[column] = actual[column].astype('string')
            expected[column] = expected[column].astype('string')
        assert_frame_equal(actual, expected, check_dtype=False, rtol=1e-10, atol=1e-10)
        sample = prices[prices.symbol.isin(['SPY','AAPL'])]
        cutoff = sample.date.sort_values().unique()[250]
        original = sample.copy(deep=True)
        full = compute_daily_scores(sample)
        prefix = compute_daily_scores(sample[sample.date <= cutoff])
        assert_frame_equal(sample, original)
        assert_frame_equal(full[pd.to_datetime(full.date) <= cutoff].reset_index(drop=True),
                           prefix.reset_index(drop=True))

    def test_validation_does_not_change_research_database(self):
        database = Path('trading.duckdb')
        if not database.exists():
            self.skipTest('Existing research database not available')
        before = file_hash(database)
        with ResearchRepository(database) as repository:
            report = validate(repository, as_of='2026-10-19')
        self.assertEqual(file_hash(database), before)
        self.assertEqual(set(report['target_coverage']), {'NDX','TQQQ','SQQQ','QQQ'})
        self.assertIn('invalid_bounds', report['price_validity'])

    def test_legacy_regime_matches_stored_research(self):
        database = Path('trading.duckdb')
        if not database.exists():
            self.skipTest('Existing research database not available')
        with duckdb.connect(str(database), read_only=True) as con:
            expected = con.sql('SELECT * FROM market_regime_daily ORDER BY date').df().set_index('date')
            series = {}
            for name in ['SPY','QQQ','^VIX']:
                series[name] = con.execute('SELECT date,close FROM price_history WHERE symbol=? ORDER BY date', [name]).df().set_index('date')['close']
        actual = compute_market_regime(series['SPY'], series['QQQ'], series['^VIX'],
                                       expected.breadth_pct, require_breadth=False)
        actual.index.name = 'date'
        assert_frame_equal(actual, expected, check_dtype=False, rtol=1e-10, atol=1e-10)


if __name__ == '__main__':
    unittest.main()
