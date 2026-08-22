// Ship decloak -- the classic sci-fi materialise.
//
//   p.x  progress, 0 = fully cloaked, 1 = fully solid
//   p.y  time in seconds (drives the shimmer; independent of progress)
//   p.z  ripple amplitude, in UV units at full cloak
//   uvr  the sprite's UV rect: xy = min, zw = max
//
// WHY uvr EXISTS.  GM pads a sprite's texture up to a power of two when the
// device demands it, and its UVs then stop at imageWidth/textureWidth rather
// than at 1.  Past that edge there is exactly ONE texel of edge replication and
// then uninitialised heap that was uploaded to the texture along with the image
// (D3D8-INTEROP.md 2.3, read out of the runner at 0x004A49A0-0x004A4A53).  Any
// shader that MOVES uv can walk into that, and it would show up as garbage
// pixels along one edge of a distorted sprite -- so the rect is passed in and
// the warped coordinate is clamped to it.  Measured on this device the rect is
// the full 0..1 (no padding is applied), but a shader that only works because
// of that is one device away from being wrong.
// ⚠ NO sin().  wine's HLSL compiler (vkd3d-shader) refuses it for every d3dbc
// target -- ps_1_x through ps_3_0, which it calls "SM1":
//     E5017: Aborting due to not yet implemented feature: SM1 "sin" expression
// The shader compiles to nothing and sh_compile returns an error, which is at
// least loud.  This parabolic wave is the replacement: frac() is `frc`, a real
// ps_2_0 instruction, and abs() is a source modifier, so it costs a handful of
// ALU ops.  4t(1-|t|) over t in -1..1 peaks at +-1, hits zero at the wrap, and
// is C1 across it -- close enough to a sine that nothing downstream can tell.
float wave(float cycles)
{
    float t = frac(cycles) * 2.0 - 1.0;
    return 4.0 * t * (1.0 - abs(t));
}

sampler2D s0  : register(s0);
float4    p   : register(c0);
float4    uvr : register(c1);

float4 main(float2 uv : TEXCOORD0, float4 diff : COLOR0) : COLOR0
{
    float k = 1.0 - p.x;                     // 1 = cloaked, 0 = solid

    // --- 1. warp: two travelling bands across the hull, dying out as it forms
    float w = wave(uv.y * 6.0 + p.y * 1.1) * 0.55
            + wave(uv.y * 2.1 - p.y * 0.5) * 0.45;
    float2 uv2 = clamp(uv + float2(w * p.z * k, 0.0), uvr.xy, uvr.zw);

    float4 c = tex2D(s0, uv2) * diff;        // the fixed-function stage, warped

    // --- 2. ghost: throw the hue away while it is still forming
    float  l     = dot(c.rgb, float3(0.30, 0.59, 0.11));
    float3 ghost = float3(l * 0.25, l * 0.85, l * 1.45);
    c.rgb = lerp(c.rgb, ghost, k);

    // --- 3. the materialising band: a bright edge that sweeps along the hull
    //        exactly once over the transition
    float span  = max(uvr.w - uvr.y, 1e-5);
    float where = (uv.y - uvr.y) / span;
    float sweep = saturate(1.0 - abs(where - p.x) * 5.0);

    // --- 4. fade in.  Alpha is the honest fade for a normally-blended sprite.
    //
    // ⚠ The sweep MULTIPLIES the sampled alpha, it is never ADDED to it. Adding
    // it lit up the sprite's transparent margin as well as the sprite, and every
    // part came with a faint rectangle around it -- the texture's bounding box,
    // drawn in shimmer. Multiplying leaves a transparent texel transparent, so
    // the band can only appear where the ship actually is.
    c.a   = c.a * saturate(p.x + sweep * k * 1.60);
    c.rgb = c.rgb + ghost * sweep * k * 1.60;

    return c;
}
