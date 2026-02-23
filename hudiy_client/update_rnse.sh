#!/bin/bash
# ==============================================================================
# RNS-E Hudiy Integration - Updater Script
# ==============================================================================

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Let the API send responses and clean up Hudiy UI
sleep 3

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

# Download the latest installer script directly from the repository
wget -q -O install_update.sh https://raw.githubusercontent.com/DSparks156x/RNS-E-Hudiy/main/install.sh
chmod +x install_update.sh

# Run install script and auto-reject the reboot prompt at the end
echo "n" | sudo ./install_update.sh

#rebooting immediately causes reboot to take forever, something is taking its time. 

sleep 10
sudo reboot now