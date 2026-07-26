# quant_engine/core/github_client.py

import os
import requests
import base64

def upload_file_to_github(file_path, repo, path_in_repo, github_token, logger=print):
    """
    Uploads or updates a file directly in your GitHub repository via GitHub REST API.
    repo format: "owner/repository_name" (e.g. "rkovath-netizen/Index_stochastic_intraday")
    """
    if not os.path.exists(file_path):
        logger(f"⚠️ Upload failed: {file_path} does not exist.")
        return False

    url = f"https://api.github.com/repos/{repo}/contents/{path_in_repo}"
    headers = {
        "Authorization": f"token {github_token}",
        "Accept": "application/vnd.github.v3+json"
    }

    with open(file_path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    # Check if the file already exists on GitHub to obtain its SHA (required for overwrite)
    res = requests.get(url, headers=headers)
    data = {
        "message": f"Auto-upload backtest result: {os.path.basename(file_path)}",
        "content": content
    }
    
    if res.status_code == 200:
        data["sha"] = res.json()["sha"]

    put_res = requests.put(url, headers=headers, json=data)
    
    if put_res.status_code in [200, 201]:
        logger(f"✅ Successfully uploaded {path_in_repo} to GitHub.")
        return True
    else:
        logger(f"❌ GitHub API Error ({put_res.status_code}): {put_res.text}")
        return False
