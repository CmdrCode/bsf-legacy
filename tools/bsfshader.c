/* bsfshader.c -- a GML-callable pixel-shader API for Battleships Forever.
 *
 * WHAT IT IS FOR: visual effects -- damage states, cloak, shield hits, a colour
 * grade per faction.  NOT performance.  Nothing here makes the game faster:
 * with d3d8to9 loaded the runner still issues one DrawPrimitiveUP per sprite,
 * exactly as it does against wine's builtin d3d8.
 *
 *   sh_init()                  bind to the game's live D3D9 device
 *   sh_compile(path)           compile mods/<file>.hlsl at ps_2_0 -> handle
 *   sh_compile_as(path,target) ... at an explicit target
 *   sh_set(handle) / sh_reset()
 *   sh_const(reg,x,y,z,w)      float4 constant
 *   sh_const_col(reg,col,a)    a GM colour as a float4, swizzle handled
 *   sh_free(handle)
 *   sh_err()                   last error, as a string
 *   sh_stat(which)             counters
 *
 * WHY THERE IS NO INJECTOR HERE.  GM draws through its own D3D8 calls; with
 * d3d8to9 loaded those become D3D9 calls on a device we can simply reach.  The
 * runner never touches the pixel-shader slot (171-site census,
 * HWVP-STATIC-RISK.md 10), so a shader bound once stays bound across every
 * later draw.  Nothing is patched, hooked or detoured.
 *
 * Needs d3d8to9 to be the loaded d3d8, which `tools/wineenv.py` arranges on
 * every launch path.  Without it sh_init returns -1 and every later call is a
 * no-op, so the game is unaffected and effects are simply off.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define EXP __declspec(dllexport)
#define MAX_SHADERS 32

int caps9_read(void *, unsigned *, unsigned *, unsigned *, unsigned *);
int d9_create_ps(void *, const void *, void **);
int d9_set_ps(void *, void *);
int d9_set_const(void *, unsigned, const float *);
void d9_release_ps(void *);

static void  *g_dev9;
static void  *g_ps[MAX_SHADERS];
static char   g_err[1024] = "";
static double g_compiles, g_binds, g_fails;

static void err(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt); vsnprintf(g_err, sizeof g_err, fmt, ap); va_end(ap);
    g_fails += 1;
}

static int readable(const void *p, SIZE_T n)
{
    MEMORY_BASIC_INFORMATION mbi;
    if (!p) return 0;
    if (!VirtualQuery(p, &mbi, sizeof mbi)) return 0;
    if (mbi.State != MEM_COMMIT) return 0;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return 0;
    return (SIZE_T)((const char *) mbi.BaseAddress + mbi.RegionSize - (const char *) p) >= n;
}

/* AllocationBase of a mapped image is its HMODULE, so this is exact, not a
 * heuristic -- which is what lets the D3D9 member be found by provenance
 * instead of by a hardcoded offset that a different d3d8to9 build would move. */
static int in_module(const void *p, const char *mod)
{
    MEMORY_BASIC_INFORMATION mbi;
    HMODULE h = GetModuleHandleA(mod);
    if (!h || !p) return 0;
    if (!VirtualQuery(p, &mbi, sizeof mbi)) return 0;
    return mbi.AllocationBase == (void *) h;
}

static void *find_dev9(void)
{
    void *dev, *p1;
    int off;
    if (!GetModuleHandleA("d3d9.dll")) { err("d3d9.dll not in process -- is d3d8=n,b set?"); return NULL; }
    /* 0x00589B08 is an ALIAS: it holds the address of 0x00587A64, which is the
     * device pointer.  One deref lands on a global, not an interface. */
    if (!readable((void *) 0x00589B08, 4)) { err("runner global unreadable"); return NULL; }
    p1 = *(void **) 0x00589B08;
    if (!readable(p1, 4)) { err("device alias unreadable"); return NULL; }
    dev = *(void **) p1;
    if (!readable(dev, 4)) { err("device unreadable"); return NULL; }
    for (off = 4; off <= 128; off += 4) {
        void *cand; unsigned a, b, c, d;
        if (!readable((char *) dev + off, 4)) continue;
        cand = *(void **) ((char *) dev + off);
        if (!readable(cand, 4)) continue;
        if (!in_module(*(void **) cand, "d3d9.dll")) continue;
        if (caps9_read(cand, &a, &b, &c, &d)) return cand;
    }
    err("no IDirect3DDevice9 inside the d3d8 object -- is d3d8to9 the loaded d3d8?");
    return NULL;
}

/* Cached, but re-validated: a stale pointer would fault rather than fail, so
 * confirm the vtable still lives in d3d9.dll before trusting it. */
static void *dev9(void)
{
    if (g_dev9 && readable(g_dev9, 4) && in_module(*(void **) g_dev9, "d3d9.dll"))
        return g_dev9;
    g_dev9 = find_dev9();
    return g_dev9;
}

EXP double __cdecl sh_init(void)
{
    g_err[0] = 0;
    return dev9() ? 1.0 : -1.0;
}

/* ------------------------------------------------------------------ compile */

typedef HRESULT (WINAPI *PFN_D3DCompile)(LPCVOID, SIZE_T, LPCSTR, const void *, void *,
                                         LPCSTR, LPCSTR, UINT, UINT, void **, void **);

static void *blob_ptr(void *b)   { void **vt = *(void ***) b; return ((void *(WINAPI *)(void *)) vt[3])(b); }
static void  blob_release(void *b){ void **vt = *(void ***) b; ((ULONG (WINAPI *)(void *)) vt[2])(b); }

static double compile_file(const char *path, const char *target)
{
    static PFN_D3DCompile compile;
    char src[16384];
    void *code = NULL, *errs = NULL, *ps = NULL;
    FILE *f;
    size_t n;
    HRESULT hr;
    int i, rc;

    g_err[0] = 0;
    if (!dev9()) return -1;

    if (!compile) {
        HMODULE m = LoadLibraryA("d3dcompiler_47.dll");
        if (!m) m = LoadLibraryA("d3dcompiler_43.dll");
        if (!m) { err("no d3dcompiler_47/43.dll"); return -2; }
        compile = (PFN_D3DCompile) GetProcAddress(m, "D3DCompile");
        if (!compile) { err("d3dcompiler has no D3DCompile"); return -2; }
    }

    f = fopen(path, "rb");
    if (!f) { err("cannot open %s", path); return -3; }
    n = fread(src, 1, sizeof src - 1, f);
    fclose(f);
    src[n] = 0;
    if (!n) { err("%s is empty", path); return -3; }

    hr = compile(src, n, path, NULL, NULL, "main", target, 0, 0, &code, &errs);
    if (errs && readable(errs, 4)) {
        if (FAILED(hr)) err("%s: %.700s", path, (char *) blob_ptr(errs));
        blob_release(errs);
    }
    if (FAILED(hr) || !code) {
        if (!g_err[0]) err("%s: D3DCompile failed 0x%08lx", path, (unsigned long) hr);
        return -4;
    }

    rc = d9_create_ps(dev9(), blob_ptr(code), &ps);
    blob_release(code);
    if (rc) { err("%s: CreatePixelShader failed 0x%08x", path, rc); return -5; }

    for (i = 0; i < MAX_SHADERS; i++)
        if (!g_ps[i]) { g_ps[i] = ps; g_compiles += 1; return (double) i; }

    d9_release_ps(ps);
    err("shader table full (%d)", MAX_SHADERS);
    return -6;
}

EXP double __cdecl sh_compile(const char *path) { return compile_file(path, "ps_2_0"); }

EXP double __cdecl sh_compile_as(const char *path, const char *target)
{
    return compile_file(path, target && *target ? target : "ps_2_0");
}

/* ---------------------------------------------------------------- bind/state */

EXP double __cdecl sh_set(double h)
{
    int i = (int) h;
    void *d = dev9();
    if (!d) return 0;
    if (i < 0 || i >= MAX_SHADERS || !g_ps[i]) { err("bad shader handle %d", i); return 0; }
    if (!d9_set_ps(d, g_ps[i])) { err("SetPixelShader failed"); return 0; }
    g_binds += 1;
    return 1;
}

EXP double __cdecl sh_reset(void)
{
    void *d = dev9();
    return (d && d9_set_ps(d, NULL)) ? 1.0 : 0.0;
}

EXP double __cdecl sh_const(double reg, double x, double y, double z, double w)
{
    float v[4]; void *d = dev9();
    v[0] = (float) x; v[1] = (float) y; v[2] = (float) z; v[3] = (float) w;
    if (!d) return 0;
    return d9_set_const(d, (unsigned) reg, v) ? 1.0 : 0.0;
}

/* GM packs colour as BGR -- `make_color_rgb(r,g,b)` stores b<<16|g<<8|r -- so a
 * naive cast gives red/blue-swapped shaders that look like a blend-mode bug.
 * (Same swizzle gm82dx9 needs in gm_col_to_dx9; here it lands in floats rather
 * than a D3DCOLOR, because a shader constant is four floats.) */
EXP double __cdecl sh_const_col(double reg, double col, double alpha)
{
    unsigned c = (unsigned) col;
    float v[4]; void *d = dev9();
    v[0] = (float)( c        & 0xff) / 255.0f;   /* GM low byte  = red   */
    v[1] = (float)((c >> 8)  & 0xff) / 255.0f;
    v[2] = (float)((c >> 16) & 0xff) / 255.0f;   /* GM high byte = blue  */
    v[3] = (float) alpha;
    if (!d) return 0;
    return d9_set_const(d, (unsigned) reg, v) ? 1.0 : 0.0;
}

EXP double __cdecl sh_free(double h)
{
    int i = (int) h;
    if (i < 0 || i >= MAX_SHADERS || !g_ps[i]) return 0;
    d9_release_ps(g_ps[i]);
    g_ps[i] = NULL;
    return 1;
}

EXP const char * __cdecl sh_err(void) { return g_err; }

EXP double __cdecl sh_stat(double which)
{
    switch ((int) which) {
        case 0: return g_dev9 ? 1 : 0;
        case 1: return g_compiles;
        case 2: return g_binds;
        case 3: return g_fails;
        default: return -1;
    }
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD r, LPVOID v) { (void) h; (void) r; (void) v; return TRUE; }
