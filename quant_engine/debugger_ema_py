"""
================================================================================
PURPOSE: HISTORICAL INTRADAY DEBUGGER FOR V2 VWAP + EMA STRATEGY
================================================================================
Updates:
- DYNAMIC DATE TARGETING: Automatically analyzes the most recent trading day 
  available. If run before 09:15 AM, it naturally analyzes the previous day.
- FULL DAY SCAN: Scans every 3-minute interval until 15:30, explicitly 
  flagging any signals generated on or after the 14:00 cutoff.
- DUAL INDEX: Scans both NIFTY and SENSEX sequentially.
================================================================================
"""

import pandas_ta as ta
import pandas as pd
import requests
import datetime
from datetime import timedelta
import urllib.parse
import pytz
import warnings

warnings.filterwarnings('ignore')

# ==========================================
# CONFIGURATION
# ==========================================
IST = pytz.timezone('Asia/Kolkata')
TOKEN_FILE = "upstox_analytics_token.txt"

SYMBOLS_TO_SCAN = ["NIFTY", "SENSEX"]

try:
    with open(TOKEN_FILE, 'r') as file:
        ACCESS_TOKEN = file.read().strip()
except FileNotFoundError:
    print(f"Error: {TOKEN_FILE} not found. Ensure token exists.")
    ACCESS_TOKEN = "YOUR_DUMMY_TOKEN"

HEADERS = {
    'Accept': 'application/json',
    'Authorization': f'Bearer {ACCESS_TOKEN}'
}

# ==========================================
# DATA FETCHING UTILITIES
# ==========================================
def get_current_front_month_future(symbol_prefix):
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    try:
        df = pd.read_csv(url)
        df.columns = df.columns.str.strip().str.lower()
        ex_col = 'exchange' if 'exchange' in df.columns else 'segment'
        
        exchange_target = 'BSE_FO' if symbol_prefix == 'SENSEX' else 'NSE_FO'
        
        df_f = df[(df[ex_col] == exchange_target) & 
                  (df['instrument_type'] == 'FUTIDX') & 
                  (df['name'] == symbol_prefix)]
                  
        if df_f.empty: return None
        
        df_f['expiry'] = pd.to_datetime(df_f['expiry']).dt.date
        today = datetime.datetime.now(IST).date()
        active_contracts = df_f[df_f['expiry'] >= today].sort_values('expiry')
        if not active_contracts.empty:
            return active_contracts.iloc[0]['instrument_key']
    except Exception as e:
        pass
    return None

def fetch_full_data(instrument_key, days=5):
    encoded_key = urllib.parse.quote(instrument_key)
    
    now = datetime.datetime.now(IST)
    start_date = now - timedelta(days=days)
    to_str = now.strftime('%Y-%m-%d')
    from_str = start_date.strftime('%Y-%m-%d')
    
    hist_url = f"https://api.upstox.com/v2/historical-candle/{encoded_key}/1minute/{to_str}/{from_str}"
    hist_res = requests.get(hist_url, headers=HEADERS)
    hist_data = hist_res.json().get('data', {}).get('candles', []) if hist_res.status_code == 200 else []
    
    intra_url = f"https://api.upstox.com/v2/historical-candle/intraday/{encoded_key}/1minute"
    intra_res = requests.get(intra_url, headers=HEADERS)
    intra_data = intra_res.json().get('data', {}).get('candles', []) if intra_res.status_code == 200 else []
    
    all_data = hist_data + intra_data
    
    if all_data:
        df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
        df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_localize(None) 
        df = df.sort_values('timestamp').drop_duplicates('timestamp').set_index('timestamp')
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        return df
        
    return pd.DataFrame()

# ==========================================
# INDICATOR LOGIC
# ==========================================
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
    return df

# ==========================================
# DEBUGGER ENGINE
# ==========================================
def analyze_symbol(symbol_prefix):
    fut_key = get_current_front_month_future(symbol_prefix)
    if not fut_key:
        print(f"Could not resolve futures key for {symbol_prefix}.")
        return
        
    df_1m_full = fetch_full_data(fut_key, days=5)
    if df_1m_full.empty:
        print(f"Data fetch failed for {symbol_prefix}. Check API token or network.")
        return
        
    # DYNAMIC TARGETING: Get the date of the very last row of available data
    latest_data_date = df_1m_full.index[-1].date()
    
    print("\n" + "="*110)
    print(f"ANALYZING: {symbol_prefix} FUTURES | DATE: {latest_data_date}")
    print("="*110)
    print(f"{'TIME':<10} | {'BIAS':<8} | {'PULLBACK':<10} | {'VOLUME':<10} | {'REJECTION':<10} | {'RESULT'}")
    print("-" * 110)
    
    df_target_day = df_1m_full[df_1m_full.index.date == latest_data_date]
    found_signals = False
    
    for current_time in df_target_day.index:
        # Evaluate exactly on the 3-minute boundaries up until market close
        if current_time.minute % 3 == 0:
            
            df_simulated_live = df_1m_full[df_1m_full.index < current_time]
            if df_simulated_live.empty: continue
            
            df_3m = resample_candles(df_simulated_live, '3min')
            df_15m = resample_candles(df_simulated_live, '15min')
            
            df_3m = calculate_vwap_ema_indicators(df_3m)
            df_15m = calculate_vwap_ema_indicators(df_15m)
            
            if len(df_3m) < 3 or len(df_15m) < 2: continue
            
            df_15m = df_15m.add_suffix('_15m')
            df_merged = pd.merge_asof(df_3m.reset_index(), df_15m.reset_index(), on='timestamp', direction='backward')
            df_merged.set_index('timestamp', inplace=True)
            
            row = df_merged.iloc[-1]
            candle_time = row.name.strftime('%H:%M')
            is_late = current_time.time() >= datetime.time(14, 0)
            
            bias_ce = (row['close_15m'] > row['VWAP_15m']) and (row['EMA_9_15m'] > row['EMA_21_15m'])
            ce_pullback = (row['low'] <= row['EMA_9']) or (row['low'] <= row['VWAP'])
            vol_increase = row['volume'] > row['volume_prev']
            bullish_rej = row['close'] > row['open']
            
            bias_pe = (row['close_15m'] < row['VWAP_15m']) and (row['EMA_9_15m'] < row['EMA_21_15m'])
            pe_pullback = row['high'] >= row['EMA_9']
            bearish_rej = (row['close'] < row['open']) and (row['close'] < row['EMA_9'])
            
            if bias_ce:
                found_signals = True
                if ce_pullback and vol_increase and bullish_rej:
                    result = "🔥 CE SIGNAL! (REJECTED: >= 14:00)" if is_late else "🔥 CE SIGNAL! (VALID ENTRY)"
                else:
                    result = "No Setup"
                print(f"{candle_time:<10} | {'LONG':<8} | {str(ce_pullback):<10} | {str(vol_increase):<10} | {str(bullish_rej):<10} | {result}")
                
            elif bias_pe:
                found_signals = True
                if pe_pullback and vol_increase and bearish_rej:
                    result = "🔥 PE SIGNAL! (REJECTED: >= 14:00)" if is_late else "🔥 PE SIGNAL! (VALID ENTRY)"
                else:
                    result = "No Setup"
                print(f"{candle_time:<10} | {'SHORT':<8} | {str(pe_pullback):<10} | {str(vol_increase):<10} | {str(bearish_rej):<10} | {result}")
                
    if not found_signals:
        print(f"No biased setups detected on {latest_data_date}.")

def run_debugger():
    print("\n" + "*"*110)
    print("INITIALIZING HISTORICAL DEBUGGER (DYNAMIC DATE & DUAL INDEX)".center(110))
    print("*"*110)
    
    for symbol in SYMBOLS_TO_SCAN:
        analyze_symbol(symbol)

if __name__ == "__main__":
    run_debugger()
