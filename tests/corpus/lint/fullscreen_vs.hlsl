// Trivial vertex shader with no resources: nothing should be reported.
struct VSOut { float4 pos : SV_Position; float2 uv : TEXCOORD0; };

VSOut main(uint id : SV_VertexID)
{
    VSOut o;
    o.uv = float2((id << 1) & 2, id & 2);
    o.pos = float4(o.uv * 2.0 - 1.0, 0.0, 1.0);
    return o;
}
