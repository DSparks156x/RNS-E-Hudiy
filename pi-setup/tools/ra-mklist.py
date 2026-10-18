#!/usr/bin/python3
"""Build /etc/boottuning/readahead.list from a boot trace of
filemap:mm_filemap_add_to_page_cache (kernel cmdline trace_event=...).

usage: ra-mklist.py TRACE OUT [--until SECONDS] [--gap KB] [--order first|disk]
List format: one line per range, "offset length path" (bytes), in read order.
"""
import argparse, collections, os, re, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument("trace"); ap.add_argument("out")
ap.add_argument("--until", type=float, default=15.0)
ap.add_argument("--gap", type=int, default=64, help="merge ranges closer than this (KB)")
ap.add_argument("--order", choices=["first", "disk"], default="first")
ap.add_argument("--whole", action="store_true", help="whole files instead of ranges")
a = ap.parse_args()

rx = re.compile(r"^\s*(.+?)-(\d+)\s+\[\d+\].*?\s([\d.]+): mm_filemap_add_to_page_cache: dev (\d+):(\d+) ino ([0-9a-f]+) pfn=\S+ ofs=(\d+) order=(\d+)")
root = os.stat("/")
rmaj, rmin = os.major(root.st_dev), os.minor(root.st_dev)
psz = os.sysconf("SC_PAGE_SIZE")
first = {}                          # ino -> first time
pages = collections.defaultdict(set)  # ino -> page indices
comm = {}
n = late = 0
for line in open(a.trace, errors="replace"):
    m = rx.match(line)
    if not m:
        continue
    t = float(m.group(3))
    if int(m.group(4)) != rmaj or int(m.group(5)) != rmin:
        continue
    n += 1
    if t > a.until:
        late += 1
        continue
    ino = int(m.group(6), 16); ofs = int(m.group(7)); order = int(m.group(8))
    first.setdefault(ino, t); comm.setdefault(ino, m.group(1))
    p0 = ofs // psz
    pages[ino].update(range(p0, p0 + (1 << order)))
print(f"events on root: {n}, after {a.until}s: {late}, inodes: {len(first)}", file=sys.stderr)

# inode -> path (root fs only)
want = set(first); path = {}
for d, dirs, files in os.walk("/", topdown=True):
    try:
        if os.lstat(d).st_dev != root.st_dev:
            dirs[:] = []; continue
    except OSError:
        continue
    for f in files:
        p = os.path.join(d, f)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if st.st_ino in want and st.st_dev == root.st_dev and st.st_ino not in path:
            path[st.st_ino] = (p, st.st_size)
missing = [i for i in want if i not in path]
print(f"resolved {len(path)}, unresolved {len(missing)} (dirs/deleted/metadata), "
      f"unresolved MB {sum(len(pages[i]) for i in missing)*psz/1e6:.1f}", file=sys.stderr)

def phys(p):
    try:
        o = subprocess.run(["filefrag", "-e", p], capture_output=True, text=True).stdout
        m = re.search(r"^\s*0:\s+\d+\.\.\s*\d+:\s+(\d+)\.\.", o, re.M)
        return int(m.group(1)) if m else 1 << 62
    except Exception:
        return 1 << 62

entries = []
gap = a.gap * 1024 // psz
for ino in sorted(path, key=lambda i: first[i]):
    p, size = path[ino]
    if a.whole:
        entries.append((first[ino], p, [(0, size)]))
        continue
    idx = sorted(pages[ino]); rs = []
    s = e = idx[0]
    for i in idx[1:]:
        if i - e > gap:
            rs.append((s, e)); s = i
        e = i
    rs.append((s, e))
    rr = [(s * psz, min((e + 1) * psz, size) - s * psz) for s, e in rs]
    rr = [(o, l) for o, l in rr if l > 0]
    if rr:
        entries.append((first[ino], p, rr))
if a.order == "disk":
    entries.sort(key=lambda x: phys(x[1]))
tot = 0
with open(a.out, "w") as f:
    for t, p, rr in entries:
        for o, l in rr:
            f.write(f"{o} {l} {p}\n"); tot += l
print(f"wrote {a.out}: {len(entries)} files, {tot/1e6:.1f} MB", file=sys.stderr)
