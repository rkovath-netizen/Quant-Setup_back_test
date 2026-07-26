# quant_engine/app.py

import os
import sys
import json
import time
import subprocess
import streamlit as st

st.set_page_config(page_title="Quant Backtest Launcher", page_icon="📈", layout="centered")

st.title("📈 Modular Backtest Controller")
st.caption("Mobile-optimized UI with detached background execution & automatic GitHub upload")

LOG_FILE = "background_execution.log"
CONFIG_FILE = "run_config.json"
PID_FILE = "backtest.pid"

def is_process_running(pid):
    """Checks if the detached background process is actively running."""
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

# --- SIDEBAR / INPUT CONFIGURATION ---
with st.sidebar:
    st.header("⚙️ Credentials & Parameters")
    
    upstox_token = st.text_input("Upstox Access Token", type="password", help="Enter today's active Upstox access token")
    github_token = st.text_input("GitHub Token", type="password", help="Personal Access Token with repository write permissions")
    github_repo = st.text_input("GitHub Repo", value="rkovath-netizen/Index_stochastic_intraday", help="format: owner/repository_name")
    
    st.divider()
    days = st.slider("Lookback Window (Days)", min_value=5, max_value=90, value=30, step=5)
    selected_symbols = st.multiselect("Select Instruments", options=["NIFTY", "SENSEX"], default=["NIFTY", "SENSEX"])

running_pid = get_running_pid()

# --- MAIN ACTION BUTTONS ---
st.subheader("🚀 Execution Control")

if running_pid:
    st.warning(f"⏳ Backtest is currently running in the background (PID: {running_pid})...")
    if st.button("🔄 Refresh Live Logs"):
        st.rerun()
else:
    st.success("🟢 System Ready")
    
    if st.button("▶️ Launch Background Backtest", type="primary", use_container_width=True):
        if not upstox_token:
            st.error("Please enter your Upstox Access Token in the sidebar.")
        elif not selected_symbols:
            st.error("Please select at least one instrument.")
        else:
            # 1. Write current configuration parameters
            config_data = {
                "upstox_token": upstox_token.strip(),
                "github_token": github_token.strip() if github_token else "",
                "github_repo": github_repo.strip() if github_repo else "",
                "days": days,
                "symbols": selected_symbols
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(config_data, f, indent=4)

            # 2. Launch detached background process writing output to background_execution.log
            with open(LOG_FILE, "w") as log_f:
                proc = subprocess.Popen(
                    [sys.executable, "main.py"],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    start_new_session=True  # Completely detaches process from Streamlit session
                )
                
            # 3. Store PID for process tracking
            with open(PID_FILE, "w") as pid_f:
                pid_f.write(str(proc.pid))

            st.success(f"Started background process (PID: {proc.pid})! You can safely close your phone browser.")
            time.sleep(1)
            st.rerun()

st.divider()

# --- REAL-TIME LOG MONITOR ---
st.subheader("📜 Execution Log Output")

if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
        log_content = f.read()
    
    st.code(log_content[-4000:] if len(log_content) > 4000 else log_content, language="text")
else:
    st.info("No log file found yet. Click 'Launch Background Backtest' to start.")
