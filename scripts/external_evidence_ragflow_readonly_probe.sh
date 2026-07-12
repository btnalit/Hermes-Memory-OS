#!/usr/bin/env bash
set -euo pipefail

hermes_home="${HERMES_HOME:-${HOME}/.hermes}"
python_bin="${MEMORY_OS_PYTHON_BIN:-python3}"

set +e
"${python_bin}" "${hermes_home}/scripts/memory_os_ragflow_readonly_probe.py" \
  --hermes-home "${hermes_home}" \
  --output json
status=$?
set -e

# Provider-disabled is a healthy optional-boundary state for cron.  Preserve
# the JSON status for observability while reserving non-zero for real failure.
if [[ "${status}" -eq 1 ]]; then
  exit 0
fi
exit "${status}"
