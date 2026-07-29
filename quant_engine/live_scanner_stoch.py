import os
import sys
import time
import json
import base64
import requests
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST
from data.candle_fetcher import fetch_candle_chunk
from core.notifier import send_email_alert

def get_front_month_future(symbol_prefix):
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    try:
        df = pd.read_csv(url)
        df.columns = df.columns.str.strip().str.lower()
        df_f = df[(df['instrument_type'] == 'FUTIDX') & (df['name'] == symbol_prefix)]
        if df_f.empty: return None
        df_f['expiry'] = pd.to_datetime(df_f['expiry']).dt.date
        today = datetime.now(IST).date()
        active = df_f[df_f['expiry'] >= today].sort_values('expiry')
        if not active.empty: return active.iloc[0]['instrument_key'], active.iloc[0]['expiry']
    except Exception: pass
    return None, None

def push_to_github(data_dict, strategy_name, gh_token, gh_repo):
    """Pushes a new row to a CSV file directly on GitHub."""
    if not gh_token or not gh_repo: return
    try:
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        filename = f"Live_Signals_{strategy_name}_{date_str}.csv"
        api_url = f"https://api.github.com/repos/{gh_repo}/contents/logs/{filename}"
        headers = {"Authorization": f"token {gh_token}", "Accept": "application/vnd.github.v3+json"}
        
        res = requests.get(api_url, headers=headers)
        new_row = ",".join([str(v) for v in data_dict.values()]) + "\n"
        
        if res.status_code == 200:
            file_data = res.json()
            sha = file_data['sha']
            content = base64.b64decode(file_data['content']).decode('utf-8')
            updated_content = content + new_row
        else:
            sha = None
            headers_str = ",".join(data_dict.keys()) + "\n"
            updated_content = headers_str + new_row
            
        payload = {
            "message": f"Auto-log {strategy_name} signal for {data_dict.get('Symbol', 'Unknown')}",
            "content": base64.b64encode(updated_content.encode('utf-8')).decode('utf-8')
        }
        if sha: payload["sha"] = sha
        requests.put(api_url, headers=headers, json=payload)
    except Exception as e:
        print(f"⚠️ GitHub Push Failed: {e}")

def resample_candles(df, timeframe):
    if df.empty: return df
    df.columns = df.columns.str.lower()
    if 'volume' not in df.columns: df['volume'] = 1
    if not isinstance(df.index, pd.DatetimeIndex):
        time_cols = [c for c in df.columns if c in ['timestamp', 'date', 'datetime']]
        if time_cols: df.set_index(time_cols[0], inplace=True)
        df.index = pd.to_datetime(df.index)
    agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    return df.resample(timeframe).agg(agg_dict).dropna(subset=['close'])

def calculate_indicators_and_rr(df, ltf_k=14, ltf_d=3, htf_ema=50, atr_period=14, rr_ratio=2.0):
    df = df.copy()
    df['EMA_50'] = ta.ema(df['close'], length=htf_ema)
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=ltf_k, d=ltf_d)
    
    if stoch is not None and not stoch.empty:
        df['STOCH_K'], df['STOCH_D'] = stoch[f'STOCHk_{ltf_k}_{ltf_d}_3'], stoch[f'STOCHd_{ltf_k}_{ltf_d}_3']
    else:
        df['STOCH_K'], df['STOCH_D'] = 50.0, 50.0

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

    return df.dropna()

def scan_symbol(symbol, token, config):
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    start_str = (datetime.now(IST) - timedelta(days=5)).strftime('%Y-%m-%d')
    
    future_key, expiry_date = get_front_month_future(symbol)
    if not future_key: return None

    # Fetch 1m and resample to guarantee alignment with debugger
    df_1m = fetch_candle_chunk(future_key, start_str, today_str, token, interval='1minute', logger=lambda x: None)
    if df_1m.empty: return None

    df_5m = resample_candles(df_1m, '5min')
    scanned_df = calculate_indicators_and_rr(df_5m, rr_ratio=2.0)
    
    if scanned_df.empty: return None
    latest_bar = scanned_df.iloc[-1]
    
    if latest_bar['Signal'] != 0:
        opt_type = "CE" if latest_bar['Signal'] == 1 else "PE"
        strike_step = 100 if symbol == "SENSEX" else 50
        atm_strike = int(round(latest_bar['Entry'] / strike_step) * strike_step)
        
        signal_payload = {
            "Timestamp": str(scanned_df.index[-1]),
            "Symbol": symbol,
            "Strategy": "STOCHASTIC",
            "Action": "BUY CALL" if latest_bar['Signal'] == 1 else "BUY PUT",
            "Entry": latest_bar['Entry'],
            "SL": latest_bar['SL'],
            "Target": latest_bar['TP'],
            "Option": f"{symbol} {atm_strike} {opt_type} ({expiry_date})"
        }
        
        # PUSH TO GITHUB LOGS
        push_to_github(signal_payload, "STOCH", config.get("github_token"), config.get("github_repo"))
        
        return signal_payload
        
    return {"status": "NO SETUP", "last_price": latest_bar['close']}

def run():
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    with open(config_file, "r") as f: config = json.load(f)
    token, symbols = config.get("upstox_token"), config.get("symbols", ["NIFTY", "SENSEX"])
    gmail_user, gmail_pass = config.get("gmail_user"), config.get("gmail_pass")
    
    last_alert = {sym: None for sym in symbols}
    print(f"🚀 [STOCHASTIC] SCANNER ACTIVE (GITHUB LOGGING ENABLED)")

    while True:
        current_time = datetime.now(IST)
        is_weekday = current_time.weekday() <= 4 
        market_start = current_time.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
        
        if not is_weekday or current_time < market_start or current_time > market_end:
            print(f"😴 [STOCHASTIC] Market Closed.")
            time.sleep(300)
            continue

        # WAKE UP EXACTLY ON THE 5-MINUTE BOUNDARY
        if current_time.minute % 5 == 0:
            print(f"⏰ [STOCHASTIC] Boundary Reached: {current_time.strftime('%H:%M:%S')}")
            for symbol in symbols:
                res = scan_symbol(symbol, token, config)
                
                if res and "Action" in res and res["Timestamp"] != last_alert[symbol]:
                    last_alert[symbol] = res["Timestamp"]
                    subject = f"🚨 [STOCH] {symbol} ALERT: {res['Action']} @ {res['Entry']}"
                    body = f"Strategy: STOCHASTIC 1:2 RR\nEntry: {res['Entry']}\nTarget: {res['Target']}\nSL: {res['SL']}\nOption: {res['Option']}"
                    
                    if gmail_user and gmail_pass: 
                        send_email_alert(subject, body, gmail_user, gmail_pass, gmail_user)
                        
                    print(f"🔥 [STOCHASTIC] SIGNAL LOGGED & SENT FOR {symbol}")
                elif res:
                    print(f"  🟢 [STOCH] {symbol} CMP: {res.get('last_price', 'N/A')}")
        else:
            print(f"  ⏳ Waiting for next 5-minute close... ({current_time.strftime('%H:%M:%S')})")
            
        time.sleep(60)

if __name__ == "__main__": run()
