#include <stdint.h>
#include <stddef.h>

#define SYS_memfd_create 279
#define SYS_openat 56
#define SYS_read 63
#define SYS_write 64
#define SYS_lseek 62
#define SYS_close 57
#define SYS_exit 93

#define MFD_CLOEXEC 0x0001U
#define SEEK_SET 0
#define O_RDONLY 0

extern "C" {
int strcmp(const char *, const char *);
char *strstr(const char *, const char *);
int strlen(const char *);
}

extern "C" __attribute__((noinline, optnone))
long my_raw_syscall(long nr, long a0, long a1, long a2, long a3, long a4, long a5) {
    register long x8 __asm__("x8") = nr;
    register long x0 __asm__("x0") = a0;
    register long x1 __asm__("x1") = a1;
    register long x2 __asm__("x2") = a2;
    register long x3 __asm__("x3") = a3;
    register long x4 __asm__("x4") = a4;
    register long x5 __asm__("x5") = a5;
    __asm__ volatile(
        "svc #0"
        : "+r"(x0)
        : "r"(x8), "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x5)
        : "memory"
    );
    return x0;
}

static void print_str(const char *s) {
    long len = 0;
    while (s[len]) len++;
    my_raw_syscall(SYS_write, 1, (long)s, len, 0, 0, 0);
}

static void print_int(long v) {
    char buf[32];
    int idx = 30;
    buf[31] = 0;
    if (v == 0) { buf[idx--] = '0'; }
    else {
        long x = v < 0 ? -v : v;
        while (x > 0) {
            buf[idx--] = '0' + (x % 10);
            x /= 10;
        }
        if (v < 0) buf[idx--] = '-';
    }
    print_str(&buf[idx + 1]);
}

static bool line_has_bad_word(const char *line) {
    if (strstr(line, "magisk") || strstr(line, "zygisk") ||
        strstr(line, "debug_ramdisk") || strstr(line, "goldfish") ||
        strstr(line, "pa1q") || strstr(line, "ranchu.adb")) {
        return true;
    }
    return false;
}

static int create_clean_proc_fd(const char *path) {
    int real_fd = (int)my_raw_syscall(SYS_openat, -100 /*AT_FDCWD*/, (long)path, O_RDONLY, 0, 0, 0);
    if (real_fd < 0) return -1;

    int memfd = (int)my_raw_syscall(SYS_memfd_create, (long)"proc_clean", MFD_CLOEXEC, 0, 0, 0, 0);
    if (memfd < 0) {
        my_raw_syscall(SYS_close, real_fd, 0, 0, 0, 0, 0);
        return -1;
    }

    char in_buf[4096];
    char line[2048];
    int line_len = 0;
    long n;
    while ((n = my_raw_syscall(SYS_read, real_fd, (long)in_buf, sizeof(in_buf), 0, 0, 0)) > 0) {
        for (long i = 0; i < n; i++) {
            char c = in_buf[i];
            if (c != '\n') {
                if (line_len < (int)sizeof(line) - 1) line[line_len++] = c;
                continue;
            }
            line[line_len] = 0;
            if (!line_has_bad_word(line)) {
                line[line_len++] = '\n';
                my_raw_syscall(SYS_write, memfd, (long)line, line_len, 0, 0, 0);
            }
            line_len = 0;
        }
    }
    my_raw_syscall(SYS_close, real_fd, 0, 0, 0, 0, 0);
    my_raw_syscall(SYS_lseek, memfd, 0, SEEK_SET, 0, 0, 0);
    return memfd;
}

extern "C" void _start() {
    print_str("Testing create_clean_proc_fd on /proc/self/mounts...\n");
    int fd = create_clean_proc_fd("/proc/self/mounts");
    if (fd < 0) {
        print_str("FAILED to create clean proc fd: ");
        print_int(fd);
        print_str("\n");
        my_raw_syscall(SYS_exit, 1, 0, 0, 0, 0, 0);
    }
    print_str("SUCCESS: got memfd=");
    print_int(fd);
    print_str("\n");

    char in_buf[4096];
    char line[2048];
    int line_len = 0;
    int count = 0;
    int bad_count = 0;
    long n;
    while ((n = my_raw_syscall(SYS_read, fd, (long)in_buf, sizeof(in_buf), 0, 0, 0)) > 0) {
        for (long i = 0; i < n; i++) {
            char c = in_buf[i];
            if (c != '\n') {
                if (line_len < (int)sizeof(line) - 1) line[line_len++] = c;
                continue;
            }
            line[line_len] = 0;
            count++;
            if (line_has_bad_word(line)) {
                print_str("LEAKED BAD LINE: ");
                print_str(line);
                print_str("\n");
                bad_count++;
            }
            line_len = 0;
        }
    }
    my_raw_syscall(SYS_close, fd, 0, 0, 0, 0, 0);
    print_str("Total clean lines: ");
    print_int(count);
    print_str(", bad lines: ");
    print_int(bad_count);
    print_str("\n");

    my_raw_syscall(SYS_exit, bad_count, 0, 0, 0, 0, 0);
}
