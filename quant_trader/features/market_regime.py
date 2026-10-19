"""Versioned trailing regime calculation, independent of storage and brokers."""
import numpy as np
import pandas as pd

REGIME_VERSION = "strict-breadth-v1"

def compute_market_regime(spy, qqq, vix, breadth, *, require_breadth=True,
                          bullish_exposure=0.9, neutral_exposure=0.6,
                          defensive_exposure=0.3):
    """End-of-session features; earliest execution is a later eligible session.

    require_breadth=False preserves the legacy readiness mask for comparisons.
    Monthly membership provenance remains a limitation of supplied breadth.
    """
    spy = spy.sort_index()
    qqq = qqq.sort_index()
    spy_ma20 = spy.rolling(20).mean()
    spy_ma50 = spy.rolling(50).mean()
    spy_ma200 = spy.rolling(200).mean()
    qqq_ma50 = qqq.rolling(50).mean()
    all_dates = spy.index
    df = pd.DataFrame(index=all_dates)
    df['spy_close'] = spy
    df['spy_ma20'] = spy_ma20
    df['spy_ma50'] = spy_ma50
    df['spy_ma200'] = spy_ma200
    df['qqq_close'] = qqq.reindex(all_dates)
    df['qqq_ma50'] = qqq_ma50.reindex(all_dates)
    df['vix_close'] = vix.reindex(all_dates)
    df['breadth_pct'] = breadth.reindex(all_dates)
    
    df['breadth_positive'] = np.where(df['breadth_pct'] > 0.5, 'Yes', 'No')
    df['volatility_favorable'] = np.where(df['vix_close'] < 20, 'Yes', 'No')
    
    market_score = (
        np.where(df['spy_close'] > df['spy_ma20'], 2, 0)
        + np.where(df['spy_close'] > df['spy_ma50'], 3, 0)
        + np.where(df['spy_close'] > df['spy_ma200'], 2, 0)
        + np.where(df['spy_ma20'] > df['spy_ma50'], 2, 0)
        + np.where(df['qqq_close'] > df['qqq_ma50'], 2, 0)
        + np.where(df['breadth_positive'] == 'Yes', 2, 0)
        + np.where(df['volatility_favorable'] == 'Yes', 2, 0)
    )
    # NaN-out days where inputs weren't ready yet (e.g. before 200-day MA has enough history)
    missing = df[['spy_ma20', 'spy_ma50', 'spy_ma200', 'qqq_ma50', 'vix_close']].isna().any(axis=1)
    if require_breadth:
        missing |= df[['spy_close', 'qqq_close', 'breadth_pct']].isna().any(axis=1)
    market_score = np.where(missing, np.nan, market_score)
    df['market_score'] = market_score
    
    df['regime'] = np.select(
        [df['market_score'] >= 11, df['market_score'] >= 6],
        ['Bullish', 'Neutral'],
        default='Defensive'
    )
    df.loc[df['market_score'].isna(), 'regime'] = None
    
    df['max_exposure'] = np.select(
        [df['regime'] == 'Bullish', df['regime'] == 'Neutral', df['regime'] == 'Defensive'],
        [bullish_exposure, neutral_exposure, defensive_exposure],
        default=np.nan
    )
    
    return df
