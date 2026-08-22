#include <windows.h>
#include <d3d9.h>

/* The D3D9 half of bsfshader.dll.
 *
 * A separate translation unit because d3d8.h and d3d9.h both define
 * D3D_SDK_VERSION (220 vs 32) and cannot be included together.  Every D3D9 call
 * the extension makes lives here; the boundary is plain `void *`. */

int caps9_read(void *p, unsigned *ps, unsigned *vs, unsigned *maxw, unsigned *nrt)
{
    IDirect3DDevice9 *dev = (IDirect3DDevice9 *) p;
    D3DCAPS9 c;
    if (FAILED(IDirect3DDevice9_GetDeviceCaps(dev, &c))) return 0;
    *ps = c.PixelShaderVersion; *vs = c.VertexShaderVersion;
    *maxw = c.MaxTextureWidth;  *nrt = c.NumSimultaneousRTs;
    return 1;
}

int d9_create_ps(void *p, const void *code, void **out)
{
    IDirect3DPixelShader9 *sh = NULL;
    HRESULT hr = IDirect3DDevice9_CreatePixelShader((IDirect3DDevice9 *) p, (const DWORD *) code, &sh);
    if (FAILED(hr)) return (int) hr;
    *out = sh;
    return 0;
}

int d9_set_ps(void *p, void *sh)
{
    return SUCCEEDED(IDirect3DDevice9_SetPixelShader((IDirect3DDevice9 *) p, (IDirect3DPixelShader9 *) sh));
}

int d9_set_const(void *p, unsigned reg, const float *v)
{
    return SUCCEEDED(IDirect3DDevice9_SetPixelShaderConstantF((IDirect3DDevice9 *) p, reg, v, 1));
}

void d9_release_ps(void *sh)
{
    if (sh) IDirect3DPixelShader9_Release((IDirect3DPixelShader9 *) sh);
}
