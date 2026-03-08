#!/bin/bash
# ==============================================================================
# RNS-E Hudiy Integration - Updater Script
# ==============================================================================

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Let the API send responses and clean up Hudiy UI
sleep 3

# --- Flag Parsing ---
INSTALL_MODE=false
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -i|--install) INSTALL_MODE=true; shift ;;
        *) shift ;;
    esac
done

echo "Waiting for Wi-Fi connection..."
# Loop until we have internet connectivity (e.g. connected to Hotspot)
while true; do
    if ping -q -c 1 -W 1 github.com >/dev/null; then
        echo "Internet connection established."
        break
    else
        echo "Waiting for internet..."
        sleep 5
    fi
done

echo "Pulling latest installer..."
cd ~

# --- Smart Branch/Tag Logic ---
CONFIG_FILE="$HOME/config.json"
# Detect Repo from config if available
REPO=$(python3 -c "import json, os; f=os.path.expanduser('$CONFIG_FILE'); print(json.load(open(f)).get('repo', 'DSparks156x/RNS-E-Hudiy')) if os.path.exists(f) else print('DSparks156x/RNS-E-Hudiy')" 2>/dev/null || echo "DSparks156x/RNS-E-Hudiy")
echo "   Using Repository: $REPO"

# Use Python to handle JSON, GitHub API tag listing, and date comparisons
BRANCH=$(python3 <<EOF
import json
import urllib.request
import os
from datetime import datetime

def request_github(url):
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'RNS-E-Hudiy-Updater')
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

def get_commit_date(ref):
    data = request_github(f"https://api.github.com/repos/{REPO}/commits/{ref}")
    if data:
        try:
            date_str = data['commit']['committer']['date']
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        except: pass
    return None

def find_latest_ref(prefix):
    """Finds the latest tag starting with prefix, or the literal prefix branch/tag."""
    tags_data = request_github(f"https://api.github.com/repos/{REPO}/tags") or []
    candidate_refs = [t['name'] for t in tags_data if t['name'].startswith(prefix)]
    
    # Also consider the literal prefix as a branch/tag (e.g., 'beta' or 'release')
    candidate_refs.append(prefix)
    
    latest_ref = prefix
    latest_date = datetime.min
    
    for ref in set(candidate_refs):
        date = get_commit_date(ref)
        if date and date > latest_date:
            latest_date = date
            latest_ref = ref
            
    return latest_ref, latest_date

# 1. Load config
config_branch = "release" # Default to release
if os.path.exists("$CONFIG_FILE"):
    try:
        with open("$CONFIG_FILE", 'r') as f:
            config_branch = json.load(f).get('branch', 'release')
    except: pass

# 2. Handle "testing" (always main)
if config_branch == "testing":
    print("main")
    exit()

# 3. Smart Logic for "beta" or "release"
if config_branch == "beta":
    # Find latest beta and latest release
    final_beta_ref, beta_date = find_latest_ref("beta")
    final_release_ref, release_date = find_latest_ref("release")
    
    # If release is newer than beta, upgrade to release
    if release_date > beta_date:
        print(final_release_ref)
    else:
        print(final_beta_ref)
    exit()

if config_branch == "release":
    # Just find the latest release tag/branch
    final_release_ref, _ = find_latest_ref("release")
    print(final_release_ref)
    exit()

# 4. Fallback/Default
print(config_branch)
EOF
)

echo "Selected Update Branch/Tag: $BRANCH"

# Map "testing" to "main" for the URL if it wasn't caught
TARGET_BRANCH=$BRANCH
[ "$BRANCH" == "testing" ] && TARGET_BRANCH="main"

# Download the latest installer script from the selected branch/tag
URL="https://raw.githubusercontent.com/${REPO}/${TARGET_BRANCH}/install.sh"
echo "Fetching installer from: $URL"

wget -q -O install_update.sh "$URL"
chmod +x install_update.sh

# Build install command
INSTALL_CMD="sudo ./install_update.sh \"$BRANCH\""
if [ "$INSTALL_MODE" = false ]; then
    INSTALL_CMD="$INSTALL_CMD -u"
fi

# Run install script
echo "n" | eval $INSTALL_CMD

#rebooting immediately causes reboot to take forever, something is taking its time. 

sleep 10
sudo reboot now