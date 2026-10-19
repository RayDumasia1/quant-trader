"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    from quant_trader.research.scoring import compute_daily_scores
    import duckdb
    import pandas as pd
    import numpy as np
    
    START_DATE = "2022-07-01"
    
    con = duckdb.connect('trading.duckdb')
    
    # Schema changed (setup/structure/full scores added) -- rebuild the table cleanly
    con.execute("DROP TABLE IF EXISTS daily_scores")
    con.execute("""
    CREATE TABLE daily_scores (
        symbol VARCHAR NOT NULL,
        date DATE NOT NULL,
        return_5d DOUBLE,
        return_20d DOUBLE,
        return_60d DOUBLE,
        rel_strength_20d DOUBLE,
        momentum_score DOUBLE,
        ma_20 DOUBLE,
        ma_50 DOUBLE,
        ma_200 DOUBLE,
        rsi_14 DOUBLE,
        macd DOUBLE,
        macd_signal DOUBLE,
        setup VARCHAR,
        structure VARCHAR,
        setup_score DOUBLE,
        structure_score DOUBLE,
        technical_score DOUBLE,          -- now the full 20-point score
        avg_volume_20d DOUBLE,
        relative_volume DOUBLE,
        price_volume_confirm VARCHAR,
        accumulation VARCHAR,
        volume_score DOUBLE,             -- now the full 10-point score
        atr_14 DOUBLE,
        risk_quality_score DOUBLE,       -- ATR/Price tiers only for now; earnings blackout added once
                                          -- earnings_calendar is populated (currently defaults to "not blacked out")
        PRIMARY KEY (symbol, date)
    );
    """)
    
    # ---------- scoring functions, ported directly from Scanner column formulas ----------
    
    # ---------- ensure SPY is available for the Relative Strength component ----------
    
    existing_symbols = set(con.sql("SELECT DISTINCT symbol FROM price_history").df()['symbol'])
    if 'SPY' not in existing_symbols:
        import yfinance as yf
        print("Pulling SPY...")
        spy_df = yf.Ticker('SPY').history(start=START_DATE, auto_adjust=True).reset_index()
        spy_df = spy_df.rename(columns={
            'Date': 'date', 'Open': 'open', 'High': 'high',
            'Low': 'low', 'Close': 'close', 'Volume': 'volume',
        })
        spy_df['symbol'] = 'SPY'
        spy_df['date'] = spy_df['date'].dt.date
        spy_df = spy_df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']]
        con.execute("INSERT INTO price_history SELECT * FROM spy_df")
    
    # ---------- load price data (now including High, needed for Breakout) ----------
    
    prices = con.sql("SELECT symbol, date, high, low, close, volume FROM price_history ORDER BY symbol, date").df()
    scores_df = compute_daily_scores(prices)
    con.execute("INSERT INTO daily_scores SELECT * FROM scores_df")
    
    print(con.sql("""
        SELECT COUNT(*) AS total_rows, COUNT(DISTINCT symbol) AS tickers,
               MIN(date) AS earliest, MAX(date) AS latest
        FROM daily_scores
    """))
    
    print("\nSetup distribution, most recent scan date:")
    print(con.sql("""
        SELECT COALESCE(setup, '(none)') AS setup, COUNT(*) AS n
        FROM daily_scores
        WHERE date = (SELECT MAX(date) FROM daily_scores)
        GROUP BY setup
        ORDER BY n DESC
    """))
    
    print("\nTop 10 by combined Momentum + Technical + Volume, most recent scan date:")
    print(con.sql("""
        SELECT symbol, setup, momentum_score, technical_score, volume_score,
               (momentum_score + technical_score + volume_score) AS combined
        FROM daily_scores
        WHERE date = (SELECT MAX(date) FROM daily_scores)
        ORDER BY combined DESC
        LIMIT 10
    """))
    
    print("\nATR / Risk Quality spot check, most recent date:")
    print(con.sql("""
        SELECT symbol, atr_14, risk_quality_score
        FROM daily_scores
        WHERE date = (SELECT MAX(date) FROM daily_scores)
        ORDER BY risk_quality_score DESC
        LIMIT 10
    """))
    
    print("\nRisk Quality Score distribution, most recent date:")
    print(con.sql("""
        SELECT risk_quality_score, COUNT(*) AS n
        FROM daily_scores
        WHERE date = (SELECT MAX(date) FROM daily_scores)
        GROUP BY risk_quality_score
        ORDER BY risk_quality_score
    """))
    
    print("\nATR as % of price, random sample of 15:")
    print(con.sql("""
        SELECT symbol, atr_14, atr_14 / (SELECT close FROM price_history p
            WHERE p.symbol = daily_scores.symbol AND p.date = daily_scores.date) AS atr_pct_of_price
        FROM daily_scores
        WHERE date = (SELECT MAX(date) FROM daily_scores)
          AND atr_14 IS NOT NULL
        USING SAMPLE 15
    """))
    
    con.close()


if __name__ == "__main__":
    main()
