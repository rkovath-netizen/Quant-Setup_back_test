import os
import sys
import json
import time
import subprocess
import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

st.set_page_config(page_title="Quant Dashboard", page_icon="📈", layout="centered")
st.title("📈 Quant Master Dashboard")
st.caption("Multi-Strategy Background Engines")

# --- Process Trackers ---
LOG_BT = os.path.join(BASE_DIR, "background_execution.log")
PID_BT = os.path.join(BASE_DIR, "backtest.pid")

LOG_STOCH = os.path.join(BASE_DIR, "scanner_stoch.log")
PID_STOCH = os.path.join(BASE_DIR, "scanner_stoch.pid")

LOG_VWAP = os.path.join(BASE_DIR, "scanner_vwap.log")
PID_VWAP = os.path.join(BASE_DIR, "scanner_vwap.pid")

CONFIG_FILE = os.path.join(BASE_DIR, "scanner_config.json")

def is_running(pid_file):
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = int(f.read().strip())
                os.kill(pid, 0)
                return pid
        except Exception: pass
    return None

def kill_process(pid_file):
    pid = is_running(pid_file)
    if pid:
        try: os.kill(pid, 9)
        except Exception: pass

def start_process(script_name, log_file, pid_file):
    with open(log_file, "w") as log_f:
        proc = subprocess.Popen([sys.executable, "-u", script_name], stdout=log_f, stderr=subprocess.STDOUT, cwd=BASE_DIR, start_new_session=True)
    with open(pid_file, "w") as pid_f: pid_f.write(str(proc.pid))

# --- SECRETS ---
try:
    upstox_secret = st.secrets.get("UPSTOX_API_TOKEN", "")
    gmail_user = st.secrets.get("GMAIL_USER", "")
    gmail_pass = st.secrets.get("GMAIL_APP_PASSWORD", "")
    github_secret = st.secrets.get("GITHUB_TOKEN", "")
    github_repo = st.secrets.get("GITHUB_REPO", "")
    secrets_found = bool(upstox_secret)
except Exception:
    upstox_secret, gmail_user, gmail_pass, github_secret, github_repo = "", "", "", "", ""
    secrets_found = False

with st.sidebar:
    st.header("⚙️ System Config")
    if secrets_found: st.success("✅ Vault Active")
    else: st.error("⚠️ Vault Empty")
    selected_symbols = st.multiselect("Instruments", ["NIFTY", "SENSEX"], ["NIFTY", "SENSEX"])

    # Always keep config updated for whichever scanner starts
    if secrets_found:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"upstox_token": upstox_secret, "gmail_user": gmail_user, "gmail_pass": gmail_pass, "symbols": selected_symbols}, f)

pid_stoch = is_running(PID_STOCH)
pid_vwap = is_running(PID_VWAP)

tab1, tab2 = st.tabs(["📊 Backtester", "📡 Live Multi-Scanner"])

with tab2:
    st.subheader("📡 Multi-Strategy Alert Engine")
    if st.button("🔄 Refresh All Logs"): st.rerun()
    
    # ---- STOCHASTIC SCANNER ----
    st.markdown("### 1️⃣ Stochastic Momentum (1:2 RR)")
    if pid_stoch:
        st.success(f"✅ Running (PID: {pid_stoch})")
        if st.button("🛑 Stop Stochastic", key="stop_stoch"):
            kill_process(PID_STOCH)
            st.rerun()
    else:
        if st.button("▶️ Start Stochastic Scanner", key="start_stoch"):
            start_process("live_scanner_stoch.py", LOG_STOCH, PID_STOCH)
            st.rerun()
            
    if os.path.exists(LOG_STOCH):
        with open(LOG_STOCH, "r") as f: text = f.read()
        st.code(text[-1500:] if len(text)>1500 else text, language="text")

    st.divider()

    # ---- VWAP V2 SCANNER ----
    st.markdown("### 2️⃣ VWAP + EMA V2")
    if pid_vwap:
        st.success(f"✅ Running (PID: {pid_vwap})")
        if st.button("🛑 Stop VWAP V2", key="stop_vwap"):
            kill_process(PID_VWAP)
            st.rerun()
    else:
        if st.button("▶️ Start VWAP V2 Scanner", key="start_vwap"):
            start_process("live_scanner_vwap.py", LOG_VWAP, PID_VWAP)
            st.rerun()

    if os.path.exists(LOG_VWAP):
        with open(LOG_VWAP, "r") as f: text = f.read()
        st.code(text[-1500:] if len(text)>1500 else text, language="text")
