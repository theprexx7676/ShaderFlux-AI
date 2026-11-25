// Non-square matrices: dimension order differs between HLSL and GLSL.
[[vk::binding(0, 0)]] cbuffer Bones
{
    row_major float3x4 boneTransforms[64];
};

float3 main(float4 position : POSITION, uint bone : BLENDINDICES) : POSITION1
{
    return mul(boneTransforms[bone], position);
}
