#!/bin/bash
# ==============================================================================
# RNS-E Hudiy Integration - Config Restore Script
# ==============================================================================

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Let the API send responses and clean up Hudiy UI
sleep 3

echo "Waiting for Wi-Fi connection..."
while true; do
    if ping -q -c 1 -W 1 github.com >/dev/null; then
        echo "Internet connection established."
        break
    else
        echo "Waiting for internet..."
        sleep 5
    fi
done

CONFIG_FILE="$HOME/config.json"

# Detect Repo and Branch from config if available (using config_restore_ prefixed keys)
REPO_PATH=$(python3 -c "import json, os; f=os.path.expanduser('$CONFIG_FILE'); \
conf=json.load(open(f)) if os.path.exists(f) else {}; \
r=conf.get('config_restore_repo') or conf.get('repo', 'DSparks156x/RNS-E-Hudiy'); \
print(r.replace('https://github.com/', '').replace('.git', ''))" 2>/dev/null || echo "DSparks156x/RNS-E-Hudiy")

REPO_URL="https://github.com/${REPO_PATH}.git"
echo "   Using Restore Repository: $REPO_URL"

BRANCH=$(python3 -c "import json, os; f=os.path.expanduser('$CONFIG_FILE'); \
conf=json.load(open(f)) if os.path.exists(f) else {}; \
print(conf.get('config_restore_branch') or conf.get('branch', 'main'))" 2>/dev/null || echo "main")

# Smart Tag Selection Logic (similar to update_rnse.sh)
if [[ "$BRANCH" != "main" && "$BRANCH" != "testing" ]]; then
    echo "   Checking for versioned tags for branch: $BRANCH..."
    LATEST_TAG=$(git ls-remote --tags --sort="v:refname" "$REPO_URL" "refs/tags/${BRANCH}-*" | tail -n1 | sed 's/.*refs\/tags\///')
    
    if [ ! -z "$LATEST_TAG" ]; then
        echo "   Found tag: $LATEST_TAG. Switching to tag for restore."
        SELECTED_REF="$LATEST_TAG"
    else
        SELECTED_REF="$BRANCH"
    fi
else
    SELECTED_REF="$BRANCH"
fi

# Fallback check
if ! git ls-remote --exit-code --heads "$REPO_URL" "$SELECTED_REF" >/dev/null 2>&1 && \
   ! git ls-remote --exit-code --tags "$REPO_URL" "$SELECTED_REF" >/dev/null 2>&1; then
    echo "   Reference $SELECTED_REF not found. Falling back to 'main'."
    SELECTED_REF="main"
fi

echo "Selected Restore Branch/Tag: $SELECTED_REF"

# Create temporary directory
TEMP_DIR=$(mktemp -d)
echo "Cloning repository to temporary folder..."
git clone -b "$SELECTED_REF" --depth 1 "$REPO_URL" "$TEMP_DIR"

# Define backup logic (incrementing folders)
DATE_DIR=$(date +%Y-%m-%d)
BACKUP_BASE="$HOME/confbackup/$DATE_DIR"

backup_file() {
    local DEST="$1"
    if [ -f "$DEST" ]; then
        local INCREMENT=1
        while [ -d "$BACKUP_BASE/$INCREMENT" ] && [ -f "$BACKUP_BASE/$INCREMENT/$(basename "$DEST")" ]; do
            INCREMENT=$((INCREMENT + 1))
        done
        mkdir -p "$BACKUP_BASE/$INCREMENT"
        cp "$DEST" "$BACKUP_BASE/$INCREMENT/"
        echo "   Backed up $(basename "$DEST") to $BACKUP_BASE/$INCREMENT/"
    fi
}

echo "Restoring configurations..."

# Restore config.json
if [ -f "$TEMP_DIR/config.json" ]; then
    echo "Restoring config.json..."
    backup_file "$HOME/config.json"
    cp "$TEMP_DIR/config.json" "$HOME/config.json"
fi

# Restore Hudiy configs
HUDIY_CONFIG_DIR="$HOME/.hudiy/share/config"
mkdir -p "$HUDIY_CONFIG_DIR"

if [ -d "$TEMP_DIR/config/hudiy" ]; then
    echo "Restoring Hudiy configs..."
    for f in "$TEMP_DIR/config/hudiy/"*.json; do
        if [ -f "$f" ]; then
            DEST="$HUDIY_CONFIG_DIR/$(basename "$f")"
            backup_file "$DEST"
            cp "$f" "$DEST"
        fi
    done
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo "Restore complete. Rebooting in 10 seconds..."
sleep 10
sudo reboot now
