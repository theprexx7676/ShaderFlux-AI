#version 450
layout(location=0) in vec3 position;
layout(set=0,binding=0,std140) uniform U {
    mat4 colMajor;                       // default
    layout(row_major) mat4 rowMajor;     // explicit
    mat2x3 rect;                         // 2 columns, 3 rows
} u;
void main(){
    vec4 p = vec4(position,1.0);
    gl_Position = u.colMajor * p;                 // matrix * vector
    gl_Position += p * u.colMajor;                // vector * matrix
    gl_Position += u.rowMajor * p;
    vec3 r = u.rect * vec2(1.0, 2.0);
    gl_Position.xyz += r;
}
