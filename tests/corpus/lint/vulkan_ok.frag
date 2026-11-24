#version 450
// The same shader written for Vulkan GLSL: a false positive here is a bug.
layout(set = 0, binding = 0) uniform Params { float gain; };
layout(set = 0, binding = 1) uniform sampler2D albedo;
layout(location = 0) in vec2 uv;
layout(location = 0) out vec4 color;

void main() {
    color = texture(albedo, uv) * gain;
}
