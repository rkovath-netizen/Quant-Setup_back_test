import pandas as pd
from core.config import INDEX_CONFIG
from data.instrument_master import get_closest_weekly_expiry, resolve_exact_contract
from data.candle_fetcher import get_specific_candle_close

def simulate_options_trades(signal_df, symbol, tf_label, token, all_expiries, logger=None):
    trades = []
    step = INDEX_CONFIG[symbol]["step"]
    
    for idx, row in signal_df.iterrows():
        if row['long_signal'] or row['short_signal']:
            entry_dt_str = str(idx)[:16]
            entry_date = entry_dt_str[:10]
            future_price = row['close']
            
            weekly_expiry = get_closest_weekly_expiry(all_expiries, entry_date)
            if not weekly_expiry: continue
            
            atm_strike = round(future_price / step) * step
            is_long = row['long_signal']
            trade_type = 'Bull Put Spread' if is_long else 'Bear Call Spread'
            opt_type = 'PE' if is_long else 'CE'
            otm2_strike = atm_strike - (step * 2) if is_long else atm_strike + (step * 2)
            
            sell_key = resolve_exact_contract(symbol, weekly_expiry, token, "OPTIDX", atm_strike, opt_type, logger)
            buy_key = resolve_exact_contract(symbol, weekly_expiry, token, "OPTIDX", otm2_strike, opt_type, logger)
            
            sell_price = round(get_specific_candle_close(sell_key, entry_dt_str, token), 2) if sell_key else 0.0
            buy_price = round(get_specific_candle_close(buy_key, entry_dt_str, token), 2) if buy_key else 0.0
            net_credit = round(sell_price - buy_price, 2)
            
            trades.append({
                'Entry_Time': entry_dt_str,
                'Symbol': symbol,
                'Timeframe': tf_label,
                'Trade_Type': trade_type,
                'Weekly_Expiry': weekly_expiry,
                'Future_Price': round(future_price, 2),
                'Sell_Leg': f"{atm_strike} {opt_type}",
                'Buy_Leg': f"{otm2_strike} {opt_type}",
                'Sell_Entry_Price': sell_price,
                'Buy_Entry_Price': buy_price,
                'Net_Credit_Received': net_credit,
                'Stop_Loss': round(sell_price * 1.15, 2) if sell_price > 0 else 0.0,
                'Take_Profit_Target': round(net_credit * 0.30, 2) if net_credit > 0 else 0.0
            })
            
    return pd.DataFrame(trades)
