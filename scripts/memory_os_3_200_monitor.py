"""Read-only Memory-OS monitor for the 10.20.3.200 test host.

The script intentionally reports metadata, counters, headings, and trend
signals only. It must not print raw event summaries, private transcript bodies,
or selected context text.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


EXPECTED_RH26_HEADINGS: dict[str, list[str]] = {
    "cancel_failed_video": ["Current Foreground Task"],
    "continue_current_task": ["Current Foreground Task"],
    "casual_memory_system_change": [],
    "diagnostic_current_architecture": ["Diagnostic Grounding", "Current Memory-OS Runtime Facts"],
    "candidate_vs_crystallized": ["Crystallized Review Candidates", "Indexed Recall"],
    "active_comfyui_install": ["Current Foreground Task", "Indexed Recall"],
    "deferred_cancellation": ["Current Foreground Task"],
}
SAFE_CASUAL_HEADINGS = {"Conversation Carryover", "Recent Event Summaries"}
FORBIDDEN_CASUAL_HEADINGS = {
    "Current Foreground Task",
    "Diagnostic Grounding",
    "Current Memory-OS Runtime Facts",
    "Crystallized Review Candidates",
}


def find_rh26_heading_anomalies(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for probe in probes:
        prompt_id = str(probe.get("id") or "")
        actual = list(probe.get("headings") or [])
        expected = EXPECTED_RH26_HEADINGS.get(prompt_id)
        if expected is None:
            continue
        if prompt_id == "casual_memory_system_change":
            if not actual or all(heading in SAFE_CASUAL_HEADINGS for heading in actual):
                continue
            forbidden = [heading for heading in actual if heading in FORBIDDEN_CASUAL_HEADINGS]
            anomalies.append(
                {
                    "id": prompt_id,
                    "severity": "fail" if forbidden else "warning",
                    "code": "casual_context_forbidden_heading" if forbidden else "casual_context_needs_review",
                    "expected": expected,
                    "actual": actual,
                }
            )
            continue
        if actual != expected:
            anomalies.append(
                {
                    "id": prompt_id,
                    "severity": "fail",
                    "code": "unexpected_rh26_headings",
                    "expected": expected,
                    "actual": actual,
                }
            )
    return anomalies


def compute_deltas(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {"counts_delta": {}, "audit_entries_per_new_event": None}
    current_counts = _counts(current)
    previous_counts = _counts(previous)
    keys = sorted(set(current_counts) | set(previous_counts))
    deltas = {key: int(current_counts.get(key, 0)) - int(previous_counts.get(key, 0)) for key in keys}
    new_events = int(deltas.get("events", 0))
    if new_events > 0:
        audit_per_event: float | None = round(float(deltas.get("audit_entries", 0)) / float(new_events), 3)
    else:
        audit_per_event = None
    return {"counts_delta": deltas, "audit_entries_per_new_event": audit_per_event}


def classify_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    passed: list[dict[str, Any]] = []
    warn: list[dict[str, Any]] = []
    fail: list[dict[str, Any]] = []

    if snapshot.get("gateway", {}).get("ActiveState") == "active":
        passed.append({"code": "gateway_active"})
    else:
        fail.append({"code": "gateway_inactive", "value": snapshot.get("gateway")})

    heartbeat = snapshot.get("heartbeat_timer", {})
    if heartbeat.get("ActiveState") == "active" and heartbeat.get("UnitFileState") == "enabled":
        passed.append({"code": "heartbeat_timer_active"})
    else:
        fail.append({"code": "heartbeat_timer_inactive", "value": heartbeat})
    if not snapshot.get("heartbeat_listed", False):
        fail.append({"code": "heartbeat_timer_not_listed"})

    cognitive_loop_timer = snapshot.get("cognitive_loop_timer", {})
    if (
        cognitive_loop_timer.get("ActiveState") == "active"
        and cognitive_loop_timer.get("UnitFileState") == "enabled"
    ):
        passed.append({"code": "cognitive_loop_timer_active"})
    else:
        fail.append({"code": "cognitive_loop_timer_inactive", "value": cognitive_loop_timer})
    if not snapshot.get("cognitive_loop_listed", False):
        fail.append({"code": "cognitive_loop_timer_not_listed"})

    cognitive_loop = snapshot.get("cognitive_loop", {})
    if cognitive_loop.get("last_status") == "error":
        fail.append({"code": "cognitive_loop_last_cycle_error", "value": cognitive_loop})
    elif cognitive_loop.get("last_status") in {"ok", "warning"}:
        passed.append({"code": "cognitive_loop_last_cycle_present"})
    else:
        warn.append({"code": "cognitive_loop_no_cycle_yet", "value": cognitive_loop})
    for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_crystallized_approval"):
        if (cognitive_loop.get("boundaries") or {}).get(key) is True:
            fail.append({"code": f"cognitive_loop_{key}_true"})

    memory_status = snapshot.get("memory_status", {})
    if memory_status.get("index_health", {}).get("state") == "healthy":
        passed.append({"code": "index_healthy"})
    else:
        warn.append({"code": "index_not_healthy", "value": memory_status.get("index_health")})
    if memory_status.get("prefetch_mode") != "indexed":
        warn.append({"code": "prefetch_not_indexed", "value": memory_status.get("prefetch_mode")})
    if int(memory_status.get("counts", {}).get("crystallized_records", 0)) != 0:
        fail.append({"code": "unexpected_crystallized_records", "value": memory_status.get("counts", {})})

    doctor = snapshot.get("doctor", {})
    if doctor.get("status") == "ok":
        passed.append({"code": "doctor_ok"})
    else:
        fail.append({"code": "doctor_not_ok", "value": doctor})
    for code, severity in doctor.get("findings", []) or []:
        if code == "hindsight_adapter_disabled":
            continue
        if severity == "error":
            fail.append({"code": "doctor_error_finding", "finding": code})
        else:
            warn.append({"code": "doctor_warning_finding", "finding": code})

    contract = snapshot.get("status_tool_contract", {})
    if contract.get("status") == "ok":
        passed.append({"code": "status_tool_contract_ok"})
    else:
        fail.append({"code": "status_tool_contract_failed", "value": contract})

    shell_alias = snapshot.get("shell_alias_no_env", {})
    if shell_alias.get("status_ok") is True and shell_alias.get("doctor_ok") is True:
        passed.append({"code": "shell_alias_no_env_ok"})
    else:
        fail.append({"code": "shell_alias_no_env_failed", "value": shell_alias})

    router = snapshot.get("context_router", {})
    if router.get("enabled") is True and router.get("mode") == "apply":
        passed.append({"code": "context_router_apply"})
    else:
        warn.append({"code": "context_router_not_apply", "value": router})

    rh26_anomalies = find_rh26_heading_anomalies(list(snapshot.get("rh26_apply_probe") or []))
    for anomaly in rh26_anomalies:
        if anomaly.get("severity") == "fail":
            fail.append(anomaly)
        else:
            warn.append(anomaly)
    for probe in snapshot.get("rh26_apply_probe") or []:
        if probe.get("id") == "casual_memory_system_change" and int(probe.get("chars", 0)) == 0:
            warn.append({"code": "rh26_casual_empty"})

    deep_reflection = snapshot.get("deep_reflection", {})
    for key in ("actual_send", "actual_execute", "actual_identity_write", "actual_crystallized_approval"):
        if deep_reflection.get(key) is True:
            fail.append({"code": f"deep_reflection_{key}_true"})
    rolling = deep_reflection.get("rolling_injection_source_classes", {})
    selected_by_source = rolling.get("selected_by_source_class", {}) if isinstance(rolling, dict) else {}
    if selected_by_source and set(selected_by_source) == {"working"}:
        warn.append({"code": "deep_reflection_source_skew", "selected_by_source_class": selected_by_source})

    compaction = snapshot.get("compaction", {})
    if int(compaction.get("focus_none_count") or 0) > 0:
        warn.append(
            {
                "code": "compression_focus_none",
                "recent_count": compaction.get("recent_count"),
                "focus_none_count": compaction.get("focus_none_count"),
            }
        )

    status = "FAIL" if fail else "WARN" if warn else "PASS"
    return {"status": status, "pass": passed, "warn": warn, "fail": fail}


def render_chinese_summary(snapshot: dict[str, Any]) -> str:
    classification = snapshot.get("classification") or classify_snapshot(snapshot)
    memory_status = snapshot.get("memory_status", {})
    counts = memory_status.get("counts", {})
    router = snapshot.get("context_router", {})
    deltas = snapshot.get("deltas", {})
    counts_delta = deltas.get("counts_delta", {})
    lines = [
        f"监控结果: {classification['status']}",
        "",
        f"- host={snapshot.get('hostname')} time={snapshot.get('date_utc')}",
        f"- gateway={snapshot.get('gateway', {}).get('ActiveState')} pid={snapshot.get('gateway', {}).get('MainPID')}",
        (
            f"- heartbeat={snapshot.get('heartbeat_timer', {}).get('ActiveState')}/"
            f"{snapshot.get('heartbeat_timer', {}).get('UnitFileState')}"
        ),
        (
            f"- cognitive_loop={snapshot.get('cognitive_loop', {}).get('last_status')} "
            f"timer={snapshot.get('cognitive_loop_timer', {}).get('ActiveState')}/"
            f"{snapshot.get('cognitive_loop_timer', {}).get('UnitFileState')}"
        ),
        (
            f"- counts: audit_entries={counts.get('audit_entries')}, events={counts.get('events')}, "
            f"working_items={counts.get('working_items')}, candidates={counts.get('crystallized_candidates')}, "
            f"crystallized_records={counts.get('crystallized_records')}"
        ),
        (
            f"- deltas: audit_entries={_signed(counts_delta.get('audit_entries'))}, "
            f"events={_signed(counts_delta.get('events'))}, "
            f"working_items={_signed(counts_delta.get('working_items'))}, "
            f"candidates={_signed(counts_delta.get('crystallized_candidates'))}, "
            f"audit_per_new_event={deltas.get('audit_entries_per_new_event')}"
        ),
        (
            f"- index_health={memory_status.get('index_health')} "
            f"prefetch_mode={memory_status.get('prefetch_mode')}"
        ),
        f"- doctor={snapshot.get('doctor', {}).get('status')} findings={snapshot.get('doctor', {}).get('findings')}",
        f"- shell_alias_no_env={snapshot.get('shell_alias_no_env')}",
        (
            f"- context_router={router.get('mode')} apply_routes={router.get('apply_routes')} "
            f"llm_judge={router.get('llm_judge_mode')}"
        ),
        f"- RH-26 probe={_probe_summary(snapshot.get('rh26_apply_probe') or [])}",
        f"- compaction={snapshot.get('compaction')}",
        f"- DeepReflection={_deep_reflection_summary(snapshot.get('deep_reflection') or {})}",
        f"- disk={snapshot.get('disk_du')}",
        "",
        f"PASS: {[item.get('code') for item in classification['pass']]}",
        f"WARN: {[item.get('code') for item in classification['warn']]}",
        f"FAIL: {[item.get('code') for item in classification['fail']]}",
    ]
    return "\n".join(lines)


def collect_snapshot(*, host: str = "hermes-media", previous: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = _ssh_json(host, _remote_probe_script())
    raw["deltas"] = compute_deltas(raw, previous)
    raw["classification"] = classify_snapshot(raw)
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="hermes-media")
    parser.add_argument("--previous-json")
    parser.add_argument("--snapshot-out")
    parser.add_argument("--output", choices=["summary", "json"], default="summary")
    args = parser.parse_args(argv)

    previous = None
    if args.previous_json:
        previous_path = Path(args.previous_json)
        if previous_path.exists():
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
    snapshot = collect_snapshot(host=args.host, previous=previous)
    if args.snapshot_out:
        output_path = Path(args.snapshot_out)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.output == "json":
        print(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_chinese_summary(snapshot))
    return 0 if snapshot["classification"]["status"] != "FAIL" else 2


def _counts(snapshot: dict[str, Any]) -> dict[str, int]:
    counts = snapshot.get("memory_status", {}).get("counts", {})
    if not isinstance(counts, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in counts.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _signed(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:+d}"


def _probe_summary(probes: list[dict[str, Any]]) -> str:
    parts = []
    for probe in probes:
        parts.append(f"{probe.get('id')}:{probe.get('chars')}:{'/'.join(probe.get('headings') or [])}")
    return "; ".join(parts)


def _deep_reflection_summary(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": status.get("enabled"),
        "injection_mode": status.get("injection_mode"),
        "latest": status.get("latest_injection_source_classes"),
        "rolling": status.get("rolling_injection_source_classes"),
        "actual_send": status.get("actual_send"),
        "actual_execute": status.get("actual_execute"),
        "actual_identity_write": status.get("actual_identity_write"),
        "actual_crystallized_approval": status.get("actual_crystallized_approval"),
    }


def _ssh_json(host: str, script: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["ssh", host, "python3 -"],
        input=script,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _remote_probe_script() -> str:
    return r'''
import json, os, re, subprocess
from pathlib import Path

def run(cmd, env=None):
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, env=env)
        return {"ok": True, "out": out.strip(), "code": 0}
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "out": (exc.output or "").strip(), "code": exc.returncode}

def system_show(unit):
    r = run(["systemctl", "--user", "show", unit, "-p", "LoadState", "-p", "ActiveState", "-p", "SubState", "-p", "UnitFileState", "-p", "MainPID", "--no-pager"])
    data = {"ok": r["ok"], "code": r["code"]}
    for line in r["out"].splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            data[key] = value
    return data

def load_json_cmd(cmd, env=None):
    r = run(cmd, env=env)
    if not r["ok"]:
        return {"_error": r["out"], "_code": r["code"]}
    try:
        return json.loads(r["out"])
    except Exception as exc:
        return {"_parse_error": str(exc)}

def memory_os_cli(args):
    env = dict(os.environ)
    env["HERMES_HOME"] = "/root/.hermes"
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python:/root/.hermes/plugins:" + env.get("PYTHONPATH", "")
    return load_json_cmd(["python3", "-m", "plugins.memory.memory_os"] + list(args), env=env)

def compaction_stats():
    r = run(["journalctl", "--user", "-u", "hermes-gateway.service", "--since", "6 hours ago", "--no-pager", "-o", "cat"])
    text = r["out"] if r["ok"] else ""
    starts = len(re.findall(r"context compression started|Compacting context|Preflight compression", text))
    focus_none = len(re.findall(r"focus=None", text))
    return {"recent_count": starts, "focus_none_count": focus_none}

def hook_marker_counts():
    r = run(["grep", "-R", '"action": "agent_os_shell_session_', "/root/.hermes/memory-os/audit"])
    text = r["out"] if r["ok"] else ""
    return {
        "started": text.count("agent_os_shell_session_started"),
        "reset": text.count("agent_os_shell_session_reset"),
        "finalized": text.count("agent_os_shell_session_finalized"),
    }

def rh26_probe():
    code = r"""
import json, re
from plugins.memory.memory_os.config import load_config
from plugins.memory.memory_os.index import MemoryOSIndex
from plugins.memory.memory_os.prefetch import build_prefetch
from plugins.memory.memory_os.roots import MemoryOSRoots
from plugins.memory.memory_os.store import MemoryOSStore
home="/root/.hermes"
roots=MemoryOSRoots.from_hermes_home(home, profile="default")
store=MemoryOSStore(roots)
config=load_config(home)
cases=[
 ("cancel_failed_video","太垃圾了，算了，你还是别做视频了","Current task: render ComfyUI tutorial video and fix missing content."),
 ("continue_current_task","继续当前任务","Current task: install ComfyUI Impact Pack."),
 ("casual_memory_system_change","我们继续聊刚才那套记忆系统，你觉得它现在带来的变化是什么？",""),
 ("diagnostic_current_architecture","当前记忆架构是什么？",""),
 ("candidate_vs_crystallized","那些 crystallized candidates 是已经沉淀的长期记忆吗？",""),
 ("active_comfyui_install","帮我继续安装 ComfyUI 插件","Current task: install ComfyUI plugins."),
 ("deferred_cancellation","这个先放一下，明天再说","Current task: render ComfyUI tutorial video."),
]
summary=[]
for cid, query, anchor_text in cases:
    anchor=("### Memory-OS Current Task Anchor\n- current task: "+anchor_text) if anchor_text else ""
    context=build_prefetch(query, budget_chars=2200, store=store, index=MemoryOSIndex(roots), runtime_facts={"provider":"memory_os","prefetch_mode":"indexed"}, current_task_anchor=anchor, context_router_config=config.get("context_router"))
    headings=re.findall(r"^### (.+)$", context, flags=re.M)
    summary.append({"id":cid,"chars":len(context),"headings":headings})
print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python"
    r = run(["python3", "-c", code], env=env)
    return json.loads(r["out"]) if r["ok"] else {"_error": r["out"], "_code": r["code"]}

def deep_reflection_status():
    code = r"""
import json
from plugins.modules.cognition.deep_reflection import DeepReflectionModule
status = DeepReflectionModule("/root/.hermes", profile="default").status()
keys = [
  "enabled","injection_mode","working_updates_enabled","llm_enabled",
  "self_evolution_proposals_enabled","wandering_seed_enabled",
  "current_injection_exists","latest_injection_source_classes",
  "rolling_injection_source_classes","actual_send","actual_execute",
  "actual_identity_write","actual_crystallized_approval"
]
print(json.dumps({k:status.get(k) for k in keys if k in status}, ensure_ascii=False, sort_keys=True))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = "/root/.hermes/memory-os/runtime/python"
    r = run(["python3", "-c", code], env=env)
    return json.loads(r["out"]) if r["ok"] else {"_error": r["out"], "_code": r["code"]}

def shell_alias_no_env():
    status = load_json_cmd(["hermes", "memory-os-agent-os", "status"])
    doctor = load_json_cmd(["hermes", "memory-os-agent-os", "doctor"])
    return {
      "status_ok": isinstance(status, dict) and status.get("schema_version") == "memory-os.status.v0",
      "doctor_ok": isinstance(doctor, dict) and doctor.get("schema_version") == "memory-os.doctor.v0" and doctor.get("status") == "ok",
      "status_error": status.get("_error") if isinstance(status, dict) else None,
      "doctor_error": doctor.get("_error") if isinstance(doctor, dict) else None,
    }

status = memory_os_cli(["status"])
doctor = memory_os_cli(["doctor"])
contract = memory_os_cli(["conversation-regression", "status-tool-contract"])
cfg_path = Path("/root/.hermes/memory-os/config.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
df = run(["df", "-h", "/root/.hermes/memory-os"])["out"]
du = run(["du", "-sh", "/root/.hermes/memory-os"])["out"]
heartbeat_list = run(["systemctl", "--user", "list-timers", "hermes-memory-os-heartbeat.timer", "--no-pager"])["out"]

print(json.dumps({
  "hostname": run(["hostname"])["out"],
  "date_utc": run(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"])["out"],
  "date_local": run(["date", "+%Y-%m-%d %H:%M:%S %Z"])["out"],
  "gateway": system_show("hermes-gateway.service"),
  "heartbeat_timer": system_show("hermes-memory-os-heartbeat.timer"),
  "heartbeat_listed": "hermes-memory-os-heartbeat.timer" in heartbeat_list,
  "cognitive_loop_timer": system_show("hermes-memory-os-cognitive-loop.timer"),
  "cognitive_loop_listed": "hermes-memory-os-cognitive-loop.timer" in run(["systemctl", "--user", "list-timers", "hermes-memory-os-cognitive-loop.timer", "--no-pager"])["out"],
  "memory_status": {
    "counts": status.get("counts") if isinstance(status, dict) else None,
    "index_health": status.get("index_health") if isinstance(status, dict) else None,
    "prefetch_mode": status.get("prefetch_mode") if isinstance(status, dict) else None,
    "hindsight_adapter_enabled": status.get("hindsight_adapter_enabled") if isinstance(status, dict) else None,
    "queue_backlog": status.get("queue_backlog") if isinstance(status, dict) else None,
  },
  "doctor": {
    "status": doctor.get("status") if isinstance(doctor, dict) else None,
    "exit_code": doctor.get("exit_code") if isinstance(doctor, dict) else None,
    "findings": [(x.get("code"), x.get("severity")) for x in doctor.get("findings", [])] if isinstance(doctor, dict) else None,
  },
  "status_tool_contract": contract.get("validation") if isinstance(contract, dict) else contract,
  "shell_alias_no_env": shell_alias_no_env(),
  "cognitive_loop": memory_os_cli(["cognitive-loop", "status"]),
  "context_router": cfg.get("context_router", {}),
  "rh26_apply_probe": rh26_probe(),
  "deep_reflection": deep_reflection_status(),
  "hook_markers": hook_marker_counts(),
  "compaction": compaction_stats(),
  "disk_df": df,
  "disk_du": du,
}, ensure_ascii=False, sort_keys=True))
'''


if __name__ == "__main__":
    raise SystemExit(main())
