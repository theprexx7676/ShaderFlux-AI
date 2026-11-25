# Releasing

`main` is protected: every change, including a release, lands through a pull request with green checks.

1. **Prepare on the working branch.** Bump `version` in `pyproject.toml` (the package reads its version from the installed metadata, so that is the only place). Move the `[Unreleased]` notes in `CHANGELOG.md` under a new `## [x.y.z] - date` heading. Update any `@vX.Y.Z` / `rev: vX.Y.Z` pins in `README.md`, `examples/workflows/lint-shaders.yml`, `.pre-commit-hooks.yaml`, `docs/tutorial-first-port.md` and the template in `src/shaderflux/workflows/init_project.py` (a test keeps the last two in step).
2. **Check the build, not only the tests.** `uv build`, install the wheel into a fresh virtual environment, and run `shaderflux --version`, `shaderflux explain INT001` (reads a bundled data file) and `shaderflux translate <glsl> --to hlsl --repair --dry-run` (reads the bundled prompts). Check that the sdist contains the same data files.
3. **Open the pull request, wait for every job, merge.**
4. **Tag the merge commit** and push the tag: `git tag -a vX.Y.Z -m "ShaderFlux-AI X.Y.Z" <merge commit> && git push origin vX.Y.Z`.
   Some restricted environments (cloud coding sessions, for example) refuse tag pushes with HTTP 403. In that case create the tag from a normal clone, or create the release in the GitHub web UI (Releases, "Draft a new release", choose or create the tag on the merge commit); the next step then runs the same way.
5. **Check the tag from the outside:** in a clean environment run `pip install "git+https://github.com/theprexx7676/ShaderFlux-AI.git@vX.Y.Z"` and `shaderflux --version`; run `pre-commit try-repo https://github.com/theprexx7676/ShaderFlux-AI shaderflux-lint --rev vX.Y.Z --files <a shader>`.
6. **Create the GitHub Release** from the tag and paste the changelog section as the notes.

Publishing to PyPI is a separate decision (it needs an account that owns the `shaderflux` name). Until then every install hint points at the GitHub repository; see `install_hint` in `src/shaderflux/llm/anthropic_provider.py`.
