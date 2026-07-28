import os
import sys
import json
import time
import subprocess
import streamlit as st

# --- Paths ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

st.set_page_config(page_title="Quant Dashboard", page_icon="📈", layout="centered")
st.title("📈 Quant Master Dashboard")
st.caption("Background Engines: Backtesting & Live Email Alerts")

# Background Engine Paths
LOG_FILE_BT = os.path.join(BASE_DIR, "background_execution.log")
PID_FILE_BT = os.path.join(BASE_DIR, "backtest.pid")

LOG_FILE_SCAN = os.path.join(BASE_DIR, "scanner_execution.log")
PID_FILE_SCAN = os.path.join(BASE_DIR, "scanner.pid")
CONFIG_FILE_SCAN = os.path.join(BASE_DIR, "scanner_config.json")

def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False

def get_running_pid(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
                if is_process_running(pid): return pid
        except Exception: pass
    return None

# --- SECRETS MANAGEMENT ---
try:
    upstox_secret = st.secrets.get("UPSTOX_API_TOKEN", "")
    gmail_user_secret = st.secrets.get("GMAIL_USER", "")
    gmail_pass_secret = st.secrets.get("GMAIL_APP_PASSWORD", "")
    github_secret = st.secrets.get("GITHUB_TOKEN", "")
    github_repo_secret = st.secrets.get("GITHUB_REPO", "rkovath-netizen/Quant-Setup_back_test")
    secrets_found = bool(upstox_secret)
except Exception:
    upstox_secret, gmail_user_secret, gmail_pass_secret, github_secret = "", "", "", ""
    github_repo_secret = "rkovath-netizen/Quant-Setup_back_test"
    secrets_found = False

with st.sidebar:
    st.header("⚙️ System Status")
    if secrets_found:
        st.success("✅ Secure Vault Linked. API & Email credentials loaded.")
    else:
        st.error("⚠️ Streamlit Secrets empty. The system will fail without them.")
    
    st.divider()
    days = st.slider("Backtest Window (Days)", min_value=5, max_value=90, value=30, step=5)
    selected_symbols = st.multiselect("Select Instruments", options=["NIFTY", "SENSEX"], default=["NIFTY", "SENSEX"])

pid_bt = get_running_pid(PID_FILE_BT)
pid_scan = get_running_pid(PID_FILE_SCAN)

# --- DASHBOARD TABS ---
tab1, tab2 = st.tabs(["📊 Backtest Engine", "📡 Live Email Scanner"])

with tab1:
    st.subheader("🚀 Backtest Execution")
    if pid_bt:
        st.warning(f"⏳ Backtester running (PID: {pid_bt})...")
        if st.button("🔄 Refresh Backtest Logs"): st.rerun()
    else:
        if st.button("▶️ Launch Backtest Background Job", type="primary", use_container_width=True):
            config_data = {
                "upstox_token": upstox_secret, "github_token": github_secret,
                "github_repo": github_repo_secret, "days": days, "symbols": selected_symbols
            }
            with open(os.path.join(BASE_DIR, "run_config.json"), "w") as f: json.dump(config_data, f)
            with open(LOG_FILE_BT, "w") as log_f:
                proc = subprocess.Popen([sys.executable, "main.py"], stdout=log_f, stderr=subprocess.STDOUT, cwd=BASE_DIR, start_new_session=True)
            with open(PID_FILE_BT, "w") as pid_f: pid_f.write(str(proc.pid))
            st.success("Started! You can close your phone.")
            time.sleep(1)
            st.rerun()

    if os.path.exists(LOG_FILE_BT):
        with open(LOG_FILE_BT, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()
        st.code(log_content[-2000:] if len(log_content) > 2000 else log_content, language="text")

with tab2:
    st.subheader("📡 Live Alert Engine")
    st.caption("Scans every 5 minutes and emails you high-probability setups.")
    
    if pid_scan:
        st.warning(f"📡 Scanner actively hunting in background (PID: {pid_scan}). Alerts will be emailed.")
        if st.button("🛑 Stop Live Scanner", type="secondary"):
            try:
                os.kill(pid_scan, 9)
                st.success("Scanner terminated.")
                time.sleep(1)
                st.rerun()
            except Exception: pass
            
        if st.button("🔄 Refresh Scanner Logs"): st.rerun()
    else:
        if st.button("▶️ Start Live Scanner (Emails ON)", type="primary", use_container_width=True):
            if not gmail_pass_secret or not upstox_secret:
                st.error("Missing Gmail or Upstox keys in Secrets.")
            else:
                config_data = {
                    "upstox_token": upstox_secret,
                    "gmail_user": gmail_user_secret,
                    "gmail_pass": gmail_pass_secret,
                    "symbols": selected_symbols
                }
                with open(CONFIG_FILE_SCAN, "w") as f: json.dump(config_data, f)
                with open(LOG_FILE_SCAN, "w") as log_f:
                    proc = subprocess.Popen([sys.executable, "live_scanner.py"], stdout=log_f, stderr=subprocess.STDOUT, cwd=BASE_DIR, start_new_session=True)
                with open(PID_FILE_SCAN, "w") as pid_f: pid_f.write(str(proc.pid))
                st.success("Scanner deployed! Waiting for signals...")
                time.sleep(1)
                st.rerun()

    if os.path.exists(LOG_FILE_SCAN):
        with open(LOG_FILE_SCAN, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()
        st.code(log_content[-2000:] if len(log_content) > 2000 else log_content, language="text")
