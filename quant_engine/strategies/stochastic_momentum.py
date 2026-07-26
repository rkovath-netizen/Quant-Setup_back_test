import pandas_ta as ta

def resample_timeframes(df_base, ltf_interval, htf_interval):
    agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'vol': 'sum'}
    ltf_df = df_base.resample(ltf_interval).agg(agg_dict).dropna()
    htf_df = df_base.resample(htf_interval).agg(agg_dict).dropna()
    return ltf_df, htf_df

def generate_signals(df_base, ltf_interval, htf_interval):
    """Universal standard strategy entry point."""
    ltf, htf = resample_timeframes(df_base, ltf_interval, htf_interval)
    
    htf['ema_25'] = ta.ema(htf['close'], length=25)
    stoch_htf = ta.stoch(htf['high'], htf['low'], htf['close'], k=14, d=3, smooth_k=3)
    if stoch_htf is not None: htf = htf.join(stoch_htf)
    htf['obv'] = ta.obv(htf['close'], htf['vol'])
    htf['obv_sma_20'] = ta.sma(htf['obv'], length=20)
    
    htf.rename(columns={c: 'htf_stoch_k' for c in htf.columns if 'STOCHk' in c}, inplace=True)
    htf.rename(columns={c: 'htf_stoch_d' for c in htf.columns if 'STOCHd' in c}, inplace=True)

    stoch_ltf = ta.stoch(ltf['high'], ltf['low'], ltf['close'], k=14, d=3, smooth_k=3)
    if stoch_ltf is not None: ltf = ltf.join(stoch_ltf)
    ltf.rename(columns={c: 'ltf_stoch_k' for c in ltf.columns if 'STOCHk' in c}, inplace=True)
    ltf.rename(columns={c: 'ltf_stoch_d' for c in ltf.columns if 'STOCHd' in c}, inplace=True)
    
    if 'ltf_stoch_k' in ltf.columns and 'ltf_stoch_d' in ltf.columns:
        ltf['stoch_cross_up'] = (ltf['ltf_stoch_k'] > ltf['ltf_stoch_d']) & (ltf['ltf_stoch_k'].shift(1) <= ltf['ltf_stoch_d'].shift(1))
        ltf['stoch_cross_down'] = (ltf['ltf_stoch_k'] < ltf['ltf_stoch_d']) & (ltf['ltf_stoch_k'].shift(1) >= ltf['ltf_stoch_d'].shift(1))
        
    required_htf_cols = ['ema_25', 'htf_stoch_k', 'htf_stoch_d', 'obv', 'obv_sma_20']
    for col in required_htf_cols:
        if col not in htf.columns: htf[col] = 0.0
            
    required_ltf_cols = ['stoch_cross_up', 'stoch_cross_down']
    for col in required_ltf_cols:
        if col not in ltf.columns: ltf[col] = False

    htf_aligned = htf[[c for c in required_htf_cols if c in htf.columns]].reindex(ltf.index, method='ffill').fillna(0)
    df = ltf.join(htf_aligned)
    
    df['htf_long_bias'] = (df['close'] > df['ema_25']) & (df['htf_stoch_k'] > df['htf_stoch_d']) & (df['obv'] > df['obv_sma_20'])
    df['htf_short_bias'] = (df['close'] < df['ema_25']) & (df['htf_stoch_k'] < df['htf_stoch_d']) & (df['obv'] < df['obv_sma_20'])
    
    if 'vol' in df.columns:
        df['vol_surge'] = (df['vol'] > df['vol'].shift(1)) & (df['vol'] > df['vol'].shift(2))
    else:
        df['vol_surge'] = False
    
    df['long_signal'] = (df['close'] > df['open']) & df['stoch_cross_up'].shift(1).fillna(False) & df['vol_surge'] & df['htf_long_bias']
    df['short_signal'] = (df['close'] < df['open']) & df['stoch_cross_down'].shift(1).fillna(False) & df['vol_surge'] & df['htf_short_bias']
        
    return df.dropna()
