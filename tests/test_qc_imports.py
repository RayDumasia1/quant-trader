import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

from quant_trader.data.datasets import DatasetStore,canonical
from quant_trader.data.imports import CoverageError,import_csv,normalize_import
from quant_trader.data.providers import acquire,ingest_fred_csv,ingest_alpha_json
from quant_trader.strategies.base import snapshot_from_dataset

PRICES=b'session,open,high,low,close,volume,adjusted_close\n2025-01-02,100,101,99,100,1000,49\n2025-01-03,49,50,48,49,2000,49\n2025-01-06,50,51,49,50,2100,50\n'
SPLITS=b'session,numerator,denominator\n2025-01-03,2,1\n'
DISTRIBUTIONS=b'ex_session,pay_session,amount,basis\n2025-01-03,2025-01-10,1,post_split_share\n'


def metadata():
    return {'symbol':'TQQQ','provider_symbol':'TQQQ','convention':'alpha_vantage_daily_adjusted',
            'source_url':'https://www.alphavantage.co/query','retrieved_at':'2025-01-07T22:00:00Z',
            'start':'2025-01-02','end_exclusive':'2025-01-07','currency':'USD','timezone':'America/New_York'}


class CSVImportTests(unittest.TestCase):
    def test_malformed_sidecar_reports_failure_without_dataset(self):
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            base=Path(directory);(base/'prices.txt').write_bytes(PRICES);(base/'meta.txt').write_text('[]')
            report=import_csv(base/'prices.txt',base/'meta.txt',root=base/'store')
            self.assertEqual(report['failure'],'ValueError');self.assertIsNone(report['dataset_id'])
            self.assertFalse((base/'store'/'datasets').exists())

    def test_split_and_distribution_math_without_price_fabrication(self):
        bars,actions,_,_,validation=normalize_import(PRICES,SPLITS,DISTRIBUTIONS,metadata())
        self.assertEqual(len(bars),3)
        self.assertEqual(bars[0]['unadjusted_close'],100)
        self.assertEqual(bars[0]['split_adjusted_close'],50)
        self.assertEqual(bars[1]['unadjusted_close'],49)
        self.assertEqual(bars[1]['cash_total_return'],0)
        self.assertAlmostEqual(bars[2]['cash_total_return'],50/49-1)
        self.assertAlmostEqual(bars[2]['cash_total_return_index'],100*50/49)
        self.assertEqual({event['kind'] for event in actions},{'splits','dividends'})
        self.assertTrue(validation['arithmetic_validated']);self.assertFalse(validation['execution_ready'])

    def test_reverse_split_is_not_a_spurious_gain(self):
        prices=b'session,open,high,low,close,volume,adjusted_close\n2025-01-02,10,11,9,10,1000,50\n2025-01-03,50,51,49,50,200,50\n2025-01-06,51,52,50,51,200,51\n'
        split=b'session,numerator,denominator\n2025-01-03,1,5\n'
        bars,*_=normalize_import(prices,split,b'ex_session,pay_session,amount,basis\n',metadata())
        self.assertEqual(bars[0]['split_adjusted_close'],50)
        self.assertEqual(bars[1]['cash_total_return'],0)

    def test_inconsistent_adjustments_and_actions_rejected(self):
        with self.assertRaises(ValueError):normalize_import(PRICES,b'session,numerator,denominator\n',DISTRIBUTIONS,metadata())
        with self.assertRaises(ValueError):normalize_import(PRICES,SPLITS,b'ex_session,pay_session,amount,basis\n',metadata())
        with self.assertRaises(ValueError):normalize_import(PRICES,SPLITS,DISTRIBUTIONS.replace(b'post_split_share',b'pre_split_share'),metadata())
        with self.assertRaises(ValueError):normalize_import(PRICES,SPLITS,DISTRIBUTIONS.replace(b'2025-01-10',b'2025-01-02'),metadata())

    def test_unknown_provider_conventions_and_credentials_rejected(self):
        meta=metadata();meta['convention']='unknown_split_adjusted'
        with self.assertRaises(KeyError):normalize_import(PRICES,SPLITS,DISTRIBUTIONS,meta)
        meta=metadata();meta['source_url']='https://example.com/data?apikey=placeholder'
        with self.assertRaises(ValueError):normalize_import(PRICES,SPLITS,DISTRIBUTIONS,meta)
        meta=metadata();meta['symbol']='SQQQ'
        with self.assertRaises(ValueError):normalize_import(PRICES,SPLITS,DISTRIBUTIONS,meta)

    def test_missing_duplicate_and_nonmarket_rows_are_rejected(self):
        missing=PRICES.replace(b'2025-01-06,50,51,49,50,2100,50\n',b'')
        for prices in [missing,PRICES+b'2025-01-06,50,51,49,50,2100,50\n',PRICES+b'2025-01-04,50,51,49,50,2100,50\n']:
            with self.assertRaises(CoverageError):normalize_import(prices,SPLITS,DISTRIBUTIONS,metadata())

    def test_local_import_retains_provenance_sources_and_immutable_ids(self):
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            base=Path(directory);paths={}
            for name,raw in [('prices',PRICES),('splits',SPLITS),('distributions',DISTRIBUTIONS),('metadata',canonical(metadata()))]:
                paths[name]=base/(name+'.txt');paths[name].write_bytes(raw)
            a=import_csv(paths['prices'],paths['metadata'],splits=paths['splits'],distributions=paths['distributions'],root=base/'store')
            b=import_csv(paths['prices'],paths['metadata'],splits=paths['splits'],distributions=paths['distributions'],root=base/'store')
            self.assertIsNotNone(a['dataset_id']);self.assertEqual(a['dataset_id'],b['dataset_id'])
            manifest,bars=DatasetStore(base/'store').load(a['dataset_id'])
            self.assertEqual(manifest['provenance']['retrieved_at'],metadata()['retrieved_at'])
            saved=base/'store'/'datasets'/a['dataset_id']
            self.assertEqual((saved/'source_prices.csv').read_bytes(),PRICES)
            self.assertEqual(len(json.loads((saved/'splits.json').read_bytes())),1)
            self.assertEqual(len(json.loads((saved/'distributions.json').read_bytes())),1)
            bad=import_csv(paths['prices'],paths['metadata'],root=base/'store')
            self.assertIsNone(bad['dataset_id'])

    def test_fred_close_only_holiday_placeholders_and_historical_availability(self):
        raw=b'observation_date,NASDAQ100\n2025-01-01,.\n2025-01-02,20000\n2025-01-03,20010\n2025-01-06,20020\n'
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            result=ingest_fred_csv(raw,start='2025-01-01',end='2025-01-07',retrieved_at='2025-01-07T22:00:00Z',root=directory)
            store=DatasetStore(directory);_,bars=store.load(result['dataset_id'])
            self.assertEqual(len(bars),3);self.assertNotIn('unadjusted_open',bars[0])
            snapshot=snapshot_from_dataset(store,result['dataset_id'],as_of='2025-01-06T22:00:00Z')
            self.assertEqual(snapshot.bars,())
            with self.assertRaises(CoverageError):ingest_fred_csv(raw.replace(b'2025-01-03,20010',b'2025-01-03,.'),start='2025-01-01',end='2025-01-07',retrieved_at='2025-01-07T22:00:00Z',root=directory)

    def test_api_failure_records_no_key_no_network_and_no_secret_in_provenance(self):
        with tempfile.TemporaryDirectory(dir='artifacts') as directory,patch.dict(os.environ,{},clear=True):
            result=acquire('alpha_vantage','TQQQ',start='2025-01-02',end='2025-01-07',root=directory,transport=lambda *a,**k:self.fail('Missing key must not trigger network'))
            self.assertEqual(result['failure'],'missing_ALPHAVANTAGE_API_KEY')
            self.assertEqual(len(list(Path(directory).glob('attempts/*/attempt.json'))),1)
        response=requests.Response();response.status_code=403;response._content=b'Forbidden'
        with tempfile.TemporaryDirectory(dir='artifacts') as directory,patch.dict(os.environ,{'ALPHAVANTAGE_API_KEY':'test-only-placeholder'}):
            result=acquire('alpha_vantage','TQQQ',start='2025-01-02',end='2025-01-07',root=directory,transport=lambda *a,**k:response)
            self.assertEqual(result['http_status'],403);self.assertIsNone(result['dataset_id'])
            self.assertNotIn('test-only-placeholder',json.dumps(result))

    def test_alpha_response_identity_and_source_parsing(self):
        entries={}
        for session,close,adj,split,div in [('2025-01-02',100,49,1,0),('2025-01-03',49,49,2,1),('2025-01-06',50,50,1,0)]:
            entries[session]={'1. open':close,'2. high':close+1,'3. low':close-1,'4. close':close,'5. adjusted close':adj,'6. volume':1000,'7. dividend amount':div,'8. split coefficient':split}
        payload={'Meta Data':{'2. Symbol':'TQQQ','5. Time Zone':'US/Eastern'},'Time Series (Daily)':entries}
        with tempfile.TemporaryDirectory(dir='artifacts') as directory:
            report=ingest_alpha_json(canonical(payload),symbol='TQQQ',start='2025-01-02',end='2025-01-07',retrieved_at='2025-01-07T22:00:00Z',root=directory)
            self.assertEqual(report['validation']['rows'],3)
            with self.assertRaises(ValueError):ingest_alpha_json(canonical(payload),symbol='SQQQ',start='2025-01-02',end='2025-01-07',retrieved_at='2025-01-07T22:00:00Z',root=directory)


if __name__=='__main__':unittest.main()
