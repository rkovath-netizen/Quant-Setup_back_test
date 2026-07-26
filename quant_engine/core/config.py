import pytz

IST = pytz.timezone('Asia/Kolkata')

TIMEFRAME_COMBOS = [
    ('3min', '15min'),
    ('5min', '30min'),
    ('10min', '60min')
]

INDEX_CONFIG = {
    "NIFTY": {"underlying": "NSE_INDEX|Nifty 50", "step": 50, "segment": "NSE_FO"},
    "SENSEX": {"underlying": "BSE_INDEX|SENSEX", "step": 100, "segment": "BSE_FO"}
}

