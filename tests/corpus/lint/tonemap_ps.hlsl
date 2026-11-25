// Post-process. Explicit bindings; uses functions that differ between languages.
[[vk::binding(0, 0)]] Texture2D hdrColor;
[[vk::binding(1, 0)]] SamplerState pointSampler;
[[vk::binding(2, 0)]] cbuffer Settings { float exposure; float levels; float2 pad; };

float4 main(float2 uv : TEXCOORD0) : SV_Target
{
    float3 c = hdrColor.Sample(pointSampler, uv).rgb * exposure;
    c = c / (1.0 + c);
    float3 quantised = round(c * levels) / levels;
    float wrapped = fmod(uv.x * 10.0, 1.0);
    return float4(quantised * wrapped, 1.0);
}
