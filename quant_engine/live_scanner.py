import os
import sys
import time
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST
from data.instrument_master import get_all_expiries, resolve_exact_contract
from data.candle_fetcher import fetch_candle_chunk

def calculate_indicators_and_rr(df, ltf_k=14, ltf_d=3, htf_ema=50, atr_period=14, rr_ratio=2.0):
    df = df.copy()
    df['EMA_50'] = ta.ema(df['close'], length=htf_ema)
    
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=ltf_k, d=ltf_d)
    if stoch is not None and not stoch.empty:
        df['STOCH_K'] = stoch[f'STOCHk_{ltf_k}_{ltf_d}_3']
        df['STOCH_D'] = stoch[f'STOCHd_{ltf_k}_{ltf_d}_3']
    else:
        df['STOCH_K'] = 50.0
        df['STOCH_D'] = 50.0

    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=atr_period)

    df['Signal'] = 0
    df['Entry'] = 0.0
    df['SL'] = 0.0
    df['TP'] = 0.0

    for i in range(1, len(df)):
        prev_k, prev_d = df['STOCH_K'].iloc[i-1], df['STOCH_D'].iloc[i-1]
        curr_k, curr_d = df['STOCH_K'].iloc[i], df['STOCH_D'].iloc[i]
        price = df['close'].iloc[i]
        ema = df['EMA_50'].iloc[i]
        atr = df['ATR'].iloc[i] if not pd.isna(df['ATR'].iloc[i]) else price * 0.005

        if price > ema and prev_k < prev_d and curr_k > curr_d and prev_k <= 30:
            sl_distance = max(atr * 1.2, price * 0.0025)
            tp_distance = sl_distance * rr_ratio
            df.iloc[i, df.columns.get_loc('Signal')] = 1
            df.iloc[i, df.columns.get_loc('Entry')] = round(price, 2)
            df.iloc[i, df.columns.get_loc('SL')] = round(price - sl_distance, 2)
            df.iloc[i, df.columns.get_loc('TP')] = round(price + tp_distance, 2)

        elif price < ema and prev_k > prev_d and curr_k < curr_d and prev_k >= 70:
            sl_distance = max(atr * 1.2, price * 0.0025)
            tp_distance = sl_distance * rr_ratio
            df.iloc[i, df.columns.get_loc('Signal')] = -1
            df.iloc[i, df.columns.get_loc('Entry')] = round(price, 2)
            df.iloc[i, df.columns.get_loc('SL')] = round(price + sl_distance, 2)
            df.iloc[i, df.columns.get_loc('TP')] = round(price - tp_distance, 2)

    return df

def scan_symbol(symbol, token, lookback_days=3):
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    start_str = (datetime.now(IST) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    all_expiries = get_all_expiries(symbol, token, logger=print)
    if not all_expiries: return None

    near_expiry = all_expiries[0]
    future_key = resolve_exact_contract(symbol, near_expiry, token, inst_type="FUTIDX", logger=print)
    if not future_key: return None

    df = fetch_candle_chunk(future_key, start_str, today_str, token, interval='5minute', logger=print)
    if df.empty: return None

    scanned_df = calculate_indicators_and_rr(df, rr_ratio=2.0)
    latest_bar = scanned_df.iloc[-1]
    latest_time = scanned_df.index[-1]
    signal = latest_bar['Signal']
    
    if signal != 0:
        opt_type = "CE" if signal == 1 else "PE"
        strike_step = 100 if symbol == "SENSEX" else 50
        atm_strike = int(round(latest_bar['Entry'] / strike_step) * strike_step)
        
        return {
            "timestamp": str(latest_time),
            "symbol": symbol,
            "direction": "BUY CALL (BULLISH)" if signal == 1 else "BUY PUT (BEARISH)",
            "underlying_entry": latest_bar['Entry'],
            "stop_loss": latest_bar['SL'],
            "target": latest_bar['TP'],
            "risk_pts": round(abs(latest_bar['Entry'] - latest_bar['SL']), 2),
            "reward_pts": round(abs(latest_bar['TP'] - latest_bar['Entry']), 2),
            "rr_ratio": "1:2.0+",
            "recommended_option": f"{symbol} {atm_strike} {opt_type} ({near_expiry})"
        }
    
    return {
        "timestamp": str(latest_time),
        "symbol": symbol,
        "status": "NO MATCHING SETUP",
        "last_price": latest_bar['close']
    }
