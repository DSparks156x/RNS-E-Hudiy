#!/bin/bash
# ==============================================================================
# RNS-E Hudiy Integration - Updater Script
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
echo -e "${CYAN}${BOLD}   RNS-E Hudiy Integration - Updater Script         ${NC}"
echo -e "${CYAN}${BOLD}====================================================${NC}"

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# When invoked with sudo, HOME points at /root. Read the configuration from
# the account that launched sudo, matching install.sh's REAL_HOME behavior.
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
else
    USER_HOME="$HOME"
fi
USER_HOME="${USER_HOME:-$HOME}"

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

echo -e "${YELLOW}Waiting for GitHub connection...${NC}"
# ICMP may be blocked while HTTPS/Git traffic still works. Probe the same
# public repository used by the update instead of relying on ping.
CONFIG_FILE="$USER_HOME/config.json"
REPO_PATH=$(python3 -c "import json, os; f='$CONFIG_FILE'; r=json.load(open(f)).get('repo', 'DSparks156x/RNS-E-Hudiy') if os.path.exists(f) else 'DSparks156x/RNS-E-Hudiy'; print(r.replace('https://github.com/', '').replace('.git', ''))" 2>/dev/null || echo "DSparks156x/RNS-E-Hudiy")
REPO_URL="https://github.com/${REPO_PATH}.git"
while true; do
    if git ls-remote "$REPO_URL" HEAD >/dev/null 2>&1; then
        echo -e "${GREEN}GitHub connection established.${NC}"
        break
    else
        echo -e "${YELLOW}Waiting for GitHub access...${NC}"
        sleep 5
    fi
done

echo -e "${CYAN}Pulling latest installer...${NC}"
cd "$USER_HOME" || exit 1

# --- Smart Branch/Tag Logic ---
# Detect Repo from config if available
REPO_URL="https://github.com/${REPO_PATH}.git"
echo -e "   Using Repository: ${BLUE}$REPO_URL${NC}"

# 1. Load config branch
BRANCH=$(python3 -c "import json, os; f='$CONFIG_FILE'; print(json.load(open(f)).get('branch', 'main') if os.path.exists(f) else 'main')" 2>/dev/null) || {
    echo -e "${RED}Could not read branch from $CONFIG_FILE. Update cancelled.${NC}"
    exit 1
}
BRANCH="${BRANCH:-main}"
echo -e "   Configured Branch: ${BLUE}$BRANCH${NC}"

# 2. Smart Tag Selection Logic
# If branch is not 'main' or 'testing', look for latest tag matching 'branch-*'
if [[ "$BRANCH" != "main" && "$BRANCH" != "testing" ]]; then
    echo "   Checking for versioned tags for branch: $BRANCH..."
    # Get latest tag starting with $BRANCH- using git ls-remote
    LATEST_TAG=$(git ls-remote --tags --sort="v:refname" "$REPO_URL" "refs/tags/${BRANCH}-*" | tail -n1 | sed 's/.*refs\/tags\///')
    
    if [ ! -z "$LATEST_TAG" ]; then
        echo -e "   Found tag: ${GREEN}$LATEST_TAG${NC}. Switching to tag for update."
        SELECTED_REF="$LATEST_TAG"
    else
        # Fallback to literal branch name
        SELECTED_REF="$BRANCH"
    fi
else
    SELECTED_REF="$BRANCH"
fi

# Verify the selected reference. Never silently change a configured branch to
# main, since that can install a different release channel than requested.
if ! git ls-remote --exit-code --heads "$REPO_URL" "$SELECTED_REF" >/dev/null 2>&1 && \
   ! git ls-remote --exit-code --tags "$REPO_URL" "$SELECTED_REF" >/dev/null 2>&1; then
    echo -e "${RED}Reference $SELECTED_REF was not found on $REPO_URL. Update cancelled.${NC}"
    exit 1
fi

echo -e "Selected Update Branch/Tag: ${GREEN}$SELECTED_REF${NC}"

# Download the latest installer script from the selected branch/tag
URL="https://raw.githubusercontent.com/${REPO_PATH}/${SELECTED_REF}/install.sh"
echo -e "Fetching installer from: ${BLUE}$URL${NC}"

wget -q -O install_update.sh "$URL"
chmod +x install_update.sh

# Build install command
# Pass the original BRANCH (not the tag) to the installer so it can do its own lookup/persistence
INSTALL_CMD="sudo ./install_update.sh \"$BRANCH\""
if [ "$INSTALL_MODE" = false ]; then
    INSTALL_CMD="$INSTALL_CMD -u"
fi

# Run install script
echo -e "${CYAN}Executing installer...${NC}"
echo "n" | eval $INSTALL_CMD

# rebooting immediately causes reboot to take forever, something is taking its time. 
echo -e "${YELLOW}Update finished. Rebooting system in 10 seconds...${NC}"
sleep 10
sudo reboot now
