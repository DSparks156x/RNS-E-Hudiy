# Top 15 processes by bytes read from disk since they started. Run as root after boot.
import os
rows = []
for pid in os.listdir("/proc"):
    if not pid.isdigit():
        continue
    try:
        io = dict(l.split(": ") for l in open(f"/proc/{pid}/io").read().splitlines())
        comm = open(f"/proc/{pid}/comm").read().strip()
        cmd = open(f"/proc/{pid}/cmdline").read().replace("\0", " ")[:70]
        st = open(f"/proc/{pid}/stat").read().split(")")[-1].split()
        start = int(st[19]) / os.sysconf("SC_CLK_TCK")
        rows.append((int(io["read_bytes"]) // 1048576, int(io["rchar"]) // 1048576, start, pid, comm, cmd))
    except Exception:
        pass
print("readMB rcharMB start pid comm cmd")
for r in sorted(rows, reverse=True)[:15]:
    print(f"{r[0]:6} {r[1]:7} {r[2]:6.2f} {r[3]:>6} {r[4]:16} {r[5]}")
