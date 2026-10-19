"""Legacy research command. Explicit execution may rebuild database tables."""

def main():
    import duckdb
    
    con = duckdb.connect('trading.duckdb')
    
    # Identify contiguous runs of the same regime by comparing each day's regime to the previous
    # trading day's regime -- a new "episode" starts wherever the regime changes.
    episodes = con.sql("""
        WITH ordered AS (
            SELECT date, regime,
                   LAG(regime) OVER (ORDER BY date) AS prev_regime
            FROM market_regime_daily
            WHERE regime IS NOT NULL
        ),
        flagged AS (
            SELECT date, regime,
                   CASE WHEN regime != prev_regime OR prev_regime IS NULL THEN 1 ELSE 0 END AS is_new_episode
            FROM ordered
        ),
        episode_ids AS (
            SELECT date, regime,
                   SUM(is_new_episode) OVER (ORDER BY date) AS episode_id
            FROM flagged
        )
        SELECT episode_id, regime, MIN(date) AS start_date, MAX(date) AS end_date, COUNT(*) AS trading_days
        FROM episode_ids
        GROUP BY episode_id, regime
        ORDER BY start_date
    """).df()
    
    print("All Defensive-regime episodes (contiguous stretches):")
    defensive_episodes = episodes[episodes['regime'] == 'Defensive']
    print(defensive_episodes.to_string(index=False))
    print(f"\n{len(defensive_episodes)} distinct Defensive episodes, "
          f"totaling {defensive_episodes['trading_days'].sum()} trading days.")
    
    print("\nAll Neutral-regime episodes (contiguous stretches):")
    neutral_episodes = episodes[episodes['regime'] == 'Neutral']
    print(neutral_episodes.to_string(index=False))
    print(f"\n{len(neutral_episodes)} distinct Neutral episodes, "
          f"totaling {neutral_episodes['trading_days'].sum()} trading days.")
    
    con.close()


if __name__ == "__main__":
    main()
