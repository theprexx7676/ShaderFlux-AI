#version 450
layout(location = 0) out vec4 color;
#ifndef TINT
#error TINT must be defined
#endif
void main() { color = vec4(TINT); }
