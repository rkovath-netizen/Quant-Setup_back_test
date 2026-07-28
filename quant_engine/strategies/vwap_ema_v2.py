import pandas as pd
import pandas_ta as ta

def resample_candles(df, timeframe):
    if df.empty: return df
    agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    df_resampled = df.resample(timeframe).agg(agg_dict)
    return df_resampled.dropna(subset=['close'])

def calculate_vwap_ema_indicators(df):
    if df.empty: return df
    df['EMA_9'] = ta.ema(df['close'], length=9)
    df['EMA_21'] = ta.ema(df['close'], length=21)
    df['VWAP'] = ta.vwap(df['high'], df['low'], df['close'], df['volume'], anchor='D')
    df['volume_prev'] = df['volume'].shift(1)
    df.dropna(inplace=True)
    return df

def generate_v2_signals(df_1m, target_pts=25, sl_pts=15):
    """
    Takes 1-minute OHLCV data, resamples to 3m and 15m, 
    and checks for the V2 VWAP + EMA entry conditions.
    """
    df_3m = resample_candles(df_1m, '3min')
    df_15m = resample_candles(df_1m, '15min')
    
    df_3m = calculate_vwap_ema_indicators(df_3m)
    df_15m = calculate_vwap_ema_indicators(df_15m)
    
    if len(df_3m) < 3 or len(df_15m) < 2: 
        return None
        
    df_15m = df_15m.add_suffix('_15m')
    # Merge 15m HTF bias down to the 3m LTF trigger timeframe
    df = pd.merge_asof(df_3m.reset_index(), df_15m.reset_index(), on='timestamp', direction='backward')
    df.set_index('timestamp', inplace=True)
    
    # Evaluate the most recently completed 3-minute candle
    row = df.iloc[-2] 
    
    # 15m BIAS
    bias_ce = (row['close_15m'] > row['VWAP_15m']) and (row['EMA_9_15m'] > row['EMA_21_15m'])
    bias_pe = (row['close_15m'] < row['VWAP_15m']) and (row['EMA_9_15m'] < row['EMA_21_15m'])
    
    # 3m PULLBACK & TRIGGER
    ce_pullback_support = (row['low'] <= row['EMA_9']) or (row['low'] <= row['VWAP'])
    increasing_vol = row['volume'] > row['volume_prev']
    bullish_rejection = row['close'] > row['open']
    
    pe_pullback_resist = row['high'] >= row['EMA_9']
    bearish_rejection = (row['close'] < row['open']) and (row['close'] < row['EMA_9'])
    
    signal = 0
    if bias_ce and ce_pullback_support and increasing_vol and bullish_rejection:
        signal = 1
    elif bias_pe and pe_pullback_resist and bearish_rejection:
        signal = -1

    if signal != 0:
        entry_price = row['close']
        return {
            "timestamp": row.name,
            "signal": signal,
            "direction": "BUY CE" if signal == 1 else "BUY PE",
            "entry_price": round(entry_price, 2),
            "sl_price": round(entry_price - sl_pts, 2) if signal == 1 else round(entry_price + sl_pts, 2),
            "target_price": round(entry_price + target_pts, 2) if signal == 1 else round(entry_price - target_pts, 2)
        }
    return None
