# --- SIDEBAR INPUTS ---
with st.sidebar:
    st.header("⚙️ Credentials & Parameters")
    
    # Securely fetch defaults from Streamlit Secrets (if they exist)
    default_upstox = st.secrets.get("UPSTOX_TOKEN", "")
    default_github = st.secrets.get("GITHUB_TOKEN", "")
    default_repo = st.secrets.get("GITHUB_REPO", "rkovath-netizen/Index_stochastic_intraday")
    
    upstox_token = st.text_input("Upstox Access Token", value=default_upstox, type="password")
    github_token = st.text_input("GitHub Token", value=default_github, type="password")
    github_repo = st.text_input("GitHub Repo", value=default_repo)
    
    st.divider()
    days = st.slider("Lookback Window (Days)", min_value=5, max_value=90, value=30, step=5)
    selected_symbols = st.multiselect("Select Instruments", options=["NIFTY", "SENSEX"], default=["NIFTY", "SENSEX"])
