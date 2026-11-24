#version 450
layout(set=0,binding=0) uniform U { mat4 m; vec4 a; vec4 b; } u;
layout(location=0) out vec4 o;
void main(){
    mat4 inv = inverse(u.m);
    vec4 r = mod(u.a, u.b) + round(u.a) + roundEven(u.a) + fma(u.a,u.b,u.a) + vec4(float(gl_VertexIndex));
    o = inv * r + vec4(inversesqrt(u.a.x)) + fract(u.a) + mix(u.a,u.b,0.5);
    gl_Position = o;
}
