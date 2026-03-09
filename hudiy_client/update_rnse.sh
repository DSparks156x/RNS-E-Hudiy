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
REPO_PATH=$(python3 -c "import json, os; f=os.path.expanduser('$CONFIG_FILE'); r=json.load(open(f)).get('repo', 'DSparks156x/RNS-E-Hudiy') if os.path.exists(f) else 'DSparks156x/RNS-E-Hudiy'; print(r.replace('https://github.com/', '').replace('.git', ''))" 2>/dev/null || echo "DSparks156x/RNS-E-Hudiy")
REPO_URL="https://github.com/${REPO_PATH}.git"
echo "   Using Repository: $REPO_URL"

# 1. Load config branch
BRANCH=$(python3 -c "import json, os; f=os.path.expanduser('$CONFIG_FILE'); print(json.load(open(f)).get('branch', 'main')) if os.path.exists(f) else print('main')" 2>/dev/null || echo "main")

# 2. Smart Tag Selection Logic
# If branch is not 'main' or 'testing', look for latest tag matching 'branch-*'
if [[ "$BRANCH" != "main" && "$BRANCH" != "testing" ]]; then
    echo "   Checking for versioned tags for branch: $BRANCH..."
    # Get latest tag starting with $BRANCH- using git ls-remote
    LATEST_TAG=$(git ls-remote --tags --sort="v:refname" "$REPO_URL" "refs/tags/${BRANCH}-*" | tail -n1 | sed 's/.*refs\/tags\///')
    
    if [ ! -z "$LATEST_TAG" ]; then
        echo "   Found tag: $LATEST_TAG. Switching to tag for update."
        SELECTED_REF="$LATEST_TAG"
    else
        # Fallback to literal branch name
        SELECTED_REF="$BRANCH"
    fi
else
    SELECTED_REF="$BRANCH"
fi

# Final Reachability Check - Fallback to main if branch/tag doesn't exist
if ! git ls-remote --exit-code --heads "$REPO_URL" "$SELECTED_REF" >/dev/null 2>&1 && \
   ! git ls-remote --exit-code --tags "$REPO_URL" "$SELECTED_REF" >/dev/null 2>&1; then
    echo "   ⚠ Reference $SELECTED_REF not found on remote. Falling back to 'main'."
    BRANCH="main"
    SELECTED_REF="main"
fi

echo "Selected Update Branch/Tag: $SELECTED_REF"

# Download the latest installer script from the selected branch/tag
URL="https://raw.githubusercontent.com/${REPO_PATH}/${SELECTED_REF}/install.sh"
echo "Fetching installer from: $URL"

wget -q -O install_update.sh "$URL"
chmod +x install_update.sh

# Build install command
# Pass the original BRANCH (not the tag) to the installer so it can do its own lookup/persistence
INSTALL_CMD="sudo ./install_update.sh \"$BRANCH\""
if [ "$INSTALL_MODE" = false ]; then
    INSTALL_CMD="$INSTALL_CMD -u"
fi

# Run install script
echo "n" | eval $INSTALL_CMD

# rebooting immediately causes reboot to take forever, something is taking its time. 
sleep 10
sudo reboot now
