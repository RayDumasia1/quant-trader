"""Non-mutating diagnostics. SPY sessions are a proxy, not an exchange calendar."""
from datetime import date


def validate(repository, *, as_of, max_age_days=7, tolerance=1e-10):
    if max_age_days < 0 or tolerance < 0:
        raise ValueError("Age and tolerance must be nonnegative")
    as_of = date.fromisoformat(str(as_of))
    con = repository._connection

    def rows(sql, parameters=None):
        result = con.execute(sql, parameters or [])
        names = [column[0] for column in result.description]
        return [dict(zip(names, row)) for row in result.fetchall()]

    tables = [row[0] for row in con.execute('SHOW TABLES').fetchall()]
    counts = {table: con.execute('SELECT COUNT(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
              for table in tables}
    coverage = rows("SELECT symbol, COUNT(*) AS rows, MIN(date) AS first_date, "
                    "MAX(date) AS last_date FROM price_history WHERE date <= ? "
                    "GROUP BY symbol ORDER BY symbol", [as_of])
    targets = {}
    for label, aliases in {'NDX': ['NDX', '^NDX'], 'TQQQ': ['TQQQ'],
                           'SQQQ': ['SQQQ'], 'QQQ': ['QQQ']}.items():
        found = [item for item in coverage if item['symbol'] in aliases]
        targets[label] = {
            'present': bool(found), 'coverage': found,
            'stale': bool(found) and any((as_of - item['last_date']).days > max_age_days for item in found),
        }
    validity = rows('''SELECT
        COUNT(*) FILTER (WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL) AS null_ohlc,
        COUNT(*) FILTER (WHERE NOT isfinite(open) OR NOT isfinite(high) OR NOT isfinite(low) OR NOT isfinite(close)) AS nonfinite_ohlc,
        COUNT(*) FILTER (WHERE least(open,high,low,close) <= 0) AS nonpositive_ohlc,
        COUNT(*) FILTER (WHERE high + ? < greatest(open,close,low) OR low - ? > least(open,close,high)) AS invalid_bounds,
        COUNT(*) FILTER (WHERE volume < 0) AS negative_volume,
        COUNT(*) FILTER (WHERE volume IS NULL) AS null_volume
        FROM price_history WHERE date <= ?''', [tolerance, tolerance, as_of])[0]
    missing_members = rows('''SELECT DISTINCT im.symbol FROM index_membership im
        WHERE im.start_date <= ? AND NOT EXISTS
        (SELECT 1 FROM price_history p WHERE p.symbol=im.symbol AND p.date <= ?)
        ORDER BY im.symbol''', [as_of, as_of])
    missing_breadth = rows('''SELECT COUNT(*) AS rows FROM market_regime_daily
        WHERE date <= ? AND breadth_pct IS NULL AND market_score IS NOT NULL''', [as_of])[0]['rows']
    session_gaps = rows('''WITH bounds AS (
        SELECT symbol, MIN(date) first_date, MAX(date) last_date FROM price_history
        WHERE date <= ? AND symbol IN ('QQQ','TQQQ','SQQQ','NDX','^NDX','^VIX') GROUP BY symbol
        ) SELECT b.symbol, COUNT(*) AS missing_spy_sessions
        FROM bounds b JOIN price_history s ON s.symbol='SPY'
          AND s.date BETWEEN b.first_date AND b.last_date
        WHERE NOT EXISTS (SELECT 1 FROM price_history p WHERE p.symbol=b.symbol AND p.date=s.date)
        GROUP BY b.symbol ORDER BY b.symbol''', [as_of])
    extra_sessions = rows('''SELECT p.symbol,p.date FROM price_history p
        WHERE p.symbol IN ('QQQ','TQQQ','SQQQ','NDX','^NDX','^VIX') AND p.date <= ?
        AND p.date BETWEEN (SELECT MIN(date) FROM price_history WHERE symbol='SPY')
                       AND (SELECT MAX(date) FROM price_history WHERE symbol='SPY')
        AND NOT EXISTS (SELECT 1 FROM price_history s WHERE s.symbol='SPY' AND s.date=p.date)
        ORDER BY p.symbol,p.date''', [as_of])
    warnings = [f"{name}: missing" for name, item in targets.items() if not item['present']]
    warnings += [f"{name}: stale" for name, item in targets.items() if item['stale']]
    if missing_breadth:
        warnings.append(f"{missing_breadth} legacy scored regime rows have missing breadth")
    if missing_members:
        warnings.append(f"{len(missing_members)} membership symbols have no stored price history")
    if any(validity.values()):
        warnings.append('Price validity checks found exceptions')
    if session_gaps or extra_sessions:
        warnings.append('Target or VIX sessions differ from the stored SPY session proxy')
    return {
        'as_of': as_of, 'database': str(repository.path), 'table_counts': counts,
        'target_coverage': targets, 'price_validity': validity,
        'missing_membership_symbols': missing_members,
        'scored_regimes_missing_breadth': missing_breadth,
        'missing_spy_sessions': session_gaps, 'extra_spy_sessions': extra_sessions,
        'warnings': warnings,
        'limitations': [
            'Stored SPY sessions are not an authoritative exchange calendar.',
            'No provider provenance, adjustment consistency or corporate-action verification.',
            'Membership snapshots do not establish exact effective or knowledge dates.',
            'As-of bounds restrict rows; revised historical prices are not point-in-time snapshots.',
        ],
    }
