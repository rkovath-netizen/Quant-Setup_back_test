import os
import sys
import time
import json
import base64
import requests
import pandas as pd
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST
from data.candle_fetcher import fetch_candle_chunk
from core.notifier import send_email_alert
from strategies.vwap_ema_v2 import generate_v2_signals

OPEN_TRADES = {"NIFTY": None, "SENSEX": None}
INSTRUMENT_CONFIG = {
    "NIFTY": {"default_lot": 25, "target_pts": 25, "sl_pts": 15},
    "SENSEX": {"default_lot": 10, "target_pts": 75, "sl_pts": 45} 
}

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
        if not active.empty: return active.iloc[0]['instrument_key']
    except Exception: pass
    return None

def push_to_github(data_dict, strategy_name, gh_token, gh_repo):
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
            "message": f"Auto-log {strategy_name} signal",
            "content": base64.b64encode(updated_content.encode('utf-8')).decode('utf-8')
        }
        if sha: payload["sha"] = sha
        requests.put(api_url, headers=headers, json=payload)
    except Exception as e:
        print(f"⚠️ GitHub Push Failed: {e}")

def process_symbol(symbol, token, config, email_creds, global_config):
    now = datetime.now(IST)
    current_time = now.time()
    active_trade = OPEN_TRADES[symbol]
    
    fut_key = get_front_month_future(symbol)
    if not fut_key: return

    # INCREASED TO 10 DAYS FOR EMA 21 WARMUP
    start_str = (now - timedelta(days=10)).strftime('%Y-%m-%d')
    today_str = now.strftime('%Y-%m-%d')
    df_1m = fetch_candle_chunk(fut_key, start_str, today_str, token, interval='1minute', logger=lambda x: None)
    
    if df_1m.empty: return
    current_close = df_1m.iloc[-1]['close']

    # --- TRADE EXITS ---
    if active_trade is not None:
        exit_price, exit_reason = None, None
        
        if current_time >= datetime.time(15, 15):
            exit_price, exit_reason = current_close, '15:15 Auto Square Off'
        elif active_trade['type'] == 'BUY CE':
            if current_close <= active_trade['sl_price']: exit_price, exit_reason = active_trade['sl_price'], 'SL Hit'
            elif current_close >= active_trade['target_price']: exit_price, exit_reason = active_trade['target_price'], 'Target Achieved'
        elif active_trade['type'] == 'BUY PE':
            if current_close >= active_trade['sl_price']: exit_price, exit_reason = active_trade['sl_price'], 'SL Hit'
            elif current_close <= active_trade['target_price']: exit_price, exit_reason = active_trade['target_price'], 'Target Achieved'

        if exit_price is not None:
            pnl = (exit_price - active_trade['entry_price']) * active_trade['qty'] if active_trade['type'] == 'BUY CE' else (active_trade['entry_price'] - exit_price) * active_trade['qty']
            
            # PUSH EXIT TO GITHUB
            exit_payload = {
                "Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "Symbol": symbol,
                "Strategy": "VWAP V2",
                "Action": f"EXIT ({exit_reason})",
                "Entry": active_trade['entry_price'],
                "SL": exit_price, # Actual exit price recorded here
                "Target": 0,
                "Option": f"PnL: Rs {round(pnl, 2)}"
            }
            push_to_github(exit_payload, "VWAP", global_config.get("github_token"), global_config.get("github_repo"))

            print(f"💰 TRADE CLOSED | {symbol} {exit_reason} | PnL: Rs {round(pnl, 2)}")
            if email_creds['user'] and email_creds['pass']:
                body = f"Trade Closed: {symbol} {active_trade['type']}\nReason: {exit_reason}\nEntry: {active_trade['entry_price']}\nExit: {exit_price}\nPnL: Rs {round(pnl, 2)}"
                send_email_alert(f"[VWAP V2] TRADE EXIT: {symbol} ({exit_reason})", body, email_creds['user'], email_creds['pass'], email_creds['user'])
            
            OPEN_TRADES[symbol] = None
        else:
            mtm = (current_close - active_trade['entry_price']) * active_trade['qty'] if active_trade['type'] == 'BUY CE' else (active_trade['entry_price'] - current_close) * active_trade['qty']
            print(f"⚡ ACTIVE TRADE | {symbol} {active_trade['type']} | CMP: {current_close} | MTM: Rs {round(mtm, 2)}")
        return

    # --- TRADE ENTRIES ---
    if current_time >= datetime.time(14, 0):
        print(f"🛑 [{symbol}] Post 14:00 IST. Scanning disabled.")
        return 

    if now.minute % 3 == 0:
        # Force column formatting before passing to generator
        df_1m.columns = df_1m.columns.str.lower()
        if 'volume' not in df_1m.columns: df_1m['volume'] = 1
        df_1m['volume'] = df_1m['volume'].replace(0, 1)

        signal_data = generate_v2_signals(df_1m, target_pts=config['target_pts'], sl_pts=config['sl_pts'])
        
        if signal_data:
            trade = {
                'type': signal_data['direction'], 'entry_time': now, 
                'entry_price': signal_data['entry_price'], 'qty': config['default_lot'], 
                'sl_price': signal_data['sl_price'], 'target_price': signal_data['target_price']
            }
            OPEN_TRADES[symbol] = trade
            
            # PUSH ENTRY TO GITHUB
            entry_payload = {
                "Timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "Symbol": symbol,
                "Strategy": "VWAP V2",
                "Action": trade['type'],
                "Entry": trade['entry_price'],
                "SL": trade['sl_price'],
                "Target": trade['target_price'],
                "Option": "-"
            }
            push_to_github(entry_payload, "VWAP", global_config.get("github_token"), global_config.get("github_repo"))

            print(f"🔥 LIVE SIGNAL LOGGED: {symbol} {signal_data['direction']} 🔥")
            if email_creds['user'] and email_creds['pass']:
                body = f"Strategy: VWAP + EMA V2\nNew Trade Executed: {symbol} {trade['type']}\nEntry: {trade['entry_price']}\nTarget: {trade['target_price']}\nSL: {trade['sl_price']}"
                send_email_alert(f"🚨 [VWAP V2] TRADE ENTRY: {symbol} {trade['type']}", body, email_creds['user'], email_creds['pass'], email_creds['user'])
        else:
            print(f"🟢 [{symbol}] Monitoring 3m Boundary... No setup.")
    else:
        print(f"  ⏳ [{symbol}] Waiting for next 3-minute candle close. CMP: {current_close}")

def run_live_scanner_loop():
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    if not os.path.exists(config_file): return

    with open(config_file, "r") as f:
        config = json.load(f)

    token = config.get("upstox_token")
    symbols = config.get("symbols", ["NIFTY", "SENSEX"])
    email_creds = {"user": config.get("gmail_user"), "pass": config.get("gmail_pass")}
    
    print("=" * 60)
    print(f"🚀 [VWAP V2] SCANNER ACTIVE (GITHUB LOGGING ENABLED)")
    print("=" * 60)

    try:
        while True:
            current_time = datetime.now(IST)
            is_weekday = current_time.weekday() <= 4 
            market_start = current_time.replace(hour=9, minute=15, second=0, microsecond=0)
            market_end = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            
            if not is_weekday or current_time < market_start or current_time > market_end:
                print(f"😴 [VWAP V2] Market Closed.")
                time.sleep(300) 
                continue

            for symbol in symbols:
                if symbol in INSTRUMENT_CONFIG:
                    process_symbol(symbol, token, INSTRUMENT_CONFIG[symbol], email_creds, config)
            
            time.sleep(60)

    except KeyboardInterrupt:
        print("\n🛑 Scanner stopped.")

if __name__ == "__main__":
    run_live_scanner_loop()
