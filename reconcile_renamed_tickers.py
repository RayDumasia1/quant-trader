"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    import pandas as pd
    import yfinance as yf
    
    START_DATE = "2022-07-01"
    
    # Confirmed same-company ticker changes (not acquisitions -- the security just got a new symbol)
    RENAMES = {
        'BK': 'BNY',    # Bank of New York Mellon, effective 2026-05-21
        'FI': 'FISV',   # Fiserv, effective 2025-11-11 (moved back to Nasdaq)
    }
    
    con = duckdb.connect('trading.duckdb')
    existing_symbols = set(con.sql("SELECT DISTINCT symbol FROM price_history").df()['symbol'])
    
    for old_sym, new_sym in RENAMES.items():
        if new_sym in existing_symbols:
            print(f"{new_sym} already present in price_history (pulled fine under its own name in the original run).")
        else:
            print(f"Pulling {new_sym} (formerly {old_sym})...")
            df = yf.Ticker(new_sym).history(start=START_DATE, auto_adjust=True)
            if df.empty:
                print(f"  Still no data for {new_sym} -- needs manual investigation, skipping relabel.")
                continue
            earliest = df.index.min().date()
            carried_over = str(earliest) <= "2022-07-15"
            print(f"  Got data back to {earliest} "
                  f"({'full history carried over under new symbol' if carried_over else 'NOTE: shorter than requested range -- check this'})")
            df = df.reset_index().rename(columns={
                'Date': 'date', 'Open': 'open', 'High': 'high',
                'Low': 'low', 'Close': 'close', 'Volume': 'volume',
            })
            df['symbol'] = new_sym
            df['date'] = df['date'].dt.date
            df = df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']]
            con.execute("INSERT INTO price_history SELECT * FROM df")
    
        # Relabel the old symbol's membership stints so the full history reads as one continuous entity
        con.execute(f"UPDATE index_membership SET symbol = '{new_sym}' WHERE symbol = '{old_sym}'")
        print(f"  Relabeled '{old_sym}' -> '{new_sym}' in index_membership.\n")
    
    print(con.sql("""
        SELECT COUNT(*) AS total_rows, COUNT(DISTINCT symbol) AS tickers,
               MIN(date) AS earliest, MAX(date) AS latest
        FROM price_history
    """))
    
    con.close()


if __name__ == "__main__":
    main()
