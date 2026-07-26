import time
import urllib.parse
import pandas as pd
from datetime import datetime, timedelta
from core.api_client import robust_api_get

def fetch_candle_chunk(instrument_key, from_date, to_date, token, interval='1minute', logger=None):
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    encoded_key = urllib.parse.quote(instrument_key)
    
    start_dt = datetime.strptime(from_date, '%Y-%m-%d').date()
    end_dt = datetime.strptime(to_date, '%Y-%m-%d').date()
    
    all_candles = []
    current = start_dt
    
    while current <= end_dt:
        chunk_end = min(current + timedelta(days=2), end_dt)
        str_from = current.strftime('%Y-%m-%d')
        str_to = chunk_end.strftime('%Y-%m-%d')
        
        url_active = f"https://api.upstox.com/v2/historical-candle/{encoded_key}/{interval}/{str_to}/{str_from}"
        res = robust_api_get(url_active, headers)
        chunk_candles = []
        
        if res and res.status_code == 200:
            chunk_candles = res.json().get('data', {}).get('candles', [])
            
        if not chunk_candles:
            url_expired = f"https://api.upstox.com/v2/expired-instruments/historical-candle/{encoded_key}/{interval}/{str_to}/{str_from}"
            res_exp = robust_api_get(url_expired, headers)
            if res_exp and res_exp.status_code == 200:
                chunk_candles = res_exp.json().get('data', {}).get('candles', [])
                
        if chunk_candles:
            all_candles.extend(chunk_candles)
            
        current = chunk_end + timedelta(days=1)
        time.sleep(0.2)
            
    if not all_candles: return pd.DataFrame()
    
    df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'vol', 'oi'])
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    return df.sort_index().astype(float)

def get_specific_candle_close(instrument_key, target_dt_str, token):
    if not instrument_key: return 0.0
    target_date = target_dt_str[:10]
    headers = {'Accept': 'application/json', 'Authorization': f'Bearer {token}'}
    encoded_key = urllib.parse.quote(instrument_key)
    
    if instrument_key.count('|') >= 2:
        url = f"https://api.upstox.com/v2/expired-instruments/historical-candle/{encoded_key}/1minute/{target_date}/{target_date}"
    else:
        url = f"https://api.upstox.com/v3/historical-candle/intraday/{encoded_key}/minutes/1"
        
    res = robust_api_get(url, headers)
    if res and res.status_code == 200:
        candles = res.json().get("data", {}).get("candles", [])
        candles.sort(key=lambda x: x[0]) 
        for candle in candles:
            if str(candle[0])[:16].replace('T', ' ') >= target_dt_str:
                return float(candle[4])
    return 0.0
