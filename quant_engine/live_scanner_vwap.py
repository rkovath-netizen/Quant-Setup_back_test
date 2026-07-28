import os
import sys
import time
import json
import pandas as pd
from datetime import datetime, timedelta

# --- Ensure quant_engine directory is in Python path ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST
from data.instrument_master import get_all_expiries, resolve_exact_contract
from data.candle_fetcher import fetch_candle_chunk
from core.notifier import send_email_alert
from strategies.vwap_ema_v2 import generate_v2_signals

TIMESTAMP_STR = datetime.now(IST).strftime("%Y%m%d")
TRADE_LOG_FILE = os.path.join(BASE_DIR, f"Live_Debugger_V2_{TIMESTAMP_STR}.xlsx")

OPEN_TRADES = {"NIFTY": None, "SENSEX": None}
INSTRUMENT_CONFIG = {
    "NIFTY": {"default_lot": 25, "target_pts": 25, "sl_pts": 15},
    "SENSEX": {"default_lot": 10, "target_pts": 75, "sl_pts": 45} # Scaled for Sensex volatility
}

def initialize_excel_log():
    """Initializes the Daily Excel Debugger for validation."""
    if not os.path.exists(TRADE_LOG_FILE):
        conditions = [
            "STRATEGY ENTRY AND EXIT CONDITIONS (V2)",
            "15-MINUTE BIAS",
            "- BUY CE: 15m Close > 15m VWAP AND 15m 9 EMA > 15m 21 EMA",
            "- BUY PE: 15m Close < 15m VWAP AND 15m 9 EMA < 15m 21 EMA",
            "3-MINUTE ENTRY TRIGGER",
            "- Pullback touching 9 EMA or VWAP + Vol Expansion + Rejection",
            "RISK MANAGEMENT",
            "- Target/SL predefined per instrument.",
            "- No new entries >= 14:00 IST",
            "- Auto Square-Off at 15:15 IST"
        ]
        cond_df = pd.DataFrame({"Strategy Rules": conditions})
        cols = ['Stock', 'Trade_Type', 'Entry_Date_Time', 'Entry_Price', 'Qty', 
                'Initial_SL', 'Target_Price', 'Exit_Date_Time', 'Exit_Price', 
                'Exit_Reason', 'Bars_In_Trade', 'PnL']
        trade_df = pd.DataFrame(columns=cols)
        
        with pd.ExcelWriter(TRADE_LOG_FILE, engine='openpyxl') as writer:
            trade_df.to_excel(writer, sheet_name='Trade_Log', index=False)
            cond_df.to_excel(writer, sheet_name='Conditions', index=False)

def log_trade_to_excel(trade_dict):
    """Appends closed trades to the Excel Debugger."""
    df = pd.DataFrame([trade_dict])
    with pd.ExcelWriter(TRADE_LOG_FILE, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
        startrow = writer.sheets['Trade_Log'].max_row
        df.to_excel(writer, sheet_name='Trade_Log', startrow=startrow, index=False, header=False)

def process_symbol(symbol, token, config, email_creds):
    now = datetime.now(IST)
    current_time = now.time()
    active_trade = OPEN_TRADES[symbol]
    
    # 1. Resolve Instrument
    expiries = get_all_expiries(symbol, token, logger=lambda x: None)
    if not expiries: return
    fut_key = resolve_exact_contract(symbol, expiries[0], token, inst_type="FUTIDX", logger=lambda x: None)
    if not fut_key: return

    # 2. Fetch Unified Data (1-minute timeframe for resampling)
    start_str = (now - timedelta(days=5)).strftime('%Y-%m-%d')
    today_str = now.strftime('%Y-%m-%d')
    df_1m = fetch_candle_chunk(fut_key, start_str, today_str, token, interval='1minute', logger=lambda x: None)
    
    if df_1m.empty: return
    current_close = df_1m.iloc[-1]['close']

    # ==========================================
    # TRADE MANAGEMENT (EXIT LOGIC)
    # ==========================================
    if active_trade is not None:
        exit_price, exit_reason = None, None
        
        if current_time >= datetime.time(15, 15):
            exit_price = current_close
            exit_reason = '15:15 Auto Square Off'
        elif active_trade['type'] == 'BUY CE':
            if current_close <= active_trade['sl_price']:
                exit_price = active_trade['sl_price']
                exit_reason = 'SL Hit'
            elif current_close >= active_trade['target_price']:
                exit_price = active_trade['target_price']
                exit_reason = 'Target Achieved'
        elif active_trade['type'] == 'BUY PE':
            if current_close >= active_trade['sl_price']:
                exit_price = active_trade['sl_price']
                exit_reason = 'SL Hit'
            elif current_close <= active_trade['target_price']:
                exit_price = active_trade['target_price']
                exit_reason = 'Target Achieved'

        if exit_price is not None:
            # Calculate PnL & Log Trade
            pnl = (exit_price - active_trade['entry_price']) * active_trade['qty'] if active_trade['type'] == 'BUY CE' else (active_trade['entry_price'] - exit_price) * active_trade['qty']
            bars_held = int((now - active_trade['entry_time']).total_seconds() // 180)
            
            log_trade_to_excel({
                'Stock': symbol, 'Trade_Type': active_trade['type'], 
                'Entry_Date_Time': active_trade['entry_time'].strftime("%Y-%m-%d %H:%M:%S"), 
                'Entry_Price': active_trade['entry_price'], 'Qty': active_trade['qty'], 
                'Initial_SL': active_trade['sl_price'], 'Target_Price': active_trade['target_price'],
                'Exit_Date_Time': now.strftime("%Y-%m-%d %H:%M:%S"), 'Exit_Price': exit_price, 
                'Exit_Reason': exit_reason, 'Bars_In_Trade': bars_held, 'PnL': round(pnl, 2)
            })
            
            print(f"💰 TRADE CLOSED | {symbol} {exit_reason} | PnL: Rs {round(pnl, 2)}")
            if email_creds['user'] and email_creds['pass']:
                body = f"Trade Closed: {symbol} {active_trade['type']}\nReason: {exit_reason}\nEntry: {active_trade['entry_price']}\nExit: {exit_price}\nPnL: Rs {round(pnl, 2)}"
                send_email_alert(f"[VWAP V2] TRADE EXIT: {symbol} ({exit_reason})", body, email_creds['user'], email_creds['pass'], email_creds['user'])
            
            OPEN_TRADES[symbol] = None
        else:
            mtm = (current_close - active_trade['entry_price']) * active_trade['qty'] if active_trade['type'] == 'BUY CE' else (active_trade['entry_price'] - current_close) * active_trade['qty']
            print(f"⚡ ACTIVE TRADE | {symbol} {active_trade['type']} | CMP: {current_close} | MTM: Rs {round(mtm, 2)}")
        return

    # ==========================================
    # SCANNER LOGIC (ENTRY)
    # ==========================================
    if current_time >= datetime.time(14, 0):
        print(f"🛑 [{symbol}] Post 14:00 IST. Scanning disabled for new entries.")
        return 

    # Only evaluate on strict 3-minute boundaries
    if now.minute % 3 == 0:
        signal_data = generate_v2_signals(df_1m, target_pts=config['target_pts'], sl_pts=config['sl_pts'])
        
        if signal_data:
            print(f"🔥 LIVE SIGNAL DETECTED: {symbol} {signal_data['direction']} 🔥")
            trade = {
                'type': signal_data['direction'], 
                'entry_time': now, 
                'entry_price': signal_data['entry_price'],
                'qty': config['default_lot'], 
                'sl_price': signal_data['sl_price'], 
                'target_price': signal_data['target_price']
            }
            OPEN_TRADES[symbol] = trade
            
            if email_creds['user'] and email_creds['pass']:
                body = f"Strategy: VWAP + EMA V2\nNew Trade Executed: {symbol} {trade['type']}\nEntry: {trade['entry_price']}\nTarget: {trade['target_price']}\nSL: {trade['sl_price']}"
                send_email_alert(f"🚨 [VWAP V2] TRADE ENTRY: {symbol} {trade['type']}", body, email_creds['user'], email_creds['pass'], email_creds['user'])
        else:
            print(f"🟢 [{symbol}] Monitoring 3m Boundary... No setup.")
    else:
        print(f"🟢 [{symbol}] Waiting for next 3-minute candle close. CMP: {current_close}")

def run_live_scanner_loop():
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    if not os.path.exists(config_file):
        print("❌ Error: scanner_config.json not found.")
        return

    with open(config_file, "r") as f:
        config = json.load(f)

    token = config.get("upstox_token")
    symbols = config.get("symbols", ["NIFTY", "SENSEX"])
    email_creds = {"user": config.get("gmail_user"), "pass": config.get("gmail_pass")}
    
    initialize_excel_log()
    print("=" * 60)
    print(f"🚀 [VWAP V2] SCANNER DETACHED & ACTIVE [{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}]")
    print(f"📊 Daily Validation Debugger: {TRADE_LOG_FILE}")
    print("=" * 60)

    try:
        while True:
            current_time = datetime.now(IST)
            is_weekday = current_time.weekday() <= 4 
            market_start = current_time.replace(hour=9, minute=15, second=0, microsecond=0)
            market_end = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            
            if not is_weekday or current_time < market_start or current_time > market_end:
                print(f"😴 [VWAP V2] Market Closed. Scanner resting... ({current_time.strftime('%H:%M:%S')} IST)")
                time.sleep(300) 
                continue

            print(f"\n⏰ [VWAP V2] Scan Cycle: {current_time.strftime('%H:%M:%S')} IST")
            for symbol in symbols:
                if symbol in INSTRUMENT_CONFIG:
                    process_symbol(symbol, token, INSTRUMENT_CONFIG[symbol], email_creds)
            
            # Wake up every 60 seconds to check for active trade targets/stops
            time.sleep(60)

    except KeyboardInterrupt:
        print("\n🛑 Scanner stopped.")

if __name__ == "__main__":
    run_live_scanner_loop()
