// Clean: explicit Vulkan bindings, explicit matrix layout, one mul convention.
struct VSOut { float4 pos : SV_Position; float3 normal : NORMAL; float2 uv : TEXCOORD0; };

[[vk::binding(0, 0)]] cbuffer Frame
{
    row_major float4x4 viewProj;
    float3 cameraPos;
    float pad0;
};
[[vk::binding(1, 0)]] Texture2D albedoTex;
[[vk::binding(2, 0)]] Texture2D normalTex;
[[vk::binding(3, 0)]] SamplerState linearSampler;

float3 fresnelSchlick(float cosTheta, float3 f0)
{
    return f0 + (1.0 - f0) * pow(saturate(1.0 - cosTheta), 5.0);
}

float4 main(VSOut input) : SV_Target
{
    float3 albedo = albedoTex.Sample(linearSampler, input.uv).rgb;
    float3 n = normalize(input.normal);
    float3 v = normalize(cameraPos - input.pos.xyz);
    float3 f = fresnelSchlick(max(dot(n, v), 0.0), float3(0.04, 0.04, 0.04));
    return float4(lerp(albedo, f, 0.1), 1.0);
}
