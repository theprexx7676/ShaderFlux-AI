// Compensates a layout mismatch with transpose() per pixel.
cbuffer Camera : register(b0, space0)
{
    float4x4 viewProj;
};

float4 main(float4 position : POSITION) : SV_Position
{
    return mul(transpose(viewProj), position);
}
