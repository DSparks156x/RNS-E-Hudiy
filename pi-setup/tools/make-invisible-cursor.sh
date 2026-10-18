#!/bin/bash
# Invisible cursor theme: one 1x1 transparent Xcursor, linked under every common cursor name.
# Run as the desktop user. Enable it with XCURSOR_THEME=invisible in ~/.config/labwc/environment.
set -e
I=$HOME/.local/share/icons/invisible/cursors
mkdir -p "$I"
python3 - "$I/default" <<'EOF'
import struct, sys
# Xcursor file: one 1x1 fully transparent image, nominal size 24
w = h = 1
img = struct.pack('<IIIIIIIII', 36, 0xfffd0002, 24, 1, w, h, 0, 0, 0) + b'\0\0\0\0' * (w * h)
hdr = struct.pack('<4sIII', b'Xcur', 16, 0x10000, 1)
toc = struct.pack('<III', 0xfffd0002, 24, 16 + 12)
open(sys.argv[1], 'wb').write(hdr + toc + img)
EOF
for n in left_ptr arrow top_left_arrow pointer hand hand1 hand2 pointing_hand text xterm ibeam vertical-text \
  wait watch progress left_ptr_watch half-busy crosshair cross tcross cell move fleur grab grabbing openhand closedhand \
  all-scroll not-allowed no-drop forbidden crossed_circle help question_arrow whats_this context-menu alias copy \
  dnd-move dnd-copy dnd-link dnd-none col-resize row-resize sb_h_double_arrow sb_v_double_arrow split_h split_v \
  n-resize s-resize e-resize w-resize ne-resize nw-resize se-resize sw-resize ns-resize ew-resize nesw-resize nwse-resize \
  top_side bottom_side left_side right_side top_left_corner top_right_corner bottom_left_corner bottom_right_corner \
  size_hor size_ver size_bdiag size_fdiag size_all zoom-in zoom-out X_cursor pirate; do
  ln -sf default "$I/$n"
done
printf '[Icon Theme]\nName=invisible\nComment=Transparent cursor (boot-tuning)\n' > "$I/../index.theme"
