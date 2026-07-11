#!/usr/bin/env bash
set -euo pipefail

hermes_home="${HERMES_HOME:-${HOME}/.hermes}"
python_bin="${MEMORY_OS_PYTHON_BIN:-python3}"

exec "${python_bin}" "${hermes_home}/scripts/memory_os_ragflow_readonly_probe.py" \
  --hermes-home "${hermes_home}" \
  --output json
