"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    
    # Connecting to a filename that doesn't exist yet creates it automatically.
    con = duckdb.connect('trading.duckdb')
    
    con.sql("""
    CREATE TABLE IF NOT EXISTS price_history (
        symbol VARCHAR NOT NULL,
        date DATE NOT NULL,
        open DOUBLE,
        high DOUBLE,
        low DOUBLE,
        close DOUBLE,     -- always split/dividend-adjusted close
        volume BIGINT,
        PRIMARY KEY (symbol, date)
    );
    """)
    
    con.sql("""
    CREATE TABLE IF NOT EXISTS fundamentals_history (
        symbol VARCHAR NOT NULL,
        report_date DATE NOT NULL,      -- date the figures became public (point-in-time key)
        fiscal_period VARCHAR,          -- e.g. 'Q1 2025'
        revenue DOUBLE,
        revenue_yoy DOUBLE,
        eps DOUBLE,
        eps_yoy DOUBLE,
        eps_surprise_pct DOUBLE,
        gross_margin DOUBLE,
        operating_margin DOUBLE,
        PRIMARY KEY (symbol, report_date)
    );
    """)
    
    con.sql("""
    CREATE TABLE IF NOT EXISTS earnings_calendar (
        symbol VARCHAR NOT NULL,
        earnings_date DATE NOT NULL,
        timing VARCHAR,                 -- 'BMO' or 'AMC'
        PRIMARY KEY (symbol, earnings_date)
    );
    """)
    
    con.sql("""
    CREATE TABLE IF NOT EXISTS index_membership (
        symbol VARCHAR NOT NULL,
        index_name VARCHAR NOT NULL,    -- 'SP500', 'DOW', or 'NASDAQ100'
        start_date DATE NOT NULL,
        end_date DATE,                  -- NULL means still a current member
        PRIMARY KEY (symbol, index_name, start_date)
    );
    """)
    
    print("Schema created successfully. Tables now in trading.duckdb:")
    print(con.sql("SHOW TABLES"))
    
    con.close()


if __name__ == "__main__":
    main()
