"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    import pandas as pd
    import numpy as np
    
    con = duckdb.connect('trading.duckdb')
    
    con.execute("DROP TABLE IF EXISTS signal_outcomes")
    con.execute("""
    CREATE TABLE signal_outcomes (
        signal_date DATE NOT NULL,
        symbol VARCHAR NOT NULL,
        opportunity_score DOUBLE,   -- PARTIAL: Momentum+Technical+Volume+MarketRegime+RiskQuality (max 70 of 100)
        score_percentile DOUBLE,    -- cross-sectional percentile among that day's in-universe scan
        setup_type VARCHAR,
        regime VARCHAR,             -- extra vs. the Excel schema -- useful for regime-conditioned analysis later
        eligible VARCHAR,           -- left NULL -- needs full score + R:R logic, not built yet
        signal_close DOUBLE,
        close_5d DOUBLE,
        forward_5d_return DOUBLE,
        close_10d DOUBLE,
        forward_10d_return DOUBLE,
        mfe_10d DOUBLE,
        mae_10d DOUBLE,
        positive_5d VARCHAR,
        positive_10d VARCHAR,
        spy_forward_5d_return DOUBLE,
        spy_forward_10d_return DOUBLE,
        excess_5d_return DOUBLE,     -- forward_5d_return minus SPY's own forward 5D return, same window
        excess_10d_return DOUBLE,    -- forward_10d_return minus SPY's own forward 10D return, same window
        ew_forward_5d_return DOUBLE,   -- equal-weighted average forward 5D return across the in-universe scan that day
        ew_forward_10d_return DOUBLE,  -- same, 10D
        excess_5d_return_ew DOUBLE,    -- forward_5d_return minus the equal-weighted universe average (not SPY)
        excess_10d_return_ew DOUBLE,   -- forward_10d_return minus the equal-weighted universe average (not SPY)
        momentum_score DOUBLE,
        technical_score DOUBLE,
        volume_score DOUBLE,
        risk_quality_score DOUBLE,
        momentum_percentile DOUBLE,       -- cross-sectional percentile of this factor alone, same day
        technical_percentile DOUBLE,
        volume_percentile DOUBLE,
        risk_quality_percentile DOUBLE,
        PRIMARY KEY (symbol, signal_date)
    );
    """)
    
    print("Building partial Opportunity Score for every in-universe symbol/date...")
    partial = con.sql("""
        WITH combined AS (
            SELECT ds.symbol, ds.date,
                   ds.setup,
                   mr.regime,
                   ds.momentum_score, ds.technical_score, ds.volume_score, ds.risk_quality_score,
                   (ds.momentum_score + ds.technical_score + ds.volume_score
                    + ds.risk_quality_score + mr.market_score) AS opportunity_score
            FROM daily_scores ds
            JOIN market_regime_daily mr ON mr.date = ds.date
            JOIN index_membership im
              ON im.symbol = ds.symbol
             AND ds.date >= im.start_date
             AND (im.end_date IS NULL OR ds.date < im.end_date)
            WHERE ds.momentum_score IS NOT NULL
              AND ds.technical_score IS NOT NULL
              AND ds.volume_score IS NOT NULL
              AND ds.risk_quality_score IS NOT NULL
              AND mr.market_score IS NOT NULL
        )
        -- DISTINCT because a symbol can match index_membership more than once on the same date
        -- (e.g. simultaneously S&P 500 and Nasdaq-100) -- scores are identical either way, just dedupe.
        SELECT DISTINCT symbol, date, opportunity_score, setup, regime,
               momentum_score, technical_score, volume_score, risk_quality_score,
               CUME_DIST() OVER (PARTITION BY date ORDER BY opportunity_score) AS score_percentile,
               CUME_DIST() OVER (PARTITION BY date ORDER BY momentum_score) AS momentum_percentile,
               CUME_DIST() OVER (PARTITION BY date ORDER BY technical_score) AS technical_percentile,
               CUME_DIST() OVER (PARTITION BY date ORDER BY volume_score) AS volume_percentile,
               CUME_DIST() OVER (PARTITION BY date ORDER BY risk_quality_score) AS risk_quality_percentile
        FROM combined
    """).df()
    partial['date'] = pd.to_datetime(partial['date'])
    print(f"  {len(partial):,} in-universe symbol/date observations scored.")
    
    print("Computing forward returns and 10D MFE/MAE from price history...")
    prices = con.sql("SELECT symbol, date, high, low, close FROM price_history").df()
    prices['date'] = pd.to_datetime(prices['date'])
    
    def forward_rolling(series, window, agg):
        """Rolling max/min over the NEXT `window` days (excludes the current day itself)."""
        shifted = series.shift(-1)
        rev = pd.Series(shifted.values[::-1])
        rolled = getattr(rev.rolling(window, min_periods=window), agg)()
        return rolled.values[::-1]
    
    fwd_frames = []
    for symbol, g in prices.groupby('symbol'):
        g = g.sort_values('date').set_index('date')
        close = g['close']
        high = g['high']
        low = g['low']
    
        close_5d = close.shift(-5)
        close_10d = close.shift(-10)
        mfe_10d = forward_rolling(high, 10, 'max') / close.values - 1
        mae_10d = forward_rolling(low, 10, 'min') / close.values - 1
    
        out = pd.DataFrame({
            'symbol': symbol,
            'date': close.index,
            'signal_close': close.values,
            'close_5d': close_5d.values,
            'close_10d': close_10d.values,
            'mfe_10d': mfe_10d,
            'mae_10d': mae_10d,
        })
        fwd_frames.append(out)
    
    fwd_df = pd.concat(fwd_frames, ignore_index=True)
    
    # ---------- SPY's own forward returns, for excess-return benchmarking ----------
    spy_prices = prices[prices['symbol'] == 'SPY'].sort_values('date').set_index('date')
    spy_close = spy_prices['close']
    spy_fwd = pd.DataFrame({
        'date': spy_close.index,
        'spy_forward_5d_return': (spy_close.shift(-5) / spy_close - 1).values,
        'spy_forward_10d_return': (spy_close.shift(-10) / spy_close - 1).values,
    })
    
    merged = partial.merge(fwd_df, on=['symbol', 'date'], how='left')
    merged = merged.merge(spy_fwd, on='date', how='left')
    merged['forward_5d_return'] = merged['close_5d'] / merged['signal_close'] - 1
    merged['forward_10d_return'] = merged['close_10d'] / merged['signal_close'] - 1
    merged['excess_5d_return'] = merged['forward_5d_return'] - merged['spy_forward_5d_return']
    merged['excess_10d_return'] = merged['forward_10d_return'] - merged['spy_forward_10d_return']
    
    # ---------- equal-weighted universe benchmark: average forward return across all in-universe stocks that day ----------
    ew = merged.groupby('date')[['forward_5d_return', 'forward_10d_return']].transform('mean')
    merged['ew_forward_5d_return'] = ew['forward_5d_return']
    merged['ew_forward_10d_return'] = ew['forward_10d_return']
    merged['excess_5d_return_ew'] = merged['forward_5d_return'] - merged['ew_forward_5d_return']
    merged['excess_10d_return_ew'] = merged['forward_10d_return'] - merged['ew_forward_10d_return']
    
    merged['positive_5d'] = np.where(merged['forward_5d_return'].isna(), None,
                                      np.where(merged['forward_5d_return'] > 0, 'Yes', 'No'))
    merged['positive_10d'] = np.where(merged['forward_10d_return'].isna(), None,
                                       np.where(merged['forward_10d_return'] > 0, 'Yes', 'No'))
    
    merged = merged.rename(columns={'date': 'signal_date', 'setup': 'setup_type'})
    merged['eligible'] = None
    
    final_cols = ['signal_date', 'symbol', 'opportunity_score', 'score_percentile', 'setup_type', 'regime',
                  'eligible', 'signal_close', 'close_5d', 'forward_5d_return', 'close_10d',
                  'forward_10d_return', 'mfe_10d', 'mae_10d', 'positive_5d', 'positive_10d',
                  'spy_forward_5d_return', 'spy_forward_10d_return', 'excess_5d_return', 'excess_10d_return',
                  'ew_forward_5d_return', 'ew_forward_10d_return', 'excess_5d_return_ew', 'excess_10d_return_ew',
                  'momentum_score', 'technical_score', 'volume_score', 'risk_quality_score',
                  'momentum_percentile', 'technical_percentile', 'volume_percentile', 'risk_quality_percentile']
    merged = merged[final_cols]
    merged['signal_date'] = merged['signal_date'].dt.date
    
    con.execute("INSERT INTO signal_outcomes SELECT * FROM merged")
    
    print(con.sql("""
        SELECT COUNT(*) AS total_signals, COUNT(DISTINCT symbol) AS tickers,
               MIN(signal_date) AS earliest, MAX(signal_date) AS latest,
               SUM(CASE WHEN forward_10d_return IS NOT NULL THEN 1 ELSE 0 END) AS with_10d_outcome_known
        FROM signal_outcomes
    """))
    
    print("\nObservations by score band -- vs SPY and vs equal-weighted universe (80+ not reachable yet):")
    print(con.sql("""
        SELECT CASE
                 WHEN opportunity_score < 60 THEN '<60'
                 WHEN opportunity_score < 70 THEN '60-69'
                 ELSE '70 (max)'
               END AS band,
               COUNT(*) AS n,
               ROUND(AVG(excess_10d_return), 4) AS avg_excess_vs_spy,
               ROUND(AVG(excess_10d_return_ew), 4) AS avg_excess_vs_ew_universe,
               ROUND(AVG(CASE WHEN excess_10d_return_ew > 0 THEN 1.0 ELSE 0.0 END), 3) AS beat_ew_rate_10d
        FROM signal_outcomes
        WHERE forward_10d_return IS NOT NULL
        GROUP BY band
        ORDER BY band
    """))
    
    print("\nAvg 10D excess return (vs equal-weighted universe) by decile, PER FACTOR:")
    for factor, pct_col in [
        ('Momentum', 'momentum_percentile'),
        ('Technical', 'technical_percentile'),
        ('Volume', 'volume_percentile'),
        ('Risk Quality', 'risk_quality_percentile'),
        ('Combined Score', 'score_percentile'),
    ]:
        print(f"\n  -- {factor} --")
        print(con.sql(f"""
            SELECT
                CASE
                    WHEN {pct_col} >= 0.9 THEN '90-100 (top)'
                    WHEN {pct_col} >= 0.7 THEN '70-90'
                    WHEN {pct_col} >= 0.5 THEN '50-70'
                    WHEN {pct_col} >= 0.3 THEN '30-50'
                    WHEN {pct_col} >= 0.1 THEN '10-30'
                    ELSE '0-10 (bottom)'
                END AS decile,
                COUNT(*) AS n,
                ROUND(AVG(excess_10d_return_ew), 4) AS avg_excess_vs_ew,
                ROUND(AVG(CASE WHEN excess_10d_return_ew > 0 THEN 1.0 ELSE 0.0 END), 3) AS beat_ew_rate
            FROM signal_outcomes
            WHERE forward_10d_return IS NOT NULL
            GROUP BY decile
            ORDER BY decile DESC
        """))
    
    con.close()


if __name__ == "__main__":
    main()
