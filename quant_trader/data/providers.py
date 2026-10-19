"""Explicit alternative providers: FRED NDX and Alpha Vantage ETF data only."""
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import uuid

import requests

from quant_trader.data.calendar import schedule
from quant_trader.data.datasets import DatasetStore, canonical, checksum
from quant_trader.data.imports import CoverageError, csv_bytes, csv_rows, normalize_import


def _publish(raw, prices, splits, distributions, meta, root):
    bars,actions,calendar,provenance,validation=normalize_import(prices,splits,distributions,meta)
    identifier=DatasetStore(root).put(raw=raw,bars=bars,actions=actions,calendar=calendar,
        provenance=provenance,validation=validation,
        source_files={'source_prices.csv':prices,'source_splits.csv':splits,
                      'source_distributions.csv':distributions,'source_metadata.json':canonical(meta)})
    return {'status':'validated_retrieval_snapshot','dataset_id':identifier,'validation':validation}


def ingest_fred_csv(raw, *, start, end, retrieved_at, root='data/v1.1-qc'):
    """NDX closing index only. Non-session missing markers are not price records."""
    fields,rows=csv_rows(raw)
    if fields!=['observation_date','NASDAQ100']: raise ValueError('FRED identity/header mismatch')
    expected_list=[day['session'] for day in schedule(start,date.fromordinal(date.fromisoformat(end).toordinal()-1))]
    expected=set(expected_list)
    observed_dates=[row['observation_date'] for row in rows]
    for session in observed_dates:date.fromisoformat(session)
    if observed_dates!=sorted(set(observed_dates)):raise ValueError('Duplicate or unordered source dates')
    if any(row['observation_date'] in expected and row['NASDAQ100'] in {'','.','NA'} for row in rows):
        raise CoverageError([row['observation_date'] for row in rows if row['NASDAQ100'] not in {'','.','NA'}],expected_list)
    prices=[]
    for row in rows:
        session=row['observation_date'];value=row['NASDAQ100']
        if value in {'','.','NA'} and session not in expected:
            continue  # Explicitly absent holiday observation, no synthesized price.
        prices.append({'session':session,'close':value})
    meta={'symbol':'NDX','provider_symbol':'NASDAQ100','convention':'fred_nasdaq100_close',
          'source_url':'https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQ100',
          'retrieved_at':retrieved_at,'start':start,'end_exclusive':end,
          'currency':'USD','timezone':'America/New_York'}
    return _publish(raw,csv_bytes(prices,['session','close']),b'session,numerator,denominator\n',
                    b'ex_session,pay_session,amount,basis\n',meta,root)


def ingest_alpha_json(raw, *, symbol, start, end, retrieved_at, root='data/v1.1-qc'):
    if symbol not in {'TQQQ','SQQQ','QQQ'}: raise ValueError('ETF identity required')
    payload=json.loads(raw)
    if payload['Meta Data']['2. Symbol']!=symbol: raise ValueError('Provider symbol mismatch')
    if payload['Meta Data']['5. Time Zone']!='US/Eastern': raise ValueError('Provider timezone mismatch')
    prices=[];splits=[];distributions=[]
    for session,row in sorted(payload['Time Series (Daily)'].items()):
        if not start<=session<end: continue
        prices.append({'session':session,'open':row['1. open'],'high':row['2. high'],
            'low':row['3. low'],'close':row['4. close'],'volume':row['6. volume'],
            'adjusted_close':row['5. adjusted close']})
        if float(row['8. split coefficient'])!=1:
            splits.append({'session':session,'numerator':row['8. split coefficient'],'denominator':1})
        if float(row['7. dividend amount']):
            distributions.append({'ex_session':session,'pay_session':'','amount':row['7. dividend amount'],'basis':'post_split_share'})
    meta={'symbol':symbol,'provider_symbol':symbol,'convention':'alpha_vantage_daily_adjusted',
          'source_url':'https://www.alphavantage.co/query','retrieved_at':retrieved_at,
          'start':start,'end_exclusive':end,'currency':'USD','timezone':'America/New_York'}
    return _publish(raw,csv_bytes(prices,['session','open','high','low','close','volume','adjusted_close']),
        csv_bytes(splits,['session','numerator','denominator']),
        csv_bytes(distributions,['ex_session','pay_session','amount','basis']),meta,root)


def acquire(provider, symbol, *, start, end, root='data/v1.1-qc', transport=None):
    if provider not in {'fred','alpha_vantage'}: raise ValueError('Explicit provider required')
    if (provider=='fred' and symbol!='NDX') or (provider=='alpha_vantage' and symbol not in {'TQQQ','SQQQ','QQQ'}):
        raise ValueError('No implicit instrument substitution')
    attempt=Path(root)/'attempts'/uuid.uuid4().hex;attempt.mkdir(parents=True)
    retrieved=datetime.now(timezone.utc).isoformat()
    report={'provider':provider,'symbol':symbol,'retrieved_at':retrieved,'start':start,'end_exclusive':end,
            'status':'failed','dataset_id':None}
    try:
        if provider=='fred':
            url='https://fred.stlouisfed.org/graph/fredgraph.csv'
            params={'id':'NASDAQ100','cosd':start,'coed':date.fromordinal(date.fromisoformat(end).toordinal()-1).isoformat()}
        else:
            key=os.environ.get('ALPHAVANTAGE_API_KEY')
            if not key:
                report['failure']='missing_ALPHAVANTAGE_API_KEY'
                return report
            url='https://www.alphavantage.co/query'
            params={'function':'TIME_SERIES_DAILY_ADJUSTED','symbol':symbol,'outputsize':'full','apikey':key}
        response=(transport or requests.get)(url,params=params,timeout=30)
        raw=response.content
        with (attempt/'response.bin').open('xb') as handle:handle.write(raw)
        report.update(http_status=response.status_code,raw_sha256=checksum(raw))
        response.raise_for_status()
        if provider=='fred': result=ingest_fred_csv(raw,start=start,end=end,retrieved_at=retrieved,root=root)
        else: result=ingest_alpha_json(raw,symbol=symbol,start=start,end=end,retrieved_at=retrieved,root=root)
        report.update(result)
    except (requests.RequestException,ValueError,KeyError,TypeError,OverflowError) as error:
        report['failure']=type(error).__name__
        if isinstance(error,CoverageError):report['validation_failure']=error.details
    finally:
        with (attempt/'attempt.json').open('xb') as handle:handle.write(canonical(report))
    return report


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider',choices=['fred','alpha_vantage']);parser.add_argument('symbol',choices=['NDX','TQQQ','SQQQ','QQQ'])
    parser.add_argument('--start',required=True);parser.add_argument('--end',required=True)
    parser.add_argument('--root',default='data/v1.1-qc')
    args=parser.parse_args(argv)
    report=acquire(args.provider,args.symbol,start=args.start,end=args.end,root=args.root)
    print(json.dumps(report,indent=2));return 0 if report['dataset_id'] else 1


if __name__=='__main__':raise SystemExit(main())
