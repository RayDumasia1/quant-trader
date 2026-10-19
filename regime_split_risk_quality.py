"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    
    con = duckdb.connect('trading.duckdb')
    
    print("Risk Quality decile vs 10D excess return (vs equal-weighted universe), SPLIT BY REGIME:")
    for regime in ['Bullish', 'Neutral', 'Defensive']:
        print(f"\n  ===== {regime} =====")
        print(con.sql(f"""
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
            WHERE forward_10d_return IS NOT NULL AND regime = '{regime}'
            GROUP BY decile
            ORDER BY decile DESC
        """))
    
    print("\n\nFor reference -- how many observations and days fall in each regime:")
    print(con.sql("""
        SELECT regime, COUNT(*) AS observations, COUNT(DISTINCT signal_date) AS trading_days
        FROM signal_outcomes
        WHERE forward_10d_return IS NOT NULL
        GROUP BY regime
        ORDER BY observations DESC
    """))
    
    con.close()


if __name__ == "__main__":
    main()
