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

st.set_page_config(page_title="Quant Backtest Launcher", page_icon="📈", layout="centered")

st.title("📈 Modular Backtest Controller")
st.caption("Mobile-optimized UI with detached background execution & automatic GitHub upload")

# Explicit paths inside quant_engine directory
LOG_FILE = os.path.join(BASE_DIR, "background_execution.log")
CONFIG_FILE = os.path.join(BASE_DIR, "run_config.json")
PID_FILE = os.path.join(BASE_DIR, "backtest.pid")
MAIN_SCRIPT = os.path.join(BASE_DIR, "main.py")

def is_process_running(pid):
    """Checks if the background process is actively executing."""
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
    
    upstox_token = st.text_input("Upstox Access Token", type="password")
    github_token = st.text_input("GitHub Token", type="password")
    github_repo = st.text_input("GitHub Repo", value="rkovath-netizen/Index_stochastic_intraday")
    
    st.divider()
    days = st.slider("Lookback Window (Days)", min_value=5, max_value=90, value=30, step=5)
    selected_symbols = st.multiselect("Select Instruments", options=["NIFTY", "SENSEX"], default=["NIFTY", "SENSEX"])

running_pid = get_running_pid()

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
            # Save runtime configuration
            config_data = {
                "upstox_token": upstox_token.strip(),
                "github_token": github_token.strip() if github_token else "",
                "github_repo": github_repo.strip() if github_repo else "",
                "days": days,
                "symbols": selected_symbols
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(config_data, f, indent=4)

            # Launch detached process with cwd set to quant_engine
            with open(LOG_FILE, "w") as log_f:
                proc = subprocess.Popen(
                    [sys.executable, MAIN_SCRIPT],
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    cwd=BASE_DIR,  # Run execution strictly inside quant_engine directory
                    start_new_session=True
                )
                
            with open(PID_FILE, "w") as pid_f:
                pid_f.write(str(proc.pid))

            st.success(f"Started background process (PID: {proc.pid})! You can safely close your phone browser.")
            time.sleep(1)
            st.rerun()

st.divider()
st.subheader("📜 Execution Log Output")

if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
        log_content = f.read()
    st.code(log_content[-4000:] if len(log_content) > 4000 else log_content, language="text")
else:
    st.info("No log file found yet. Click 'Launch Background Backtest' to start.")
