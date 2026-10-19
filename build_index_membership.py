"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    import pandas as pd
    from datetime import date
    
    # Maps our internal index label -> the code this data source uses in its URLs
    INDICES = {
        'SP500': 'sp500',
        'NASDAQ100': 'nasdaq100',
        'DOW': 'dowjones',
    }
    
    BASE_URL = "https://yfiua.github.io/index-constituents"
    
    
    def month_range(start_year, start_month):
        """Yield (year, month) tuples from the start date through the current month."""
        today = date.today()
        y, m = start_year, start_month
        while (y, m) <= (today.year, today.month):
            yield y, m
            m += 1
            if m > 12:
                m = 1
                y += 1
    
    
    def fetch_snapshot(index_code, year, month):
        """Download one month's constituent list. Returns None if that month isn't archived."""
        url = f"{BASE_URL}/{year}/{month:02d}/constituents-{index_code}.csv"
        try:
            df = pd.read_csv(url)
            return set(df['Symbol'].str.strip())
        except Exception:
            return None
    
    
    def build_membership(index_code, index_name):
        """Diff consecutive monthly snapshots to build (symbol, start_date, end_date) stints."""
        records = []      # finished stints: (symbol, index_name, start_date, end_date)
        active = {}        # symbol -> start_date, for stints still open
        prev_symbols = None
    
        for y, m in month_range(2023, 7):
            symbols = fetch_snapshot(index_code, y, m)
            if symbols is None:
                continue  # that month wasn't archived; skip and keep comparing against the last one we had
            snapshot_date = date(y, m, 1)
    
            if prev_symbols is None:
                # First available month: treat every member as starting here
                # (their real start could be earlier -- this source just doesn't go back further)
                for s in symbols:
                    active[s] = snapshot_date
            else:
                added = symbols - prev_symbols
                removed = prev_symbols - symbols
                for s in added:
                    active[s] = snapshot_date
                for s in removed:
                    start = active.pop(s, snapshot_date)
                    records.append((s, index_name, start, snapshot_date))
    
            prev_symbols = symbols
    
        # Anyone still active at the end is a current member -> end_date stays NULL
        for s, start in active.items():
            records.append((s, index_name, start, None))
    
        return records
    
    
    con = duckdb.connect('trading.duckdb')
    con.execute("DELETE FROM index_membership")  # safe to rerun this script from scratch
    
    all_records = []
    for index_name, index_code in INDICES.items():
        print(f"Building membership history for {index_name}...")
        recs = build_membership(index_code, index_name)
        all_records.extend(recs)
        print(f"  {len(recs)} membership stints found")
    
    df = pd.DataFrame(all_records, columns=['symbol', 'index_name', 'start_date', 'end_date'])
    con.execute("INSERT INTO index_membership SELECT * FROM df")
    
    print(f"\nTotal membership records inserted: {len(df)}")
    print(con.sql("""
        SELECT index_name, COUNT(*) AS stints, COUNT(DISTINCT symbol) AS unique_symbols
        FROM index_membership
        GROUP BY index_name
    """))
    print("\nSample of tickers currently active in all three indices at once:")
    print(con.sql("""
        SELECT symbol, COUNT(DISTINCT index_name) AS index_count
        FROM index_membership
        WHERE end_date IS NULL
        GROUP BY symbol
        HAVING COUNT(DISTINCT index_name) = 3
        LIMIT 10
    """))
    
    con.close()


if __name__ == "__main__":
    main()
