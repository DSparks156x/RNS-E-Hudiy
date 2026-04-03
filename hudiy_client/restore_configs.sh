#!/bin/bash
# ==============================================================================
# RNS-E Hudiy Integration - Config Restore Script
# ==============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${CYAN}${BOLD}====================================================${NC}"
echo -e "${CYAN}${BOLD}   RNS-E Hudiy Integration - Config Restore Script  ${NC}"
echo -e "${CYAN}${BOLD}====================================================${NC}"

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Let the API send responses and clean up Hudiy UI
sleep 3

echo -e "${YELLOW}Waiting for Wi-Fi connection...${NC}"
while true; do
    if ping -q -c 1 -W 1 github.com >/dev/null; then
        echo -e "${GREEN}Internet connection established.${NC}"
        break
    else
        echo -e "${YELLOW}Waiting for internet...${NC}"
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
echo -e "   Using Restore Repository: ${BLUE}$REPO_URL${NC}"

BRANCH=$(python3 -c "import json, os; f=os.path.expanduser('$CONFIG_FILE'); \
conf=json.load(open(f)) if os.path.exists(f) else {}; \
print(conf.get('config_restore_branch') or conf.get('branch', 'main'))" 2>/dev/null || echo "main")

# Smart Tag Selection Logic (similar to update_rnse.sh)
if [[ "$BRANCH" != "main" && "$BRANCH" != "testing" ]]; then
    echo "   Checking for versioned tags for branch: $BRANCH..."
    LATEST_TAG=$(git ls-remote --tags --sort="v:refname" "$REPO_URL" "refs/tags/${BRANCH}-*" | tail -n1 | sed 's/.*refs\/tags\///')
    
    if [ ! -z "$LATEST_TAG" ]; then
        echo -e "   Found tag: ${GREEN}$LATEST_TAG${NC}. Switching to tag for restore."
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

echo -e "Selected Restore Branch/Tag: ${GREEN}$SELECTED_REF${NC}"

# Create temporary directory
TEMP_DIR=$(mktemp -d)
echo "Cloning repository (optimized sparse-checkout)..."
git clone -b "$SELECTED_REF" --depth 1 --filter=blob:none --sparse --no-checkout "$REPO_URL" "$TEMP_DIR"
echo -e "${CYAN}Checking out configuration files...${NC}"
cd "$TEMP_DIR" || exit 1
git sparse-checkout set config.json config/hudiy
git checkout

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
        echo -e "   ${YELLOW}Backed up $(basename "$DEST") to $BACKUP_BASE/$INCREMENT/${NC}"
    fi
}

echo -e "${CYAN}Restoring configurations...${NC}"

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
    echo -e "${CYAN}Restoring Hudiy configs...${NC}"
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

echo -e "${GREEN}Restore complete. Rebooting in 10 seconds...${NC}"
sleep 10
sudo reboot now
