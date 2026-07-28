def run_live_scanner_loop():
    """Runs continuously in the background, sending emails when a setup hits during market hours."""
    config_file = os.path.join(BASE_DIR, "scanner_config.json")
    if not os.path.exists(config_file):
        print("❌ Error: scanner_config.json not found.")
        return

    with open(config_file, "r") as f:
        config = json.load(f)

    token = config.get("upstox_token")
    symbols = config.get("symbols", ["NIFTY", "SENSEX"])
    gmail_user = config.get("gmail_user")
    gmail_pass = config.get("gmail_pass")
    
    # State tracker to prevent duplicate emails for the same candle signal
    last_alert_time = {sym: None for sym in symbols}

    print("=" * 60)
    print(f"🚀 LIVE BACKGROUND SCANNER ACTIVE [{datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}]")
    print("=" * 60)

    try:
        while True:
            current_time = datetime.now(IST)
            
            # --- MARKET HOURS CHECK ---
            is_weekday = current_time.weekday() <= 4 # 0=Mon, 4=Fri
            market_start = current_time.replace(hour=9, minute=15, second=0, microsecond=0)
            market_end = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            
            if not is_weekday or current_time < market_start or current_time > market_end:
                print(f"😴 Market Closed. Scanner resting... ({current_time.strftime('%H:%M:%S')} IST)")
                time.sleep(300) # Sleep for 5 minutes and check again
                continue
            # --------------------------

            print(f"\n⏰ Scan Cycle: {current_time.strftime('%H:%M:%S')} IST")

            for symbol in symbols:
                res = scan_symbol(symbol, token)
                if res and "direction" in res:
                    signal_time = res["timestamp"]
                    
                    # Only alert if this is a brand new signal timestamp
                    if signal_time != last_alert_time[symbol]:
                        last_alert_time[symbol] = signal_time
                        
                        print(f"🔥 NEW {symbol} SIGNAL DETECTED! Processing Alert...")
                        
                        subject = f"🚨 {symbol} ALERT: {res['direction']} @ {res['underlying_entry']}"
                        body = (
                            f"Live Quant Alert Triggered\n"
                            f"--------------------------\n"
                            f"Instrument : {res['symbol']}\n"
                            f"Action     : {res['direction']}\n"
                            f"Entry Px   : {res['underlying_entry']}\n"
                            f"Stop Loss  : {res['stop_loss']} (-{res['risk_pts']} pts)\n"
                            f"Target     : {res['target']} (+{res['reward_pts']} pts)\n\n"
                            f"Recommended Strike:\n{res['recommended_option']}\n\n"
                            f"Signal Time: {signal_time} IST"
                        )
                        
                        if gmail_user and gmail_pass:
                            send_email_alert(subject, body, gmail_user, gmail_pass, gmail_user)
                        else:
                            print("⚠️ Email skipped: Gmail credentials missing in Streamlit Secrets.")
                            
                    else:
                        print(f"  🟢 [{symbol}] Signal active, but alert already sent for this candle.")
                else:
                    last_px = res.get('last_price', 'N/A') if res else 'N/A'
                    print(f"  🟢 [{symbol}] Monitoring... Last Price: {last_px}")

            # Sleep for 5 minutes between checks to align with the 5-min candle chart
            time.sleep(300)

    except KeyboardInterrupt:
        print("\n🛑 Scanner stopped.")

if __name__ == "__main__":
    run_live_scanner_loop()
