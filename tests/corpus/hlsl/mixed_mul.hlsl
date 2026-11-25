cbuffer Camera : register(b0)
{
    float4x4 viewProj;       // no explicit layout
    row_major float4x4 world;
};

float4 main(float4 position : POSITION) : SV_Position
{
    float4 a = mul(position, world);       // vector on the left
    float4 b = mul(viewProj, position);    // vector on the right
    float4 c = mul(transpose(viewProj), a);
    return a + b + c;
}
