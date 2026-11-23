# Contributing to ShaderFlux-AI

Thanks for helping. This project is pre-release, so the best contributions are
small, tested, and tied to a task in [docs/PLAN.md](docs/PLAN.md).

## Setup

You need Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/theprexx7676/ShaderFlux-AI.git
cd ShaderFlux-AI
make setup        # creates .venv, installs dev dependencies and pre-commit hooks
make check        # lint + type check + unit tests
```

Without `make`: `uv venv && uv pip install -e ".[dev]"`, then run `ruff`, `mypy`
and `pytest` from the virtual environment.

## Tests

- `make test` runs the fast unit tests. No network, no external tools.
- Tests that need real shader tools use `@pytest.mark.needs_tools`; tests that
  need a real LLM key use `@pytest.mark.needs_llm`. These are skipped by default
  and must never be required for CI on pull requests.
- Every bug fix gets a test that fails without the fix.

## Code style

- `ruff` for lint and formatting (line length 100), `mypy --strict` for `src/`.
- Prefer small functions and typed models over dictionaries.
- Never call external tools through a shell. Use the subprocess runner (plan phase 2).

## Commits and pull requests

- One logical change per commit. Imperative subject line ("Add DXC backend").
- Reference the plan task ID in the PR description (for example `2.5.3`).
- Update `CHANGELOG.md` and the docs when behaviour changes.
- Open the PR as a draft until `make check` passes.

## Adding a test shader (corpus)

The corpus lives in `tests/corpus/` (see plan phase 10). Rules:

1. The shader must be **your own work** or under a permissive license that
   allows redistribution, with attribution recorded in the manifest.
2. **No proprietary, NDA-covered or console-SDK code.** Not even a snippet.
3. Keep it small and focused on one behaviour, and say what the expected
   outcome is.

## Reporting problems

Use the issue templates. For porting problems, a minimal shader is worth more
than a long description.
