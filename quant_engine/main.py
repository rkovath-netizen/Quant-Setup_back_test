import os
import sys
import json
import pandas as pd
from datetime import datetime, timedelta

# --- Force Python to recognize quant_engine directory for module imports ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.config import IST, TIMEFRAME_COMBOS
from core.github_client import upload_file_to_github
from data.instrument_master import get_all_expiries, resolve_exact_contract
from data.candle_fetcher import fetch_candle_chunk
from strategies.stochastic_momentum import generate_signals
from execution.simulator import simulate_options_trades

def build_continuous_futures(symbol, start_date_str, token, logger=print):
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    start_dt = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    
    all_expiries = get_all_expiries(symbol, token, logger=logger)
    if not all_expiries:
        logger(f"CRITICAL: 0 expiries found for {symbol}.")
        return pd.DataFrame(), []

    local_filename = os.path.join(BASE_DIR, f"{symbol}_continuous.csv")
    if os.path.exists(local_filename):
        try:
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
        except Exception:
            pass

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
        
        df = fetch_candle_chunk(future_key, current_start, end_fetch, token, interval='1minute', logger=logger)
        
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
    config_file = os.path.join(BASE_DIR, "run_config.json")
    if not os.path.exists(config_file):
        print("❌ Error: run_config.json not found.")
        return

    with open(config_file, "r") as f:
        config = json.load(f)

    token = config.get("upstox_token")
    github_token = config.get("github_token")
    github_repo = config.get("github_repo")
    days = int(config.get("days", 30))
    symbols = config.get("symbols", ["NIFTY", "SENSEX"])

    start_date = (datetime.now(IST) - timedelta(days=days)).strftime("%Y-%m-%d")
    timestamp_str = datetime.now(IST).strftime("%Y%m%d_%H%M%S")

    print(f"[{datetime.now(IST)}] --- BACKGROUND BACKTEST STARTED FOR {days} DAYS ({start_date}) ---")

    all_generated_files = []

    for symbol in symbols:
        print(f"\nProcessing {symbol}...")
        
        futures_df, all_expiries = build_continuous_futures(symbol, start_date, token, logger=print)
        
        if futures_df.empty:
            print(f"Failed to fetch base data for {symbol}. Skipping.")
            continue
            
        print(f"Loaded {len(futures_df)} base rows for {symbol}.")
        symbol_trades = []
        
        for ltf, htf in TIMEFRAME_COMBOS:
            print(f"Evaluating Strategy: {ltf} / {htf} for {symbol}...")
            signal_df = generate_signals(futures_df, ltf, htf)
            
            print(f"Simulating trades and fetching Option prices for {ltf}/{htf}...")
            trades_df = simulate_options_trades(signal_df, symbol, f"{ltf}/{htf}", token, all_expiries, logger=print)
            
            if not trades_df.empty:
                print(f"Found {len(trades_df)} trades for {ltf}/{htf}.")
                symbol_trades.append(trades_df)
            else:
                print(f"0 trades for {ltf}/{htf}.")
                
        if symbol_trades:
            final_df = pd.concat(symbol_trades, ignore_index=True)
            output_dir = os.path.join(BASE_DIR, "backtest_results")
            os.makedirs(output_dir, exist_ok=True)
            
            filename = os.path.join(output_dir, f"{symbol}_trades_{timestamp_str}.csv")
            final_df.to_csv(filename, index=False)
            print(f"Successfully saved {filename}")
            all_generated_files.append(filename)

    # --- PUSH RESULTS TO GITHUB ---
    if github_token and github_repo and all_generated_files:
        print("\nPushing backtest results to GitHub...")
        for local_file in all_generated_files:
            rel_path = f"backtest_results/{os.path.basename(local_file)}"
            upload_file_to_github(local_file, github_repo, rel_path, github_token, logger=print)

    print(f"\n[{datetime.now(IST)}] --- BACKGROUND BACKTEST FULLY COMPLETE & UPLOADED ---")

if __name__ == "__main__":
    run_backtest()
