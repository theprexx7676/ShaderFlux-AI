// Separable blur. Texture t0, UAV u0 and constant buffer b0 all land on binding 0.
cbuffer Params : register(b0)
{
    float2 direction;
    int radius;
    int pad;
};

Texture2D<float4> source : register(t0);
RWTexture2D<float4> destination : register(u0);

[numthreads(8, 8, 1)]
void main(uint3 id : SV_DispatchThreadID)
{
    float4 sum = 0;
    for (int i = -radius; i <= radius; ++i)
    {
        sum += source.Load(int3(id.xy + int2(direction * i), 0));
    }
    destination[id.xy] = sum / (2 * radius + 1);
}
