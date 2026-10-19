"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    import pandas as pd
    import yfinance as yf
    import time
    
    START_DATE = "2022-07-01"
    
    # Tickers that are genuinely active/liquid today but failed on the bulk pull --
    # most likely a transient rate-limit issue within their batch, not a real data gap.
    RETRY_TICKERS = ['BK', 'CMA', 'CTRA', 'FI', 'HOLX', 'SEE']
    
    con = duckdb.connect('trading.duckdb')
    
    frames = []
    still_failed = []
    
    for sym in RETRY_TICKERS:
        print(f"Retrying {sym}...")
        try:
            df = yf.Ticker(sym).history(start=START_DATE, auto_adjust=True)
            if df.empty:
                still_failed.append(sym)
                continue
            df = df.reset_index()
            df = df.rename(columns={
                'Date': 'date', 'Open': 'open', 'High': 'high',
                'Low': 'low', 'Close': 'close', 'Volume': 'volume',
            })
            df['symbol'] = sym
            df['date'] = df['date'].dt.date
            frames.append(df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']])
        except Exception as e:
            print(f"  Still failing: {e}")
            still_failed.append(sym)
        time.sleep(3)  # slower pacing than the bulk pull, one ticker at a time
    
    if frames:
        retry_df = pd.concat(frames, ignore_index=True)
        # Remove any partial/stale rows for these symbols first, then insert fresh
        con.execute("DELETE FROM price_history WHERE symbol IN (SELECT DISTINCT symbol FROM retry_df)")
        con.execute("INSERT INTO price_history SELECT * FROM retry_df")
        print(f"\nInserted {len(retry_df):,} rows for {retry_df['symbol'].nunique()} tickers.")
    
    if still_failed:
        print(f"\nStill failed (worth checking manually on finance.yahoo.com): {still_failed}")
    
    print(con.sql("""
        SELECT COUNT(*) AS total_rows, COUNT(DISTINCT symbol) AS tickers,
               MIN(date) AS earliest, MAX(date) AS latest
        FROM price_history
    """))
    
    con.close()


if __name__ == "__main__":
    main()
