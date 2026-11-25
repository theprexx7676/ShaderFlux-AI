#version 450
layout(set = 0, binding = 0) uniform Params { mat4 viewProj; vec4 value; } p;
layout(location = 0) in vec4 clip;
layout(location = 0) out vec4 color;
void main() {
    vec4 world = inverse(p.viewProj) * clip;
    color = mod(world, p.value);
}
