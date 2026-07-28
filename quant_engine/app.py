import os
import sys
import json
import time
import subprocess
import streamlit as st

# --- Force Python to recognize quant_engine directory for module imports ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

st.set_page_config(page_title="Quant Dashboard", page_icon="📈", layout="centered")
st.title("📈 Quant Master Dashboard")
st.caption("Mobile-optimized UI: Backtesting & Live Risk-Reward Scanner")

# Explicit paths
LOG_FILE = os.path.join(BASE_DIR, "background_execution.log")
CONFIG_FILE = os.path.join(BASE_DIR, "run_config.json")
PID_FILE = os.path.join(BASE_DIR, "backtest.pid")
MAIN_SCRIPT = os.path.join(BASE_DIR, "main.py")

def is_process_running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False

def get_running_pid():
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                pid = int(f.read().strip())
                if is_process_running(pid):
                    return pid
        except Exception:
            pass
    return None

# --- SIDEBAR INPUTS ---
with st.sidebar:
    st.header("⚙️ Credentials & Parameters")
    
    try:
        default_upstox = st.secrets.get("UPSTOX_API_TOKEN", "")
        default_github = st.secrets.get("GITHUB_TOKEN", "")
        default_repo = st.secrets.get("GITHUB_REPO", "rkovath-netizen/Quant-Setup_back_test")
        
        if default_upstox and default_github:
            st.success("✅ Secure tokens loaded!")
        else:
            st.warning("⚠️ Secrets vault is empty.")
    except Exception:
        default_upstox, default_github = "", ""
        default_repo = "rkovath-netizen/Quant-Setup_back_test"
    
    upstox_token = st.text_input("Upstox Access Token", value=default_upstox, type="password")
    github_token = st.text_input("GitHub Token", value=default_github, type="password")
    github_repo = st.text_input("GitHub Repo", value=default_repo)
    
    st.divider()
    days = st.slider("Lookback Window (Days)", min_value=5, max_value=90, value=30, step=5)
    selected_symbols = st.multiselect("Select Instruments", options=["NIFTY", "SENSEX"], default=["NIFTY", "SENSEX"])

running_pid = get_running_pid()

# --- TABS CREATION ---
tab1, tab2 = st.tabs(["📊 Backtest Engine", "📡 Live Scanner"])

# --- TAB 1: BACKTESTER ---
with tab1:
    st.subheader("🚀 Backtest Execution Control")

    if running_pid:
        st.warning(f"⏳ Backtest is currently running in the background (PID: {running_pid})...")
        if st.button("🔄 Refresh Live Logs"):
            st.rerun()
    else:
        st.success("🟢 Backtest Engine Ready")
        
        if st.button("▶️ Launch Background Backtest", type="primary", use_container_width=True):
            if not upstox_token or not selected_symbols:
                st.error("Missing Token or Instruments.")
            else:
                config_data = {
                    "upstox_token": upstox_token.strip(),
                    "github_token": github_token.strip(),
                    "github_repo": github_repo.strip(),
                    "days": days,
                    "symbols": selected_symbols
                }
                with open(CONFIG_FILE, "w") as f:
                    json.dump(config_data, f, indent=4)

                with open(LOG_FILE, "w") as log_f:
                    proc = subprocess.Popen(
                        [sys.executable, MAIN_SCRIPT],
                        stdout=log_f, stderr=subprocess.STDOUT,
                        cwd=BASE_DIR, start_new_session=True
                    )
                    
                with open(PID_FILE, "w") as pid_f:
                    pid_f.write(str(proc.pid))

                st.success(f"Started background process (PID: {proc.pid})!")
                time.sleep(1)
                st.rerun()

    st.divider()
    st.subheader("📜 Execution Log Output")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()
        st.code(log_content[-4000:] if len(log_content) > 4000 else log_content, language="text")

# --- TAB 2: LIVE SCANNER ---
with tab2:
    st.subheader("📡 Real-Time Risk-Reward Scanner")
    st.caption("Filters for 1:2 RR setups aligned with 50-EMA trend.")
    
    if st.button("🔎 Run Live Scan Now", type="primary", use_container_width=True):
        if not upstox_token:
            st.error("❌ Upstox Token required in sidebar.")
        else:
            with st.spinner("Connecting to Upstox & Scanning..."):
                try:
                    from live_scanner import scan_symbol
                    
                    for sym in selected_symbols:
                        res = scan_symbol(sym, upstox_token)
                        if res and "direction" in res:
                            st.success(f"🎯 **{sym} SETUP FOUND!**")
                            st.json(res)
                        elif res:
                            st.info(f"🟢 **{sym}**: {res.get('status')} | Last Px: {res.get('last_price', 'N/A')}")
                except Exception as e:
                    st.error(f"Scanner encountered an error: {e}")
