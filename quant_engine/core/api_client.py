import requests
import time

def robust_api_get(url, headers, max_retries=3, params=None):
    """Universal API caller with exponential backoff for 429 errors."""
    for attempt in range(max_retries):
        res = requests.get(url, headers=headers, params=params)
        if res.status_code == 200:
            return res
        elif res.status_code == 429:
            time.sleep(1 + attempt) 
        else:
            time.sleep(0.5)
    return res

