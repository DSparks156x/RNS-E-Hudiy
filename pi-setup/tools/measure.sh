#!/bin/bash
# One-shot boot timing summary. Run after each boot (sudo needed for vclog). Uses user 1000 and nvme0n1.
echo "fw: $(sudo vclog -m | grep 'Starting OS' | tail -1)"
echo "fwdetail: $(sudo vclog -m | grep -E "BOOTMODE|AVS|dtb_file|Loaded overlay|Read command line|Device tree loaded|HAT|hat" | cut -c1-60 | tr "
" "|")"
systemd-analyze | head -1
for u in sysinit.target lightdm.service user@1000.service rnse-late.target; do printf "%s=%.2f " $u $(echo "$(systemctl show -p ActiveEnterTimestampMonotonic --value $u)/1000000" | bc -l); done; echo
T=$(getconf CLK_TCK)
L=$(pgrep -x labwc | head -1); H=$(pgrep -f 'share/hudiy$' | head -1)
echo "labwc=$(awk -v t=$T '{printf "%.2f", $22/t}' /proc/$L/stat) hudiy=$(awk -v t=$T '{printf "%.2f", $22/t}' /proc/$H/stat)"
echo "startup-log: $(tr '\n' ' ' < /run/user/1000/hudiy-startup.log)"
awk '{printf "nvme reads=%d sectors=%d MB=%.0f read_ms=%d\n",$1,$3,$3*512/1e6,$4}' /sys/block/nvme0n1/stat
echo "uptime $(cut -d' ' -f1 /proc/uptime); swap: $(cat /proc/swaps | tail -n+2)"
systemctl --failed --no-legend | head
