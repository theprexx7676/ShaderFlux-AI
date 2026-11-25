#version 450
layout(location=0) in vec2 uv;
layout(location=1) flat in int mode;
layout(location=0) out vec4 color;
layout(set=0,binding=0) uniform Params { mat4 mvp; vec4 tint; float weights[4]; } p;
layout(set=0,binding=1) uniform texture2D tex;
layout(set=0,binding=2) uniform sampler samp;
layout(set=1,binding=0) uniform sampler2D combined;
layout(set=1,binding=1, rgba8) uniform readonly image2D img;
layout(set=2,binding=0, std430) buffer Data { float values[]; } data;
layout(push_constant) uniform Push { vec4 offset; } pc;
void main(){ color = texture(sampler2D(tex,samp), uv) * p.tint + texture(combined, uv) + imageLoad(img, ivec2(0)) + vec4(data.values[0]) + pc.offset + vec4(float(mode)); }
