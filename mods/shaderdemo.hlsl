// Stage 3 demo shader.
//
// p.x = 0  ->  exact passthrough: this must reproduce the fixed-function stage
//              GM's sprite quad uses (sample stage 0, modulate by the vertex
//              colour), so a frame drawn with it bound has to match a frame
//              drawn with no shader at all.  That equality is the real test.
// p.x = 1  ->  full heat ramp.
sampler2D s0 : register(s0);
float4    p  : register(c0);

float4 main(float2 uv : TEXCOORD0, float4 diff : COLOR0) : COLOR0
{
    float4 c   = tex2D(s0, uv) * diff;
    float  l   = dot(c.rgb, float3(0.30, 0.59, 0.11));
    float3 hot = float3(l * 1.4, l * 0.45, l * 0.15);
    return float4(lerp(c.rgb, hot, p.x), c.a);   // alpha through, or blending breaks
}
