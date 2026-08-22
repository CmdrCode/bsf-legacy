// Second shader for mods/shaderspr.gml -- deliberately nothing like the first.
//
// mods/shaderdemo.hlsl pushes a sprite towards orange; this one pushes it
// towards cold cyan, so a frame carrying both proves more than "a shader ran":
// it proves the runner's one-DrawPrimitiveUP-per-sprite model lets a DIFFERENT
// shader be live for each sprite inside a single frame.
//
// p.x = 0 -> passthrough, p.x = 1 -> full cloak.
sampler2D s0 : register(s0);
float4    p  : register(c0);

float4 main(float2 uv : TEXCOORD0, float4 diff : COLOR0) : COLOR0
{
    float4 c    = tex2D(s0, uv) * diff;
    float  l    = dot(c.rgb, float3(0.30, 0.59, 0.11));
    float3 cold = float3(l * 0.20, l * 0.85, l * 1.35);
    return float4(lerp(c.rgb, cold, p.x), c.a);   // alpha through, or blending breaks
}
