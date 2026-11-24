// Bindings are separated by space, so no collision. The matrix handling is the problem.
cbuffer Light : register(b0, space0)
{
    float4x4 lightViewProj;
    float4x4 invViewProj;
};

Texture2D shadowMap : register(t0, space1);
SamplerComparisonState shadowSampler : register(s0, space2);

float4 main(float4 worldPos : TEXCOORD0, float4 clip : TEXCOORD1) : SV_Target
{
    float4 lightPos = mul(worldPos, lightViewProj);   // vector * matrix
    float4 world = mul(invViewProj, clip);            // matrix * vector
    float2 uv = lightPos.xy / lightPos.w * 0.5 + 0.5;
    float lit = shadowMap.SampleCmp(shadowSampler, uv, lightPos.z / lightPos.w);
    return float4(lit.xxx, 1.0) * (world.w > 0 ? 1.0 : 0.5);
}
