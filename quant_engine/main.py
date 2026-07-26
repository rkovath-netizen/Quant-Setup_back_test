import os
import pandas as pd
from datetime import datetime, timedelta

# --- Import from our custom modules ---
from core.config import IST, TIMEFRAME_COMBOS
from data.instrument_master import get_all_expiries, resolve_exact_contract
from data.candle_fetcher import fetch_candle_chunk
from strategies.stochastic_momentum import generate_signals
from execution.simulator import simulate_options_trades

def build_continuous_futures(symbol, start_date_str, token, logger=print):
    """
    Orchestrates the fetching and stitching of continuous futures data.
    Automatically handles 1-min to 5-min timeframe fallbacks for illiquid BSE contracts.
    """
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    
    # 1. Fetch exact exchange-approved expiries
    all_expiries = get_all_expiries(symbol, token, logger=logger)
    if not all_expiries:
        logger(f"CRITICAL: 0 expiries found for {symbol}.")
        return pd.DataFrame(), []

    # 2. Check local CSV cache to save time
    local_filename = f"{symbol}_continuous.csv"
    if os.path.exists(local_filename):
        df = pd.read_csv(local_filename)
        if not df.empty:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df.set_index('timestamp', inplace=True)
            if df.index.tz is not None: df.index = df.index.tz_localize(None)
            
            if df.index.min() <= pd.to_datetime(start_date_str):
                if df.index.max() >= pd.to_datetime(today_str) - timedelta(days=5):
                    df = df[df.index >= pd.to_datetime(start_date_str)]
                    if not df.empty:
                        logger(f"Successfully loaded {len(df)} rows from local cache.")
                        return df, all_expiries

    # 3. Stitch fresh API data if cache fails/is old
    logger(f"Fetching methodical continuous data for {symbol}...")
    relevant_expiries = [e for e in all_expiries if datetime.strptime(e, '%Y-%m-%d').date() >= start_dt]
    
    continuous_df = pd.DataFrame()
    current_start = start_date_str
    
    for exp in relevant_expiries:
        future_key = resolve_exact_contract(symbol, exp, token, inst_type="FUTIDX", logger=logger)
        if not future_key:
            continue
        
        end_fetch = min(exp, today_str)
        logger(f"Fetching Upstox 1-min data for {symbol} Future Key: {future_key} ({current_start} to {end_fetch})")
        
        # Micro-chunking API download
        df = fetch_candle_chunk(future_key, current_start, end_fetch, token, interval='1minute', logger=logger)
        
        # Fallback for illiquid contracts (e.g. SENSEX)
        if df.empty:
            logger(f"⚠️ 1-min empty for {future_key}. Falling back to 3-min candles...")
            df = fetch_candle_chunk(future_key, current_start, end_fetch, token, interval='3minute', logger=logger)
            
        if df.empty:
            logger(f"⚠️ 3-min empty for {future_key}. Falling back to 5-min candles...")
            df = fetch_candle_chunk(future_key, current_start, end_fetch, token, interval='5minute', logger=logger)
        
        if not df.empty:
            continuous_df = pd.concat([continuous_df, df])
        else:
            logger(f"⚠️ UPSTOX DATA LIMIT: 0 historical candles returned for {future_key}.")
            
        current_start = (datetime.strptime(exp, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        if current_start > today_str: break
            
    if not continuous_df.empty:
        continuous_df = continuous_df[~continuous_df.index.duplicated(keep='first')]
        try: continuous_df.to_csv(local_filename)
        except: pass
        
    return continuous_df, all_expiries

def run_backtest():
    # --- CONFIGURATION ---
    TOKEN = "YOUR_UPSTOX_ACCESS_TOKEN" # <-- Insert your live token here
    START_DATE = "2026-06-26"          # 30-day lookback window
    SYMBOLS = ["NIFTY", "SENSEX"]
    # ---------------------

    print(f"--- BACKGROUND BACKTEST STARTED FOR {START_DATE} ONWARDS ---")

    for symbol in SYMBOLS:
        print(f"\nProcessing {symbol}...")
        
        # STEP 1: Build the massive continuous Future baseline
        futures_df, all_expiries = build_continuous_futures(symbol, START_DATE, TOKEN, logger=print)
        
        if futures_df.empty:
            print(f"Failed to fetch base data for {symbol}. Skipping.")
            continue
            
        print(f"Loaded {len(futures_df)} base rows for {symbol}.")
        
        symbol_trades = []
        
        # STEP 2: Loop through each Strategy Timeframe Combo
        for ltf, htf in TIMEFRAME_COMBOS:
            print(f"Evaluating Strategy: {ltf} / {htf} for {symbol}...")
            
            # STEP 3: Pass Data to the Strategy Module
            signal_df = generate_signals(futures_df, ltf, htf)
            
            print(f"Simulating trades and fetching Option prices for {ltf}/{htf}...")
            # STEP 4: Pass Signals to the Execution/Simulation Module
            trades_df = simulate_options_trades(signal_df, symbol, f"{ltf}/{htf}", TOKEN, all_expiries, logger=print)
            
            if not trades_df.empty:
                print(f"Found {len(trades_df)} trades for {ltf}/{htf}.")
                symbol_trades.append(trades_df)
            else:
                print(f"0 trades for {ltf}/{htf}.")
                
        # STEP 5: Consolidate and Output metrics
        if symbol_trades:
            final_df = pd.concat(symbol_trades, ignore_index=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            output_dir = "backtest_results"
            os.makedirs(output_dir, exist_ok=True)
            
            filename = f"{output_dir}/{symbol}_trades_{timestamp}.csv"
            final_df.to_csv(filename, index=False)
            print(f"Successfully created {filename}")

    print("\n--- BACKGROUND BACKTEST FULLY COMPLETE ---")

if __name__ == "__main__":
    run_backtest()
