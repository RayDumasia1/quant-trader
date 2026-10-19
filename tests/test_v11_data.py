import copy
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

import requests

from quant_trader.data.calendar import latest_session, schedule
from quant_trader.data.datasets import DatasetStore, canonical
from quant_trader.data.ingestion import acquire, normalize, validate_bars
from quant_trader.strategies.base import snapshot_from_dataset


def fixture(symbol='NDX'):
    calendar = schedule('2025-01-02','2025-01-06')
    timestamps = [int(datetime.fromisoformat(row['open_at']).timestamp()) for row in calendar]
    result = {'meta':{'symbol':'^NDX' if symbol=='NDX' else symbol,
                      'instrumentType':'INDEX' if symbol=='NDX' else 'ETF',
                      'exchangeTimezoneName':'America/New_York','currency':'USD','exchangeName':'NMS'},
              'timestamp':timestamps,
              'indicators':{'quote':[{'open':[100,101,102], 'high':[102,103,104],
                                      'low':[99,100,101], 'close':[101,102,103], 'volume':[1000]*3}],
                            'adjclose':[{'adjclose':[99.99,100.98,101.97]}]},
              'events':{}}
    return {'chart':{'result':[result],'error':None}},calendar


class DataV11Tests(unittest.TestCase):
    def test_calendar_holidays_early_close_and_dst(self):
        self.assertEqual(schedule('2025-07-04','2025-07-04'),[])
        self.assertIn('17:00:00',schedule('2025-07-03','2025-07-03')[0]['close_at'])
        before = schedule('2025-03-07','2025-03-07')[0]
        after = schedule('2025-03-10','2025-03-10')[0]
        self.assertIn('21:00:00',before['close_at'])
        self.assertIn('20:00:00',after['close_at'])
        self.assertEqual(latest_session('2025-03-10T20:04:00Z')['session'],'2025-03-07')
        self.assertEqual(latest_session('2025-03-10T20:05:00Z')['session'],'2025-03-10')

    def test_adjustments_are_distinct_and_not_reconstructed(self):
        payload, calendar = fixture()
        bars, _ = normalize(payload,'NDX',calendar)
        self.assertEqual(bars[0]['split_adjusted_close'],101)
        self.assertEqual(bars[0]['distribution_adjusted_close'],99.99)
        self.assertIsNone(bars[0]['unadjusted_close'])
        self.assertIsNone(bars[0]['unadjusted_open'])
        self.assertIsNone(bars[0]['distribution_adjusted_return'])
        self.assertAlmostEqual(bars[1]['distribution_adjusted_return'],100.98/99.99-1)
        self.assertEqual(len(bars),3)

    def test_index_venue_and_invalid_volume(self):
        payload,calendar=fixture()
        payload['chart']['result'][0]['meta']['exchangeName']='NIM'
        bars,actions=normalize(payload,'NDX',calendar)
        bars[0]['volume']=float('inf')
        self.assertIn('invalid_volume',validate_bars(bars,actions,calendar)['errors'])

    def test_identity_mismatch_is_rejected(self):
        payload,calendar = fixture('QQQ')
        with self.assertRaises(ValueError): normalize(payload,'NDX',calendar)
        payload['chart']['result'][0]['meta']['exchangeName']='NYQ'
        with self.assertRaises(ValueError): normalize(payload,'QQQ',calendar)

    def test_missing_duplicates_invalid_prices_and_returns(self):
        payload,calendar = fixture()
        bars,actions = normalize(payload,'NDX',calendar)
        self.assertIn('missing_sessions',validate_bars(bars[:-1],actions,calendar)['errors'])
        self.assertIn('duplicate_sessions',validate_bars(bars+[bars[0]],actions,calendar)['errors'])
        self.assertIn('unordered_sessions',validate_bars(list(reversed(bars)),actions,calendar)['errors'])
        broken=copy.deepcopy(bars);broken[0]['split_adjusted_high']=10
        self.assertIn('invalid_ohlc_bounds',validate_bars(broken,actions,calendar)['errors'])
        broken=copy.deepcopy(bars);broken[0]['split_adjusted_close']=float('nan')
        self.assertIn('invalid_ohlc',validate_bars(broken,actions,calendar)['errors'])
        broken=copy.deepcopy(bars)
        for field in ['open','high','low','close']: broken[-1]['split_adjusted_'+field]*=2
        self.assertTrue(validate_bars(broken,actions,calendar)['anomalous_returns'])

    def test_corporate_action_diagnostics(self):
        payload,calendar=fixture();bars,_=normalize(payload,'NDX',calendar)
        split={'kind':'splits','date':payload['chart']['result'][0]['timestamp'][1], 'numerator':0,'denominator':1}
        self.assertIn('invalid_split_ratio',validate_bars(bars,[split],calendar)['errors'])
        # A 2:1 split should not halve a split-adjusted native series.
        split['numerator']=2
        for field in ['open','high','low','close']: bars[1]['split_adjusted_'+field]/=2
        self.assertIn('possible_unadjusted_split_jump_in_native_series',validate_bars(bars,[split],calendar)['errors'])
        bars,_=normalize(payload,'NDX',calendar)
        bars[1]['distribution_adjusted_close']*=0.8
        self.assertTrue(validate_bars(bars,[],calendar)['unexplained_factor_changes'])
        distribution={'kind':'dividends','date':payload['chart']['result'][0]['timestamp'][1],'amount':10000}
        self.assertIn('distribution_exceeds_previous_close',validate_bars(bars,[distribution],calendar)['errors'])

    def test_immutable_bundle_reuse_and_corruption_detection(self):
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            store=DatasetStore(directory)
            kwargs=dict(raw=b'{}',bars=[],actions=[],calendar=[],provenance={'provider':'fixture'},validation={})
            identifier=store.put(**kwargs)
            before=(Path(directory)/'datasets'/identifier/'manifest.json').read_bytes()
            self.assertEqual(store.put(**kwargs),identifier)
            self.assertEqual((Path(directory)/'datasets'/identifier/'manifest.json').read_bytes(),before)
            (Path(directory)/'datasets'/identifier/'bars.json').write_bytes(b'[1]')
            with self.assertRaises(ValueError): store.load(identifier)
            with self.assertRaises(ValueError): store.put(**kwargs)
            with self.assertRaises(ValueError): store.load('../escape')

    def test_successful_offline_ingestion_and_dataset_snapshot(self):
        payload,calendar=fixture()
        response=requests.Response();response.status_code=200;response._content=canonical(payload)
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            reports=[acquire('NDX',start='2025-01-02',end='2025-01-07',root=directory,
                             transport=lambda *a,**k:response) for _ in range(2)]
            self.assertEqual(reports[0]['dataset_id'],reports[1]['dataset_id'])
            self.assertIsNotNone(reports[0]['dataset_id'])
            manifest,bars=DatasetStore(directory).load(reports[0]['dataset_id'])
            self.assertEqual(len(bars),3)
            snapshot=snapshot_from_dataset(DatasetStore(directory),reports[0]['dataset_id'],as_of=calendar[1]['available_at'])
            self.assertEqual(len(snapshot.bars),2)
            self.assertFalse(reports[0]['validation']['execution_ready'])

    def test_blocked_provider_does_not_populate_dataset(self):
        response=requests.Response();response.status_code=429;response._content=b'Too Many Requests'
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            report=acquire('NDX',start='2025-01-02',end='2025-01-07',root=directory,transport=lambda *a,**k:response)
            self.assertEqual(report['http_status'],429)
            self.assertIsNone(report['dataset_id'])
            self.assertFalse((Path(directory)/'datasets').exists())
            self.assertEqual(len(list((Path(directory)/'attempts').glob('*/response.bin'))),1)

    def test_invalid_response_and_unknown_instrument_never_substituted(self):
        response=requests.Response();response.status_code=200;response._content=b'not-json'
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            report=acquire('SQQQ',start='2025-01-02',end='2025-01-07',root=directory,transport=lambda *a,**k:response)
            self.assertIsNone(report['dataset_id'])
            with self.assertRaises(ValueError): acquire('NASDAQ',start='2025-01-02',end='2025-01-07',root=directory)


if __name__=='__main__': unittest.main()
