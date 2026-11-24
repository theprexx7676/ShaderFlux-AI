// b0 and t0 are different HLSL slots but the same Vulkan binding under DXC's default mapping.
cbuffer Params : register(b0)
{
    float4x4 mvp;
    float4 tint;
};

Texture2D albedo : register(t0);
Texture2D normals : register(t1);
SamplerState samp : register(s0);
RWStructuredBuffer<float> output : register(u0);

float4 main(float2 uv : TEXCOORD0) : SV_Target
{
    output[0] = 1.0;
    return albedo.Sample(samp, uv) * tint + normals.Sample(samp, uv);
}
