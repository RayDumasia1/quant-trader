"""Explicit Yahoo chart acquisition, retaining raw bytes and all failures.

No fallback, repair, filling, adjustment reconstruction or credential use.
"""
from datetime import date, datetime, timezone
import importlib.metadata as metadata
import json
import math
from pathlib import Path
from urllib.parse import quote
import uuid

import requests

from quant_trader.data.calendar import schedule
from quant_trader.data.datasets import DatasetStore, canonical, checksum

INSTRUMENTS = {
    'NDX': {'provider_symbol': '^NDX', 'type': 'INDEX'},
    'TQQQ': {'provider_symbol': 'TQQQ', 'type': 'ETF'},
    'SQQQ': {'provider_symbol': 'SQQQ', 'type': 'ETF'},
    'QQQ': {'provider_symbol': 'QQQ', 'type': 'ETF'},
}
ADJUSTMENTS = {
    'unadjusted_ohlc': 'unavailable; null, never reconstructed',
    'split_adjusted_ohlc': 'Yahoo native quote OHLC; provider split-adjustment assumption, unverified independently',
    'distribution_adjusted_close': 'Yahoo adjclose; provider split/distribution-adjusted series, not execution price',
    'volume': 'provider-native, adjustment convention not independently verified',
}


def normalize(payload, symbol, calendar):
    result = payload['chart']['result'][0]
    meta = result['meta']
    required = INSTRUMENTS[symbol]
    if meta.get('symbol') != required['provider_symbol'] or meta.get('instrumentType') != required['type']:
        raise ValueError('Provider instrument identity mismatch')
    if meta.get('exchangeTimezoneName') != 'America/New_York' or meta.get('currency') != 'USD':
        raise ValueError('Provider market timezone or currency mismatch')
    allowed_exchanges = {'NIM', 'NMS', 'NAS', 'NASDAQ'} if symbol == 'NDX' else {'NMS','NGM','NCM','NAS','NASDAQ'}
    if meta.get('exchangeName') not in allowed_exchanges:
        raise ValueError('Provider exchange is not recognized as Nasdaq')
    quote_data = result['indicators']['quote'][0]
    adj = result['indicators'].get('adjclose', [{}])[0].get('adjclose')
    timestamps = result.get('timestamp', [])
    if not timestamps:
        raise ValueError('Provider returned no bars')
    if any(len(quote_data.get(field, [])) != len(timestamps) for field in ['open','high','low','close','volume']):
        raise ValueError('Provider quote lengths do not match timestamps')
    if adj is not None and len(adj) != len(timestamps):
        raise ValueError('Provider adjusted-close length mismatch')
    lookup = {row['session']: row for row in calendar}
    bars = []
    for i, timestamp in enumerate(timestamps):
        from zoneinfo import ZoneInfo
        session = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
        row = {'symbol': symbol, 'session': session,
               'available_at': lookup.get(session, {}).get('available_at'),
               'unadjusted_open': None, 'unadjusted_high': None,
               'unadjusted_low': None, 'unadjusted_close': None,
               **{f'split_adjusted_{field}': quote_data[field][i] for field in ['open','high','low','close']},
               'volume': quote_data['volume'][i],
               'distribution_adjusted_close': adj[i] if adj is not None else None}
        bars.append(row)
    for previous, current in zip(bars, bars[1:]):
        a, b = previous['distribution_adjusted_close'], current['distribution_adjusted_close']
        current['distribution_adjusted_return'] = b/a-1 if a and b and math.isfinite(a) and math.isfinite(b) else None
    bars[0]['distribution_adjusted_return'] = None
    actions = []
    for kind, events in result.get('events', {}).items():
        for event in events.values():
            actions.append({'kind': kind, **event})
    return bars, sorted(actions, key=lambda row: (row['date'], row['kind']))


def validate_bars(bars, actions, calendar, *, anomaly_threshold=0.35):
    expected = {row['session'] for row in calendar}
    dates = [row['session'] for row in bars]
    errors, warnings = [], []
    if len(set(dates)) != len(dates): errors.append('duplicate_sessions')
    if dates != sorted(dates): errors.append('unordered_sessions')
    missing = sorted(expected - set(dates))
    unexpected = sorted(set(dates) - expected)
    if missing: errors.append('missing_sessions')
    if unexpected: errors.append('unexpected_sessions')
    anomalies, factor_jumps = [], []
    ordered = sorted(bars, key=lambda row: row['session'])
    action_dates = set()
    cash_distributions = {}
    from zoneinfo import ZoneInfo
    for action in actions:
        day = datetime.fromtimestamp(action['date'], timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
        action_dates.add(day)
        if day not in expected: errors.append('action_outside_calendar')
        if action['kind'] == 'splits':
            numerator, denominator = action.get('numerator'), action.get('denominator')
            if not numerator or not denominator or not math.isfinite(numerator) or not math.isfinite(denominator) or numerator <= 0 or denominator <= 0:
                errors.append('invalid_split_ratio')
        elif action['kind'] in {'dividends', 'capitalGains'}:
            amount = action.get('amount')
            if amount is None or not math.isfinite(amount) or amount < 0: errors.append('invalid_distribution')
            else: cash_distributions[day] = cash_distributions.get(day, 0) + amount
        else:
            warnings.append('unknown_corporate_action_kind')
    previous = None
    for row in ordered:
        values = [row[f'split_adjusted_{f}'] for f in ['open','high','low','close']]
        if any(value is None or not math.isfinite(value) or value <= 0 for value in values):
            errors.append('invalid_ohlc'); previous = None; continue
        o, h, l, c = values
        if h + 1e-8 < max(o,l,c) or l - 1e-8 > min(o,h,c): errors.append('invalid_ohlc_bounds')
        if row['available_at'] is None: errors.append('unmapped_availability')
        if row['volume'] is None or not math.isfinite(row['volume']) or row['volume'] < 0: errors.append('invalid_volume')
        adjusted = row['distribution_adjusted_close']
        if adjusted is None or not math.isfinite(adjusted) or adjusted <= 0:
            errors.append('invalid_distribution_adjusted_close'); previous = None; continue
        factor = adjusted / c
        if previous:
            last, last_factor = previous
            r = c / last['split_adjusted_close'] - 1
            if abs(r) > anomaly_threshold: anomalies.append({'session':row['session'],'return':r})
            # Unexpected factor changes are diagnostics, never repaired.
            if abs(factor / last_factor - 1) > 1e-5 and row['session'] not in action_dates:
                factor_jumps.append(row['session'])
            distribution = cash_distributions.get(row['session'], 0)
            if distribution:
                prior_close = last['split_adjusted_close']
                if distribution >= prior_close:
                    errors.append('distribution_exceeds_previous_close')
                elif abs((factor/last_factor) * (1-distribution/prior_close) - 1) > 1e-3:
                    warnings.append('distribution_adjustment_factor_inconsistent')
            for action in actions:
                if action['kind'] != 'splits': continue
                day = datetime.fromtimestamp(action['date'], timezone.utc).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                if day == row['session'] and action.get('numerator',0) > 0 and action.get('denominator',0) > 0:
                    ratio = action['numerator'] / action['denominator']
                    if abs(ratio-1) > 0.1 and abs((1+r)*ratio - 1) < 0.15 and abs(r) > 0.25:
                        errors.append('possible_unadjusted_split_jump_in_native_series')
        previous = row, factor
    if anomalies: warnings.append('anomalous_native_returns')
    if factor_jumps: warnings.append('adjustment_factor_changes_without_reported_actions')
    warnings.append('unadjusted_execution_prices_and_independent_action_verification_unavailable')
    return {'errors': sorted(set(errors)), 'warnings': sorted(set(warnings)),
            'missing_sessions': missing, 'unexpected_sessions': unexpected,
            'anomalous_returns': anomalies, 'unexplained_factor_changes': factor_jumps,
            'rows': len(bars), 'first_session': min(dates) if dates else None,
            'last_session': max(dates) if dates else None,
            'signal_data_valid': bool(bars) and not errors and not anomalies and not factor_jumps,
            'execution_ready': False}


def acquire(symbol, *, start, end, root='data/v1.1', transport=None):
    """Inclusive start, exclusive end; one request and a unique attempt record.

    Blocked/invalid responses never populate a dataset. Raw response bytes are
    retained with the attempt, including HTTP failures. No network retries.
    """
    if symbol not in INSTRUMENTS: raise ValueError('Unknown instrument; no substitution is permitted')
    start, end = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    if start >= end: raise ValueError('start must precede exclusive end')
    retrieved = datetime.now(timezone.utc)
    if end > retrieved.date(): raise ValueError('Request must exclude the current, potentially incomplete session')
    calendar = schedule(start, end.fromordinal(end.toordinal()-1))
    attempt = Path(root) / 'attempts' / uuid.uuid4().hex
    attempt.mkdir(parents=True, exist_ok=False)
    params = {'period1':int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp()),
              'period2':int(datetime.combine(end, datetime.min.time(), timezone.utc).timestamp()),
              'interval':'1d', 'events':'div,splits,capitalGains'}
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(INSTRUMENTS[symbol]['provider_symbol'], safe='')
    provenance = {'provider':'Yahoo Finance chart', 'adapter_version':'yahoo-chart-v1.1',
                  'symbol':symbol, **INSTRUMENTS[symbol], 'url':url, 'request':params,
                  'requested_start':str(start), 'requested_end_exclusive':str(end),
                  'adjustments':ADJUSTMENTS, 'calendar':'NASDAQ',
                  'calendar_version':metadata.version('pandas_market_calendars'),
                  'publication_lag_minutes':5}
    report = {'symbol':symbol, 'retrieved_at':retrieved.isoformat(), 'provenance':provenance,
              'status':'failed', 'dataset_id':None}
    try:
        response = (transport or requests.get)(url, params=params, timeout=30)
        raw = response.content
        with (attempt/'response.bin').open('xb') as handle: handle.write(raw)
        report.update(http_status=response.status_code, raw_sha256=checksum(raw))
        response.raise_for_status()
        payload = json.loads(raw)
        if payload.get('chart',{}).get('error'): raise ValueError('Provider returned a chart error')
        bars, actions = normalize(payload, symbol, calendar)
        validation = validate_bars(bars, actions, calendar)
        report['validation'] = validation
        if validation['errors']:
            report['failure'] = 'Validation failed; dataset not populated'
        else:
            report['dataset_id'] = DatasetStore(root).put(raw=raw, bars=bars, actions=actions,
                calendar=calendar, provenance=provenance, validation=validation)
            report['status'] = 'available_unverified_execution'
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError) as error:
        # Exception messages may include proxy credentials or response bodies.
        report['failure'] = type(error).__name__
    with (attempt/'attempt.json').open('xb') as handle: handle.write(canonical(report))
    return report


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True, help='Exclusive end date; current session is excluded')
    parser.add_argument('--root', default='data/v1.1')
    args = parser.parse_args(argv)
    reports = [acquire(symbol,start=args.start,end=args.end,root=args.root) for symbol in INSTRUMENTS]
    print(json.dumps(reports, indent=2))
    return 0 if all(row['dataset_id'] for row in reports) else 1


if __name__ == '__main__':
    raise SystemExit(main())
