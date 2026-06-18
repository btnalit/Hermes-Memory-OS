#!/usr/bin/env bash
set -euo pipefail

# Safe interactive installer for Memory-OS Agent OS.
#
# The script checks the existing Hermes home, lets the operator choose which
# parts to install or enable, and delegates actual file writes to the Python
# installer. The script does not restart hermes-gateway.service, does not delete
# Memory-OS data, and does not run cleanup or shadow-journal apply.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

YES=0
DRY_RUN=0
SKIP_VERIFY=0
ALLOW_CREATE=0
MODE="interactive"
HERMES_HOME_INPUT="${HERMES_HOME:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RUNTIME_INTERVAL="${RUNTIME_INTERVAL:-5min}"
COGNITIVE_LOOP_INTERVAL="${COGNITIVE_LOOP_INTERVAL:-6h}"
OWNER_REVIEW_CRON_SCHEDULE="${OWNER_REVIEW_CRON_SCHEDULE:-0 9 * * *}"
OWNER_REVIEW_CRON_DELIVER="${OWNER_REVIEW_CRON_DELIVER:-auto}"
OWNER_REVIEW_CRON_OWNER="${OWNER_REVIEW_CRON_OWNER:-owner}"
OWNER_REVIEW_CRON_CHANNEL="${OWNER_REVIEW_CRON_CHANNEL:-auto}"
OWNER_CRON_PROFILE="${OWNER_CRON_PROFILE:-active-closure}"
DEEP_REFLECTION_PRESET="${DEEP_REFLECTION_PRESET:-}"
MEMORY_SOURCES_PRESET="${MEMORY_SOURCES_PRESET:-}"
LLM_JUDGE_PRESET="${LLM_JUDGE_PRESET:-}"
HINDSIGHT_MODE="${HINDSIGHT_MODE:-auto}"

INSTALL_SHELL=""
ENABLE_PROVIDER=""
ENABLE_SHELL=""
INSTALL_SYSTEM_MODULES=""
INSTALL_RUNTIME=""
ENABLE_RUNTIME=""
INSTALL_COGNITIVE_LOOP=""
ENABLE_COGNITIVE_LOOP=""
INSTALL_OWNER_REVIEW_CRON_HELPER=""
ENABLE_OWNER_CRON_ONBOARDING=""
ENABLE_OWNER_REVIEW_CRON=""
INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=""
ENABLE_RIGHT_BRAIN_EXPRESSION_CRON=""
RIGHT_BRAIN_EXPRESSION_CRON_SCHEDULE="${RIGHT_BRAIN_EXPRESSION_CRON_SCHEDULE:-30 4 * * 0}"
RIGHT_BRAIN_EXPRESSION_CRON_DELIVER="${RIGHT_BRAIN_EXPRESSION_CRON_DELIVER:-origin}"

usage() {
  cat <<'USAGE'
Usage: scripts/install_memory_os.sh [options]

Safe installer for Memory-OS Agent OS.

Options:
  --hermes-home PATH            Target existing Hermes home.
  --yes, -y                     Accept defaults / run non-interactively.
  --operational                 Product-style one-command install: install and
                                enable provider, shell, runtime, module
                                runtime, cognitive loop, and active-closure
                                Hermes cron onboarding with owner channel
                                autodetect.
  --test-host                   Test-host defaults: install and enable all
                                Memory-OS pieces with DeepReflection test-host.
  --production-safe             Production-safe defaults with DeepReflection
                                explicitly disabled.
  --deep-reflection-preset NAME none|production-safe|observe|auto-bounded|test-host|operational.
  --memory-sources-preset NAME none|production-safe|test-host|operational.
  --llm-judge-preset NAME      active|none|report-only|bounded-vote. Low-clue
                                recall LLM judge; default active reuses Hermes
                                provider/model config in bounded-vote mode.
  --hindsight MODE             auto|off|adopt|active|wizard. Default: auto.
                                auto adopts a new Hindsight config into shadow
                                mode and preserves an already-active adoption;
                                active enables retain/recall/reflect for a
                                controlled live cutover.
  --runtime-interval VALUE      Heartbeat timer interval. Default: 5min.
  --cognitive-loop-interval VALUE
                                Cognitive-loop integration harness interval. Default: 6h.
  --no-install-shell            Do not install memory-os-agent-os shell plugin.
  --no-enable-shell             Do not add memory-os-agent-os to plugins.enabled.
  --no-install-system-modules   Do not install portable L2-L4 runtime modules.
  --no-install-runtime          Do not write heartbeat wrapper/systemd artifacts.
  --no-enable-runtime           Do not enable heartbeat timer.
  --no-install-cognitive-loop   Do not write cognitive-loop wrapper/systemd artifacts.
  --no-enable-cognitive-loop    Do not enable cognitive-loop timer.
  --install-owner-review-cron-helper
                                Copy the Memory-OS owner review helper and
                                explicit recurring-enable gate to
                                HERMES_HOME/scripts. Does not create or enable
                                a cron job.
  --install-right-brain-expression-cron-helper
                                Copy the Memory-OS right-brain expression helper
                                and explicit recurring-enable gate to
                                HERMES_HOME/scripts. Does not create or enable
                                a cron job.
  --enable-owner-cron-onboarding
                                Enable Memory-OS active-closure Hermes cron
                                onboarding. Owner-facing deliver targets are
                                auto-detected from Hermes channel_directory.
  --no-enable-owner-cron-onboarding
                                Do not create/enable Memory-OS Hermes cron jobs.
  --owner-cron-profile VALUE    active-closure|full. Default: active-closure.
                                active-closure creates owner review digest,
                                proposal follow-up OpsGate, and baseline local
                                index sync jobs. full also creates optional
                                feedback/right-brain/report jobs.
  --right-brain-expression-cron-schedule VALUE
                                Hermes cron schedule. Default: 30 4 * * 0
  --right-brain-expression-cron-deliver VALUE
                                Hermes cron --deliver target. Default: origin.
  --owner-review-cron-schedule VALUE
                                Hermes cron schedule. Default: 0 9 * * *
  --owner-review-cron-deliver VALUE
                                Hermes cron --deliver target. Default: auto.
                                auto is resolved by the onboarding script from
                                Hermes channel_directory.json.
  --owner-review-cron-owner VALUE
                                Owner id used by the digest helper. Default: owner
  --owner-review-cron-channel VALUE
                                Channel label for active digest binding.
                                Default: auto, derived from --owner-review-cron-deliver.
  --dry-run                     Print installer report without writing.
  --skip-verify                 Skip post-install verification commands.
  --allow-create                Allow creating HERMES_HOME if it does not exist.
  --help                        Show this help.

The script does not restart hermes-gateway.service.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home)
      HERMES_HOME_INPUT="${2:?missing --hermes-home value}"
      shift 2
      ;;
    --yes|-y)
      YES=1
      shift
      ;;
    --operational)
      MODE="operational"
      YES=1
      DEEP_REFLECTION_PRESET="${DEEP_REFLECTION_PRESET:-operational}"
      MEMORY_SOURCES_PRESET="${MEMORY_SOURCES_PRESET:-operational}"
      LLM_JUDGE_PRESET="${LLM_JUDGE_PRESET:-active}"
      ENABLE_OWNER_CRON_ONBOARDING=1
      INSTALL_OWNER_REVIEW_CRON_HELPER=1
      INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=1
      shift
      ;;
    --test-host)
      MODE="test-host"
      YES=1
      DEEP_REFLECTION_PRESET="${DEEP_REFLECTION_PRESET:-test-host}"
      MEMORY_SOURCES_PRESET="${MEMORY_SOURCES_PRESET:-test-host}"
      LLM_JUDGE_PRESET="${LLM_JUDGE_PRESET:-active}"
      shift
      ;;
    --production-safe)
      MODE="production-safe"
      DEEP_REFLECTION_PRESET="${DEEP_REFLECTION_PRESET:-production-safe}"
      MEMORY_SOURCES_PRESET="${MEMORY_SOURCES_PRESET:-production-safe}"
      LLM_JUDGE_PRESET="${LLM_JUDGE_PRESET:-active}"
      shift
      ;;
    --deep-reflection-preset)
      DEEP_REFLECTION_PRESET="${2:?missing --deep-reflection-preset value}"
      shift 2
      ;;
    --memory-sources-preset)
      MEMORY_SOURCES_PRESET="${2:?missing --memory-sources-preset value}"
      shift 2
      ;;
    --llm-judge-preset)
      LLM_JUDGE_PRESET="${2:?missing --llm-judge-preset value}"
      shift 2
      ;;
    --hindsight)
      HINDSIGHT_MODE="${2:?missing --hindsight value}"
      shift 2
      ;;
    --runtime-interval)
      RUNTIME_INTERVAL="${2:?missing --runtime-interval value}"
      shift 2
      ;;
    --cognitive-loop-interval)
      COGNITIVE_LOOP_INTERVAL="${2:?missing --cognitive-loop-interval value}"
      shift 2
      ;;
    --no-install-shell)
      INSTALL_SHELL=0
      shift
      ;;
    --no-enable-shell)
      ENABLE_SHELL=0
      shift
      ;;
    --no-install-system-modules)
      INSTALL_SYSTEM_MODULES=0
      shift
      ;;
    --no-install-runtime)
      INSTALL_RUNTIME=0
      ENABLE_RUNTIME=0
      shift
      ;;
    --no-enable-runtime)
      ENABLE_RUNTIME=0
      shift
      ;;
    --no-install-cognitive-loop)
      INSTALL_COGNITIVE_LOOP=0
      ENABLE_COGNITIVE_LOOP=0
      shift
      ;;
    --no-enable-cognitive-loop)
      ENABLE_COGNITIVE_LOOP=0
      shift
      ;;
    --install-owner-review-cron-helper)
      INSTALL_OWNER_REVIEW_CRON_HELPER=1
      shift
      ;;
    --install-right-brain-expression-cron-helper)
      INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=1
      shift
      ;;
    --enable-owner-cron-onboarding)
      ENABLE_OWNER_CRON_ONBOARDING=1
      INSTALL_OWNER_REVIEW_CRON_HELPER=1
      INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=1
      shift
      ;;
    --no-enable-owner-cron-onboarding)
      ENABLE_OWNER_CRON_ONBOARDING=0
      shift
      ;;
    --enable-owner-review-cron)
      ENABLE_OWNER_CRON_ONBOARDING=1
      ENABLE_OWNER_REVIEW_CRON=1
      INSTALL_OWNER_REVIEW_CRON_HELPER=1
      shift
      ;;
    --no-enable-owner-review-cron)
      ENABLE_OWNER_CRON_ONBOARDING=0
      ENABLE_OWNER_REVIEW_CRON=0
      shift
      ;;
    --enable-right-brain-expression-cron)
      ENABLE_OWNER_CRON_ONBOARDING=1
      ENABLE_RIGHT_BRAIN_EXPRESSION_CRON=1
      INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=1
      shift
      ;;
    --no-enable-right-brain-expression-cron)
      ENABLE_OWNER_CRON_ONBOARDING=0
      ENABLE_RIGHT_BRAIN_EXPRESSION_CRON=0
      shift
      ;;
    --right-brain-expression-cron-schedule)
      RIGHT_BRAIN_EXPRESSION_CRON_SCHEDULE="${2:?missing --right-brain-expression-cron-schedule value}"
      shift 2
      ;;
    --right-brain-expression-cron-deliver)
      RIGHT_BRAIN_EXPRESSION_CRON_DELIVER="${2:?missing --right-brain-expression-cron-deliver value}"
      shift 2
      ;;
    --owner-review-cron-schedule)
      OWNER_REVIEW_CRON_SCHEDULE="${2:?missing --owner-review-cron-schedule value}"
      shift 2
      ;;
    --owner-cron-profile)
      OWNER_CRON_PROFILE="${2:?missing --owner-cron-profile value}"
      case "${OWNER_CRON_PROFILE}" in
        active-closure|full) ;;
        *)
          echo "Invalid --owner-cron-profile: ${OWNER_CRON_PROFILE}" >&2
          exit 2
          ;;
      esac
      shift 2
      ;;
    --owner-review-cron-deliver)
      OWNER_REVIEW_CRON_DELIVER="${2:?missing --owner-review-cron-deliver value}"
      shift 2
      ;;
    --owner-review-cron-owner)
      OWNER_REVIEW_CRON_OWNER="${2:?missing --owner-review-cron-owner value}"
      shift 2
      ;;
    --owner-review-cron-channel)
      OWNER_REVIEW_CRON_CHANNEL="${2:?missing --owner-review-cron-channel value}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-verify)
      SKIP_VERIFY=1
      shift
      ;;
    --allow-create)
      ALLOW_CREATE=1
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

add_candidate() {
  local candidate="$1"
  [[ -n "${candidate}" ]] || return 0
  candidate="$(cd -- "${candidate}" 2>/dev/null && pwd || true)"
  [[ -n "${candidate}" ]] || return 0
  local existing
  for existing in "${HERMES_HOME_CANDIDATES[@]:-}"; do
    [[ "${existing}" == "${candidate}" ]] && return 0
  done
  HERMES_HOME_CANDIDATES+=("${candidate}")
}

discover_hermes_homes() {
  HERMES_HOME_CANDIDATES=()
  [[ -d "${HERMES_HOME_INPUT:-}" ]] && add_candidate "${HERMES_HOME_INPUT}"
  [[ -d "${HOME}/.hermes" ]] && add_candidate "${HOME}/.hermes"
  [[ -d "/root/.hermes" ]] && add_candidate "/root/.hermes"
}

select_hermes_home() {
  if [[ -n "${HERMES_HOME_INPUT}" ]]; then
    if [[ -d "${HERMES_HOME_INPUT}" || "${ALLOW_CREATE}" == "1" ]]; then
      mkdir -p "${HERMES_HOME_INPUT}"
      HERMES_HOME="$(cd -- "${HERMES_HOME_INPUT}" && pwd)"
      export HERMES_HOME
      return
    fi
    echo "HERMES_HOME does not exist: ${HERMES_HOME_INPUT}" >&2
    echo "Pass --allow-create only when you intend to initialize that path." >&2
    exit 1
  fi

  discover_hermes_homes
  if [[ "${#HERMES_HOME_CANDIDATES[@]}" -eq 1 || "${YES}" == "1" ]]; then
    HERMES_HOME="${HERMES_HOME_CANDIDATES[0]:-${HOME}/.hermes}"
    if [[ ! -d "${HERMES_HOME}" && "${ALLOW_CREATE}" != "1" ]]; then
      echo "No existing Hermes home found. Pass --hermes-home or --allow-create." >&2
      exit 1
    fi
    export HERMES_HOME
    return
  fi

  echo "Detected Hermes homes:"
  local i=1
  local candidate
  for candidate in "${HERMES_HOME_CANDIDATES[@]}"; do
    echo "  ${i}) ${candidate}"
    i=$((i + 1))
  done
  echo "  ${i}) enter another path"
  read -r -p "Select Hermes home [1]: " choice
  choice="${choice:-1}"
  if [[ "${choice}" == "${i}" ]]; then
    read -r -p "Hermes home path: " custom
    HERMES_HOME_INPUT="${custom}"
    select_hermes_home
    return
  fi
  if ! [[ "${choice}" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#HERMES_HOME_CANDIDATES[@]} )); then
    echo "Invalid selection: ${choice}" >&2
    exit 1
  fi
  HERMES_HOME="${HERMES_HOME_CANDIDATES[$((choice - 1))]}"
  export HERMES_HOME
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

inspect_current_state() {
  echo "Memory-OS install preflight"
  echo "---------------------------"
  echo "repo_root=${REPO_ROOT}"
  echo "hermes_home=${HERMES_HOME}"
  echo "config_yaml=$([[ -f "${HERMES_HOME}/config.yaml" ]] && echo yes || echo no)"
  echo "provider_dir=$([[ -d "${HERMES_HOME}/plugins/memory_os" ]] && echo present || echo missing)"
  echo "shell_dir=$([[ -d "${HERMES_HOME}/plugins/memory-os-agent-os" ]] && echo present || echo missing)"
  echo "runtime_dir=$([[ -d "${HERMES_HOME}/memory-os/runtime/python" ]] && echo present || echo missing)"
  echo "cognitive_loop_unit=$([[ -f "${HERMES_HOME}/memory-os/systemd/hermes-memory-os-cognitive-loop.timer" ]] && echo present || echo missing)"

  if command_exists hermes; then
    echo
    echo "Current Hermes memory provider:"
    HERMES_HOME="${HERMES_HOME}" hermes memory || true
    echo
    echo "Current Memory-OS shell plugin entry:"
    HERMES_HOME="${HERMES_HOME}" hermes plugins list 2>/dev/null | grep -E "memory-os-agent-os|memory_os" || true
  else
    echo "WARN: hermes command not found in PATH"
  fi

  if command_exists systemctl; then
    echo
    echo "Heartbeat timer state:"
    systemctl --user show hermes-memory-os-heartbeat.timer \
      -p LoadState -p ActiveState -p SubState -p UnitFileState --no-pager 2>/dev/null || true
    echo
    echo "Cognitive loop timer state:"
    systemctl --user show hermes-memory-os-cognitive-loop.timer \
      -p LoadState -p ActiveState -p SubState -p UnitFileState --no-pager 2>/dev/null || true
  fi
  echo
  echo "The script does not restart hermes-gateway.service."
  echo
}

ask_yes_no() {
  local prompt="$1"
  local default="$2"
  local answer
  if [[ "${YES}" == "1" ]]; then
    echo "${prompt} [${default}] -> ${default}"
    [[ "${default}" == "yes" ]]
    return
  fi
  read -r -p "${prompt} [${default}] " answer
  answer="${answer:-${default}}"
  case "${answer}" in
    y|Y|yes|YES) return 0 ;;
    n|N|no|NO) return 1 ;;
    *) echo "Please answer yes or no." >&2; ask_yes_no "${prompt}" "${default}" ;;
  esac
}

choose_preset() {
  local default="$1"
  local answer
  if [[ "${YES}" == "1" ]]; then
    echo "DeepReflection preset [${default}] -> ${default}"
    DEEP_REFLECTION_PRESET="${default}"
    return
  fi
  read -r -p "DeepReflection preset [none/production-safe/observe/auto-bounded/test-host/operational] [${default}] " answer
  answer="${answer:-${default}}"
  case "${answer}" in
    none|production-safe|observe|auto-bounded|test-host|operational)
      DEEP_REFLECTION_PRESET="${answer}"
      ;;
    *)
      echo "Invalid DeepReflection preset: ${answer}" >&2
      choose_preset "${default}"
      ;;
  esac
}

choose_memory_sources_preset() {
  local default="$1"
  local answer
  if [[ "${YES}" == "1" ]]; then
    echo "Memory Sources preset [${default}] -> ${default}"
    MEMORY_SOURCES_PRESET="${default}"
    return
  fi
  read -r -p "Memory Sources preset [none/production-safe/test-host/operational] [${default}] " answer
  answer="${answer:-${default}}"
  case "${answer}" in
    none|production-safe|test-host|operational)
      MEMORY_SOURCES_PRESET="${answer}"
      ;;
    *)
      echo "Invalid Memory Sources preset: ${answer}" >&2
      choose_memory_sources_preset "${default}"
      ;;
  esac
}

choose_llm_judge_preset() {
  local default="$1"
  local answer
  if [[ "${YES}" == "1" ]]; then
    echo "Low-Clue LLM judge preset [${default}] -> ${default}"
    LLM_JUDGE_PRESET="${default}"
    return
  fi
  read -r -p "Low-Clue LLM judge preset [none/report-only/bounded-vote] [${default}] " answer
  answer="${answer:-${default}}"
  case "${answer}" in
    none|report-only|bounded-vote)
      LLM_JUDGE_PRESET="${answer}"
      ;;
    *)
      echo "Invalid Low-Clue LLM judge preset: ${answer}" >&2
      choose_llm_judge_preset "${default}"
      ;;
  esac
}

normalize_shell_enablement() {
  [[ "${INSTALL_SHELL}" == "0" ]] || return 0

  local shell_dir="${HERMES_HOME}/plugins/memory-os-agent-os"
  if [[ "${ENABLE_SHELL}" == "1" ]]; then
    if [[ -d "${shell_dir}" ]]; then
      echo "Enable existing memory-os-agent-os shell plugin -> yes"
      return 0
    fi
    echo "Cannot enable memory-os-agent-os because --no-install-shell was selected and no existing shell plugin is present at ${shell_dir}" >&2
    exit 1
  fi

  if [[ -z "${ENABLE_SHELL}" ]]; then
    if [[ -d "${shell_dir}" && "${YES}" != "1" ]]; then
      ask_yes_no "Enable existing memory-os-agent-os shell plugin?" "no" && ENABLE_SHELL=1 || ENABLE_SHELL=0
    else
      echo "Enable memory-os-agent-os in plugins.enabled? [no] -> no (--no-install-shell selected)"
      ENABLE_SHELL=0
    fi
  fi
}

select_options() {
  local default_shell="yes"
  local default_enable_provider="yes"
  local default_enable_shell="yes"
  local default_system_modules="yes"
  local default_install_runtime="yes"
  local default_enable_runtime="yes"
  local default_install_cognitive_loop="no"
  local default_enable_cognitive_loop="no"
  local default_owner_review_cron_helper="yes"
  local default_enable_owner_cron_onboarding="yes"
  local default_right_brain_expression_cron_helper="yes"
  local default_preset="production-safe"
  local default_memory_sources_preset="production-safe"
  local default_llm_judge_preset="report-only"

  if [[ "${MODE}" == "test-host" || "${MODE}" == "operational" ]]; then
    default_preset="${MODE}"
    default_memory_sources_preset="${MODE}"
    default_install_cognitive_loop="yes"
    default_enable_cognitive_loop="yes"
  fi
  if [[ "${MODE}" == "production-safe" ]]; then
    default_enable_owner_cron_onboarding="no"
  fi

  [[ -n "${INSTALL_SHELL}" ]] || { ask_yes_no "Install/update memory-os-agent-os shell plugin?" "${default_shell}" && INSTALL_SHELL=1 || INSTALL_SHELL=0; }
  normalize_shell_enablement
  [[ -n "${ENABLE_PROVIDER}" ]] || { ask_yes_no "Set memory.provider=memory_os?" "${default_enable_provider}" && ENABLE_PROVIDER=1 || ENABLE_PROVIDER=0; }
  [[ -n "${ENABLE_SHELL}" ]] || { ask_yes_no "Enable memory-os-agent-os in plugins.enabled?" "${default_enable_shell}" && ENABLE_SHELL=1 || ENABLE_SHELL=0; }
  [[ -n "${INSTALL_SYSTEM_MODULES}" ]] || { ask_yes_no "Install portable L2-L4 system modules?" "${default_system_modules}" && INSTALL_SYSTEM_MODULES=1 || INSTALL_SYSTEM_MODULES=0; }
  [[ -n "${INSTALL_RUNTIME}" ]] || { ask_yes_no "Install heartbeat runtime artifacts?" "${default_install_runtime}" && INSTALL_RUNTIME=1 || INSTALL_RUNTIME=0; }
  if [[ "${INSTALL_RUNTIME}" == "0" && -z "${ENABLE_RUNTIME}" ]]; then
    echo "Enable heartbeat timer? [no] -> no (runtime artifacts are not being installed)"
    ENABLE_RUNTIME=0
  fi
  [[ -n "${ENABLE_RUNTIME}" ]] || { ask_yes_no "Enable heartbeat timer?" "${default_enable_runtime}" && ENABLE_RUNTIME=1 || ENABLE_RUNTIME=0; }

  [[ -n "${INSTALL_COGNITIVE_LOOP}" ]] || { ask_yes_no "Install cognitive-loop integration harness runtime artifacts?" "${default_install_cognitive_loop}" && INSTALL_COGNITIVE_LOOP=1 || INSTALL_COGNITIVE_LOOP=0; }
  if [[ "${INSTALL_COGNITIVE_LOOP}" == "0" && -z "${ENABLE_COGNITIVE_LOOP}" ]]; then
    echo "Enable cognitive-loop timer? [no] -> no (cognitive-loop artifacts are not being installed)"
    ENABLE_COGNITIVE_LOOP=0
  fi
  [[ -n "${ENABLE_COGNITIVE_LOOP}" ]] || { ask_yes_no "Enable cognitive-loop integration harness timer?" "${default_enable_cognitive_loop}" && ENABLE_COGNITIVE_LOOP=1 || ENABLE_COGNITIVE_LOOP=0; }
  [[ -n "${INSTALL_OWNER_REVIEW_CRON_HELPER}" ]] || { ask_yes_no "Install owner review Hermes cron helper/gate scripts?" "${default_owner_review_cron_helper}" && INSTALL_OWNER_REVIEW_CRON_HELPER=1 || INSTALL_OWNER_REVIEW_CRON_HELPER=0; }
  [[ -n "${INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER}" ]] || { ask_yes_no "Install right-brain expression Hermes cron helper/gate scripts?" "${default_right_brain_expression_cron_helper}" && INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=1 || INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=0; }
  [[ -n "${ENABLE_OWNER_CRON_ONBOARDING}" ]] || { ask_yes_no "Enable Memory-OS active-closure Hermes cron onboarding?" "${default_enable_owner_cron_onboarding}" && ENABLE_OWNER_CRON_ONBOARDING=1 || ENABLE_OWNER_CRON_ONBOARDING=0; }
  if [[ "${ENABLE_OWNER_CRON_ONBOARDING}" == "1" ]]; then
    ENABLE_OWNER_REVIEW_CRON=1
    ENABLE_RIGHT_BRAIN_EXPRESSION_CRON=1
    INSTALL_OWNER_REVIEW_CRON_HELPER=1
    INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER=1
    resolve_owner_review_cron_deliver
    resolve_owner_review_cron_channel
    resolve_right_brain_expression_cron_deliver
  fi

  if [[ -z "${DEEP_REFLECTION_PRESET}" ]]; then
    choose_preset "${default_preset}"
  fi
  if [[ -z "${MEMORY_SOURCES_PRESET}" ]]; then
    choose_memory_sources_preset "${default_memory_sources_preset}"
  fi
  if [[ -z "${LLM_JUDGE_PRESET}" ]]; then
    choose_llm_judge_preset "${default_llm_judge_preset}"
  fi
}

resolve_owner_review_cron_deliver() {
  if [[ "${OWNER_REVIEW_CRON_DELIVER}" != "auto" ]]; then
    return 0
  fi
  echo "Owner review cron deliver target [auto] -> onboarding will detect Hermes owner channel"
}

resolve_owner_review_cron_channel() {
  case "${OWNER_REVIEW_CRON_CHANNEL}" in
    ""|"auto"|"owner_review_cron"|"unknown")
      local target="${OWNER_REVIEW_CRON_DELIVER}"
      target="${target%%:*}"
      target="${target//-/_}"
      OWNER_REVIEW_CRON_CHANNEL="${target:-unknown}"
      ;;
  esac
}

resolve_right_brain_expression_cron_deliver() {
  if [[ "${RIGHT_BRAIN_EXPRESSION_CRON_DELIVER}" != "auto" ]]; then
    return 0
  fi
  RIGHT_BRAIN_EXPRESSION_CRON_DELIVER="origin"
  echo "Right-brain expression cron deliver target [auto] -> origin"
}

require_hermes_for_selected_actions() {
  [[ "${DRY_RUN}" == "1" ]] && return 0
  command_exists hermes && return 0

  if [[ "${ENABLE_PROVIDER}" == "1" || "${ENABLE_SHELL}" == "1" || "${ENABLE_OWNER_CRON_ONBOARDING}" == "1" || "${SKIP_VERIFY}" != "1" ]]; then
    echo "ERROR: hermes command not found in PATH." >&2
    echo "Install Hermes or rerun with --skip-verify and without provider/shell enablement for file-copy-only installs." >&2
    exit 1
  fi
}

run_installer() {
  # install_runtime / enable_runtime choices are converted to Python installer flags below.
  local args=("${PYTHON_BIN}" "${REPO_ROOT}/scripts/install_memory_os_plugin.py" "--hermes-home" "${HERMES_HOME}")
  [[ "${INSTALL_SHELL}" == "0" ]] && args+=("--no-install-shell")
  [[ "${ENABLE_PROVIDER}" == "1" ]] && args+=("--enable")
  [[ "${ENABLE_SHELL}" == "1" ]] && args+=("--enable-shell")
  [[ "${INSTALL_SYSTEM_MODULES}" == "1" ]] && args+=("--install-system-modules")
  [[ "${INSTALL_RUNTIME}" == "1" ]] && args+=("--install-runtime")
  [[ "${ENABLE_RUNTIME}" == "1" ]] && args+=("--enable-runtime")
  args+=("--runtime-interval" "${RUNTIME_INTERVAL}")
  [[ "${INSTALL_COGNITIVE_LOOP}" == "1" ]] && args+=("--install-cognitive-loop")
  [[ "${ENABLE_COGNITIVE_LOOP}" == "1" ]] && args+=("--enable-cognitive-loop")
  args+=("--cognitive-loop-interval" "${COGNITIVE_LOOP_INTERVAL}")
  [[ "${INSTALL_OWNER_REVIEW_CRON_HELPER}" == "1" ]] && args+=("--install-owner-review-cron-helper")
  [[ "${INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER}" == "1" ]] && args+=("--install-right-brain-expression-cron-helper")
  if [[ "${ENABLE_OWNER_CRON_ONBOARDING}" == "1" ]]; then
    args+=(
      "--install-owner-cron-onboarding"
      "--run-owner-cron-onboarding"
      "--owner-cron-owner-approved"
      "--owner-review-deliver" "${OWNER_REVIEW_CRON_DELIVER}"
      "--right-brain-deliver" "${RIGHT_BRAIN_EXPRESSION_CRON_DELIVER}"
      "--owner-review-owner" "${OWNER_REVIEW_CRON_OWNER}"
      "--owner-review-channel" "${OWNER_REVIEW_CRON_CHANNEL}"
      "--owner-review-schedule" "${OWNER_REVIEW_CRON_SCHEDULE}"
      "--owner-cron-profile" "${OWNER_CRON_PROFILE}"
      "--right-brain-schedule" "${RIGHT_BRAIN_EXPRESSION_CRON_SCHEDULE}"
    )
  elif [[ "${INSTALL_OWNER_REVIEW_CRON_HELPER}" == "1" || "${INSTALL_RIGHT_BRAIN_EXPRESSION_CRON_HELPER}" == "1" ]]; then
    args+=("--install-owner-cron-onboarding")
  fi
  [[ -n "${DEEP_REFLECTION_PRESET}" && "${DEEP_REFLECTION_PRESET}" != "none" ]] && args+=("--deep-reflection-preset" "${DEEP_REFLECTION_PRESET}")
  [[ -n "${MEMORY_SOURCES_PRESET}" && "${MEMORY_SOURCES_PRESET}" != "none" ]] && args+=("--memory-sources-preset" "${MEMORY_SOURCES_PRESET}")
  [[ -n "${LLM_JUDGE_PRESET}" ]] && args+=("--llm-judge-preset" "${LLM_JUDGE_PRESET}")
  args+=("--hindsight" "${HINDSIGHT_MODE}")
  [[ "${DRY_RUN}" == "1" ]] && args+=("--dry-run")

  echo "Running installer:"
  printf '  %q' "${args[@]}"
  echo
  "${args[@]}"

  # Install cleanup_expired_working.py script
  local cleanup_src="${REPO_ROOT}/scripts/cleanup_expired_working.py"
  local cleanup_dst="${HERMES_HOME}/scripts/cleanup_expired_working.py"
  if [[ -f "${cleanup_src}" ]]; then
    mkdir -p "${HERMES_HOME}/scripts"
    install -m 755 "${cleanup_src}" "${cleanup_dst}"
    echo "  ✅ cleanup_expired_working.py installed to ${cleanup_dst}"
  else
    echo "  ⚠️  cleanup_expired_working.py not found at ${cleanup_src}"
  fi

	  # Install gate wrapper for working-cleanup cron
	  local cleanup_gate_src="${REPO_ROOT}/scripts/memory_os_cron_working_cleanup_gate.py"
	  local cleanup_gate_dst="${HERMES_HOME}/scripts/memory_os_cron_working_cleanup_gate.py"
	  if [[ -f "${cleanup_gate_src}" ]]; then
	    install -m 755 "${cleanup_gate_src}" "${cleanup_gate_dst}"
	    echo "  ✅ memory_os_cron_working_cleanup_gate.py installed to ${cleanup_gate_dst}"
	  else
	    echo "  ⚠️  memory_os_cron_working_cleanup_gate.py not found at ${cleanup_gate_src}"
	  fi

  # Create working memory cleanup cron (no_agent, watchdog pattern)
  if command_exists hermes && [[ "${DRY_RUN}" != "1" ]]; then
    local cron_name="memory-os-working-cleanup"
    local cron_present=0
    cron_present=$(hermes cron list 2>/dev/null | grep -c "${cron_name}" || true)
    if [[ "${cron_present}" -eq 0 ]]; then
      hermes cron create \
        --name "${cron_name}" \
        --schedule "0 3 * * 0" \
        --script cleanup_expired_working.py \
        --no-agent \
        --deliver local 2>/dev/null && \
        echo "  ✅ Cron '${cron_name}' created (Sun 03:00 CST, 7d retention)" || \
        echo "  ⚠️  Could not create cron '${cron_name}' (hermes not fully configured?)"
    else
      echo "  ✅ Cron '${cron_name}' already exists"
    fi
  fi
}

verify_install() {
  [[ "${SKIP_VERIFY}" == "1" || "${DRY_RUN}" == "1" ]] && return 0
  echo
  echo "Memory-OS install verification"
  echo "------------------------------"
  HERMES_HOME="${HERMES_HOME}" hermes memory
  HERMES_HOME="${HERMES_HOME}" \
    PYTHONPATH="${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}" \
    "${PYTHON_BIN}" -m plugins.memory.memory_os doctor
  if [[ "${INSTALL_SHELL}" == "1" ]]; then
    HERMES_HOME="${HERMES_HOME}" hermes memory-os-agent-os status >/dev/null
    HERMES_HOME="${HERMES_HOME}" hermes memory-os-agent-os doctor >/dev/null
    local default_home=""
    default_home="$(cd -- "${HOME}/.hermes" 2>/dev/null && pwd || true)"
    local target_home
    target_home="$(cd -- "${HERMES_HOME}" && pwd)"
    if [[ -n "${default_home}" && "${default_home}" == "${target_home}" ]]; then
      hermes memory-os-agent-os status >/dev/null
      hermes memory-os-agent-os doctor >/dev/null
    fi
  fi
  if [[ "${ENABLE_RUNTIME}" == "1" ]] && command_exists systemctl; then
    systemctl --user is-active hermes-memory-os-heartbeat.timer
    systemctl --user is-enabled hermes-memory-os-heartbeat.timer
  fi
  if [[ "${ENABLE_COGNITIVE_LOOP}" == "1" ]] && command_exists systemctl; then
    systemctl --user is-active hermes-memory-os-cognitive-loop.timer
    systemctl --user is-enabled hermes-memory-os-cognitive-loop.timer
  fi
  if [[ "${INSTALL_COGNITIVE_LOOP}" == "1" ]]; then
    HERMES_HOME="${HERMES_HOME}" \
      PYTHONPATH="${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}" \
      "${PYTHON_BIN}" -m plugins.memory.memory_os cognitive-loop status >/dev/null
  fi
}

select_hermes_home
inspect_current_state
select_options
require_hermes_for_selected_actions
run_installer
verify_install

echo
echo "Memory-OS install complete."
