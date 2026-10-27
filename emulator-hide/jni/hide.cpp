// Per-app emulator-trace hider (Zygisk module).
//
// Loads ONLY inside target app processes (matched by process/package name) and:
// 1. PLT-hooks the libc calls apps use to probe for QEMU/goldfish artifacts.
// 2. Installs a Seccomp-BPF trap-and-emulate filter to catch raw inline 'svc #0'
//    syscalls (SYS_newfstatat, SYS_statx, SYS_faccessat, SYS_faccessat2,
//    SYS_readlinkat, SYS_openat) emitted directly from anti-tamper native SDKs
//    that deliberately bypass libc.
//
// KEY CONSTRAINT: the guest GPU encoder (libOpenglSystemCommon / libGLESv2_enc)
// inside every app process open()s /dev/goldfish_pipe_dprctd to reach the host
// renderer. Blocking open() of goldfish ⇒ black screen (proven on this device).
// So goldfish is hidden only from EXISTENCE checks (access/stat/faccessat/readdir/
// inline svc), never from open(). The classic qemu artifacts the app never opens
// for rendering (qemu_pipe, qemud, qemu_trace, libc_malloc_debug_qemu) are hidden
// from open() too.

#include <stdint.h>
#include <stddef.h>

// bionic LP64 types used by zygisk.hpp (64-bit; matches Magisk's side ABI).
typedef unsigned long dev_t;
typedef unsigned long ino_t;

#include "jni.h"
#include "zygisk.hpp"

using zygisk::Api;
using zygisk::AppSpecializeArgs;
using zygisk::Option;

typedef unsigned long __u64;
typedef uint32_t __u32;
typedef uint16_t __u16;
typedef uint8_t  __u8;

// ---- Linux/Bionic aarch64 signal & ucontext definitions -----------------------
struct siginfo_t {
    int si_signo;
    int si_errno;
    int si_code;
    int _pad[29]; // bionic siginfo is 128 bytes
};

struct sigcontext {
    __u64 fault_address;
    __u64 regs[31]; // X0-X30
    __u64 sp;
    __u64 pc;
    __u64 pstate;
    __u8 __reserved[4096] __attribute__((__aligned__(16)));
};

struct ucontext_t {
    unsigned long uc_flags;
    struct ucontext_t *uc_link;
    void *ss_sp;
    int ss_flags;
    size_t ss_size;
    unsigned long uc_sigmask;
    char __padding[120];
    struct sigcontext uc_mcontext;
};

struct sigaction_t {
    unsigned int sa_flags;
    void (*sa_sigaction)(int, siginfo_t *, void *);
    unsigned long sa_mask;
    void (*sa_restorer)(void);
};

// ---- Seccomp-BPF definitions --------------------------------------------------
#define AUDIT_ARCH_AARCH64 0xC00000B7

#define BPF_LD   0x00
#define BPF_W    0x00
#define BPF_ABS  0x20
#define BPF_JMP  0x05
#define BPF_JEQ  0x10
#define BPF_JGE  0x30
#define BPF_K    0x00
#define BPF_RET  0x06

#define BPF_STMT(code, k) { (uint16_t)(code), 0, 0, (uint32_t)(k) }
#define BPF_JUMP(code, k, jt, jf) { (uint16_t)(code), (uint8_t)(jt), (uint8_t)(jf), (uint32_t)(k) }

#define SECCOMP_RET_TRAP  0x00030000U
#define SECCOMP_RET_ALLOW 0x7fff0000U

#define PR_SET_NO_NEW_PRIVS 38
#define PR_SET_SECCOMP      22
#define SECCOMP_MODE_FILTER 2

struct sock_filter {
    uint16_t code;
    uint8_t  jt;
    uint8_t  jf;
    uint32_t k;
};

struct sock_fprog {
    unsigned short len;
    struct sock_filter *filter;
};

// arm64 syscall numbers
#define SYS_fstatfs     44
#define SYS_faccessat   48
#define SYS_openat      56
#define SYS_readlinkat  78
#define SYS_newfstatat  79
#define SYS_fstat       80
#define SYS_userfaultfd 282
#define SYS_statx       291
#define SYS_openat2     437
#define SYS_faccessat2  439

#define SYS_memfd_create 279
#define MFD_CLOEXEC      0x0001U
#define SEEK_SET         0

// ---- libc we call directly (resolved from the device's libc at runtime) -------
extern "C" {
int   openat(int, const char *, int, ...);
long  read(int, void *, unsigned long);
int   close(int);
unsigned long strlen(const char *);
int   strncmp(const char *, const char *, unsigned long);
int   strcmp(const char *, const char *);
char *strstr(const char *, const char *);
int  *__errno(void);
int   __system_property_get(const char *, char *);
int   __android_log_print(int, const char *, const char *, ...);
int   prctl(int, ...);
long  syscall(long, ...);
int   sigaction(int, const struct sigaction_t *, struct sigaction_t *);
int   kill(int, int);
}

#define ENOENT 2
#define O_RDONLY 0
#define ALOG(...) __android_log_print(4 /*INFO*/, "EmuHide", __VA_ARGS__)

// ---- path classification ------------------------------------------------------
static bool contains(const char *h, const char *n) { return h && strstr(h, n); }

static bool is_root_or_tamper_artifact(const char *p) {
    if (!p) return false;
    if (contains(p, "/bin/su") || contains(p, "/xbin/su") ||
        contains(p, "/sbin/su") || contains(p, "local/tmp/su") ||
        contains(p, "system/su") || contains(p, "system_ext/bin/su") ||
        strcmp(p, "su") == 0) return true;
    if (contains(p, "magisk") || contains(p, "magiskpolicy") ||
        contains(p, "/data/adb") || contains(p, "debug_ramdisk")) return true;
    if (contains(p, "Superuser") || contains(p, "busybox") ||
        contains(p, "daemonsu")) return true;
    if (contains(p, "trace_marker") || contains(p, "userfaultfd") ||
        contains(p, "selinux/policy")) return true;
    return false;
}

// Hidden from existence checks (access/stat/faccessat/lstat/fstatat/statx/inline svc)
// and from /dev enumeration. Includes goldfish (the user's EACCES≠ENOENT concern).
static bool deny_exists(const char *p) {
    if (!p) return false;
    return contains(p, "goldfish") || contains(p, "qemu_pipe") ||
           contains(p, "/dev/qemu") || contains(p, "qemud") ||
           contains(p, "qemu_trace") || contains(p, "libc_malloc_debug_qemu") ||
           // Targeted ranchu CONFIG files only — never the bare "ranchu" substring,
           // which would also hide the app's own graphics mapper .so and break GPU.
           contains(p, "fstab.ranchu") || contains(p, "init.ranchu") ||
           contains(p, "ranchu.rc") || is_root_or_tamper_artifact(p);
}

// Hidden from open()/openat() too — artifacts the app never opens for rendering.
// Deliberately EXCLUDES "goldfish": the GPU encoder must be able to open it.
static bool deny_open(const char *p) {
    if (!p) return false;
    return contains(p, "qemu_pipe") || contains(p, "/dev/qemu") ||
           contains(p, "qemud") || contains(p, "qemu_trace") ||
           contains(p, "libc_malloc_debug_qemu") || is_root_or_tamper_artifact(p);
}

// Directory-entry names to drop from readdir() of /dev etc.
static bool hide_dirent(const char *name) {
    if (!name) return false;
    return contains(name, "goldfish") || contains(name, "qemu") ||
           contains(name, "qemud") || contains(name, "magisk") ||
           strcmp(name, "su") == 0;
}

// Optional per-app property spoofs (belt-and-suspenders; the system already
// resetprops these globally). Returns spoof value or nullptr.
static const char *prop_spoof(const char *name) {
    struct { const char *k, *v; } map[] = {
        {"ro.kernel.qemu", "0"}, {"ro.boot.qemu", "0"},
        {"ro.hardware.egl", "adreno"}, {"ro.hardware.gralloc", "default"},
        {"ro.boot.hardware", "pa1q"},
        {"ro.boot.flash.locked", "1"}, {"ro.boot.verifiedbootstate", "green"},
        {"ro.boot.vbmeta.device_state", "locked"},
        {"ro.build.type", "user"}, {"ro.build.tags", "release-keys"},
        {"ro.debuggable", "0"}, {"ro.secure", "1"},
    };
    for (auto &e : map) {
        unsigned long n = strlen(e.k);
        if (strncmp(name, e.k, n) == 0 && name[n] == 0) return e.v;
    }
    return nullptr;
}

static void set_enoent() { *__errno() = ENOENT; }
// DIAGNOSTIC: log each hide so interception can be proven from logcat.
static void hid(const char *call, const char *path) { ALOG("hid %s(%s) -> ENOENT", call, path); }

// Safely inspect userspace string pointers passed in registers.
static bool safe_copy_str(const char *src, char *dst, size_t max_len) {
    if (!src || (uintptr_t)src < 0x10000 || (uintptr_t)src >= 0x800000000000ULL) {
        return false;
    }
    size_t i = 0;
    while (i < max_len - 1) {
        char c = src[i];
        dst[i] = c;
        if (c == '\0') return true;
        i++;
    }
    dst[max_len - 1] = '\0';
    return true;
}

// Raw syscall invocation stub
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

static bool line_has_bad_word(const char *line) {
    if (!line) return false;
    return strstr(line, "magisk") || strstr(line, "zygisk") ||
           strstr(line, "debug_ramdisk") || strstr(line, "goldfish") ||
           strstr(line, "pa1q") || strstr(line, "ranchu.adb");
}

static bool should_clean_proc(const char *p) {
    if (!p) return false;
    if (contains(p, "mounts") || contains(p, "mountinfo") || contains(p, "mountstats")) return true;
    if (contains(p, "net/unix")) return true;
    if (contains(p, "proc/version") || strcmp(p, "/proc/version") == 0) return true;
    return false;
}

static int create_clean_proc_fd(const char *path) {
    if (contains(path, "version")) {
        int memfd = (int)my_raw_syscall(SYS_memfd_create, (long)"proc_version", MFD_CLOEXEC, 0, 0, 0, 0);
        if (memfd >= 0) {
            const char *ver = "Linux version 6.6.53-android15-8-g50e68f3a39e8 (build-user@build-host) (Android (11904791, based on r522817) clang version 18.0.1) #1 SMP PREEMPT Wed Aug 28 17:34:02 UTC 2024\n";
            unsigned long len = strlen(ver);
            my_raw_syscall(64 /*SYS_write*/, memfd, (long)ver, len, 0, 0, 0);
            my_raw_syscall(62 /*SYS_lseek*/, memfd, 0, SEEK_SET, 0, 0, 0);
            return memfd;
        }
    }

    const char *target = path;
    if (contains(path, "mountinfo")) target = "/proc/self/mountinfo";
    else if (contains(path, "mountstats")) target = "/proc/self/mountstats";
    else if (contains(path, "mounts")) target = "/proc/self/mounts";
    else if (contains(path, "net/unix")) target = "/proc/net/unix";

    int real_fd = (int)my_raw_syscall(SYS_openat, -100 /*AT_FDCWD*/, (long)target, O_RDONLY, 0, 0, 0);
    if (real_fd < 0) return -1;

    int memfd = (int)my_raw_syscall(SYS_memfd_create, (long)"proc_clean", MFD_CLOEXEC, 0, 0, 0, 0);
    if (memfd < 0) {
        close(real_fd);
        return -1;
    }

    char in_buf[4096];
    char line[2048];
    int line_len = 0;
    long n;
    while ((n = my_raw_syscall(63 /*SYS_read*/, real_fd, (long)in_buf, sizeof(in_buf), 0, 0, 0)) > 0) {
        for (long i = 0; i < n; i++) {
            char c = in_buf[i];
            if (c != '\n') {
                if (line_len < (int)sizeof(line) - 1) line[line_len++] = c;
                continue;
            }
            line[line_len] = 0;
            if (!line_has_bad_word(line)) {
                line[line_len++] = '\n';
                my_raw_syscall(64 /*SYS_write*/, memfd, (long)line, line_len, 0, 0, 0);
            }
            line_len = 0;
        }
    }
    close(real_fd);
    my_raw_syscall(62 /*SYS_lseek*/, memfd, 0, SEEK_SET, 0, 0, 0);
    return memfd;
}

// ---- hooks --------------------------------------------------------------------
static int (*orig_openat)(int, const char *, int, ...);
static int my_openat(int dirfd, const char *path, int flags, int mode) {
    if (deny_open(path)) { hid("openat", path); set_enoent(); return -1; }
    if (should_clean_proc(path)) {
        int cfd = create_clean_proc_fd(path);
        if (cfd >= 0) { ALOG("openat/clean_proc(%s) -> fd %d", path, cfd); return cfd; }
    }
    return orig_openat(dirfd, path, flags, mode);
}

static int (*orig_open)(const char *, int, ...);
static int my_open(const char *path, int flags, int mode) {
    if (deny_open(path)) { hid("open", path); set_enoent(); return -1; }
    if (should_clean_proc(path)) {
        int cfd = create_clean_proc_fd(path);
        if (cfd >= 0) { ALOG("open/clean_proc(%s) -> fd %d", path, cfd); return cfd; }
    }
    return orig_open(path, flags, mode);
}

static int (*orig_access)(const char *, int);
static int my_access(const char *path, int mode) {
    if (deny_exists(path)) { hid("access", path); set_enoent(); return -1; }
    return orig_access(path, mode);
}

static int (*orig_faccessat)(int, const char *, int, int);
static int my_faccessat(int dirfd, const char *path, int mode, int flags) {
    if (deny_exists(path)) { hid("faccessat", path); set_enoent(); return -1; }
    return orig_faccessat(dirfd, path, mode, flags);
}

static int (*orig_stat)(const char *, void *);
static int my_stat(const char *path, void *buf) {
    if (deny_exists(path)) { hid("stat", path); set_enoent(); return -1; }
    return orig_stat(path, buf);
}

static int (*orig_lstat)(const char *, void *);
static int my_lstat(const char *path, void *buf) {
    if (deny_exists(path)) { hid("lstat", path); set_enoent(); return -1; }
    return orig_lstat(path, buf);
}

struct bionic_stat {
    unsigned long   st_dev;
    unsigned long   st_ino;
    unsigned int    st_mode;
    unsigned int    st_nlink;
    unsigned int    st_uid;
    unsigned int    st_gid;
    unsigned long   st_rdev;
    unsigned long   __pad1;
    long            st_size;
    int             st_blksize;
    int             __pad2;
    long            st_blocks;
    long            st_atime;
    unsigned long   st_atime_nsec;
    long            st_mtime;
    unsigned long   st_mtime_nsec;
    long            st_ctime;
    unsigned long   st_ctime_nsec;
};

static void fake_fstat(long fd, void *buf) {
    if (!buf) return;
    auto *st = (struct bionic_stat *)buf;
    for (size_t i = 0; i < sizeof(struct bionic_stat); i++) ((char *)buf)[i] = 0;

    char fd_path[64];
    fd_path[0] = '/'; fd_path[1] = 'p'; fd_path[2] = 'r'; fd_path[3] = 'o'; fd_path[4] = 'c';
    fd_path[5] = '/'; fd_path[6] = 's'; fd_path[7] = 'e'; fd_path[8] = 'l'; fd_path[9] = 'f';
    fd_path[10] = '/'; fd_path[11] = 'f'; fd_path[12] = 'd'; fd_path[13] = '/';
    int idx = 14;
    long temp = fd;
    if (temp <= 0) {
        fd_path[idx++] = '0';
    } else {
        char num[16];
        int nidx = 0;
        while (temp > 0) { num[nidx++] = '0' + (temp % 10); temp /= 10; }
        while (nidx > 0) { fd_path[idx++] = num[--nidx]; }
    }
    fd_path[idx] = 0;

    char link_target[256];
    long len = my_raw_syscall(SYS_readlinkat, -100 /*AT_FDCWD*/, (long)fd_path, (long)link_target, sizeof(link_target) - 1, 0, 0);
    if (len > 0) link_target[len] = 0; else link_target[0] = 0;

    if (contains(link_target, "trace_marker")) {
        st->st_mode = 0020222; // S_IFCHR | 0222
        st->st_ino = 3082;
    } else if (contains(link_target, "userfaultfd")) {
        st->st_mode = 0020600; // S_IFCHR | 0600
        st->st_ino = 1000;
    } else {
        st->st_mode = 0100644; // S_IFREG | 0644
        st->st_ino = 1001;
    }
    st->st_dev = 25;
    st->st_nlink = 1;
    st->st_uid = 0;
    st->st_gid = 0;
    st->st_blksize = 4096;
}

static int (*orig_fstatat)(int, const char *, void *, int);
static int my_fstatat(int dirfd, const char *path, void *buf, int flags) {
    if (deny_exists(path)) { hid("fstatat", path); set_enoent(); return -1; }
    int res = orig_fstatat(dirfd, path, buf, flags);
    if (res < 0 && *__errno() == 13 /*EACCES*/) {
        hid("fstatat/eacces_shield", path ? path : "empty_path");
        fake_fstat(dirfd, buf);
        *__errno() = 0;
        return 0;
    }
    return res;
}

static int (*orig_fstat)(int, void *);
static int my_fstat(int fd, void *buf) {
    int res = orig_fstat ? orig_fstat(fd, buf) : (int)my_raw_syscall(SYS_fstat, fd, (long)buf, 0, 0, 0, 0);
    if (res < 0 && *__errno() == 13 /*EACCES*/) {
        hid("fstat/eacces_shield", "trace_marker_shield");
        fake_fstat(fd, buf);
        *__errno() = 0;
        return 0;
    }
    return res;
}

static int (*orig_statx)(int, const char *, int, unsigned, void *);
static int my_statx(int dirfd, const char *path, int flags, unsigned mask, void *buf) {
    if (deny_exists(path)) { hid("statx", path); set_enoent(); return -1; }
    int res = orig_statx(dirfd, path, flags, mask, buf);
    if (res < 0 && *__errno() == 13 /*EACCES*/) {
        hid("statx/eacces_shield", path ? path : "empty_path");
        set_enoent();
        return -1;
    }
    return res;
}

struct dirent_min {
    uint64_t d_ino; int64_t d_off; uint16_t d_reclen; uint8_t d_type; char d_name[256];
};
static void *(*orig_readdir)(void *);
static void *my_readdir(void *dir) {
    void *e;
    while ((e = orig_readdir(dir)) != nullptr) {
        if (!hide_dirent(((dirent_min *)e)->d_name)) break;
    }
    return e;
}

// Catch raw syscall(__NR_*, ...) probes that bypass the named libc wrappers.
static long (*orig_syscall)(long, long, long, long, long, long, long);
static long my_syscall(long nr, long a1, long a2, long a3, long a4, long a5, long a6) {
    const char *path = nullptr;
    bool exist = false, opn = false;
    switch (nr) {
        case SYS_newfstatat: path = (const char *)a2; exist = true; break;
        case SYS_statx:      path = (const char *)a2; exist = true; break;
        case SYS_faccessat:  path = (const char *)a2; exist = true; break;
        case SYS_faccessat2: path = (const char *)a2; exist = true; break;
        case SYS_readlinkat: path = (const char *)a2; exist = true; break;
        case SYS_openat:     path = (const char *)a2; opn = true; break;
        case SYS_userfaultfd: {
            hid("syscall/userfaultfd", "userfaultfd");
            return -1; // -EPERM
        }
        case SYS_fstat: {
            long fd = a1;
            long statbuf = a2;
            long res = orig_syscall ? orig_syscall(nr, a1, a2, a3, a4, a5, a6)
                                    : syscall(nr, a1, a2, a3, a4, a5, a6);
            if (res == -13 || (res < 0 && *__errno() == 13)) {
                hid("syscall/fstat_shield", "trace_marker_shield");
                if (statbuf) {
                    char *p = (char *)statbuf;
                    for (int i = 0; i < 128; i++) p[i] = 0;
                    *(uint32_t *)(p + 24) = 0020222; // S_IFCHR | 0222
                }
                *__errno() = 0;
                return 0;
            }
            return res;
        }
    }
    if (path) {
        if (exist && deny_exists(path)) { hid("syscall/stat", path); set_enoent(); return -1; }
        if (opn) {
            if (deny_open(path)) { hid("syscall/open", path); set_enoent(); return -1; }
            if (should_clean_proc(path)) {
                int cfd = create_clean_proc_fd(path);
                if (cfd >= 0) { ALOG("syscall/clean_proc(%s) -> fd %d", path, cfd); return cfd; }
            }
        }
    }
    return orig_syscall ? orig_syscall(nr, a1, a2, a3, a4, a5, a6)
                        : syscall(nr, a1, a2, a3, a4, a5, a6);
}

static int (*orig_kill)(int, int);
static int my_kill(int pid, int sig) {
    if ((pid == 0 || pid == -1 || pid == (int)my_raw_syscall(172 /*SYS_getpid*/, 0, 0, 0, 0, 0, 0)) &&
        (sig == 9 || sig == 6)) {
        ALOG("shielded process from self-kill attempt (pid=%d, sig=%d)", pid, sig);
        return 0; // Prevent suicide
    }
    return orig_kill ? orig_kill(pid, sig) : kill(pid, sig);
}

static int (*orig_sysprop_get)(const char *, char *);
static int my_sysprop_get(const char *name, char *value) {
    const char *s = prop_spoof(name);
    if (s) {
        int n = 0;
        while (s[n]) { value[n] = s[n]; n++; }
        value[n] = 0;
        return n;
    }
    return orig_sysprop_get(name, value);
}

// Protect our SIGSYS handler from being overridden by anti-tamper SDKs.
static int (*orig_sigaction)(int, const struct sigaction_t *, struct sigaction_t *);
static void sigsys_handler(int sig, siginfo_t *info, void *context);

static int my_sigaction(int sig, const struct sigaction_t *act, struct sigaction_t *oact) {
    if (sig == 31 /*SIGSYS*/) {
        if (act && act->sa_sigaction == sigsys_handler) {
            // Our own registration: pass directly to real libc sigaction
            return orig_sigaction ? orig_sigaction(sig, act, oact) : sigaction(sig, act, oact);
        }
        ALOG("shielded SIGSYS handler from app override attempt");
        if (oact) {
            oact->sa_flags = 0x4 /*SA_SIGINFO*/ | 0x40000000 /*SA_NODEFER*/;
            oact->sa_sigaction = sigsys_handler;
            oact->sa_mask = 0;
            oact->sa_restorer = nullptr;
        }
        return 0; // Return success to caller
    }
    return orig_sigaction ? orig_sigaction(sig, act, oact) : sigaction(sig, act, oact);
}

// ---- Seccomp Trap-and-Emulate ------------------------------------------------
static uintptr_t g_hide_start = 0;
static uintptr_t g_hide_end = 0;
static uintptr_t g_linker_start = 0;
static uintptr_t g_linker_end = 0;

static void sigsys_handler(int sig, siginfo_t *info, void *context) {
    (void)sig; (void)info;
    auto *uc = (ucontext_t *)context;
    long nr = (long)uc->uc_mcontext.regs[8]; // w8/x8 holds syscall nr on ARM64

    if (nr == SYS_userfaultfd) {
        hid("seccomp_trap/userfaultfd", "userfaultfd");
        uc->uc_mcontext.regs[0] = -1; // -EPERM
        return;
    } else if (nr == SYS_fstat) {
        long fd = (long)uc->uc_mcontext.regs[0];
        long statbuf = (long)uc->uc_mcontext.regs[1];
        long res = my_raw_syscall(SYS_fstat, fd, statbuf, 0, 0, 0, 0);
        if (res == -13 /*-EACCES*/) {
            hid("seccomp_trap/fstat_shield", "trace_marker_shield");
            fake_fstat(fd, (void *)statbuf);
            uc->uc_mcontext.regs[0] = 0; // Success
            return;
        }
        uc->uc_mcontext.regs[0] = res;
        return;
    } else if (nr == SYS_fstatfs) {
        long fd = (long)uc->uc_mcontext.regs[0];
        long statfsbuf = (long)uc->uc_mcontext.regs[1];
        long res = my_raw_syscall(SYS_fstatfs, fd, statfsbuf, 0, 0, 0, 0);
        if (res == -13 /*-EACCES*/) {
            hid("seccomp_trap/fstatfs_shield", "trace_marker_shield");
            uc->uc_mcontext.regs[0] = 0;
            return;
        }
        uc->uc_mcontext.regs[0] = res;
        return;
    }

    const char *raw_path = (nr == 43 /*SYS_statfs*/)
        ? (const char *)uc->uc_mcontext.regs[0]
        : (const char *)uc->uc_mcontext.regs[1];

    char path_buf[256];
    path_buf[0] = 0;
    safe_copy_str(raw_path, path_buf, sizeof(path_buf));

    bool deny = false;

    if (nr == SYS_newfstatat || nr == SYS_statx || nr == SYS_faccessat ||
        nr == SYS_faccessat2 || nr == SYS_readlinkat || nr == 43 /*SYS_statfs*/) {
        if (deny_exists(path_buf)) {
            deny = true;
            hid("seccomp_trap/stat", path_buf);
        }
    } else if (nr == SYS_openat || nr == 437 /*SYS_openat2*/) {
        if (deny_open(path_buf)) {
            deny = true;
            hid("seccomp_trap/open", path_buf);
        } else if (should_clean_proc(path_buf)) {
            int cfd = create_clean_proc_fd(path_buf);
            if (cfd >= 0) {
                ALOG("seccomp_trap/clean_proc(%s) -> fd %d", path_buf, cfd);
                uc->uc_mcontext.regs[0] = cfd;
                return;
            }
        }
    }

    if (deny) {
        // Emulate kernel syscall return value directly in X0: -ENOENT (-2)
        uc->uc_mcontext.regs[0] = -ENOENT;
        return;
    }

    // Forward non-denied syscall directly to kernel via our own raw svc #0 stub.
    // Since my_raw_syscall is inside libemuhide.so, its IP is whitelisted by BPF.
    long res = my_raw_syscall(nr,
                              uc->uc_mcontext.regs[0], uc->uc_mcontext.regs[1],
                              uc->uc_mcontext.regs[2], uc->uc_mcontext.regs[3],
                              uc->uc_mcontext.regs[4], uc->uc_mcontext.regs[5]);
    if (res == -13 /*-EACCES*/ && (nr == SYS_newfstatat || nr == SYS_statx)) {
        long dirfd = (long)uc->uc_mcontext.regs[0];
        long statbuf = (long)uc->uc_mcontext.regs[2];
        fake_fstat(dirfd, (void *)statbuf);
        uc->uc_mcontext.regs[0] = 0;
        return;
    }
    uc->uc_mcontext.regs[0] = res;
}

static bool install_seccomp() {
    if (g_hide_start == 0 || g_hide_end <= g_hide_start) {
        ALOG("seccomp: hide module range invalid, skipping");
        return false;
    }

    struct sigaction_t sa = {};
    sa.sa_flags = 0x4 /*SA_SIGINFO*/ | 0x40000000 /*SA_NODEFER*/;
    sa.sa_sigaction = sigsys_handler;
    int sig_rc = orig_sigaction ? orig_sigaction(31 /*SIGSYS*/, &sa, nullptr)
                                : sigaction(31 /*SIGSYS*/, &sa, nullptr);
    if (sig_rc != 0) {
        ALOG("seccomp: failed to register SIGSYS handler (rc=%d)", sig_rc);
        return false;
    }

    uint32_t hide_hi   = (uint32_t)(g_hide_start >> 32);
    uint32_t hide_lo_s = (uint32_t)(g_hide_start & 0xFFFFFFFF);
    uint32_t hide_lo_e = (uint32_t)(g_hide_end & 0xFFFFFFFF);

    uint32_t link_hi   = (uint32_t)(g_linker_start >> 32);
    uint32_t link_lo_s = (uint32_t)(g_linker_start & 0xFFFFFFFF);
    uint32_t link_lo_e = (uint32_t)(g_linker_end & 0xFFFFFFFF);

    struct sock_filter filter[] = {
        // [0] Load arch
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 4),
        // [1] Check arch == AUDIT_ARCH_AARCH64 (0xC00000B7)
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_AARCH64, 0, 23),

        // [2] Load syscall nr
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 0),

        // [3..13] Check syscall numbers: 79, 439, 48, 291, 78, 56, 437, 43, 80, 44, 282
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 79,  10, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 439, 9,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 48,  8,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 291, 7,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 78,  6,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 56,  5,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 437, 4,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 43,  3,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 80,  2,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 44,  1,  0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 282, 0,  11),

        // Check libemuhide.so range:
        // [14] Load IP high
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 12),
        // [15] If IP_hi == hide_hi, next (16); else jump to check_linker (19)
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, hide_hi, 0, 3),
        // [16] Load IP low
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 8),
        // [17] If IP_lo >= hide_lo_s, next (18); else jump to check_linker (19)
        BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, hide_lo_s, 0, 1),
        // [18] If IP_lo >= hide_lo_e, next (19: check_linker); else jump to ALLOW (25)
        BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, hide_lo_e, 0, 6),

        // Check linker range:
        // [19] Load IP high
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 12),
        // [20] If IP_hi == link_hi, next (21); else jump to TRAP (24)
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, link_hi, 0, 3),
        // [21] Load IP low
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 8),
        // [22] If IP_lo >= link_lo_s, next (23); else jump to TRAP (24)
        BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, link_lo_s, 0, 1),
        // [23] If IP_lo >= link_lo_e, next (24: TRAP); else jump to ALLOW (25)
        BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, link_lo_e, 0, 1),

        // [24] Outside libemuhide and linker -> TRAP
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_TRAP),

        // [25] Inside libemuhide/linker OR not monitored syscall -> ALLOW
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };

    struct sock_fprog prog = {
        .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = filter,
    };

    prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0);

    // Synchronize seccomp filter across all threads in the thread group
    long rc = syscall(277 /*SYS_seccomp*/, 1 /*SECCOMP_SET_MODE_FILTER*/, 1 /*SECCOMP_FILTER_FLAG_TSYNC*/, &prog);
    if (rc != 0) {
        rc = prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &prog);
    }
    ALOG("seccomp filter installed: rc=%ld (hide %llx-%llx, linker %llx-%llx)", rc,
         (unsigned long long)g_hide_start, (unsigned long long)g_hide_end,
         (unsigned long long)g_linker_start, (unsigned long long)g_linker_end);
    return rc == 0;
}

// ---- maps parsing + hook registration -----------------------------------------
static dev_t make_dev(unsigned major, unsigned minor) {
    return (((dev_t)(major & 0xfffff000u) << 32) | ((major & 0xfffu) << 8) |
            ((dev_t)(minor & 0xffffff00u) << 12) | (minor & 0xffu));
}

static uintptr_t hex2ptr(const char *s, const char **end) {
    uintptr_t v = 0;
    while ((*s >= '0' && *s <= '9') || (*s >= 'a' && *s <= 'f') || (*s >= 'A' && *s <= 'F')) {
        unsigned d = (*s <= '9') ? (unsigned)(*s - '0')
                     : (*s <= 'F') ? (unsigned)(*s - 'A' + 10)
                                   : (unsigned)(*s - 'a' + 10);
        v = (v << 4) | (uintptr_t)d;
        s++;
    }
    *end = s;
    return v;
}

static unsigned hex2u(const char *s, const char **end) {
    unsigned v = 0;
    while ((*s >= '0' && *s <= '9') || (*s >= 'a' && *s <= 'f') || (*s >= 'A' && *s <= 'F')) {
        unsigned d = (*s <= '9') ? (unsigned)(*s - '0')
                     : (*s <= 'F') ? (unsigned)(*s - 'A' + 10)
                                   : (unsigned)(*s - 'a' + 10);
        v = v * 16 + d; s++;
    }
    *end = s;
    return v;
}

static unsigned long dec2ul(const char *s, const char **end) {
    unsigned long v = 0;
    while (*s >= '0' && *s <= '9') { v = v * 10 + (unsigned long)(*s - '0'); s++; }
    *end = s;
    return v;
}

static Api *g_api = nullptr;
// Some SDKs own their signal handling and depend on native syscall errors.
// Never replace those contracts with synthetic success in compatibility mode.
static bool g_native_syscalls = false;

static void register_all(dev_t dev, ino_t ino) {
    g_api->pltHookRegister(dev, ino, "openat", (void *)my_openat, (void **)&orig_openat);
    g_api->pltHookRegister(dev, ino, "open", (void *)my_open, (void **)&orig_open);
    g_api->pltHookRegister(dev, ino, "access", (void *)my_access, (void **)&orig_access);
    g_api->pltHookRegister(dev, ino, "faccessat", (void *)my_faccessat, (void **)&orig_faccessat);
    g_api->pltHookRegister(dev, ino, "stat", (void *)my_stat, (void **)&orig_stat);
    g_api->pltHookRegister(dev, ino, "lstat", (void *)my_lstat, (void **)&orig_lstat);
    if (!g_native_syscalls) {
        g_api->pltHookRegister(dev, ino, "fstat", (void *)my_fstat, (void **)&orig_fstat);
        g_api->pltHookRegister(dev, ino, "fstat64", (void *)my_fstat, (void **)&orig_fstat);
        g_api->pltHookRegister(dev, ino, "fstatat", (void *)my_fstatat, (void **)&orig_fstatat);
        g_api->pltHookRegister(dev, ino, "fstatat64", (void *)my_fstatat, (void **)&orig_fstatat);
        g_api->pltHookRegister(dev, ino, "newfstatat", (void *)my_fstatat, (void **)&orig_fstatat);
        g_api->pltHookRegister(dev, ino, "statx", (void *)my_statx, (void **)&orig_statx);
    }
    g_api->pltHookRegister(dev, ino, "readdir", (void *)my_readdir, (void **)&orig_readdir);
    if (!g_native_syscalls) {
        g_api->pltHookRegister(dev, ino, "syscall", (void *)my_syscall, (void **)&orig_syscall);
        g_api->pltHookRegister(dev, ino, "sigaction", (void *)my_sigaction, (void **)&orig_sigaction);
        g_api->pltHookRegister(dev, ino, "sigaction64", (void *)my_sigaction, (void **)&orig_sigaction);
        g_api->pltHookRegister(dev, ino, "kill", (void *)my_kill, (void **)&orig_kill);
    }
    g_api->pltHookRegister(dev, ino, "__system_property_get", (void *)my_sysprop_get,
                           (void **)&orig_sysprop_get);
}

// Read /proc/self/maps, register PLT hooks for every unique file-backed .so
// (except our own module), and locate libc.so executable range for seccomp.
static int install_hooks(const char *self_soname) {
    int fd = openat(-100 /*AT_FDCWD*/, "/proc/self/maps", O_RDONLY, 0);
    if (fd < 0) return -1;

    static char buf[1 << 16];
    static dev_t seen_dev[1024];
    static ino_t seen_ino[1024];
    int seen = 0, hooked = 0;

    // Line-oriented streaming parse. Lines can span reads; keep a small carry.
    static char line[1024];
    int ll = 0;
    long n;
    while ((n = read(fd, buf, sizeof(buf))) > 0) {
        for (long i = 0; i < n; i++) {
            char c = buf[i];
            if (c != '\n') {
                if (ll < (int)sizeof(line) - 1) line[ll++] = c;
                continue;
            }
            line[ll] = 0;
            ll = 0;
            // Parse: addr-addr perms offset dev inode path
            const char *p = line;
            uintptr_t seg_start = hex2ptr(p, &p);
            if (*p == '-') p++;
            uintptr_t seg_end = hex2ptr(p, &p);

            while (*p && *p != ' ') p++;
            while (*p == ' ') p++;              // perms
            const char *perms = p;
            while (*p && *p != ' ') p++;
            while (*p == ' ') p++;              // offset
            while (*p && *p != ' ') p++;
            while (*p == ' ') p++;              // dev major:minor
            const char *e;
            unsigned major = hex2u(p, &e); p = e;
            if (*p == ':') p++;
            unsigned minor = hex2u(p, &e); p = e;
            while (*p == ' ') p++;              // inode
            unsigned long ino = dec2ul(p, &e); p = e;
            while (*p == ' ') p++;              // path
            const char *path = p;
            if (ino == 0 || path[0] != '/') continue;
            if (perms[2] != 'x') continue;                   // executable segment

            // Record libemuhide.so and linker64 executable ranges for seccomp instruction pointer check
            uintptr_t my_fn = (uintptr_t)&my_raw_syscall;
            if (seg_start <= my_fn && my_fn < seg_end) {
                g_hide_start = seg_start;
                g_hide_end = seg_end;
            } else if (strstr(path, "linker64")) {
                g_linker_start = seg_start;
                g_linker_end = seg_end;
            }

            if (!strstr(path, ".so")) continue;             // libraries only for PLT hooks
            if (self_soname && strstr(path, self_soname)) continue;  // not ourselves

            dev_t dev = make_dev(major, minor);
            bool dup = false;
            for (int k = 0; k < seen; k++)
                if (seen_dev[k] == dev && seen_ino[k] == ino) { dup = true; break; }
            if (dup) continue;
            if (seen < 1024) { seen_dev[seen] = dev; seen_ino[seen] = ino; seen++; }
            register_all(dev, (ino_t)ino);
            hooked++;
        }
    }
    close(fd);
    g_api->pltHookCommit();
    return hooked;
}

// ---- module -------------------------------------------------------------------
static const char *kTargets[] = {
    "com.tinder", "com.bumble.app", "com.pof.android",
    "dev.emulab.devicecheck",  // self-test probe
};

static bool name_matches(const char *name) {
    for (auto t : kTargets) {
        const char *a = name, *b = t;
        while (*a && *b && *a == *b) { a++; b++; }
        if (*b == 0 && (*a == 0 || *a == ':')) return true;  // exact or pkg:proc
    }
    return false;
}

class EmuHide : public zygisk::ModuleBase {
public:
    void onLoad(Api *api, JNIEnv *env) override { api_ = api; env_ = env; g_api = api; }

    // Decide target from nice_name (the specialization process name). cmdline is
    // not yet updated at postAppSpecialize time, so nice_name is the only reliable
    // source. Save the decision for postAppSpecialize.
    void preAppSpecialize(AppSpecializeArgs *args) override {
        target_ = false;
        if (args && args->nice_name) {
            const char *nn = env_->GetStringUTFChars(args->nice_name, nullptr);
            if (nn) {
                target_ = name_matches(nn);
                g_native_syscalls = strcmp(nn, "com.tinder") == 0 ||
                                    strncmp(nn, "com.tinder:", 11) == 0;
                env_->ReleaseStringUTFChars(args->nice_name, nn);
            }
        }
    }

    void postAppSpecialize(const AppSpecializeArgs *) override {
        if (!target_) {
            api_->setOption(Option::DLCLOSE_MODULE_LIBRARY);
            return;
        }
        int h = install_hooks("libemuhide.so");
        ALOG("hooks installed across %d libraries", h);
        if (g_native_syscalls) {
            ALOG("compatibility mode: native syscalls and signal handlers preserved");
            return;
        }
        bool sec = install_seccomp();
        ALOG("seccomp trap-and-emulate initialized: %s", sec ? "OK" : "FAILED");
    }

private:
    Api *api_ = nullptr;
    JNIEnv *env_ = nullptr;
    bool target_ = false;
};

REGISTER_ZYGISK_MODULE(EmuHide)
