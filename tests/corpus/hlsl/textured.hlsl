cbuffer Params : register(b0)
{
    float4x4 mvp;
    float4 tint;
};

Texture2D tex : register(t1);
SamplerState samp : register(s1);

float4 main(float2 uv : TEXCOORD0) : SV_Target
{
    return tex.Sample(samp, uv) * tint;
}
