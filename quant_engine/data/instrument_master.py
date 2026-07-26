import os
import io
import csv
import gzip
import re
import requests
import pandas as pd
from datetime import datetime
from core.config import IST, INDEX_CONFIG
from core.api_client import robust_api_get

_LIVE_INSTRUMENTS_CACHE = None

def is_exact_symbol(tsym, symbol):
    tsym = str(tsym).upper().strip()
    symbol = symbol.upper()
    
    if symbol == "SENSEX":
        if tsym.startswith("SENSEX50"): 
            return False
        if tsym.startswith("BSX") or tsym.startswith("SENSEX"):
            pass
        else:
            return False
    else:
        if not tsym.startswith(symbol): return False
    
    if len(tsym) > len(symbol):
        next_char = tsym[len(symbol)]
        if next_char.isalpha(): return False
    return True

def get_live_instruments():
    global _LIVE_INSTRUMENTS_CACHE
    if _LIVE_INSTRUMENTS_CACHE is not None:
        return _LIVE_INSTRUMENTS_CACHE
        
    csv_file = "upstox_active_instruments.csv"
    today_dt = datetime.now(IST).date()
    
    if os.path.exists(csv_file):
        mtime = datetime.fromtimestamp(os.path.getmtime(csv_file), tz=IST).date()
        if mtime == today_dt:
            try:
                _LIVE_INSTRUMENTS_CACHE = pd.read_csv(csv_file, low_memory=False)
                return _LIVE_INSTRUMENTS_CACHE
            except: pass
            
    url_csv = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
    res_csv = requests.get(url_csv)
    if res_csv.status_code == 200:
        with gzip.open(io.BytesIO(res_csv.content), 'rt', encoding='utf-8') as f:
            df = pd.read_csv(f, low_memory=False)
            df.to_csv(csv_file, index=False)
            _LIVE_INSTRUMENTS_CACHE = df
            return df
    return pd.DataFrame()

def get_all_expiries(symbol, token, logger=None):
    available_expiries = set()
    underlying_key = INDEX_CONFIG[symbol]["underlying"]
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    
    url = "https://api.upstox.com/v2/expired-instruments/expiries"
    res = robust_api_get(url, headers, params={"instrument_key": underlying_key})
    if res and res.status_code == 200:
        for d in res.json().get("data", []):
            if isinstance(d, str): available_expiries.add(d)
            elif isinstance(d, dict) and "expiry_date" in d: available_expiries.add(d["expiry_date"])
            
    df = get_live_instruments()
    if not df.empty:
        subset = df[df['underlying_key'] == underlying_key] if 'underlying_key' in df.columns else df
        for _, row in subset.iterrows():
            tsym = str(row.get('tradingsymbol', ''))
            exp = str(row.get('expiry', ''))
            if exp and exp != 'nan' and is_exact_symbol(tsym, symbol):
                available_expiries.add(exp)
                
    return sorted(list(available_expiries))

def get_closest_weekly_expiry(all_expiries, target_date_str):
    valid_dates = [d for d in all_expiries if d >= target_date_str]
    return valid_dates[0] if valid_dates else None

def resolve_exact_contract(symbol, expiry_date_str, token, inst_type="FUTIDX", strike=None, opt_type=None, logger=None):
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    expiry_dt = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
    today_dt = datetime.now(IST).date()
    
    if expiry_dt >= today_dt:
        df = get_live_instruments()
        if not df.empty:
            segment = INDEX_CONFIG[symbol]["segment"]
            subset = df[(df['expiry'] == expiry_date_str) & (df['instrument_type'] == inst_type) & (df['exchange'] == segment)]
            
            for _, row in subset.iterrows():
                tsym_raw = str(row.get('tradingsymbol', ''))
                if not is_exact_symbol(tsym_raw, symbol): continue
                inst_key = str(row.get('instrument_key'))
                
                if inst_type == "FUTIDX": return inst_key
                if inst_type == "OPTIDX":
                    match = re.search(rf'(\d+(?:\.\d+)?)\s*{opt_type}', tsym_raw.upper())
                    if match and float(match.group(1)) == float(strike): return inst_key
    else:
        api_type = "option" if inst_type == "OPTIDX" else "future"
        underlying = INDEX_CONFIG[symbol]["underlying"]
        url = f"https://api.upstox.com/v2/expired-instruments/{api_type}/contract"
        res = robust_api_get(url, headers, params={"instrument_key": underlying, "expiry_date": expiry_date_str})
        
        if res and res.status_code == 200:
            for c in res.json().get("data", []):
                tsym_raw = str(c.get("trading_symbol", ""))
                if not is_exact_symbol(tsym_raw, symbol): continue
                inst_key = c.get("instrument_key")
                
                if inst_type == "FUTIDX": return inst_key
                if inst_type == "OPTIDX":
                    match = re.search(rf'(\d+(?:\.\d+)?)\s*{opt_type}', tsym_raw.upper())
                    if match and float(match.group(1)) == float(strike): return inst_key
    return None
