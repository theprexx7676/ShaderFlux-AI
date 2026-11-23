#version 450
layout(location=0) in vec2 uv;
layout(location=0) out vec4 color;
layout(set=0,binding=1) uniform sampler2D tex;
layout(set=0,binding=0) uniform Params { mat4 mvp; vec4 tint; } p;
void main(){ color = texture(tex, uv) * p.tint; }
