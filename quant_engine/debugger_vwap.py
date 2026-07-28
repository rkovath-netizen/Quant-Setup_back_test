import os
import sys
import json
import pandas as pd
import pandas_ta as ta
import requests
import urllib.parse
from datetime import datetime, timedelta, time as dtime

# Ensure quant_engine directory is in Python path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST
from data.instrument_master import get_all_expiries, resolve_exact_contract

def fetch_unified_data(instrument_key, token, days=5):
    """Fetches 1-minute historical and intraday data and stitches them."""
    encoded_key = urllib.parse.quote(instrument_key)
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    now = datetime.now(IST)
    start_date = now - timedelta(days=days)
    to_str = now.strftime('%Y-%m-%d')
    from_str = start_date.strftime('%Y-%m-%d')
    
    hist_url = f"https://api.upstox.com/v2/historical-candle/{encoded_key}/1minute/{to_str}/{from_str}"
    hist_res = requests.get(hist_url, headers=headers)
    hist_data = hist_res.json().get('data', {}).get('candles', []) if hist_res.status_code == 200 else []
    
    intra_url = f"https://api.upstox.com/v2/historical-candle/intraday/{encoded_key}/1minute"
    intra_res = requests.get(intra_url, headers=headers)
    intra_data = intra_res.json().get('data', {}).get('candles', []) if intra_res.status_code == 200 else []
    
    all_data = hist_data + intra_data
    
    if all_data:
        df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
        df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None)
        df = df.sort_values('timestamp').drop_duplicates('timestamp').set_index('timestamp')
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        return df
    return pd.DataFrame()

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
    return df.dropna()

def run_vwap_debugger(symbol="NIFTY"):
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    if not os.path.exists(config_file):
        print("❌ Error: scanner_config.json not found. Run the scanner from the UI first.")
        return

    with open(config_file, "r") as f:
        config = json.load(f)
    token = config.get("upstox_token")
    
    if not token:
        print("❌ Error: Upstox token missing in config.")
        return

    print(f"🔄 Fetching data for {symbol}...")
    
    # --- USE CORE INSTRUMENT MASTER TO RESOLVE CONTRACT ---
    all_expiries = get_all_expiries(symbol, token, logger=lambda x: None)
    if not all_expiries: 
        print(f"❌ Failed to fetch expiries for {symbol}.")
        return
        
    future_key = resolve_exact_contract(symbol, all_expiries[0], token, inst_type="FUTIDX", logger=lambda x: None)
    if not future_key:
        print(f"❌ Failed to resolve front-month futures contract for {symbol}.")
        return
    # ------------------------------------------------------

    df_1m = fetch_unified_data(future_key, token, days=5)
    if df_1m.empty:
        print("❌ No data returned from API.")
        return

    df_3m = resample_candles(df_1m, '3min')
    df_15m = resample_candles(df_1m, '15min')
    
    df_3m = calculate_vwap_ema_indicators(df_3m)
    df_15m = calculate_vwap_ema_indicators(df_15m)
    
    if len(df_3m) < 3 or len(df_15m) < 2: 
        print("❌ Not enough data to build indicator history.")
        return
        
    df_15m = df_15m.add_suffix('_15m')
    df = pd.merge_asof(df_3m.reset_index(), df_15m.reset_index(), on='timestamp', direction='backward')
    df.set_index('timestamp', inplace=True)

    df['date'] = df.index.date
    latest_date = df['date'].max()
    day_df = df[df['date'] == latest_date].copy()

    print("\n" + "=" * 110)
    print(f"ANALYZING: {symbol} FUTURES | DATE: {latest_date}")
    print("=" * 110)
    print(f"{'TIME':<10} | {'BIAS':<8} | {'PULLBACK':<10} | {'VOLUME':<10} | {'REJECTION':<10} | RESULT")
    print("-" * 110)

    for idx, row in day_df.iterrows():
        time_str = idx.strftime('%H:%M')
        time_obj = idx.time()
        
        if not (dtime(9, 15) <= time_obj <= dtime(15, 30)):
            continue

        bias_ce = (row['close_15m'] > row['VWAP_15m']) and (row['EMA_9_15m'] > row['EMA_21_15m'])
        bias_pe = (row['close_15m'] < row['VWAP_15m']) and (row['EMA_9_15m'] < row['EMA_21_15m'])
        
        bias_str = "LONG" if bias_ce else "SHORT" if bias_pe else "NONE"
        pb_str, vol_str, rej_str = "False", "False", "False"
        result_str = "No Setup"

        if bias_ce:
            pb_ce = (row['low'] <= row['EMA_9']) or (row['low'] <= row['VWAP'])
            vol_ce = row['volume'] > row['volume_prev']
            rej_ce = row['close'] > row['open']
            
            pb_str = str(bool(pb_ce))
            vol_str = str(bool(vol_ce))
            rej_str = str(bool(rej_ce))
            
            if pb_ce and vol_ce and rej_ce:
                if time_obj >= dtime(14, 0):
                    result_str = "🔥 CE SIGNAL! (REJECTED: >= 14:00)"
                else:
                    result_str = "🔥 CE SIGNAL! (VALID ENTRY)"

        elif bias_pe:
            pb_pe = row['high'] >= row['EMA_9']
            rej_pe = (row['close'] < row['open']) and (row['close'] < row['EMA_9'])
            
            pb_str = str(bool(pb_pe))
            vol_str = "N/A"
            rej_str = str(bool(rej_pe))
            
            if pb_pe and rej_pe:
                if time_obj >= dtime(14, 0):
                    result_str = "🔥 PE SIGNAL! (REJECTED: >= 14:00)"
                else:
                    result_str = "🔥 PE SIGNAL! (VALID ENTRY)"
        
        if bias_ce or bias_pe:
            print(f"{time_str:<10} | {bias_str:<8} | {pb_str:<10} | {vol_str:<10} | {rej_str:<10} | {result_str}")

    print("=" * 110 + "\n")

if __name__ == "__main__":
    run_vwap_debugger("NIFTY")
    run_vwap_debugger("SENSEX")
