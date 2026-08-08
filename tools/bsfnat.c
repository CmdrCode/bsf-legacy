/* bsfnat.c -- the cursor cache, plus the GM 7.0 `external_define` ABI probe it
 * grew out of.  Built as a 32-bit PE DLL (see build.sh).
 *
 * TWO ROLES, and only one of them ships:
 *
 *   the cursor cache (bottom of this file) is a feature.  mods/cursor.gml loads
 *   it on every install, so everything it costs, a player pays.
 *
 *   everything above it is measurement -- what the GM7 extension ABI actually
 *   is, and what one crossing into native code costs.  Driven by mods/native.gml
 *   and the profiler modules, none of which ship.
 *
 * Keep that split in mind before adding state at file scope: a static array here
 * is committed in the game's 32-bit address space at LoadLibrary time whether or
 * not the probe half is ever called.  See RETBUF below for the one that was.
 *
 * Every export bumps g_calls.  That counter is the proof that a call happened:
 * a timing-only check cannot tell a fast call from a silent no-op, and GM7 will
 * happily accept a define whose symbol it never resolves.  Every export that
 * takes arguments also *returns a function of them*, so a correct return value
 * proves the arguments crossed as well.
 */

#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define EXP __declspec(dllexport)

/* ------------------------------------------------------------ bookkeeping */

static double        g_calls = 0;      /* every export increments this        */
static LARGE_INTEGER g_freq, g_base;   /* QueryPerformanceCounter reference   */
static double        g_state = 0;      /* survives across calls?              */
static unsigned char *g_mem = NULL;    /* malloc'd in mem_alloc               */
static size_t         g_mem_n = 0;
static volatile LONG  g_thread_ticks = 0;
static HANDLE         g_thread = NULL;
static double         g_file_sum = 0;
static double         g_quads = 0;     /* quads accumulated by push8/push11   */
static double         g_quad_sum = 0;
static double         g_last_us = 0;   /* self-timed cost of the last bulk op */

/* 48 MB return buffer: how big a string can cross back into GML?
 *
 * Allocated on FIRST USE rather than declared as a static array. This DLL also
 * ships to players for the cursor hook alone, and a 48 MB .bss block is
 * committed in the game's 32-bit (2 GB) address space at LoadLibrary time
 * whether or not anything ever asks for a string -- which, in the shipping
 * configuration, nothing does.
 */
#define RETBUF (48u * 1024u * 1024u)
static char *g_ret = NULL;
static char *g_ret_heap = NULL;        /* deliberately freed on the NEXT call */

static char *retbuf(void)
{
    if (!g_ret) g_ret = (char *)malloc(RETBUF + 1);
    return g_ret;
}

/* 600 quads * 11 doubles, the realistic per-frame vertex sink               */
static double g_vtx[600 * 11];
static size_t g_vtx_n = 0;

static double now_us(void)
{
    LARGE_INTEGER t;
    QueryPerformanceCounter(&t);
    return (double)(t.QuadPart - g_base.QuadPart) * 1e6 / (double)g_freq.QuadPart;
}

/* --------------------------------------------------------- timing / probes */

EXP double __cdecl nat_version(void) { g_calls += 1; return 3.0; }
EXP double __cdecl nat_calls(void)   { return g_calls; }   /* NOT counted */
EXP double __cdecl nat_qpc_us(void)  { g_calls += 1; return now_us(); }
EXP double __cdecl nat_qpc_hz(void)  { g_calls += 1; return (double)g_freq.QuadPart; }
EXP double __cdecl nat_last_us(void) { g_calls += 1; return g_last_us; }

/* ------------------------------------------------------- per-object lap timer
 *
 * The instrument for "which object's Step is the expensive one" in a LIVE scene,
 * where the stub-and-diff used on the still-life sandbox cannot go: stubbing an
 * event changes the battle from that frame on, so the two arms of the A/B stop
 * being the same scene.
 *
 * How it works. A one-argument probe is APPENDED to the Step event of every
 * object that owns one. GM runs an event by walking its instances, so consecutive
 * probe calls bracket exactly one instance's stock body -- whatever object that
 * instance belongs to, and in whatever order the runner chooses to visit them.
 * The bracket needs no ordering guarantee at all; it only needs every instance
 * that runs a body to also run a probe.
 *
 *   nat_lap(b)      close the open bracket into bucket b, open a new one
 *   nat_lap_reset() zero every bucket and open a fresh bracket
 *   nat_lap_dump(p) write "bucket us n" for every non-empty bucket
 *   nat_lap_ovh()   self-measured cost of one nat_lap body, microseconds
 *
 * ⚠ The clock is read TWICE per call, once on entry and once on exit, and it is
 * the exit reading that opens the next bracket. That keeps the probe's own cost
 * out of every bucket -- it inflates step_ms, which is calibrated separately, but
 * it does not inflate any object's share. Reading once would charge each object
 * for its predecessor's probe.
 *
 * ⚠ Buckets 0-2 are the pass preambles. Whatever ran between the last probe of
 * one event pass and the first probe of the next -- the draw phase, the present,
 * GM's own bookkeeping, and this harness's unprobed instances -- lands there
 * rather than being smeared into whichever object happened to be visited first.
 */
#define LAPN 512
static double g_lap_us[LAPN];
static double g_lap_n[LAPN];
static double g_lap_last = 0;

EXP double __cdecl nat_lap(double bucket)
{
    double t = now_us();
    int b = (int)bucket;
    g_calls += 1;
    if (b >= 0 && b < LAPN) {
        g_lap_us[b] += t - g_lap_last;
        g_lap_n[b]  += 1;
    }
    g_lap_last = now_us();
    return 0.0;
}

EXP double __cdecl nat_lap_reset(void)
{
    int i;
    g_calls += 1;
    for (i = 0; i < LAPN; i++) { g_lap_us[i] = 0; g_lap_n[i] = 0; }
    g_lap_last = now_us();
    return 0.0;
}

EXP double __cdecl nat_lap_dump(const char *path)
{
    FILE *f;
    int i, n = 0;
    g_calls += 1;
    if (!path) return -1.0;
    f = fopen(path, "wb");
    if (!f) return -2.0;
    for (i = 0; i < LAPN; i++) {
        if (g_lap_n[i] == 0) continue;
        fprintf(f, "%d %.1f %.0f\n", i, g_lap_us[i], g_lap_n[i]);
        n++;
    }
    fclose(f);
    return (double)n;
}

/* Cost of one nat_lap body, measured by the same clock it uses. Deliberately
 * NOT the cost a GML caller pays -- that is this plus external_call's own
 * crossing, measured at 0.79 us + 0.027 us per argument.
 * The two are added when the calibration is applied. */
EXP double __cdecl nat_lap_ovh(void)
{
    double t0, t1;
    int i;
    const int N = 20000;
    g_calls += 1;
    t0 = now_us();
    for (i = 0; i < N; i++) nat_lap(LAPN - 1);
    t1 = now_us();
    g_lap_us[LAPN - 1] = 0; g_lap_n[LAPN - 1] = 0;
    return (t1 - t0) / (double)N;
}

/* ------------------------------------------- per-call overhead, by arity
 * These are the whole point.  Each returns a function of its arguments so a
 * correct result proves the arguments arrived, and each bumps g_calls so the
 * caller can assert the loop really made N crossings.                       */

EXP double __cdecl nop0(void) { g_calls += 1; return 1.0; }

EXP double __cdecl nop1(double a) { g_calls += 1; return a; }

EXP double __cdecl nop2(double a, double b) { g_calls += 1; return a + b; }

EXP double __cdecl nop4(double a, double b, double c, double d)
{ g_calls += 1; return a + b + c + d; }

EXP double __cdecl nop8(double a, double b, double c, double d,
                        double e, double f, double g, double h)
{ g_calls += 1; return a + b + c + d + e + f + g + h; }

EXP double __cdecl nop11(double a, double b, double c, double d, double e,
                         double f, double g, double h, double i, double j,
                         double k)
{ g_calls += 1; return a + b + c + d + e + f + g + h + i + j + k; }

/* One extra beyond GM7's ceiling, so the DLL side is never the reason a
 * 12-argument define fails. */
EXP double __cdecl nop12(double a, double b, double c, double d, double e,
                         double f, double g, double h, double i, double j,
                         double k, double l)
{ g_calls += 1; return a + b + c + d + e + f + g + h + i + j + k + l; }

/* A realistic quad sink: what a batching renderer would actually do per
 * sprite -- store 11 doubles into a C array.  Measured against nop11 this
 * separates GM's dispatch cost from the work the DLL would really do.       */
EXP double __cdecl push11(double x, double y, double ang, double xs, double ys,
                          double u0, double v0, double u1, double v1,
                          double col, double alpha)
{
    g_calls += 1;
    if (g_vtx_n + 11 <= sizeof(g_vtx) / sizeof(g_vtx[0])) {
        double *p = &g_vtx[g_vtx_n];
        p[0] = x; p[1] = y; p[2] = ang; p[3] = xs; p[4] = ys;
        p[5] = u0; p[6] = v0; p[7] = u1; p[8] = v1; p[9] = col; p[10] = alpha;
        g_vtx_n += 11;
    }
    g_quads += 1;
    g_quad_sum += x + y;
    return g_quads;
}

EXP double __cdecl push_reset(void) { g_calls += 1; g_vtx_n = 0; g_quads = 0; g_quad_sum = 0; return 0; }
EXP double __cdecl push_count(void) { g_calls += 1; return (double)(g_vtx_n / 11); }
EXP double __cdecl push_sum(void)   { g_calls += 1; return g_quad_sum; }

/* ------------------------------------------------------------- stdcall side
 * Same bodies, __stdcall.  build.sh emits two DLLs from this file: one linked
 * with --kill-at (exports undecorated) and one without (exports carry @N), so
 * GML can be asked which name it can actually resolve.                       */

EXP double __stdcall s_nop0(void) { g_calls += 1; return 1.0; }
EXP double __stdcall s_nop2(double a, double b) { g_calls += 1; return a + b; }
EXP double __stdcall s_strlen(const char *s) { g_calls += 1; return s ? (double)strlen(s) : -1.0; }

/* ------------------------------------------------------------------ strings */

/* Argument direction: returns the length, so a right answer proves the bytes
 * crossed.  -1 means GM handed us NULL. */
EXP double __cdecl str_len(const char *s) { g_calls += 1; return s ? (double)strlen(s) : -1.0; }

/* Checksum too, so "it arrived" is not confused with "a same-length string
 * arrived". */
EXP double __cdecl str_sum(const char *s)
{
    double sum = 0;
    size_t i, n;
    g_calls += 1;
    if (!s) return -1.0;
    n = strlen(s);
    for (i = 0; i < n; i++) sum += (double)(unsigned char)s[i] * (double)((i % 7) + 1);
    return sum;
}

/* Highest byte value seen -- does anything above 0x7f survive the crossing?  */
EXP double __cdecl str_maxbyte(const char *s)
{
    unsigned char m = 0;
    size_t i, n;
    g_calls += 1;
    if (!s) return -1.0;
    n = strlen(s);
    for (i = 0; i < n; i++) if ((unsigned char)s[i] > m) m = (unsigned char)s[i];
    return (double)m;
}

/* Return direction: n bytes of a repeating pattern out of a STATIC buffer. */
EXP const char * __cdecl ret_str(double n)
{
    size_t i, k = (n <= 0) ? 0 : (size_t)n;
    char *b = retbuf();
    g_calls += 1;
    if (!b) return "";
    if (k > RETBUF) k = RETBUF;
    for (i = 0; i < k; i++) b[i] = (char)('A' + (i % 26));
    b[k] = 0;
    return b;
}

/* Same, but out of a heap block that is freed on the NEXT call.  If GML still
 * holds the right content after that next call, GM copied the string at return
 * time and a transient buffer is legal. */
EXP const char * __cdecl ret_str_heap(double n)
{
    size_t i, k = (n <= 0) ? 0 : (size_t)n;
    g_calls += 1;
    if (g_ret_heap) { free(g_ret_heap); g_ret_heap = NULL; }
    g_ret_heap = (char *)malloc(k + 1);
    if (!g_ret_heap) return "";
    for (i = 0; i < k; i++) g_ret_heap[i] = (char)('A' + (i % 26));
    g_ret_heap[k] = 0;
    return g_ret_heap;
}

/* Free the heap block WITHOUT returning a new one, so the previous return is
 * definitely dangling by the time GML reads its copy again. */
EXP double __cdecl ret_str_free(void)
{
    g_calls += 1;
    if (g_ret_heap) { free(g_ret_heap); g_ret_heap = NULL; return 1; }
    return 0;
}

/* ------------------------------------------------------- bulk string channel
 * Parse "x y ang xs ys u0 v0 u1 v1 col a  x y ..." out of one big GML string.
 * Self-times so the caller can separate the crossing from the parse.        */
EXP double __cdecl parse_packed(const char *s)
{
    double t0, v;
    long n = 0;
    char *end;
    g_calls += 1;
    if (!s) return -1.0;
    t0 = now_us();
    while (*s) {
        v = strtod(s, &end);
        if (end == s) { s++; continue; }
        s = end;
        if (n < (long)(sizeof(g_vtx) / sizeof(g_vtx[0]))) g_vtx[n] = v;
        n++;
    }
    g_last_us = now_us() - t0;
    return (double)n;
}

/* ------------------------------------------------------------ state / memory */

EXP double __cdecl state_set(double v) { g_calls += 1; g_state = v; return v; }
EXP double __cdecl state_get(void)     { g_calls += 1; return g_state; }

EXP double __cdecl mem_alloc(double n)
{
    size_t i, k = (n <= 0) ? 0 : (size_t)n;
    g_calls += 1;
    if (g_mem) { free(g_mem); g_mem = NULL; g_mem_n = 0; }
    g_mem = (unsigned char *)malloc(k);
    if (!g_mem) return -1.0;
    g_mem_n = k;
    for (i = 0; i < k; i++) g_mem[i] = (unsigned char)(i * 31u + 7u);
    return (double)k;
}

/* Re-walk the block on a LATER call: a right checksum proves the allocation
 * survived between crossings. */
EXP double __cdecl mem_check(void)
{
    double sum = 0;
    size_t i;
    g_calls += 1;
    if (!g_mem) return -1.0;
    for (i = 0; i < g_mem_n; i++) sum += (double)g_mem[i];
    return sum;
}

/* --------------------------------------------------------------- threading */

static DWORD WINAPI ticker(LPVOID p)
{
    (void)p;
    for (;;) { InterlockedIncrement(&g_thread_ticks); Sleep(10); }
}

EXP double __cdecl thread_start(void)
{
    DWORD id;
    g_calls += 1;
    if (g_thread) return 0.0;                       /* already running */
    g_thread = CreateThread(NULL, 0, ticker, NULL, 0, &id);
    return g_thread ? 1.0 : -1.0;
}

EXP double __cdecl thread_ticks(void) { g_calls += 1; return (double)g_thread_ticks; }

/* --------------------------------------------------------------- filesystem */

/* Bulk-read, not fgetc: this exists to price the FILE channel against the GML
 * one, and a locked stdio call per byte would make the answer mostly stdio lock
 * overhead rather than the transfer being measured. */
EXP double __cdecl file_read(const char *path)
{
    unsigned char buf[16 * 1024];   /* automatic: keeps it out of .bss */
    FILE *f;
    long n = 0;
    size_t got, i;
    double sum = 0;
    g_calls += 1;
    if (!path) return -1.0;
    f = fopen(path, "rb");
    if (!f) return -2.0;
    while ((got = fread(buf, 1, sizeof buf, f)) > 0) {
        for (i = 0; i < got; i++) sum += (double)buf[i];
        n += (long)got;
    }
    fclose(f);
    g_file_sum = sum;
    return (double)n;
}

EXP double __cdecl file_sum(void) { g_calls += 1; return g_file_sum; }

/* Write a file from native code, so the DLL->game direction is proven too. */
EXP double __cdecl file_write(const char *path)
{
    FILE *f;
    g_calls += 1;
    if (!path) return -1.0;
    f = fopen(path, "wb");
    if (!f) return -2.0;
    fprintf(f, "written by bsfnat.dll calls=%.0f state=%.3f\n", g_calls, g_state);
    fclose(f);
    return 1.0;
}

/* Where is the DLL's cwd?  Decides whether relative paths from GML and from C
 * mean the same directory. */
EXP const char * __cdecl nat_cwd(void)
{
    char *b = retbuf();
    g_calls += 1;
    if (!b) return "";
    if (!GetCurrentDirectoryA(MAX_PATH, b)) b[0] = 0;
    return b;
}

/* Memory-mapped-file channel: map a file the game wrote, so the transfer is a
 * page mapping rather than a copy through a GML string. */
static HANDLE g_mapf = INVALID_HANDLE_VALUE, g_maph = NULL;
static void  *g_mapv = NULL;
static size_t g_mapn = 0;

EXP double __cdecl map_open(const char *path)
{
    DWORD sz;
    g_calls += 1;
    if (g_mapv) { UnmapViewOfFile(g_mapv); g_mapv = NULL; }
    if (g_maph) { CloseHandle(g_maph); g_maph = NULL; }
    if (g_mapf != INVALID_HANDLE_VALUE) { CloseHandle(g_mapf); g_mapf = INVALID_HANDLE_VALUE; }
    if (!path) return -1.0;
    g_mapf = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                         NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (g_mapf == INVALID_HANDLE_VALUE) return -2.0;
    sz = GetFileSize(g_mapf, NULL);
    if (!sz) return -3.0;
    g_maph = CreateFileMappingA(g_mapf, NULL, PAGE_READONLY, 0, 0, NULL);
    if (!g_maph) return -4.0;
    g_mapv = MapViewOfFile(g_maph, FILE_MAP_READ, 0, 0, 0);
    if (!g_mapv) return -5.0;
    g_mapn = sz;
    return (double)sz;
}

/* Re-read the mapping: after the first touch the pages are resident, so this
 * is the steady-state cost of the channel. */
EXP double __cdecl map_sum(void)
{
    double t0, sum = 0;
    size_t i;
    g_calls += 1;
    if (!g_mapv) return -1.0;
    t0 = now_us();
    for (i = 0; i < g_mapn; i++) sum += (double)((unsigned char *)g_mapv)[i];
    g_last_us = now_us() - t0;
    return sum;
}

/* ================================================== cursor cache (IAT hook)
 *
 * Why this exists, and why it is an import hook rather than GML.
 *
 * `mouse_x` is not a variable, it is a getter (0x00523DA0). Its implementation
 * (0x0049E158) calls the cursor helper 0x00466414 TWICE -- once per coordinate
 * -- and `mouse_y` (0x00523DBC -> 0x0049E19C) repeats all of it independently,
 * so reading the pair is FOUR cursor round-trips. 0x00466414 is
 *
 *     call 0x00407D8C   ; the GetCursorPos import thunk, IAT slot 0x005FA87C
 *     call 0x0040FB40   ; ScreenToClient, the client-area transform
 *
 * and under wine every GetCursorPos is an unconditional `wine_server_call` --
 * a wineserver IPC round-trip with no fast path -- plus an X11 driver
 * round-trip whenever the cursor has been IDLE for more than 100 ms
 * (dlls/win32u/input.c, get_cursor_pos; the cache is inverted, so a still
 * cursor is the expensive case). That is 176 us a read against 0.78 us for an
 * ordinary global, and BSF performs 453 per-frame reads across 75 events.
 *
 * Caching this in GML is not possible. `object_event_add` APPENDS to a stock
 * event rather than replacing it (verified in-game twice), so
 * a mod can never remove the stock reads -- only add more.
 *
 * Hooking the IMPORT fixes every caller at once and caches exactly the
 * expensive half: GM still runs its own view transform on every read, so
 * mouse_x stays correct while the camera scrolls and zooms. Only the OS cursor
 * position is held, and only until the next tick.
 *
 * Everything here fails SAFE. If the module, the export or the IAT slot cannot
 * be found, or VirtualProtect refuses, nothing is written and the game runs
 * stock. With the hook installed, `enable = 0` passes straight through to the
 * real function, which is what makes an interleaved A/B possible inside one
 * session instead of across two launches.
 */

typedef BOOL (WINAPI *GCP_FN)(LPPOINT);
typedef BOOL (WINAPI *STC_FN)(HWND, LPPOINT);
typedef BOOL (WINAPI *SCP_FN)(int, int);

#define CUR_MAXSLOT 8

static GCP_FN g_gcp_real = NULL;
static STC_FN g_stc_real = NULL;
static SCP_FN g_scp_real = NULL;
static int    g_cur_on    = 0;      /* hook installed                        */
static int    g_cur_en    = 1;      /* caching active (0 = pass through)     */
static int    g_cur_stc   = 1;      /* cache ScreenToClient as well          */
static int    g_gcp_slots = 0, g_stc_slots = 0, g_scp_slots = 0;
static double g_gcp_calls = 0, g_gcp_real_n = 0;
static double g_stc_calls = 0, g_stc_real_n = 0;
static double g_scp_calls = 0;
static POINT  g_gcp_pt;
static int    g_gcp_valid = 0;
static DWORD  g_gcp_stamp = 0;
static DWORD  g_cur_ttl   = 100;    /* ms; a SAFETY NET, not the mechanism   */
static POINT  g_stc_in, g_stc_out;
static HWND   g_stc_hwnd  = NULL;
static int    g_stc_valid = 0;
static unsigned g_gcp_va[CUR_MAXSLOT], g_stc_va[CUR_MAXSLOT], g_scp_va[CUR_MAXSLOT];

/* ------------------------------------------------------------ verify mode
 * The substitution happens at exactly one place: what GetCursorPos returns.
 * If the value handed back is the value the real call would have returned,
 * then everything downstream -- GM's view transform, every hover test, every
 * tooltip, every pixel -- is identical BY CONSTRUCTION, and no pixel diff is
 * needed to establish it.
 *
 * So verify mode answers the only question that matters, directly: on every
 * cached return, also make the real call and compare. It is deliberately
 * slower than not caching at all; it is a diagnostic, never a shipping mode. */
static int    g_cur_verify = 0;
static double g_ver_n = 0, g_ver_bad = 0;
static long   g_ver_maxdx = 0, g_ver_maxdy = 0;

static BOOL WINAPI hook_gcp(LPPOINT p)
{
    DWORD now;
    if (!p) return FALSE;
    g_gcp_calls += 1;
    if (!g_cur_en) { g_gcp_real_n += 1; return g_gcp_real(p); }
    now = GetTickCount();
    /* The TTL exists only so a game that stops ticking -- a room change, a mod
     * that failed to load, a modal dialog -- cannot freeze the cursor forever.
     * The real invalidation is nat_cursor_tick(), once per frame. */
    if (g_gcp_valid && (DWORD)(now - g_gcp_stamp) < g_cur_ttl) {
        *p = g_gcp_pt;
        if (g_cur_verify) {
            POINT live;
            g_ver_n += 1;
            if (g_gcp_real(&live)) {
                long dx = live.x - g_gcp_pt.x, dy = live.y - g_gcp_pt.y;
                if (dx || dy) {
                    g_ver_bad += 1;
                    if (dx < 0) dx = -dx;
                    if (dy < 0) dy = -dy;
                    if (dx > g_ver_maxdx) g_ver_maxdx = dx;
                    if (dy > g_ver_maxdy) g_ver_maxdy = dy;
                }
            }
        }
        return TRUE;
    }
    g_gcp_real_n += 1;
    if (!g_gcp_real(p)) return FALSE;
    g_gcp_pt = *p; g_gcp_valid = 1; g_gcp_stamp = now;
    return TRUE;
}

/* Keyed on the exact input point AND the window, so this returns a cached
 * answer only for a question already asked with the same arguments. The one
 * way it can diverge is a window that moves between two reads inside a single
 * tick, which the tick itself bounds. */
static BOOL WINAPI hook_stc(HWND h, LPPOINT p)
{
    if (!p) return FALSE;
    g_stc_calls += 1;
    if (g_cur_en && g_cur_stc && g_stc_valid && h == g_stc_hwnd
        && p->x == g_stc_in.x && p->y == g_stc_in.y) {
        *p = g_stc_out;
        return TRUE;
    }
    g_stc_in = *p;
    g_stc_real_n += 1;
    if (!g_stc_real(h, p)) return FALSE;
    g_stc_hwnd = h; g_stc_out = *p; g_stc_valid = 1;
    return TRUE;
}

/* SetCursorPos passes through, then stamps the cache with the value just set.
 *
 * This is a correctness hook, not a performance one. Under wine SetCursorPos
 * settles ASYNCHRONOUSLY: a GetCursorPos in the same frame returns the old
 * position, or a half-updated one -- measured in ShipMaker, a warp to
 * (1920,1079) read back as (1920,600) immediately after the call and as the
 * full pre-warp position later in the same step, going coherent only on the
 * next frame. ShipMaker's drag code warps the cursor to the window centre
 * every step and re-anchors on `mxprevious = mouse_x` right after -- with a
 * stale read-back, the anchor is the PRE-warp position and the next frame
 * applies the whole warp jump as if the user had moved the mouse: new parts
 * teleport off-screen and drags snap back. Stamping the cache here makes every
 * same-frame read return the warp target by definition; by the time the next
 * tick re-reads the real cursor, wine has settled.
 *
 * The ScreenToClient cache is a pure function of its inputs, not of the
 * cursor, so it needs no invalidation here. */
static BOOL WINAPI hook_scp(int x, int y)
{
    BOOL ok;
    g_scp_calls += 1;
    ok = g_scp_real(x, y);
    if (ok) {
        g_gcp_pt.x = x; g_gcp_pt.y = y;
        g_gcp_valid = 1; g_gcp_stamp = GetTickCount();
    }
    return ok;
}

/* Rewrite every import thunk in the MAIN module whose current value is `real`.
 * Matching on the resolved address rather than on the import NAME catches
 * ordinal imports and duplicate descriptors alike, and cannot be fooled by a
 * forwarder. Returns the number of slots patched, or a negative error. */
static int patch_iat(void *real, void *hook, unsigned *va, int max)
{
    HMODULE mod = GetModuleHandleA(NULL);
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)mod;
    IMAGE_NT_HEADERS *nt;
    IMAGE_IMPORT_DESCRIPTOR *imp;
    DWORD rva;
    int n = 0;

    if (!mod || dos->e_magic != IMAGE_DOS_SIGNATURE) return -1;
    nt = (IMAGE_NT_HEADERS *)((char *)mod + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return -2;
    rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return -3;

    for (imp = (IMAGE_IMPORT_DESCRIPTOR *)((char *)mod + rva); imp->Name; imp++) {
        void **thunk = (void **)((char *)mod + imp->FirstThunk);
        for (; *thunk; thunk++) {
            DWORD old;
            if (*thunk != real) continue;
            if (!VirtualProtect(thunk, sizeof(void *), PAGE_READWRITE, &old)) continue;
            *thunk = hook;
            VirtualProtect(thunk, sizeof(void *), old, &old);
            if (n < max) va[n] = (unsigned)(UINT_PTR)thunk;
            n++;
        }
    }
    return n;
}

/* Install. Idempotent, and a no-op that reports failure rather than a partial
 * state: if the GetCursorPos slot cannot be patched, the ScreenToClient one is
 * not touched either. */
EXP double __cdecl nat_cursor_hook(double ttl_ms)
{
    HMODULE u32;
    g_calls += 1;
    if (g_cur_on) return 1.0;
    u32 = GetModuleHandleA("user32.dll");
    if (!u32) u32 = LoadLibraryA("user32.dll");
    if (!u32) return -1.0;
    g_gcp_real = (GCP_FN)(void *)GetProcAddress(u32, "GetCursorPos");
    g_stc_real = (STC_FN)(void *)GetProcAddress(u32, "ScreenToClient");
    g_scp_real = (SCP_FN)(void *)GetProcAddress(u32, "SetCursorPos");
    if (!g_gcp_real) return -2.0;
    g_cur_ttl = (ttl_ms > 0) ? (DWORD)ttl_ms : 100;
    g_gcp_slots = patch_iat((void *)g_gcp_real, (void *)hook_gcp, g_gcp_va, CUR_MAXSLOT);
    if (g_gcp_slots <= 0) return -3.0;
    if (g_stc_real)
        g_stc_slots = patch_iat((void *)g_stc_real, (void *)hook_stc, g_stc_va, CUR_MAXSLOT);
    if (g_scp_real)
        g_scp_slots = patch_iat((void *)g_scp_real, (void *)hook_scp, g_scp_va, CUR_MAXSLOT);
    g_cur_on = 1;
    return 1.0;
}

/* 1 = cache, 0 = pass straight through to user32. The hook stays installed
 * either way, so the two arms of an A/B differ by one predictable branch and
 * nothing else. */
EXP double __cdecl nat_cursor_enable(double on) { g_calls += 1; g_cur_en = (on != 0); return g_cur_en; }
EXP double __cdecl nat_cursor_stc(double on)    { g_calls += 1; g_cur_stc = (on != 0); return g_cur_stc; }

/* Drop the cached position. Called once per frame from GML; the next
 * GetCursorPos after it is a real one. */
EXP double __cdecl nat_cursor_tick(void)
{
    g_calls += 1;
    g_gcp_valid = 0;
    g_stc_valid = 0;
    return g_gcp_calls;
}

EXP double __cdecl nat_cursor_stat(double which)
{
    int i = (int)which;
    /* deliberately NOT counted: reading the counters must not move them */
    switch (i) {
    case 0:  return (double)g_cur_on;
    case 1:  return (double)g_gcp_slots;
    case 2:  return (double)g_stc_slots;
    case 3:  return g_gcp_calls;
    case 4:  return g_gcp_real_n;
    case 5:  return g_stc_calls;
    case 6:  return g_stc_real_n;
    case 7:  return (double)g_gcp_va[0];
    case 8:  return (double)g_cur_en;
    case 9:  return (double)g_cur_ttl;
    case 10: return (double)g_stc_va[0];
    case 11: return (double)g_cur_stc;
    case 12: return g_ver_n;                /* cached returns checked        */
    case 13: return g_ver_bad;              /* ...of which disagreed         */
    case 14: return (double)g_ver_maxdx;    /* worst disagreement, screen px */
    case 15: return (double)g_ver_maxdy;
    case 16: return (double)g_cur_verify;
    case 17: return (double)g_gcp_pt.x;     /* the cursor last handed out    */
    case 18: return (double)g_gcp_pt.y;
    case 19: return (double)g_scp_slots;
    case 20: return g_scp_calls;
    case 21: return (double)g_scp_va[0];
    default: return -1.0;
    }
}

EXP double __cdecl nat_cursor_verify(double on)
{ g_calls += 1; g_cur_verify = (on != 0); return g_cur_verify; }

EXP double __cdecl nat_cursor_reset(void)
{
    g_calls += 1;
    g_gcp_calls = 0; g_gcp_real_n = 0;
    g_stc_calls = 0; g_stc_real_n = 0;
    g_ver_n = 0; g_ver_bad = 0; g_ver_maxdx = 0; g_ver_maxdy = 0;
    return 0.0;
}

/* Put the original addresses back. Only useful for a teardown test -- the game
 * is normally left hooked for its lifetime. */
EXP double __cdecl nat_cursor_unhook(void)
{
    g_calls += 1;
    if (!g_cur_on) return 0.0;
    patch_iat((void *)hook_gcp, (void *)g_gcp_real, g_gcp_va, CUR_MAXSLOT);
    if (g_stc_real)
        patch_iat((void *)hook_stc, (void *)g_stc_real, g_stc_va, CUR_MAXSLOT);
    if (g_scp_real)
        patch_iat((void *)hook_scp, (void *)g_scp_real, g_scp_va, CUR_MAXSLOT);
    g_cur_on = 0; g_gcp_valid = 0; g_stc_valid = 0;
    return 1.0;
}

/* --------------------------------------------------------------- DllMain */

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID reserved)
{
    (void)h; (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        QueryPerformanceFrequency(&g_freq);
        QueryPerformanceCounter(&g_base);
        if (!g_freq.QuadPart) g_freq.QuadPart = 1;
    }
    return TRUE;
}
