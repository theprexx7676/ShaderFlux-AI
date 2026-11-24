# Privacy: what leaves your machine

ShaderFlux-AI does most of its work locally. **Only one feature sends anything
over the network: `shaderflux translate --repair`**, and only when a shader fails
to compile. It is off by default and needs the optional `ai` extra
(`pip install "shaderflux[ai]"`): a plain install does not contain the Anthropic SDK at all.

## What is sent

When `--repair` is given and the shader does not compile, the following goes to the
Anthropic API:

- the source of the shader you are translating,
- the source of files it `#include`s (as read-only context),
- the compiler's error messages for that shader,
- fixed instructions (the prompts in `src/shaderflux/llm/prompts/`).

## What is never sent

- environment variables, your API key's value, or your home directory path,
- files that the shader does not `#include`, even in the same folder,
- absolute paths (files are named by their short file name),
- anything at all when you do not pass `--repair`, or when the shader compiles.

A test (`test_includes_are_read_only_context_and_nothing_else_is_sent`) checks that
a neighbouring file that is not included never appears in a request.

## See it before you send it

```bash
shaderflux translate shader.frag --to hlsl --repair --dry-run
```

prints exactly the text that would be sent and sends nothing.

## Your API key

Read from the `ANTHROPIC_API_KEY` environment variable (or an `ant auth login`
profile) by the Anthropic SDK. It is never written to a config file; a config file
that contains one is rejected. Do not use `--repair` on code you are not allowed to
share with a third party.

## What the model can and cannot do

The model only *proposes* edits as small line replacements. The tool checks that
each edit matches the file, rejects edits to any file other than the shader (include
files are read-only), limits how much can change, and applies the result to a copy.
The real compiler then decides whether it worked. Your original file is never
modified; use `--write-fixed FILE` to save the corrected source, and review the diff
that is printed.

## Not built yet

Comment and string redaction before sending, and a cost estimate, are planned
(see `docs/PLAN.md`, tasks 5.6.3 and 5.7).
