// Vertex skinning. Valid HLSL; b0 and t0 collide under DXC's default Vulkan mapping.
cbuffer Scene : register(b0)
{
    row_major float4x4 viewProj;
    row_major float4x4 world;
};

StructuredBuffer<float4x4> bones : register(t0);

struct VSIn
{
    float3 position : POSITION;
    uint4 boneIds : BLENDINDICES;
    float4 weights : BLENDWEIGHT;
};

float4 main(VSIn input) : SV_Position
{
    float4 p = float4(input.position, 1.0);
    float4 skinned = mul(p, bones[input.boneIds.x]) * input.weights.x
                   + mul(p, bones[input.boneIds.y]) * input.weights.y
                   + mul(p, bones[input.boneIds.z]) * input.weights.z
                   + mul(p, bones[input.boneIds.w]) * input.weights.w;
    return mul(mul(skinned, world), viewProj);
}
