import os
import sys
import json
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timedelta, time as dtime

# Ensure quant_engine directory is in Python path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST
from data.candle_fetcher import fetch_candle_chunk

def get_front_month_future(symbol_prefix):
    """Bypasses API maintenance by resolving contracts via Upstox's static AWS CSV."""
    url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    try:
        df = pd.read_csv(url)
        df.columns = df.columns.str.strip().str.lower()
        
        # Strict matching on exact name without hardcoding the exchange
        df_f = df[(df['instrument_type'] == 'FUTIDX') & (df['name'] == symbol_prefix)]
        if df_f.empty: return None
        
        df_f['expiry'] = pd.to_datetime(df_f['expiry']).dt.date
        today = datetime.now(IST).date()
        active_contracts = df_f[df_f['expiry'] >= today].sort_values('expiry')
        if not active_contracts.empty:
            return active_contracts.iloc[0]['instrument_key']
    except Exception:
        pass
    return None

def resample_candles(df, timeframe):
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

    print(f"\n🔄 Fetching data for {symbol}...")
    future_key = get_front_month_future(symbol)
    
    if not future_key:
        print(f"❌ Failed to resolve front-month futures contract for {symbol}.")
        return
        
    print(f"✅ Resolved Contract: {future_key}")

    now = datetime.now(IST)
    start_str = (now - timedelta(days=5)).strftime('%Y-%m-%d')
    today_str = now.strftime('%Y-%m-%d')

    # Hooking directly into your proven candle fetcher with live logging ON
    df_1m = fetch_candle_chunk(future_key, start_str, today_str, token, interval='1minute', logger=print)
    
    if df_1m.empty:
        print(f"❌ No data returned from API for {symbol}.")
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
