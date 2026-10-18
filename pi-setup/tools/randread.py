# usage: sudo python3 randread.py [BLOCKSIZE]
# Random O_DIRECT reads across the first 8 GiB of the root partition (the used part), QD1.
import os, mmap, random, time, sys
dev = "/dev/nvme0n1p2"
size = int(sys.argv[1]) if len(sys.argv) > 1 else 65536
n = 300
fd = os.open(dev, os.O_RDONLY | os.O_DIRECT)
buf = mmap.mmap(-1, size)
span = 8 * 1024**3 // size
lat = []
for _ in range(n):
    off = random.randrange(span) * size
    t = time.perf_counter()
    os.preadv(fd, [buf], off)
    lat.append((time.perf_counter() - t) * 1000)
lat.sort()
print(f"{size//1024}K random QD1: avg {sum(lat)/n:.3f} ms, p50 {lat[n//2]:.3f}, p99 {lat[int(n*.99)]:.3f}, max {lat[-1]:.3f}")
