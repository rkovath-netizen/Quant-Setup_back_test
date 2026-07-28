import os
import sys
import time
import json
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST
from data.instrument_master import get_all_expiries, resolve_exact_contract
from data.candle_fetcher import fetch_candle_chunk
from core.notifier import send_email_alert

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

    df['Signal'], df['Entry'], df['SL'], df['TP'] = 0, 0.0, 0.0, 0.0

    for i in range(1, len(df)):
        prev_k, prev_d = df['STOCH_K'].iloc[i-1], df['STOCH_D'].iloc[i-1]
        curr_k, curr_d = df['STOCH_K'].iloc[i], df['STOCH_D'].iloc[i]
        price, ema = df['close'].iloc[i], df['EMA_50'].iloc[i]
        atr = df['ATR'].iloc[i] if not pd.isna(df['ATR'].iloc[i]) else price * 0.005

        if price > ema and prev_k < prev_d and curr_k > curr_d and prev_k <= 30:
            sl_distance = max(atr * 1.2, price * 0.0025)
            df.iloc[i, df.columns.get_loc('Signal')] = 1
            df.iloc[i, df.columns.get_loc('Entry')] = round(price, 2)
            df.iloc[i, df.columns.get_loc('SL')] = round(price - sl_distance, 2)
            df.iloc[i, df.columns.get_loc('TP')] = round(price + (sl_distance * rr_ratio), 2)

        elif price < ema and prev_k > prev_d and curr_k < curr_d and prev_k >= 70:
            sl_distance = max(atr * 1.2, price * 0.0025)
            df.iloc[i, df.columns.get_loc('Signal')] = -1
            df.iloc[i, df.columns.get_loc('Entry')] = round(price, 2)
            df.iloc[i, df.columns.get_loc('SL')] = round(price + sl_distance, 2)
            df.iloc[i, df.columns.get_loc('TP')] = round(price - (sl_distance * rr_ratio), 2)

    return df

def scan_symbol(symbol, token, lookback_days=3):
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    start_str = (datetime.now(IST) - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
    
    all_expiries = get_all_expiries(symbol, token, logger=lambda x: None)
    if not all_expiries: return None
    near_expiry = all_expiries[0]
    future_key = resolve_exact_contract(symbol, near_expiry, token, inst_type="FUTIDX", logger=lambda x: None)
    if not future_key: return None

    df = fetch_candle_chunk(future_key, start_str, today_str, token, interval='5minute', logger=lambda x: None)
    if df.empty: return None

    scanned_df = calculate_indicators_and_rr(df, rr_ratio=2.0)
    latest_bar = scanned_df.iloc[-1]
    
    if latest_bar['Signal'] != 0:
        opt_type = "CE" if latest_bar['Signal'] == 1 else "PE"
        strike_step = 100 if symbol == "SENSEX" else 50
        atm_strike = int(round(latest_bar['Entry'] / strike_step) * strike_step)
        
        return {
            "timestamp": str(scanned_df.index[-1]),
            "symbol": symbol,
            "direction": "BUY CALL" if latest_bar['Signal'] == 1 else "BUY PUT",
            "underlying_entry": latest_bar['Entry'],
            "stop_loss": latest_bar['SL'],
            "target": latest_bar['TP'],
            "recommended_option": f"{symbol} {atm_strike} {opt_type} ({near_expiry})"
        }
    return {"status": "NO SETUP", "last_price": latest_bar['close']}

def run():
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    with open(config_file, "r") as f: config = json.load(f)
    token, symbols = config.get("upstox_token"), config.get("symbols", ["NIFTY", "SENSEX"])
    gmail_user, gmail_pass = config.get("gmail_user"), config.get("gmail_pass")
    
    last_alert = {sym: None for sym in symbols}
    print(f"🚀 [STOCHASTIC] SCANNER ACTIVE")

    while True:
        current_time = datetime.now(IST)
        is_weekday = current_time.weekday() <= 4 
        market_start = current_time.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if not is_weekday or current_time < market_start or current_time > market_end:
            print(f"😴 [STOCHASTIC] Market Closed.")
            time.sleep(300)
            continue

        print(f"⏰ [STOCHASTIC] Cycle: {current_time.strftime('%H:%M:%S')}")
        for symbol in symbols:
            res = scan_symbol(symbol, token)
            if res and "direction" in res and res["timestamp"] != last_alert[symbol]:
                last_alert[symbol] = res["timestamp"]
                subject = f"🚨 [STOCH] {symbol} ALERT: {res['direction']} @ {res['underlying_entry']}"
                body = f"Strategy: STOCHASTIC 1:2 RR\nEntry: {res['underlying_entry']}\nTarget: {res['target']}\nSL: {res['stop_loss']}\nOption: {res['recommended_option']}"
                if gmail_user and gmail_pass: send_email_alert(subject, body, gmail_user, gmail_pass, gmail_user)
                print(f"🔥 [STOCHASTIC] SIGNAL SENT FOR {symbol}")
            elif res:
                print(f"  🟢 [STOCH] {symbol} CMP: {res.get('last_price', 'N/A')}")
        time.sleep(300)

if __name__ == "__main__": run()

