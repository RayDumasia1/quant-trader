"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    
    con = duckdb.connect('trading.duckdb')
    
    print("10D excess return by score-percentile decile (top decile = highest relative score that day):")
    print(con.sql("""
        SELECT
            CASE
                WHEN score_percentile >= 0.9 THEN '90-100 (top decile)'
                WHEN score_percentile >= 0.8 THEN '80-90'
                WHEN score_percentile >= 0.7 THEN '70-80'
                WHEN score_percentile >= 0.6 THEN '60-70'
                WHEN score_percentile >= 0.5 THEN '50-60'
                WHEN score_percentile >= 0.4 THEN '40-50'
                WHEN score_percentile >= 0.3 THEN '30-40'
                WHEN score_percentile >= 0.2 THEN '20-30'
                WHEN score_percentile >= 0.1 THEN '10-20'
                ELSE '0-10 (bottom decile)'
            END AS decile,
            COUNT(*) AS n,
            ROUND(AVG(forward_10d_return), 4) AS avg_raw_10d,
            ROUND(AVG(excess_10d_return), 4) AS avg_excess_10d,
            ROUND(AVG(CASE WHEN excess_10d_return > 0 THEN 1.0 ELSE 0.0 END), 3) AS beat_spy_rate_10d
        FROM signal_outcomes
        WHERE forward_10d_return IS NOT NULL
        GROUP BY decile
        ORDER BY decile DESC
    """))
    
    print("\nSame breakdown for 5D excess return, for comparison:")
    print(con.sql("""
        SELECT
            CASE
                WHEN score_percentile >= 0.9 THEN '90-100 (top decile)'
                WHEN score_percentile >= 0.8 THEN '80-90'
                WHEN score_percentile >= 0.7 THEN '70-80'
                WHEN score_percentile >= 0.6 THEN '60-70'
                WHEN score_percentile >= 0.5 THEN '50-60'
                WHEN score_percentile >= 0.4 THEN '40-50'
                WHEN score_percentile >= 0.3 THEN '30-40'
                WHEN score_percentile >= 0.2 THEN '20-30'
                WHEN score_percentile >= 0.1 THEN '10-20'
                ELSE '0-10 (bottom decile)'
            END AS decile,
            COUNT(*) AS n,
            ROUND(AVG(excess_5d_return), 4) AS avg_excess_5d,
            ROUND(AVG(CASE WHEN excess_5d_return > 0 THEN 1.0 ELSE 0.0 END), 3) AS beat_spy_rate_5d
        FROM signal_outcomes
        WHERE forward_5d_return IS NOT NULL
        GROUP BY decile
        ORDER BY decile DESC
    """))
    
    con.close()


if __name__ == "__main__":
    main()
