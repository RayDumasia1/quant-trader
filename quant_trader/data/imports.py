"""Strict source-described CSV imports and action arithmetic, without repairs."""
import csv
from datetime import date, datetime, timezone
import io
import json
import math
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import uuid

from quant_trader.data.calendar import schedule, utc_timestamp
from quant_trader.data.datasets import DatasetStore, canonical, checksum

CONVENTIONS = {
    'fred_nasdaq100_close': {'provider':'FRED / Nasdaq, Inc.', 'symbols':{'NDX'},
        'reference':'https://fred.stlouisfed.org/series/NASDAQ100', 'basis':'price_index_close'},
    'alpha_vantage_daily_adjusted': {'provider':'Alpha Vantage', 'symbols':{'TQQQ','SQQQ','QQQ'},
        'reference':'https://www.alphavantage.co/documentation/#dailyadj', 'basis':'raw_as_traded'},
}


class CoverageError(ValueError):
    def __init__(self, actual, expected):
        self.details={'code':'session_coverage_mismatch','missing_sessions':sorted(set(expected)-set(actual)),
                      'unexpected_sessions':sorted(set(actual)-set(expected)),
                      'duplicates':len(actual)-len(set(actual)),'ordered':actual==sorted(actual)}
        super().__init__('Session coverage mismatch')


def csv_rows(raw):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    rows = list(reader)
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError('Missing or duplicate CSV headers')
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError('Ragged CSV row')
    return reader.fieldnames, rows


def csv_bytes(rows, fields):
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue().encode()


def positive(value, *, zero=False):
    number=float(value)
    if not math.isfinite(number) or number < 0 or (not zero and number==0):
        raise ValueError('Invalid numeric value')
    return number


def validate_metadata(meta):
    required={'symbol','provider_symbol','convention','source_url','retrieved_at','start','end_exclusive','currency','timezone'}
    if set(meta)!=required: raise ValueError('Metadata fields must match the documented contract')
    spec=CONVENTIONS[meta['convention']]
    if meta['symbol'] not in spec['symbols']: raise ValueError('Symbol is inconsistent with convention')
    expected='NASDAQ100' if meta['symbol']=='NDX' else meta['symbol']
    if meta['provider_symbol']!=expected: raise ValueError('Provider symbol mismatch')
    url=urlsplit(meta['source_url'])
    if url.scheme!='https' or not url.netloc or url.username or url.password or any(
            any(word in key.lower() for word in ['key','token','secret','password']) for key in parse_qs(url.query)):
        raise ValueError('Source URL must be HTTPS without credentials')
    if meta['currency']!='USD' or meta['timezone']!='America/New_York': raise ValueError('Market identity mismatch')
    retrieved=utc_timestamp(meta['retrieved_at'])
    start,end=date.fromisoformat(meta['start']),date.fromisoformat(meta['end_exclusive'])
    if start>=end or end>retrieved.date(): raise ValueError('Invalid coverage or incomplete current session')
    return spec,schedule(start,date.fromordinal(end.toordinal()-1)),retrieved


def normalize_import(prices, splits, distributions, meta):
    """Return validated bars and separate events. Never invent missing sessions.

    Derived split prices use only supplied events after t, anchored at window
    end. Cash total returns use shares held through the ex-date, not a fill.
    These series are distinct from provider backward-adjusted close returns.
    """
    spec,calendar,retrieved=validate_metadata(meta)
    fields,rows=csv_rows(prices)
    sessions=[row['session'] for row in rows]
    for session in sessions: date.fromisoformat(session)
    expected=[row['session'] for row in calendar]
    if sessions!=expected: raise CoverageError(sessions,expected)
    if not rows: raise ValueError('Empty dataset')
    sf,srows=csv_rows(splits)
    df,drows=csv_rows(distributions)
    if sf!=['session','numerator','denominator'] or df!=['ex_session','pay_session','amount','basis']:
        raise ValueError('Action CSV headers do not match contract')
    split_map={};cash_map={};actions=[]
    for row in srows:
        session=row['session']
        if session not in expected or session in split_map: raise ValueError('Invalid or duplicate split session')
        numerator,denominator=positive(row['numerator']),positive(row['denominator'])
        split_map[session]=numerator/denominator
        actions.append({'kind':'splits','session':session,'numerator':numerator,'denominator':denominator})
    for row in drows:
        session=row['ex_session']
        if session not in expected or session in cash_map or row['basis']!='post_split_share':
            raise ValueError('Invalid distribution session or share basis')
        if row['pay_session'] and date.fromisoformat(row['pay_session'])<date.fromisoformat(session):
            raise ValueError('Payment date precedes ex-date')
        cash_map[session]=positive(row['amount'])
        actions.append({'kind':'dividends','session':session,'pay_session':row['pay_session'] or None,
                        'amount':cash_map[session],'basis':row['basis']})
    bars=[];warnings=[]
    if meta['symbol']=='NDX':
        if fields!=['session','close'] or actions: raise ValueError('NDX requires close-only price-index data and no ETF actions')
        for row,day in zip(rows,calendar):
            close=positive(row['close'])
            bars.append({'symbol':'NDX','session':row['session'],'unadjusted_close':close,
                         'split_adjusted_close':close,'distribution_adjusted_close':None,
                         'available_at':max(retrieved,utc_timestamp(day['available_at'])).isoformat()})
    else:
        if fields!=['session','open','high','low','close','volume','adjusted_close']:
            raise ValueError('ETF prices require raw OHLCV plus provider adjusted_close')
        future_factor=1.0;factors={}
        for session in reversed(sessions):
            factors[session]=future_factor
            future_factor*=split_map.get(session,1.0)
        previous=None;total_index=100.0
        for row,day in zip(rows,calendar):
            raw={field:positive(row[field]) for field in ['open','high','low','close']}
            volume=positive(row['volume'],zero=True);adjusted=positive(row['adjusted_close'])
            if raw['high']+1e-8<max(raw.values()) or raw['low']-1e-8>min(raw.values()):
                raise ValueError('Invalid raw OHLC bounds')
            factor=factors[row['session']]
            split=split_map.get(row['session'],1.0);cash=cash_map.get(row['session'],0)
            cash_return=None;adjusted_return=None
            if previous:
                prior_raw=previous['unadjusted_close']
                if split*cash>=prior_raw: raise ValueError('Distribution exceeds split-equivalent prior close')
                observed=(adjusted/raw['close'])/(previous['distribution_adjusted_close']/prior_raw)
                expected_factor=split/(1-split*cash/prior_raw)
                if not math.isclose(observed,expected_factor,rel_tol=1e-3,abs_tol=1e-6):
                    raise ValueError('Provider adjustment factor inconsistent with supplied actions')
                cash_return=split*(raw['close']+cash)/prior_raw-1
                adjusted_return=adjusted/previous['distribution_adjusted_close']-1
                total_index*=1+cash_return
                if abs((raw['close']/factor)/previous['split_adjusted_close']-1)>.35:
                    raise ValueError('Anomalous split-neutral return requires review')
            elif split!=1 or cash:
                raise ValueError('Action on first row requires preceding session context')
            bar={'symbol':meta['symbol'],'session':row['session'],
                 **{'unadjusted_'+field:value for field,value in raw.items()},
                 **{'split_adjusted_'+field:value/factor for field,value in raw.items()},
                 'volume':volume,'distribution_adjusted_close':adjusted,
                 'distribution_adjusted_return':adjusted_return,'cash_total_return':cash_return,
                 'cash_total_return_index':total_index,
                 'available_at':max(retrieved,utc_timestamp(day['available_at'])).isoformat()}
            bars.append(bar);previous=bar
        if any(not row['pay_session'] for row in drows): warnings.append('distribution_payment_dates_unavailable')
    for previous,current in zip(bars,bars[1:]):
        if abs(current['split_adjusted_close']/previous['split_adjusted_close']-1)>.35:
            raise ValueError('Anomalous return requires review')
    validation={'errors':[], 'warnings':warnings+['historical_release_timestamps_unverified','independent_source_reconciliation_pending'],
                'rows':len(bars),'first_session':sessions[0],'last_session':sessions[-1],
                'signal_data_valid':meta['symbol']=='NDX', 'execution_ready':False,
                'convention_documented':True,'arithmetic_validated':True,
                'historical_availability_verified':False,'missing_sessions':[]}
    provenance={**meta,'provider':spec['provider'],'adjustment_reference':spec['reference'],
                'price_basis':spec['basis'],'adapter_version':'csv-qc-v1',
                'derived_split_method':'raw price / product of subsequent supplied new-shares-per-old ratios',
                'cash_return_method':'split_ratio*(raw_close+post_split_cash)/prior_raw_close-1',
                'availability_method':'retrieval timestamp; no retrospective close-time claim'}
    return bars,actions,calendar,provenance,validation


def import_csv(prices, metadata, *, splits=None, distributions=None, root='data/v1.1-qc'):
    attempt=Path(root)/'attempts'/uuid.uuid4().hex;attempt.mkdir(parents=True)
    report={'status':'failed','dataset_id':None,'imported_at':datetime.now(timezone.utc).isoformat()}
    try:
        raw=Path(prices).read_bytes();meta_raw=Path(metadata).read_bytes();meta=json.loads(meta_raw)
        if not isinstance(meta,dict):raise ValueError('Metadata must be a JSON object')
        split_raw=Path(splits).read_bytes() if splits else b'session,numerator,denominator\n'
        dist_raw=Path(distributions).read_bytes() if distributions else b'ex_session,pay_session,amount,basis\n'
        # ETF action files must be explicit, even when they contain only headers.
        if meta.get('symbol')!='NDX' and (splits is None or distributions is None):
            raise ValueError('Explicit ETF split and distribution files are required')
        report.update(symbol=meta.get('symbol'),source_sha256=checksum(raw))
        bars,actions,calendar,provenance,validation=normalize_import(raw,split_raw,dist_raw,meta)
        sources={'source_prices.csv':raw,'source_splits.csv':split_raw,
                 'source_distributions.csv':dist_raw,'source_metadata.json':meta_raw}
        report['dataset_id']=DatasetStore(root).put(raw=raw,bars=bars,actions=actions,calendar=calendar,
            provenance=provenance,validation=validation,source_files=sources)
        report.update(status='validated_retrieval_snapshot',validation=validation)
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as error:
        report['failure']=type(error).__name__
        if isinstance(error,CoverageError):report['validation_failure']=error.details
    with (attempt/'attempt.json').open('xb') as handle:handle.write(canonical(report))
    return report


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prices',required=True);parser.add_argument('--metadata',required=True)
    parser.add_argument('--splits');parser.add_argument('--distributions');parser.add_argument('--root',default='data/v1.1-qc')
    args=parser.parse_args(argv)
    report=import_csv(args.prices,args.metadata,splits=args.splits,distributions=args.distributions,root=args.root)
    print(json.dumps(report,indent=2));return 0 if report['dataset_id'] else 1


if __name__=='__main__':raise SystemExit(main())
