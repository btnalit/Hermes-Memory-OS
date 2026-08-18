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
# Set when install_memory_os_plugin.py exits 3: it ran to completion but did
# not achieve something that was requested. Carried across functions so the
# verdict is folded into verify_install's box instead of being tolerated --
# tolerating the code without folding it in would move the very "exit 0 while
# something requested did not happen" bug up into this wrapper.
INSTALLER_POST_CONDITION_FAILED=0
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

# Per-profile systemd unit-name suffix. MUST match
# install_memory_os_plugin.py::_runtime_unit_suffix: '' for a root home,
# '-<name>' for a profiles/<name>-shaped HERMES_HOME. Fixed unit names made
# every install overwrite the previous profile's units on multi-profile
# hosts (last deploy won; the loser's heartbeat silently stopped).
unit_suffix() {
  local home_base home_parent
  home_base="$(basename "${HERMES_HOME}")"
  home_parent="$(basename "$(dirname "${HERMES_HOME}")")"
  if [[ "${home_parent}" == "profiles" && -n "${home_base}" ]]; then
    echo "-${home_base}"
  else
    echo ""
  fi
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
  echo "cognitive_loop_unit=$([[ -f "${HERMES_HOME}/memory-os/systemd/hermes-memory-os-cognitive-loop$(unit_suffix).timer" ]] && echo present || echo missing)"

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
    systemctl --user show "hermes-memory-os-heartbeat$(unit_suffix).timer" \
      -p LoadState -p ActiveState -p SubState -p UnitFileState --no-pager 2>/dev/null || true
    echo
    echo "Cognitive loop timer state:"
    systemctl --user show "hermes-memory-os-cognitive-loop$(unit_suffix).timer" \
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
  local default_install_cognitive_loop="yes"
  local default_enable_cognitive_loop="yes"
  local default_owner_review_cron_helper="yes"
  local default_enable_owner_cron_onboarding="yes"
  local default_right_brain_expression_cron_helper="no"
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
    :  # owner_cron_onboarding stays default "yes" — index-sync is a core
    :  # component (D1: heartbeat + cognitive_loop + index-sync must all
    :  # be default-on).  Users who don't want cron registration can pass
    :  # --no-enable-owner-cron-onboarding.
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
    INSTALL_OWNER_REVIEW_CRON_HELPER=1
    resolve_owner_review_cron_deliver
    resolve_owner_review_cron_channel
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
  # NOTE: --skip-verify is deliberately NOT propagated. It silences this
  # wrapper's own probes only; the Python installer still runs its hot-path
  # smoke test. deploy_memory_os.py passes --skip-verify on every apply
  # (it runs its own phased postcheck), so propagating would silently drop
  # the smoke test from every production deploy.

  # ── Auto-detect gateway Python for package installs ──────────────────
  if [[ -z "${TARGET_PYTHON:-}" ]]; then
    for _candidate in \
      /usr/local/lib/hermes-agent/venv/bin/python \
      /opt/hermes-agent/venv/bin/python; do
      if [[ -x "${_candidate}" ]]; then
        TARGET_PYTHON="${_candidate}"
        break
      fi
    done
  fi
  if [[ -n "${TARGET_PYTHON:-}" && -x "${TARGET_PYTHON}" ]]; then
    args+=("--target-python" "${TARGET_PYTHON}")
    echo "  Detected gateway Python: ${TARGET_PYTHON}"
  fi

  echo "Running installer:"
  printf '  %q' "${args[@]}"
  echo
  local installer_rc=0
  "${args[@]}" || installer_rc=$?
  if [[ "${installer_rc}" == "3" ]]; then
    # Exit 3 = ran to the end, but a requested action did not happen. Keep
    # going so verify_install can render one consolidated failure box rather
    # than aborting here with a bare shell error; the flag guarantees the
    # run still fails.
    INSTALLER_POST_CONDITION_FAILED=1
    echo "  [WARN] installer reported unmet post-conditions (exit 3) — continuing to verification"
  elif [[ "${installer_rc}" != "0" ]]; then
    # Anything else is a hard failure (uncaught exception / usage error).
    exit "${installer_rc}"
  fi

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

	  # Install monitor probe scripts (used by memory_os_3_200_monitor.py).
	  # These were historically only available in the source checkout;
	  # installing them to HERMES_HOME/scripts/ decouples the monitor from
	  # the repo location.
	  mkdir -p "${HERMES_HOME}/scripts"
	  for _probe_name in memory_os_cron_adapter_probe.py memory_os_host_profile.py; do
	    local _probe_src="${REPO_ROOT}/scripts/${_probe_name}"
	    local _probe_dst="${HERMES_HOME}/scripts/${_probe_name}"
	    if [[ -f "${_probe_src}" ]]; then
	      install -m 755 "${_probe_src}" "${_probe_dst}"
	      echo "  ✅ ${_probe_name} installed to ${_probe_dst}"
	    else
	      echo "  ⚠️  ${_probe_name} not found at ${_probe_src}"
	    fi
	  done

  # NOTE: the working-cleanup cron is NOT created here any more.
  #
  # working_cleanup is now a member lane of the "memory-os-tick-daily" group
  # tick, created by memory_os_owner_cron_onboarding.py (run above when
  # ENABLE_OWNER_CRON_ONBOARDING=1), which is the single owner of Memory-OS
  # cron creation. Creating a standalone "memory-os-working-cleanup" job here
  # as well would run the same lane twice on every host that has both.
}

verify_install() {
  if [[ "${SKIP_VERIFY}" == "1" || "${DRY_RUN}" == "1" ]]; then
    # --skip-verify silences OUR probes, not the installer's own verdict: an
    # unmet post-condition is something the installer reported as fact, so it
    # still fails the run.
    if [[ "${INSTALLER_POST_CONDITION_FAILED}" == "1" ]]; then
      echo "Memory-OS install reported unmet post-conditions (exit 3); see the JSON report above." >&2
      exit 1
    fi
    return 0
  fi
  echo
  echo "Memory-OS install verification"
  echo "------------------------------"

  local verify_failures=()
  if [[ "${INSTALLER_POST_CONDITION_FAILED}" == "1" ]]; then
    verify_failures+=("installer reported unmet post-conditions (exit 3) — see JSON report above")
  fi

  # ── Doctor check (always run) ──────────────────────────────────────
  HERMES_HOME="${HERMES_HOME}" hermes memory
  HERMES_HOME="${HERMES_HOME}" \
    PYTHONPATH="${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}" \
    "${PYTHON_BIN}" -m plugins.memory.memory_os doctor

  # ── Shell plugin checks ────────────────────────────────────────────
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

  # ── Core component verification (D2: fail-loud) ────────────────────
  # Core three per deployment spec: heartbeat, cognitive_loop, index-sync.
  # Each must be active/enabled when the corresponding flag is set.
  # Failures are collected and reported together before non-zero exit.

  if command_exists systemctl; then
    # ── Heartbeat timer (core #1) ────────────────────────────────
    if [[ "${ENABLE_RUNTIME}" == "1" ]]; then
      if systemctl --user is-active "hermes-memory-os-heartbeat$(unit_suffix).timer" >/dev/null 2>&1; then
        echo "  [PASS] heartbeat timer is active"
      else
        verify_failures+=("heartbeat timer is not active (ENABLE_RUNTIME=1)")
      fi
      if systemctl --user is-enabled "hermes-memory-os-heartbeat$(unit_suffix).timer" >/dev/null 2>&1; then
        echo "  [PASS] heartbeat timer is enabled"
      else
        verify_failures+=("heartbeat timer is not enabled (ENABLE_RUNTIME=1)")
      fi
    fi

    # ── Cognitive-loop timer (core #2) ───────────────────────────
    if [[ "${ENABLE_COGNITIVE_LOOP}" == "1" ]]; then
      if systemctl --user is-active "hermes-memory-os-cognitive-loop$(unit_suffix).timer" >/dev/null 2>&1; then
        echo "  [PASS] cognitive-loop timer is active"
      else
        verify_failures+=("cognitive-loop timer is not active (ENABLE_COGNITIVE_LOOP=1)")
      fi
      if systemctl --user is-enabled "hermes-memory-os-cognitive-loop$(unit_suffix).timer" >/dev/null 2>&1; then
        echo "  [PASS] cognitive-loop timer is enabled"
      else
        verify_failures+=("cognitive-loop timer is not enabled (ENABLE_COGNITIVE_LOOP=1)")
      fi
    fi
  else
    # Non-systemd: warn but don't fail — manual scheduling is expected.
    if [[ "${ENABLE_RUNTIME}" == "1" ]]; then
      echo "  [WARN] systemctl not available — cannot verify heartbeat timer"
      echo "         Ensure heartbeat is scheduled via an alternative mechanism"
    fi
    if [[ "${ENABLE_COGNITIVE_LOOP}" == "1" ]]; then
      echo "  [WARN] systemctl not available — cannot verify cognitive-loop timer"
      echo "         Ensure cognitive-loop is scheduled via an alternative mechanism"
    fi
  fi

  # ── Index-sync onboarding (core #3) ────────────────────────────────
  # Best-effort: the onboarding script handles its own errors; we verify
  # that the onboarding was requested and the index-sync script exists.
  if [[ "${ENABLE_OWNER_CRON_ONBOARDING}" == "1" ]]; then
    local index_sync_script="${HERMES_HOME}/scripts/memory_os_index_sync.py"
    if [[ -f "${index_sync_script}" ]]; then
      echo "  [PASS] index-sync script installed (owner cron onboarding was run)"
    else
      echo "  [WARN] index-sync script not found at ${index_sync_script}"
      echo "         Owner cron onboarding may not have completed successfully"
    fi
  fi

  # ── Cognitive-loop Python status ───────────────────────────────────
  if [[ "${INSTALL_COGNITIVE_LOOP}" == "1" ]]; then
    HERMES_HOME="${HERMES_HOME}" \
      PYTHONPATH="${HERMES_HOME}/memory-os/runtime/python:${HERMES_HOME}/plugins:${PYTHONPATH:-}" \
      "${PYTHON_BIN}" -m plugins.memory.memory_os cognitive-loop status >/dev/null
  fi

  # ── Fail-loud: report all core failures and exit non-zero ──────────
  if [[ ${#verify_failures[@]} -gt 0 ]]; then
    echo
    echo "╔══════════════════════════════════════════════════════════════╗" >&2
    echo "║  CORE COMPONENT VERIFICATION FAILED                         ║" >&2
    echo "╠══════════════════════════════════════════════════════════════╣" >&2
    for failure in "${verify_failures[@]}"; do
      printf "║  ✗ %-54s ║\n" "${failure}" >&2
    done
    echo "╠══════════════════════════════════════════════════════════════╣" >&2
    echo "║  These are required for Memory-OS to function.              ║" >&2
    echo "║  Re-run the installer to fix, or use --skip-verify to       ║" >&2
    echo "║  bypass (not recommended for production).                   ║" >&2
    echo "╚══════════════════════════════════════════════════════════════╝" >&2
    exit 1
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
