import os
import sys
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

def calculate_stoch_indicators(df, ltf_k=14, ltf_d=3, htf_ema=50):
    """Calculates the indicators required for the Stochastic Strategy."""
    df = df.copy()
    df['EMA_50'] = ta.ema(df['close'], length=htf_ema)
    
    stoch = ta.stoch(df['high'], df['low'], df['close'], k=ltf_k, d=ltf_d)
    if stoch is not None and not stoch.empty:
        df['STOCH_K'] = stoch[f'STOCHk_{ltf_k}_{ltf_d}_3']
        df['STOCH_D'] = stoch[f'STOCHd_{ltf_k}_{ltf_d}_3']
    else:
        df['STOCH_K'] = 50.0
        df['STOCH_D'] = 50.0
        
    return df.dropna()

def run_stoch_debugger(symbol="NIFTY"):
    """Fetches recent data, isolates the latest trading day, and validates conditions."""
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    if not os.path.exists(config_file):
        print("❌ Error: scanner_config.json not found. Please run the scanner from the UI first to save credentials.")
        return

    with open(config_file, "r") as f:
        config = json.load(f)
    token = config.get("upstox_token")
    if not token:
        print("❌ Error: Upstox token missing in config.")
        return

    print(f"🔄 Fetching data for {symbol}...")
    
    # 1. Resolve Contract
    all_expiries = get_all_expiries(symbol, token, logger=lambda x: None)
    if not all_expiries: 
        print("❌ Failed to fetch expiries.")
        return
        
    future_key = resolve_exact_contract(symbol, all_expiries[0], token, inst_type="FUTIDX", logger=lambda x: None)
    if not future_key:
        print("❌ Failed to resolve futures contract.")
        return

    # 2. Fetch Data (Look back 5 days to ensure we have enough data for EMA/Stoch warmup)
    today = datetime.now(IST)
    start_date = today - timedelta(days=5)
    
    df = fetch_candle_chunk(
        future_key, 
        start_date.strftime('%Y-%m-%d'), 
        today.strftime('%Y-%m-%d'), 
        token, 
        interval='5minute', 
        logger=lambda x: None
    )
    
    if df.empty:
        print("❌ No data returned from API.")
        return

    # 3. Calculate Indicators
    df = calculate_stoch_indicators(df)
    
    # 4. Isolate the Latest Trading Day
    df['date'] = df.index.date
    latest_date = df['date'].max()
    day_df = df[df['date'] == latest_date].copy()
    
    if day_df.empty:
        print("❌ Not enough data to process the latest trading day.")
        return

    # 5. Print the Debugger Table
    print("\n" + "=" * 115)
    print(f"📊 [STOCHASTIC] DAILY VALIDATION DEBUGGER | {symbol} | Date: {latest_date}")
    print("=" * 115)
    print(f"{'Time':<8} | {'Close':<8} | {'50-EMA':<8} | {'Trend':<6} | {'Prv_K':<6} | {'Prv_D':<6} | {'Cur_K':<6} | {'Cur_D':<6} | {'Cross':<8} | {'OB/OS':<8} | {'SIGNAL'}")
    print("-" * 115)

    for i in range(1, len(day_df)):
        # Getting the previous and current values natively from the daily slice 
        # (using index positioning from the full df to get the true previous candle)
        curr_idx = day_df.index[i]
        prev_idx = day_df.index[i-1]
        
        curr_row = day_df.loc[curr_idx]
        prev_row = day_df.loc[prev_idx]

        time_str = curr_idx.strftime('%H:%M')
        close = curr_row['close']
        ema = curr_row['EMA_50']
        
        curr_k, curr_d = curr_row['STOCH_K'], curr_row['STOCH_D']
        prev_k, prev_d = prev_row['STOCH_K'], prev_row['STOCH_D']

        # --- Evaluate Conditions ---
        
        # 1. Trend Filter
        trend_up = close > ema
        trend_dn = close < ema
        trend_str = "✅ UP" if trend_up else "✅ DN" if trend_dn else "❌ --"

        # 2. Stochastic Crossover
        cross_up = (prev_k < prev_d) and (curr_k > curr_d)
        cross_dn = (prev_k > prev_d) and (curr_k < curr_d)
        cross_str = "✅ UP" if cross_up else "✅ DN" if cross_dn else "❌ --"

        # 3. Overbought / Oversold Filter
        os_pass = prev_k <= 30
        ob_pass = prev_k >= 70
        ob_os_str = "✅ OS" if os_pass else "✅ OB" if ob_pass else "❌ MID"

        # 4. Final Signal Check
        signal_str = "➖"
        if trend_up and cross_up and os_pass:
            signal_str = "🟢 LONG CE"
        elif trend_dn and cross_dn and ob_pass:
            signal_str = "🔴 SHORT PE"

        # --- Format Output ---
        print(f"{time_str:<8} | {close:<8.2f} | {ema:<8.2f} | {trend_str:<6} | {prev_k:<6.2f} | {prev_d:<6.2f} | {curr_k:<6.2f} | {curr_d:<6.2f} | {cross_str:<8} | {ob_os_str:<8} | {signal_str}")

    print("=" * 115)
    print("Debug run complete.\n")

if __name__ == "__main__":
    # Run for NIFTY by default, you can change this to SENSEX or run both
    run_stoch_debugger("NIFTY")
    run_stoch_debugger("SENSEX")
