"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    import pandas as pd
    import yfinance as yf
    import time
    
    # Buffer start date well before our earliest index_membership date (2023-07) so that
    # indicators needing long lookbacks (e.g. a 200-day moving average) have enough
    # history to compute correctly from day one of the actual scan window.
    START_DATE = "2022-07-01"
    
    CHUNK_SIZE = 50              # tickers per yfinance batch request -- keeps comfortably under rate limits
    PAUSE_BETWEEN_CHUNKS = 2     # seconds; polite pacing against the free API
    
    
    def to_yahoo_symbol(sym):
        """Yahoo Finance uses a dash for share classes where Wikipedia/S&P use a dot,
        e.g. BRK.B -> BRK-B, BF.B -> BF-B. We convert only for the download request and
        store data back under the original symbol so it still joins cleanly against
        index_membership."""
        return sym.replace('.', '-')
    
    
    con = duckdb.connect('trading.duckdb')
    
    tickers = con.sql("SELECT DISTINCT symbol FROM index_membership ORDER BY symbol").df()['symbol'].tolist()
    print(f"Found {len(tickers)} distinct tickers to pull.")
    
    con.execute("DELETE FROM price_history")  # full rebuild -- fine for an initial backfill
    
    chunk_frames = []
    failed = []
    
    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        yahoo_chunk = [to_yahoo_symbol(t) for t in chunk]
        yahoo_to_orig = dict(zip(yahoo_chunk, chunk))
    
        print(f"Downloading {i + 1}-{min(i + CHUNK_SIZE, len(tickers))} of {len(tickers)}...")
    
        try:
            data = yf.download(
                yahoo_chunk,
                start=START_DATE,
                group_by='ticker',
                auto_adjust=True,   # Close (and Open/High/Low) come back split & dividend adjusted
                threads=True,
                progress=False,
            )
        except Exception as e:
            print(f"  Chunk failed entirely: {e}")
            failed.extend(chunk)
            time.sleep(PAUSE_BETWEEN_CHUNKS)
            continue
    
        for yahoo_sym in yahoo_chunk:
            orig_sym = yahoo_to_orig[yahoo_sym]
            try:
                df = data.copy() if len(yahoo_chunk) == 1 else data[yahoo_sym].copy()
                df = df.dropna(subset=['Close']).reset_index()
                if df.empty:
                    failed.append(orig_sym)
                    continue
                df = df.rename(columns={
                    'Date': 'date', 'Open': 'open', 'High': 'high',
                    'Low': 'low', 'Close': 'close', 'Volume': 'volume',
                })
                df['symbol'] = orig_sym
                df['date'] = df['date'].dt.date
                chunk_frames.append(df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']])
            except Exception:
                failed.append(orig_sym)
    
        time.sleep(PAUSE_BETWEEN_CHUNKS)
    
    price_df = pd.concat(chunk_frames, ignore_index=True)
    print(f"\nCollected {len(price_df):,} price rows across {price_df['symbol'].nunique()} tickers.")
    if failed:
        print(f"Failed/empty for {len(failed)} tickers: {sorted(set(failed))}")
    
    con.execute("INSERT INTO price_history SELECT * FROM price_df")
    
    print(con.sql("""
        SELECT COUNT(*) AS total_rows, COUNT(DISTINCT symbol) AS tickers,
               MIN(date) AS earliest, MAX(date) AS latest
        FROM price_history
    """))
    
    con.close()


if __name__ == "__main__":
    main()
