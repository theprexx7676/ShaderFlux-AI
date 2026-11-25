#version 330 core
// An OpenGL fragment shader as people write it: all three Vulkan-GLSL traps in one file.
uniform float gain;
uniform sampler2D albedo;
in vec2 uv;
out vec4 color;

void main() {
    color = texture(albedo, uv) * gain;
}
