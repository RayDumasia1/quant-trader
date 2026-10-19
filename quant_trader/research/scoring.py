"""Pure extraction of legacy stock scoring, preserving its formulas."""
import pandas as pd
import numpy as np
from quant_trader.features.indicators import compute_atr, compute_rsi

def score_5d(r):
    if pd.isna(r): return np.nan
    if r < 0: return 0
    if r < 0.01: return 1
    if r < 0.03: return 2
    if r < 0.06: return 4
    if r <= 0.10: return 3
    return 1

def score_20d(r):
    if pd.isna(r): return np.nan
    if r < 0: return 0
    if r < 0.03: return 1
    if r < 0.06: return 2
    if r < 0.12: return 5
    if r <= 0.20: return 4
    return 2

def score_60d(r):
    if pd.isna(r): return np.nan
    if r < 0: return 0
    if r < 0.05: return 1
    if r < 0.12: return 2
    if r < 0.25: return 5
    if r < 0.40: return 4
    return 2

def score_rs(rel):
    if pd.isna(rel): return np.nan
    if rel < 0: return 0
    if rel < 0.02: return 2
    if rel < 0.05: return 4
    if rel < 0.10: return 6
    if rel < 0.20: return 5
    return 3

def score_rsi(rsi, max_rsi=78):
    if pd.isna(rsi): return np.nan
    if rsi < 40: return 0
    if rsi < 50: return 1
    if rsi < 65: return 3
    if rsi <= 72: return 2
    if rsi <= max_rsi: return 1
    return 0

def score_macd(macd, signal):
    if pd.isna(macd) or pd.isna(signal): return np.nan
    return (1 if macd > signal else 0) + (1 if macd > 0 else 0)

def score_setup(setup):
    if setup == 'Breakout' or setup == 'Pullback':
        return 3
    if setup == 'Trend Continuation':
        return 2
    return 0

def score_structure(structure):
    if structure == 'Strong':
        return 2
    if structure == 'Good':
        return 1
    return 0

def score_risk_quality(atr, price):   # Scanner column BF, earnings-blackout portion omitted for now
    if pd.isna(atr) or pd.isna(price) or price == 0:
        return np.nan
    ratio = atr / price
    if ratio < 0.02: return 5
    if ratio < 0.03: return 4
    if ratio < 0.04: return 3
    if ratio < 0.05: return 2
    return 1

def compute_daily_scores(prices):
    """Calculate scores without database access, network calls or input mutation."""
    prices = prices.copy()
    prices['date'] = pd.to_datetime(prices['date'])
    
    spy_close = prices[prices['symbol'] == 'SPY'].set_index('date')['close']
    spy_20d_return = spy_close / spy_close.shift(20) - 1
    
    all_scores = []
    
    for symbol, g in prices.groupby('symbol'):
        g = g.sort_values('date').set_index('date')
        high = g['high']
        low = g['low']
        close = g['close']
        volume = g['volume']
    
        # --- Momentum (unchanged, complete 20-point port) ---
        r5 = close / close.shift(5) - 1
        r20 = close / close.shift(20) - 1
        r60 = close / close.shift(60) - 1
        rel_strength = r20 - spy_20d_return.reindex(close.index)
        j = r5.apply(score_5d)
        k = r20.apply(score_20d)
        l = r60.apply(score_60d)
        m = rel_strength.apply(score_rs)
        momentum = j + k + l + m
    
        # --- Technical base ---
        ma20 = close.rolling(20).mean()
        ma50 = close.rolling(50).mean()
        ma200 = close.rolling(200).mean()
        rsi14 = compute_rsi(close, 14)
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema12 - ema26
        macd_sig = macd_line.ewm(span=9, adjust=False).mean()
    
        aa = rsi14.apply(score_rsi)
        ab = pd.Series([score_macd(mc, sg) for mc, sg in zip(macd_line, macd_sig)], index=close.index)
        w = np.where(close > ma20, 3, 0)
        x = np.where(close > ma50, 3, 0)
        y = np.where(ma20 > ma50, 2, 0)
        z = np.where(close > ma200, 2, 0)
    
        # --- Setup classification (High-based breakout, per standard convention) ---
        high_20d_max = high.rolling(20).max()
        is_breakout = high >= high_20d_max
    
        pct_above_ma20 = close / ma20 - 1
        was_extended_10d = pct_above_ma20.rolling(10).max() > 0.05
        ma20_rising = ma20 > ma20.shift(5)
        is_pullback = (
            was_extended_10d
            & (pct_above_ma20 >= 0) & (pct_above_ma20 <= 0.03)
            & ma20_rising & (close > ma50)
            & (~is_breakout)
        )
    
        is_trend_continuation = (close > ma20) & (close > ma50) & (~is_breakout) & (~is_pullback)
    
        setup = np.select(
            [is_breakout.values, is_pullback.values, is_trend_continuation.values],
            ['Breakout', 'Pullback', 'Trend Continuation'],
            default=None
        )
    
        # --- Structure classification ---
        strong = (close > ma20) & (close > ma50) & (close > ma200) & (ma20 > ma50) & (ma50 > ma200)
        good = (close > ma20) & (close > ma50) & (~strong)
        structure = np.select([strong.values, good.values], ['Strong', 'Good'], default=None)
    
        setup_score = np.array([score_setup(s) for s in setup], dtype=float)
        structure_score = np.array([score_structure(s) for s in structure], dtype=float)
    
        technical_score = w + x + y + z + aa.values + ab.values + setup_score + structure_score
    
        # --- Volume, now complete ---
        avg_vol20 = volume.rolling(20).mean()
        rel_vol = volume / avg_vol20
        prev_close = close.shift(1)
        price_volume_confirm = np.where((close > prev_close) & (volume > avg_vol20), 'Yes', 'No')
    
        is_up_day = close > prev_close
        up_volume = volume.where(is_up_day, 0)
        down_volume = volume.where(~is_up_day, 0)
        up_vol_5d = up_volume.rolling(5).sum()
        down_vol_5d = down_volume.rolling(5).sum()
        accumulation = np.where(up_vol_5d > down_vol_5d, 'Yes', 'No')
    
        volume_score = np.where(
            avg_vol20.isna().values | volume.isna().values, 0,
            np.where(volume.values > avg_vol20.values, 2, 0)
            + np.where(rel_vol.values >= 1.5, 4, np.where(rel_vol.values >= 1.25, 2, 0))
            + np.where(price_volume_confirm == 'Yes', 2, 0)
            + np.where(accumulation == 'Yes', 2, 0)
        )
    
        # --- Risk Quality (ATR/Price tiers; earnings-blackout override pending earnings_calendar data) ---
        atr14 = compute_atr(high, low, close, 14)
        risk_quality = np.array([score_risk_quality(a, c) for a, c in zip(atr14.values, close.values)])
    
        out = pd.DataFrame({
            'symbol': symbol,
            'date': close.index.date,
            'return_5d': r5.values, 'return_20d': r20.values, 'return_60d': r60.values,
            'rel_strength_20d': rel_strength.values, 'momentum_score': momentum.values,
            'ma_20': ma20.values, 'ma_50': ma50.values, 'ma_200': ma200.values,
            'rsi_14': rsi14.values, 'macd': macd_line.values, 'macd_signal': macd_sig.values,
            'setup': setup, 'structure': structure,
            'setup_score': setup_score, 'structure_score': structure_score,
            'technical_score': technical_score,
            'avg_volume_20d': avg_vol20.values, 'relative_volume': rel_vol.values,
            'price_volume_confirm': price_volume_confirm, 'accumulation': accumulation,
            'volume_score': volume_score,
            'atr_14': atr14.values, 'risk_quality_score': risk_quality,
        })
        all_scores.append(out)
    
    scores_df = pd.concat(all_scores, ignore_index=True)
    return scores_df
