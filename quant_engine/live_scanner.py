import os
import sys
import time
import json
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta

# Ensure quant_engine directory is in Python path
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

def run_live_scanner_loop():
    """Runs continuously in the background, sending emails when a setup hits during market hours."""
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    if not os.path.exists(config_file):
        print("❌ Error: scanner_config.json not found.")
        return

    with open(config_file, "r") as f:
        config = json.load(f)

    token = config.get("upstox_token")
    symbols = config.get("symbols", ["NIFTY", "SENSEX"])
    gmail_user = config.get("gmail_user")
    gmail_pass = config.get("gmail_pass")
    
    # State tracker to prevent duplicate emails for the same candle signal
    last_alert_time = {sym: None for sym in symbols}

    print("=" * 60)
    print(f"🚀 LIVE BACKGROUND SCANNER ACTIVE [{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}]")
    print("=" * 60)

    try:
        while True:
            current_time = datetime.now(IST)
            
            # --- MARKET HOURS CHECK ---
            is_weekday = current_time.weekday() <= 4 # 0=Mon, 4=Fri
            market_start = current_time.replace(hour=9, minute=15, second=0, microsecond=0)
            market_end = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            
            if not is_weekday or current_time < market_start or current_time > market_end:
                print(f"😴 Market Closed. Scanner resting... ({current_time.strftime('%H:%M:%S')} IST)")
                time.sleep(300) # Sleep for 5 minutes and check again
                continue
            # --------------------------

            print(f"\n⏰ Scan Cycle: {current_time.strftime('%H:%M:%S')} IST")

            for symbol in symbols:
                res = scan_symbol(symbol, token)
                if res and "direction" in res:
                    signal_time = res["timestamp"]
                    
                    # Only alert if this is a brand new signal timestamp
                    if signal_time != last_alert_time[symbol]:
                        last_alert_time[symbol] = signal_time
                        
                        print(f"🔥 NEW {symbol} SIGNAL DETECTED! Processing Alert...")
                        
                        subject = f"🚨 {symbol} ALERT: {res['direction']} @ {res['underlying_entry']}"
                        body = (
                            f"Live Quant Alert Triggered\n"
                            f"--------------------------\n"
                            f"Instrument : {res['symbol']}\n"
                            f"Action     : {res['direction']}\n"
                            f"Entry Px   : {res['underlying_entry']}\n"
                            f"Stop Loss  : {res['stop_loss']} (-{res['risk_pts']} pts)\n"
                            f"Target     : {res['target']} (+{res['reward_pts']} pts)\n\n"
                            f"Recommended Strike:\n{res['recommended_option']}\n\n"
                            f"Signal Time: {signal_time} IST"
                        )
                        
                        if gmail_user and gmail_pass:
                            send_email_alert(subject, body, gmail_user, gmail_pass, gmail_user)
                        else:
                            print("⚠️ Email skipped: Gmail credentials missing in Streamlit Secrets.")
                            
                    else:
                        print(f"  🟢 [{symbol}] Signal active, but alert already sent for this candle.")
                else:
                    last_px = res.get('last_price', 'N/A') if res else 'N/A'
                    print(f"  🟢 [{symbol}] Monitoring... Last Price: {last_px}")

            # Sleep for 5 minutes between checks to align with the 5-min candle chart
            time.sleep(300)

    except KeyboardInterrupt:
        print("\n🛑 Scanner stopped.")

if __name__ == "__main__":
    run_live_scanner_loop()
