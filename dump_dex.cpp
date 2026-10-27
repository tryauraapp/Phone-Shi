#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("Usage: dump_dex <pid>\n");
        return 1;
    }
    int pid = atoi(argv[1]);
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d/maps", pid);
    FILE *maps = fopen(path, "r");
    if (!maps) {
        perror("fopen maps");
        return 1;
    }

    snprintf(path, sizeof(path), "/proc/%d/mem", pid);
    int mem_fd = open(path, O_RDONLY);
    if (mem_fd < 0) {
        perror("open mem");
        fclose(maps);
        return 1;
    }

    mkdir("/data/local/tmp/dex_dumps", 0755);

    char line[512];
    int count = 0;
    while (fgets(line, sizeof(line), maps)) {
        unsigned long start, end;
        char perms[8];
        if (sscanf(line, "%lx-%lx %4s", &start, &end, perms) != 3) continue;
        if (perms[0] != 'r') continue;
        unsigned long size = end - start;
        if (size > 64 * 1024 * 1024 || size < 1024) continue;

        char *buf = (char *)malloc(size);
        if (!buf) continue;

        if (pread(mem_fd, buf, size, start) == (ssize_t)size) {
            for (unsigned long i = 0; i + 36 < size; i++) {
                if (buf[i] == 'd' && buf[i+1] == 'e' && buf[i+2] == 'x' && buf[i+3] == '\n') {
                    unsigned int dex_size = *(unsigned int *)(buf + i + 32);
                    if (dex_size > 1024 && dex_size <= 20 * 1024 * 1024 && i + dex_size <= size) {
                        // Check if FaceTec or lzQ or mbH is in it
                        bool hit = false;
                        for (unsigned long j = i; j + 6 < i + dex_size; j++) {
                            if (memcmp(buf + j, "lzQ", 3) == 0 || memcmp(buf + j, "mbH", 3) == 0 ||
                                memcmp(buf + j, "FaceTec", 7) == 0) {
                                hit = true;
                                break;
                            }
                        }
                        if (hit) {
                            char outpath[128];
                            snprintf(outpath, sizeof(outpath), "/data/local/tmp/dex_dumps/dex_%d.dex", count);
                            int out_fd = open(outpath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
                            if (out_fd >= 0) {
                                write(out_fd, buf + i, dex_size);
                                close(out_fd);
                                printf("Dumped DEX %d: size=%u to %s\n", count, dex_size, outpath);
                                count++;
                            }
                        }
                    }
                }
            }
        }
        free(buf);
    }
    close(mem_fd);
    fclose(maps);
    printf("Total DEX dumped: %d\n", count);
    return 0;
}
