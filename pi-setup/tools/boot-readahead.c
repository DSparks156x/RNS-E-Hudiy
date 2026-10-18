/* Boot readahead: read the ranges in a list into the page cache.
 * usage: boot-readahead LIST [THREADS]
 * LIST lines: "offset length path". Ranges are handed out in list order
 * to THREADS workers that pread() them in 1 MiB chunks. */
#define _GNU_SOURCE
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

struct ent { long long off, len; char *path; };
static struct ent *ents; static int nents, next;
static long long total;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
#define CHUNK (1 << 20)

static void *worker(void *arg) {
    char *buf = malloc(CHUNK); long long got = 0;
    (void)arg;
    for (;;) {
        pthread_mutex_lock(&mu); int i = next++; pthread_mutex_unlock(&mu);
        if (i >= nents) break;
        int fd = open(ents[i].path, O_RDONLY | O_NOATIME | O_CLOEXEC);
        if (fd < 0) fd = open(ents[i].path, O_RDONLY | O_CLOEXEC);
        if (fd < 0) continue;
        long long o = ents[i].off, end = o + ents[i].len;
        while (o < end) {
            size_t n = end - o > CHUNK ? CHUNK : end - o;
            ssize_t r = pread(fd, buf, n, o);
            if (r <= 0) break;
            o += r; got += r;
        }
        close(fd);
    }
    pthread_mutex_lock(&mu); total += got; pthread_mutex_unlock(&mu);
    free(buf); return NULL;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s LIST [THREADS]\n", argv[0]); return 2; }
    int nt = argc > 2 ? atoi(argv[2]) : 4;
    FILE *f = fopen(argv[1], "r"); if (!f) { perror(argv[1]); return 1; }
    int cap = 4096; ents = malloc(cap * sizeof *ents);
    char *line = NULL; size_t lc = 0; ssize_t ll;
    while ((ll = getline(&line, &lc, f)) > 0) {
        if (line[ll - 1] == '\n') line[--ll] = 0;
        long long off, len; int pos;
        if (sscanf(line, "%lld %lld %n", &off, &len, &pos) != 2) continue;
        if (nents == cap) ents = realloc(ents, (cap *= 2) * sizeof *ents);
        ents[nents++] = (struct ent){off, len, strdup(line + pos)};
    }
    fclose(f);
    struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
    pthread_t th[64]; if (nt < 1) nt = 1; if (nt > 64) nt = 64;
    for (int i = 0; i < nt; i++) pthread_create(&th[i], NULL, worker, NULL);
    for (int i = 0; i < nt; i++) pthread_join(th[i], NULL);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    printf("boot-readahead: %d ranges, %.1f MB in %.2f s (started at %.2f s), %d threads\n",
           nents, total / 1e6, (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9,
           t0.tv_sec + t0.tv_nsec / 1e9, nt);
    return 0;
}
