import pytz

IST = pytz.timezone('Asia/Kolkata')

TIMEFRAME_COMBOS = [
    ('3min', '15min'),
    ('5min', '30min'),
    ('10min', '60min')
]

# Explicitly maps indices to their respective segments, step sizes, and current SEBI-mandated lot sizes
INDEX_CONFIG = {
    "NIFTY": {"underlying": "NSE_INDEX|Nifty 50", "step": 50, "segment": "NSE_FO", "lot_size": 65},
    "SENSEX": {"underlying": "BSE_INDEX|SENSEX", "step": 100, "segment": "BSE_FO", "lot_size": 20}
}
