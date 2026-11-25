# Launch and growth plan

Goal: get ShaderFlux-AI in front of the people who port shaders, earn their trust,
and grow stars as a *result* of being useful. Do not buy or trade stars; it gets
repositories flagged and destroys trust.

You only get one first impression on each community. Do not post until the
"ready to launch" list below is true.

## Ready to launch (all must be true)

- [ ] **HLSL input verified against a real DXC.** Most people porting have HLSL. A launch that only works for GLSL will disappoint them. (Plan Phase 2.5.)
- [x] **One headline feature people can see in 30 seconds.** `shaderflux lint` catches colliding bindings, mixed `mul` order and risky matrix layouts, with `shaderflux explain` for the why. Built; it still needs a real DXC to confirm the fix flags it prints.
- [ ] **A recorded terminal demo** (GIF or asciinema, under 30 seconds) at the top of the README.
- [ ] **Install works in one command** (`pipx install shaderflux` or a Docker image) on Linux, macOS and Windows. (Plan Phase 12.)
- [ ] **CI is green** and the badge is real.
- [ ] **3 to 5 `good first issue` tickets** open, each small and clearly described.
- [ ] **Honest limits written down** (already in the README). Developers forgive limits; they do not forgive hidden ones.
- [ ] **Two or three real ports** tried and written up as short case studies in `docs/`.

## Repository settings (done by you in GitHub)

- Description: "Port shaders to PC faster: HLSL/GLSL/SPIR-V translation with porting-risk checks and LLM-assisted fixes, verified by real compilers."
- Topics: `shader`, `hlsl`, `glsl`, `spir-v`, `vulkan`, `directx`, `gamedev`, `graphics-programming`, `transpiler`, `llm`, `cli`.
- A social preview image (1280x640): the tool name and a before/after code snippet.
- Enable Discussions for questions, so Issues stay for bugs.
- Pin the "good first issue" list in the README.

## What makes it shareable

1. **A concrete, painful problem.** "Your matrices are silently transposed after porting" is more shareable than "a shader transpiler".
2. **A before/after people can understand without reading code.**
3. **Real results.** A small benchmark table (translation success rate, how many failures the LLM fixed) beats adjectives. (Plan Phase 10.)
4. **A short write-up of what you learned**, for example "What SPIRV-Cross does to your matrices" (the evidence is already in the plan). Technical posts about real findings travel further than announcements.

## Where to post (check each community's self-promotion rules first)

Typical places for graphics and game developers: r/GraphicsProgramming, r/gamedev, r/vulkan, Hacker News (Show HN), Lobsters, the Graphics Programming Discord, Khronos and Vulkan community channels, and Mastodon or X with graphics-dev hashtags.

- Post where you can answer questions for the next day or two.
- Lead with the problem and the demo, not the AI. Many developers are sceptical of AI tools; "verified by real compilers, LLM only for the hard parts" is the honest and stronger pitch.
- Be upfront about what is not done yet.

## After launch

- Reply to every issue within a day if you can.
- Turn each good bug report into a corpus test and a fix, and say so publicly.
- Ship small releases often and keep the changelog readable.
- Track: stars, clones, issues opened, issues closed, and, more importantly, "it worked on my shader" reports.

## What not to do

- No fake stars, star-for-star trades, or bot accounts.
- No claims that are not true yet ("exact rendering output", "supports console shaders").
- No NDA or console SDK code anywhere, ever.
