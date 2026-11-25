cbuffer Camera : register(b0)
{
    row_major float4x4 viewProj;
    row_major float4x4 world;
};

float4 main(float4 position : POSITION) : SV_Position
{
    return mul(mul(position, world), viewProj);
}
