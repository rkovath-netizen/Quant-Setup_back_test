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

def get_front_month_future(symbol_prefix):
    """Robustly fetches the active front-month future contract key."""
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    try:
        df = pd.read_csv(url)
        df.columns = df.columns.str.strip().str.lower()
        
        # FIX: Upstox internal name for SENSEX is BSESENSEX
        search_name = "BSESENSEX" if symbol_prefix == "SENSEX" else symbol_prefix
        
        df_f = df[(df['instrument_type'] == 'FUTIDX') & (df['name'] == search_name)]
        if df_f.empty: return None
        
        df_f['expiry'] = pd.to_datetime(df_f['expiry']).dt.date
        today = datetime.now(IST).date()
        active_contracts = df_f[df_f['expiry'] >= today].sort_values('expiry')
        if not active_contracts.empty:
            return active_contracts.iloc[0]['instrument_key']
    except Exception:
        pass
    return None

def fetch_unified_data(instrument_key, token, days=5):
    """Fetches strictly 1-minute data (which Upstox API allows)."""
    encoded_key = urllib.parse.quote(instrument_key)
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    now = datetime.now(IST)
    start_date = now - timedelta(days=days)
    to_str = now.strftime('%Y-%m-%d')
    from_str = start_date.strftime('%Y-%m-%d')
    
    # Historical Fetch (1-minute)
    hist_url = f"https://api.upstox.com/v2/historical-candle/{encoded_key}/1minute/{to_str}/{from_str}"
    hist_res = requests.get(hist_url, headers=headers)
    hist_data = hist_res.json().get('data', {}).get('candles', []) if hist_res.status_code == 200 else []
    
    # Intraday Fetch (1-minute)
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
    """Resamples 1-minute data into any requested timeframe."""
    if df.empty: return df
    agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    df_resampled = df.resample(timeframe).agg(agg_dict)
    return df_resampled.dropna(subset=['close'])

def calculate_stoch_indicators(df, ltf_k=14, ltf_d=3, htf_ema=50):
    df = df.copy()
    df['EMA_50'] = ta.ema(df['close'], length=htf_ema)
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=ltf_k, d=ltf_d)
    
    if stoch is not None and not stoch.empty:
        df['STOCH_K'] = stoch[f'STOCHk_{ltf_k}_{ltf_d}_3']
        df['STOCH_D'] = stoch[f'STOCHd_{ltf_k}_{ltf_d}_3']
    else:
        df['STOCH_K'], df['STOCH_D'] = 50.0, 50.0
        
    return df.dropna()

def run_stoch_debugger(symbol="NIFTY"):
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
    
    future_key = get_front_month_future(symbol)
    if not future_key:
        print("❌ Failed to resolve front-month futures contract.")
        return

    # FIX: Fetch 1-minute data and resample it to 5-minute to avoid API blocks
    df_1m = fetch_unified_data(future_key, token, days=5)
    if df_1m.empty:
        print("❌ No data returned from API.")
        return
        
    df = resample_candles(df_1m, '5min')
    df = calculate_stoch_indicators(df)
    
    df['date'] = df.index.date
    latest_date = df['date'].max()
    day_df = df[df['date'] == latest_date].copy()
    
    if day_df.empty:
        print("❌ Not enough data to process the latest trading day.")
        return

    print("\n" + "=" * 115)
    print(f"📊 [STOCHASTIC] DAILY VALIDATION DEBUGGER | {symbol} | Date: {latest_date}")
    print("=" * 115)
    print(f"{'Time':<8} | {'Close':<8} | {'50-EMA':<8} | {'Trend':<6} | {'Prv_K':<6} | {'Prv_D':<6} | {'Cur_K':<6} | {'Cur_D':<6} | {'Cross':<8} | {'OB/OS':<8} | {'SIGNAL'}")
    print("-" * 115)

    for i in range(1, len(day_df)):
        curr_idx = day_df.index[i]
        prev_idx = day_df.index[i-1]
        time_obj = curr_idx.time()
        
        # Only evaluate during market hours
        if not (dtime(9, 15) <= time_obj <= dtime(15, 30)):
            continue
        
        curr_row = day_df.loc[curr_idx]
        prev_row = day_df.loc[prev_idx]

        time_str = curr_idx.strftime('%H:%M')
        close, ema = curr_row['close'], curr_row['EMA_50']
        curr_k, curr_d = curr_row['STOCH_K'], curr_row['STOCH_D']
        prev_k, prev_d = prev_row['STOCH_K'], prev_row['STOCH_D']

        trend_up = close > ema
        trend_dn = close < ema
        trend_str = "✅ UP" if trend_up else "✅ DN" if trend_dn else "❌ --"

        cross_up = (prev_k < prev_d) and (curr_k > curr_d)
        cross_dn = (prev_k > prev_d) and (curr_k < curr_d)
        cross_str = "✅ UP" if cross_up else "✅ DN" if cross_dn else "❌ --"

        os_pass = prev_k <= 30
        ob_pass = prev_k >= 70
        ob_os_str = "✅ OS" if os_pass else "✅ OB" if ob_pass else "❌ MID"

        signal_str = "➖"
        if trend_up and cross_up and os_pass: signal_str = "🔥 LONG CE"
        elif trend_dn and cross_dn and ob_pass: signal_str = "🔥 SHORT PE"

        print(f"{time_str:<8} | {close:<8.2f} | {ema:<8.2f} | {trend_str:<6} | {prev_k:<6.2f} | {prev_d:<6.2f} | {curr_k:<6.2f} | {curr_d:<6.2f} | {cross_str:<8} | {ob_os_str:<8} | {signal_str}")

    print("=" * 115)
    print("Debug run complete.\n")

if __name__ == "__main__":
    run_stoch_debugger("NIFTY")
    run_stoch_debugger("SENSEX")
