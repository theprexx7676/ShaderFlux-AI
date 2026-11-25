"""Snippets for the Vulkan GLSL rules, shared by the unit test and the real-glslang test.

Each case is ``(name, stage extension, source, rules we expect)``. The integration test checks the
same table against glslangValidator: a shader we flag must be rejected, one we do not flag must
compile. That makes the table evidence about glslang, not only about our own rules.
"""

from __future__ import annotations

OUT = "layout(location = 0) out vec4 c;\n"
MAIN = "void main() { c = vec4(1.0); }\n"
H = "#version 450\n"

CASES: list[tuple[str, str, str, frozenset[str]]] = [
    ("block ok", "frag", H + "layout(set = 0, binding = 0) uniform U { float gain; };\n" + OUT
     + "void main() { c = vec4(gain); }\n", frozenset()),
    ("loose uniform", "frag", H + "uniform float gain;\n" + OUT
     + "void main() { c = vec4(gain); }\n", frozenset({"VKG002"})),
    ("loose uniform array", "frag", H + "uniform vec4 k[4];\n" + OUT
     + "void main() { c = k[1]; }\n", frozenset({"VKG002"})),
    ("sampler without binding", "frag", H + "uniform sampler2D tex;\n" + OUT
     + "void main() { c = texture(tex, vec2(0.0)); }\n", frozenset({"VKG003"})),
    ("sampler with binding", "frag", H + "layout(binding = 0) uniform sampler2D tex;\n" + OUT
     + "void main() { c = texture(tex, vec2(0.0)); }\n", frozenset()),
    ("binding on the previous line", "frag",
     H + "layout(set = 0, binding = 1)\nuniform sampler2D tex;\n" + OUT
     + "void main() { c = texture(tex, vec2(0.0)); }\n", frozenset()),
    ("sampler array with binding", "frag",
     H + "layout(binding = 0) uniform sampler2D texs[4];\n" + OUT
     + "void main() { c = texture(texs[1], vec2(0.0)); }\n", frozenset()),
    ("separate texture and sampler ok", "frag",
     H + "layout(binding = 0) uniform texture2D t;\nlayout(binding = 1) uniform sampler s;\n" + OUT
     + "void main() { c = texture(sampler2D(t, s), vec2(0.0)); }\n", frozenset()),
    ("separate texture without binding", "frag",
     H + "uniform texture2D t;\nlayout(binding = 1) uniform sampler s;\n" + OUT
     + "void main() { c = texture(sampler2D(t, s), vec2(0.0)); }\n", frozenset({"VKG003"})),
    ("storage image without binding", "frag",
     H + "layout(rgba8) uniform image2D img;\n" + OUT
     + "void main() { c = imageLoad(img, ivec2(0)); }\n", frozenset({"VKG003"})),
    ("input without location", "frag", H + "layout(location = 0) out vec4 c;\nin vec2 uv;\n"
     + "void main() { c = vec4(uv, 0.0, 1.0); }\n", frozenset({"VKG004"})),
    ("output without location", "frag", H + "out vec4 c;\n" + "void main() { c = vec4(1.0); }\n",
     frozenset({"VKG004"})),
    ("flat input with location", "frag",
     H + "layout(location = 1) flat in int idx;\n" + OUT
     + "void main() { c = vec4(float(idx)); }\n",
     frozenset()),
    ("precision qualifier", "frag",
     H + "layout(location = 1) in highp vec2 uv;\n" + OUT + "void main() { c = vec4(uv, 0, 1); }\n",
     frozenset()),
    ("location on the previous line", "frag",
     H + "layout(location = 1)\nin vec2 uv;\n" + OUT + "void main() { c = vec4(uv, 0, 1); }\n",
     frozenset()),
    ("input block with location", "frag",
     H + "layout(location = 1) in VS { vec2 uv; } vin;\n" + OUT
     + "void main() { c = vec4(vin.uv, 0, 1); }\n", frozenset()),
    ("input block without location", "frag",
     H + "in VS { vec2 uv; } vin;\n" + OUT + "void main() { c = vec4(vin.uv, 0, 1); }\n",
     frozenset({"VKG004"})),
    ("function parameters named in/out", "frag",
     H + OUT + "float f(in float x, out float y) { y = x; return x; }\n"
     + "void main() { float y; c = vec4(f(1.0, y) + y); }\n", frozenset()),
    ("push constants", "frag",
     H + "layout(push_constant) uniform PC { float k; } pc;\n" + OUT
     + "void main() { c = vec4(pc.k); }\n", frozenset()),
    ("constant global", "frag", H + "const float PI = 3.14159;\n" + OUT
     + "void main() { c = vec4(PI); }\n", frozenset()),
    ("compute local size", "comp", H + "layout(local_size_x = 8) in;\nvoid main() {}\n",
     frozenset()),
    ("vertex id", "vert", H + "void main() { gl_Position = vec4(float(gl_VertexID), 0, 0, 1); }\n",
     frozenset({"VKG001"})),
    ("instance id", "vert",
     H + "void main() { gl_Position = vec4(float(gl_InstanceID), 0, 0, 1); }\n",
     frozenset({"VKG001"})),
    ("vertex index", "vert",
     H + "void main() { gl_Position = vec4(float(gl_VertexIndex + gl_InstanceIndex), 0, 0, 1); }\n",
     frozenset()),
    ("old name only in a comment", "vert",
     H + "// gl_VertexID was renamed\nvoid main() { gl_Position = vec4(float(gl_VertexIndex)"
     + ", 0, 0, 1); }\n", frozenset()),
    ("gl_PerVertex redeclared", "vert",
     H + "out gl_PerVertex { vec4 gl_Position; };\nvoid main() { gl_Position = vec4(1.0); }\n",
     frozenset()),
]  # fmt: skip
