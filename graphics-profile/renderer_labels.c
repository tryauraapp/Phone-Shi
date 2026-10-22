/* Local GLES label fixture. All rendering and capability calls use the backend.
 * The EGL client interface prefix follows AOSP EGLClientIface.h: thread getter,
 * then getGLString. We pass the full original interface through unchanged apart
 * from the string callback; no assumptions are made about trailing fields.
 */
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
typedef const char *(*StringGetter)(int);
typedef struct {
    void *(*get_thread_info)(void);
    StringGetter get_string;
} EglInterfacePrefix;
typedef void *(*InitFunction)(void *);
static StringGetter backend_string;
static void *backend_handle;
static InitFunction backend_init;

static const char *label_string(int name) {
    if (name == 0x1f00) return "Qualcomm";       /* GL_VENDOR */
    if (name == 0x1f01) return "Adreno (TM) 830"; /* GL_RENDERER */
    return backend_string ? backend_string(name) : (const char *)0;
}

__attribute__((visibility("default")))
void *init_emul_gles(void *interface_pointer) {
    if (!interface_pointer) return (void *)0;
    if (!backend_handle) {
        backend_handle = dlopen("/vendor/lib64/egl/libGLESv2_backend.so", 2);
        if (!backend_handle) return (void *)0;
        backend_init = (InitFunction)dlsym(backend_handle, "init_emul_gles");
        if (!backend_init) return (void *)0;
    }
    EglInterfacePrefix *interface = (EglInterfacePrefix *)interface_pointer;
    if (interface->get_string != label_string) backend_string = interface->get_string;
    interface->get_string = label_string;
    return backend_init(interface_pointer);
}
