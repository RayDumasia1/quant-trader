"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    import pandas as pd
    import yfinance as yf
    
    START_DATE = "2022-07-01"
    
    # Confirmed renames where the NEW symbol already pulled fine in the original run --
    # these just need index_membership relabeled, no new price data needed.
    CLEAN_RELABELS = {
        'MMC': 'MRSH',   # Marsh & McLennan rebrand, 2026-01-14
        'FLT': 'CPAY',   # FleetCor -> Corpay rebrand, 2024-03-25
        'PEAK': 'DOC',   # Healthpeak/Physicians Realty Trust merger, 2024-03-04
    }
    
    # This one failed even under its current, correct ticker -- needs an actual retry.
    RETRY_RENAME = {'CDAY': 'DAY'}
    
    con = duckdb.connect('trading.duckdb')
    existing_symbols = set(con.sql("SELECT DISTINCT symbol FROM price_history").df()['symbol'])
    
    print("--- Clean relabels (no download needed) ---")
    for old_sym, new_sym in CLEAN_RELABELS.items():
        if new_sym in existing_symbols:
            con.execute(f"UPDATE index_membership SET symbol = '{new_sym}' WHERE symbol = '{old_sym}'")
            print(f"{new_sym} confirmed present -- relabeled '{old_sym}' -> '{new_sym}' in index_membership.")
        else:
            print(f"WARNING: {new_sym} not found in price_history -- skipping relabel, needs investigation.")
    
    print("\n--- Retrying DAY (formerly CDAY) ---")
    old_sym, new_sym = 'CDAY', 'DAY'
    df = yf.Ticker(new_sym).history(start=START_DATE, auto_adjust=True)
    
    if df.empty:
        print(f"yfinance still empty for {new_sym}, falling back to Stooq...")
        url = f"https://stooq.com/q/d/l/?s={new_sym.lower()}.us&i=d"
        df = pd.read_csv(url)
        if not df.empty and 'Close' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            df = df[df['Date'] >= START_DATE].sort_values('Date')
    
    if df.empty:
        print(f"Still no data for {new_sym} from either source -- needs manual investigation.")
    else:
        df = df.reset_index()
        date_col = 'Date' if 'Date' in df.columns else 'index'
        df = df.rename(columns={
            date_col: 'date', 'Open': 'open', 'High': 'high',
            'Low': 'low', 'Close': 'close', 'Volume': 'volume',
        })
        df['symbol'] = new_sym
        df['date'] = pd.to_datetime(df['date']).dt.date
        df = df[['symbol', 'date', 'open', 'high', 'low', 'close', 'volume']]
        con.execute("DELETE FROM price_history WHERE symbol = ?", [new_sym])
        con.execute("INSERT INTO price_history SELECT * FROM df")
        earliest = df['date'].min()
        print(f"Inserted {len(df):,} rows for {new_sym}, earliest date {earliest}.")
        con.execute(f"UPDATE index_membership SET symbol = '{new_sym}' WHERE symbol = '{old_sym}'")
        print(f"Relabeled '{old_sym}' -> '{new_sym}' in index_membership.")
    
    print(con.sql("""
        SELECT COUNT(*) AS total_rows, COUNT(DISTINCT symbol) AS tickers,
               MIN(date) AS earliest, MAX(date) AS latest
        FROM price_history
    """))
    
    con.close()


if __name__ == "__main__":
    main()
