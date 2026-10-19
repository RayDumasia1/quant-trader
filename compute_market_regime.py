"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    from quant_trader.features.market_regime import compute_market_regime
    import duckdb
    import pandas as pd
    import numpy as np
    import yfinance as yf
    
    START_DATE = "2022-07-01"
    
    # From Assumptions tab
    BULLISH_EXPOSURE = 0.9    # Assumptions!B20
    NEUTRAL_EXPOSURE = 0.6    # Assumptions!B21
    DEFENSIVE_EXPOSURE = 0.3  # Assumptions!B22
    
    con = duckdb.connect('trading.duckdb')
    
    con.execute("DROP TABLE IF EXISTS market_regime_daily")
    con.execute("""
    CREATE TABLE market_regime_daily (
        date DATE PRIMARY KEY,
        spy_close DOUBLE,
        spy_ma20 DOUBLE,
        spy_ma50 DOUBLE,
        spy_ma200 DOUBLE,
        qqq_close DOUBLE,
        qqq_ma50 DOUBLE,
        vix_close DOUBLE,
        breadth_pct DOUBLE,
        breadth_positive VARCHAR,
        volatility_favorable VARCHAR,
        market_score DOUBLE,
        regime VARCHAR,
        max_exposure DOUBLE
    );
    """)
    
    # ---------- ensure QQQ and VIX are available ----------
    
    existing = set(con.sql("SELECT DISTINCT symbol FROM price_history").df()['symbol'])
    for ticker in ['QQQ', '^VIX']:
        if ticker not in existing:
            print(f"Pulling {ticker}...")
            df = yf.Ticker(ticker).history(start=START_DATE, auto_adjust=True).reset_index()
            df = df.rename(columns={
                'Date': 'date', 'Open': 'open', 'High': 'high',
                'Low': 'low', 'Close': 'close', 'Volume': 'volume',
            })
            df['symbol'] = ticker
            df['date'] = df['date'].dt.date
            df = df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']]
            con.execute("INSERT INTO price_history SELECT * FROM df")
            print(f"  Added {len(df):,} rows.")
    
    # ---------- SPY / QQQ / VIX series ----------
    
    spy = con.sql("SELECT date, close FROM price_history WHERE symbol = 'SPY' ORDER BY date").df()
    spy['date'] = pd.to_datetime(spy['date'])
    spy = spy.set_index('date')['close']
    spy_ma20 = spy.rolling(20).mean()
    spy_ma50 = spy.rolling(50).mean()
    spy_ma200 = spy.rolling(200).mean()
    
    qqq = con.sql("SELECT date, close FROM price_history WHERE symbol = 'QQQ' ORDER BY date").df()
    qqq['date'] = pd.to_datetime(qqq['date'])
    qqq = qqq.set_index('date')['close']
    qqq_ma50 = qqq.rolling(50).mean()
    
    vix = con.sql("SELECT date, close FROM price_history WHERE symbol = '^VIX' ORDER BY date").df()
    vix['date'] = pd.to_datetime(vix['date'])
    vix = vix.set_index('date')['close']
    
    # ---------- breadth: % of that day's point-in-time universe trading above its own 50-day MA ----------
    # Uses index_membership so a stock only counts on dates it was actually a constituent --
    # this is exactly the point-in-time discipline index_membership exists for.
    
    breadth = con.sql("""
        WITH universe AS (
            SELECT DISTINCT ds.date, im.symbol
            FROM (SELECT DISTINCT date FROM daily_scores) ds
            JOIN index_membership im
              ON ds.date >= im.start_date
             AND (im.end_date IS NULL OR ds.date < im.end_date)
        ),
        joined AS (
            SELECT u.date, u.symbol, p.close, ds.ma_50
            FROM universe u
            JOIN price_history p ON p.symbol = u.symbol AND p.date = u.date
            JOIN daily_scores ds ON ds.symbol = u.symbol AND ds.date = u.date
        )
        SELECT date,
               COUNT(*) AS universe_count,
               SUM(CASE WHEN ma_50 IS NOT NULL AND close > ma_50 THEN 1 ELSE 0 END) AS above_ma50_count
        FROM joined
        GROUP BY date
    """).df()
    breadth['date'] = pd.to_datetime(breadth['date'])
    breadth['breadth_pct'] = breadth['above_ma50_count'] / breadth['universe_count']
    breadth = breadth.set_index('date')['breadth_pct']
    
    # ---------- combine into Market Score ----------
    
    df = compute_market_regime(
        spy, qqq, vix, breadth, require_breadth=False,
        bullish_exposure=BULLISH_EXPOSURE, neutral_exposure=NEUTRAL_EXPOSURE,
        defensive_exposure=DEFENSIVE_EXPOSURE,
    )
    df = df.reset_index().rename(columns={'index': 'date'})
    df['date'] = df['date'].dt.date
    
    con.execute("INSERT INTO market_regime_daily SELECT * FROM df")
    
    print(con.sql("""
        SELECT COUNT(*) AS total_rows, MIN(date) AS earliest, MAX(date) AS latest
        FROM market_regime_daily
    """))
    print("\nRegime distribution over full history:")
    print(con.sql("""
        SELECT COALESCE(regime, '(warmup period)') AS regime, COUNT(*) AS days
        FROM market_regime_daily GROUP BY regime ORDER BY days DESC
    """))
    print("\nMost recent 10 trading days:")
    print(con.sql("""
        SELECT date, spy_close, breadth_pct, vix_close, market_score, regime, max_exposure
        FROM market_regime_daily ORDER BY date DESC LIMIT 10
    """))
    
    con.close()


if __name__ == "__main__":
    main()
