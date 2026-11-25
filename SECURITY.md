# Security Policy

## Supported versions

The project is in early development. Only the latest release (0.1.x) and the `main` branch receive fixes.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Use GitHub's private vulnerability reporting for this repository
(Security tab, "Report a vulnerability"). Include:

- what you found and the impact,
- steps or a minimal shader to reproduce it,
- the output of `shaderflux doctor --json` once that command exists.

You should get an acknowledgement within a few days. Please give us a
reasonable time to fix the issue before public disclosure.

## Areas of particular interest

- Command execution and argument handling for external compilers.
- Path traversal through `#include` resolution or output paths.
- Leaking of secrets (API keys) or private files into logs, reports or LLM requests.
- Prompt injection through shader source that changes tool behaviour.
