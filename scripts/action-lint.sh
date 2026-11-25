#!/usr/bin/env bash
# Runs `shaderflux lint` for the GitHub Action (action.yml). Kept as a script so it can be tested.
#
# Inputs come from environment variables, never from string interpolation into the
# command line, so a malicious input cannot inject shell commands:
#   INPUT_PATHS       space-separated shader files or globs (required)
#   INPUT_FAIL_ON     error | warning | note | never        (default: error)
#   INPUT_TARGET      vulkan | any                          (default: vulkan)
#   INPUT_SARIF_FILE  where to write SARIF                  (default: shaderflux.sarif)
set -euo pipefail

paths="${INPUT_PATHS:-}"
fail_on="${INPUT_FAIL_ON:-error}"
target="${INPUT_TARGET:-vulkan}"
sarif="${INPUT_SARIF_FILE:-shaderflux.sarif}"

if [[ -z "$paths" ]]; then
  echo "error: the 'paths' input is required" >&2
  exit 2
fi
case "$fail_on" in error | warning | note | never) ;; *)
  echo "error: fail-on must be error, warning, note or never (got '$fail_on')" >&2
  exit 2
  ;;
esac
case "$target" in vulkan | any) ;; *)
  echo "error: target must be vulkan or any (got '$target')" >&2
  exit 2
  ;;
esac

# Split the space-separated patterns WITHOUT letting the shell expand them: bash 3.2 (the macOS
# default) has no `**`, and Windows shells expand nothing. `shaderflux lint` expands globs itself.
set -f
read -r -a patterns <<<"$paths"
set +f
if [[ ${#patterns[@]} -eq 0 ]]; then
  echo "error: the 'paths' input is required" >&2
  exit 2
fi
echo "shaderflux: checking ${patterns[*]}"

# 1. Always write the SARIF file first, so it can be uploaded even when the check fails.
shaderflux lint "${patterns[@]}" --target "$target" --fail-on never --sarif >"$sarif"
echo "shaderflux: wrote $sarif"

# 2. Human-readable output in the log; its exit code decides whether the job fails.
shaderflux lint "${patterns[@]}" --target "$target" --fail-on "$fail_on"
