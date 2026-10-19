"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    
    con = duckdb.connect('trading.duckdb')
    
    print("Defensive regime, EXCLUDING the two dominant episodes (2025-03-26/2025-04-30, 2026-03-02/2026-04-07):")
    print(con.sql("""
        SELECT
            CASE
                WHEN risk_quality_percentile >= 0.9 THEN '90-100 (top, "safest")'
                WHEN risk_quality_percentile >= 0.7 THEN '70-90'
                WHEN risk_quality_percentile >= 0.5 THEN '50-70'
                WHEN risk_quality_percentile >= 0.3 THEN '30-50'
                WHEN risk_quality_percentile >= 0.1 THEN '10-30'
                ELSE '0-10 (bottom, "riskiest")'
            END AS decile,
            COUNT(*) AS n,
            ROUND(AVG(excess_10d_return_ew), 4) AS avg_excess_vs_ew,
            ROUND(AVG(CASE WHEN excess_10d_return_ew > 0 THEN 1.0 ELSE 0.0 END), 3) AS beat_ew_rate
        FROM signal_outcomes
        WHERE forward_10d_return IS NOT NULL
          AND regime = 'Defensive'
          AND NOT (signal_date BETWEEN '2025-03-26' AND '2025-04-30')
          AND NOT (signal_date BETWEEN '2026-03-02' AND '2026-04-07')
        GROUP BY decile
        ORDER BY decile DESC
    """))
    
    print("\nFor reference -- remaining sample size and which episodes are included:")
    print(con.sql("""
        SELECT COUNT(*) AS remaining_observations, COUNT(DISTINCT signal_date) AS remaining_trading_days
        FROM signal_outcomes
        WHERE forward_10d_return IS NOT NULL
          AND regime = 'Defensive'
          AND NOT (signal_date BETWEEN '2025-03-26' AND '2025-04-30')
          AND NOT (signal_date BETWEEN '2026-03-02' AND '2026-04-07')
    """))
    
    print("\nFor comparison -- the two excluded episodes ONLY:")
    print(con.sql("""
        SELECT
            CASE
                WHEN risk_quality_percentile >= 0.9 THEN '90-100 (top, "safest")'
                WHEN risk_quality_percentile >= 0.7 THEN '70-90'
                WHEN risk_quality_percentile >= 0.5 THEN '50-70'
                WHEN risk_quality_percentile >= 0.3 THEN '30-50'
                WHEN risk_quality_percentile >= 0.1 THEN '10-30'
                ELSE '0-10 (bottom, "riskiest")'
            END AS decile,
            COUNT(*) AS n,
            ROUND(AVG(excess_10d_return_ew), 4) AS avg_excess_vs_ew
        FROM signal_outcomes
        WHERE forward_10d_return IS NOT NULL
          AND regime = 'Defensive'
          AND (
                (signal_date BETWEEN '2025-03-26' AND '2025-04-30')
             OR (signal_date BETWEEN '2026-03-02' AND '2026-04-07')
          )
        GROUP BY decile
        ORDER BY decile DESC
    """))
    
    con.close()


if __name__ == "__main__":
    main()
