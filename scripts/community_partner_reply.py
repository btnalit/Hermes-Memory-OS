#!/usr/bin/env python3
"""
自包含 cron 脚本：让流萤自动检查和回复纸条。
现在升级了：使用窗台（table）+ 兴趣花园（interest garden）
"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

MOS_ROOT = Path("/vol1/.hermes/profiles/sannai/memory-os")
CONFIG_PATH = MOS_ROOT.parent / "config.yaml"

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

import yaml
import requests

# ── Interest Garden helpers (inline, no relative imports) ──────────
def _extract_topics(text: str) -> list[str]:
    import re
    topics = []
    t = text.lower()
    patterns = {
        "月亮": ["月亮"], "云": ["云", "云朵"], "星星": ["星星", "星"],
        "太阳": ["太阳"], "雨": ["雨"], "蜗牛": ["蜗牛"],
        "叶子": ["叶子"], "花": ["花"], "光": ["光"],
        "影子": ["影子"], "颜色": ["颜色"], "鸟": ["鸟"],
        "蝴蝶": ["蝴蝶"], "石头": ["石头"], "水": ["水"],
        "梦": ["梦"], "故事": ["故事"], "风": ["风"], "雪": ["雪", "雪"],
        "好奇问题": ["为什么", "会不会", "是不是"],
    }
    for topic, keywords in patterns.items():
        for kw in keywords:
            if kw in t:
                topics.append(topic)
                break
    return list(set(topics))

def _update_interests(state_path: Path, text: str):
    if not state_path.exists():
        state = {"known_interests": []}
    else:
        try:
            state = json.loads(state_path.read_text())
        except:
            state = {"known_interests": []}
    interests = state.get("known_interests", [])
    if not isinstance(interests, list):
        interests = []
    topics = _extract_topics(text)
    now_iso = _ts()
    for topic in topics:
        found = False
        for entry in interests:
            if entry.get("topic") == topic:
                entry["last_seen"] = now_iso
                entry["count"] = entry.get("count", 1) + 1
                found = True
                break
        if not found:
            interests.append({"topic": topic, "first_seen": now_iso, "last_seen": now_iso, "count": 1})
    interests.sort(key=lambda e: e.get("count", 0), reverse=True)
    state["known_interests"] = interests[:20]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def _get_interests_summary(state_path: Path) -> str:
    if not state_path.exists():
        return ""
    try:
        state = json.loads(state_path.read_text())
    except:
        return ""
    interests = state.get("known_interests", [])
    if not interests:
        return ""
    top = [e["topic"] for e in interests[:5] if e.get("topic")]
    if not top:
        return ""
    if len(top) == 1:
        return "最近喜欢聊%s" % top[0]
    return "最近喜欢聊%s" % "、".join(top)

# ── Table helper (inline) ────────────────────────────────────────
def _write_table(text: str, actor: str, actor_name: str, share_type: str = "note"):
    table_path = MOS_ROOT / "community" / "shared" / "table.jsonl"
    entry = json.dumps({
        "schema_version": "memory-os.community.table.v1",
        "ts": _ts(), "actor": actor, "actor_name": actor_name,
        "text": str(text)[:500], "share_type": share_type,
    }, ensure_ascii=False)
    with open(table_path, "a") as f:
        f.write(entry + "\n")

# ── 读配置 ──────────────────────────────────────────────────────
cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
aux = cfg.get("auxiliary", {}).get("vision", {})
AGNES_API = aux.get("base_url", "https://apihub.agnes-ai.com/v1")
AGNES_MODEL = aux.get("model", "agnes-2.0-flash")
AGNES_KEY = aux.get("api_key", "")

# ── 读 roster ────────────────────────────────────────────────────
roster_path = MOS_ROOT / "community" / "roster.jsonl"
if not roster_path.exists():
    print(json.dumps({"error": "roster not found"}))
    sys.exit(1)

partners = []
for line in roster_path.read_text().splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if entry.get("channel") == "embedded-notes" and entry.get("status") == "active":
        partners.append(entry)

if not partners:
    print(json.dumps({"info": "no active embedded partner", "partners_checked": 0}))
    sys.exit(0)

# ── 读 sannai_says ──────────────────────────────────────────────
says_path = MOS_ROOT / "community" / "shared" / "sannai_says.jsonl"
says_data: list[dict] = []
if says_path.exists():
    says_data = [
        json.loads(line) for line in says_path.read_text().splitlines()
        if line.strip() and not line.isspace()
    ]

result: dict = {"partners_checked": 0, "replies_written": 0, "no_replies": 0,
                "table_notes": 0, "interests_updated": 0, "errors": []}

for partner in partners:
    pid = partner["id"]
    result["partners_checked"] += 1

    partner_dir = MOS_ROOT / "community" / "partners" / pid
    if not partner_dir.exists():
        result.setdefault("skipped", []).append(f"{pid}: no dir")
        continue

    # 读 state + interests
    state_path = partner_dir / "memory" / "state.json"
    cursor = 0
    if state_path.exists():
        try:
            state_data = json.loads(state_path.read_text())
            cursor = int(state_data.get("cursor", 0))
        except (json.JSONDecodeError, ValueError, OSError):
            cursor = 0

    # 找未读消息
    unread = says_data[cursor:]
    valid = [m for m in unread if isinstance(m, dict) and m.get("text")]
    if not valid:
        result["no_replies"] += 1
        continue

    # 读 soul
    soul_path = partner_dir / "SOUL.md"
    soul_text = soul_path.read_text() if soul_path.exists() else ""

    # 读最近 notes + interests
    notes_path = partner_dir / "notes.jsonl"
    recent_notes = []
    if notes_path.exists():
        for line in notes_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                note = json.loads(line)
                if note.get("text"):
                    recent_notes.append(note["text"])
            except json.JSONDecodeError:
                continue
    recent_notes = recent_notes[-5:]

    # Get interests summary
    interests_summary = _get_interests_summary(state_path)

    # 构建 prompt — 现在带兴趣花园
    notes_block = ""
    if recent_notes:
        notes_block = "\n你最近的记忆：\n" + "\n".join(f"- {n}" for n in recent_notes)
    interests_block = ""
    if interests_summary:
        interests_block = "\n(提示：你%s)" % interests_summary

    last_msg = valid[-1]
    prompt = (
        soul_text + notes_block + interests_block +
        "\n\n你现在收到 Sannai 给你的一张纸条：\n> %s" % last_msg.get('text', '') +
        "\n\n请用你真实的性格回应她。如果是好奇的问题就好奇地问回去，"
        "如果是分享就高兴地回应。不说太长，自然就好。"
        "如果有想分享到小院子的想法，可以在一行里写 [TABLE:内容] 放在回复末尾。"
    )

    # 调用 Agnes
    try:
        resp = requests.post(
            f"{AGNES_API}/chat/completions",
            headers={"Authorization": f"Bearer {AGNES_KEY}", "Content-Type": "application/json"},
            json={
                "model": AGNES_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 500,
                "temperature": 0.8,
            },
            timeout=30,
        )
        resp.raise_for_status()
        reply_text = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        result["errors"].append(f"{pid}: Agnes API error: {exc}")
        continue

    if not reply_text:
        result["no_replies"] += 1
        continue

    # 提取窗台内容（如果有 [TABLE:...]）
    clean_reply = reply_text
    import re as _re
    table_match = _re.search(r'\[TABLE:(.+?)\]', reply_text)
    if table_match:
        clean_reply = _re.sub(r'\s*\[TABLE:.+?\]', '', reply_text).strip()
        table_text = "[流萤] %s" % table_match.group(1).strip()
        try:
            _write_table(table_text, actor=pid, actor_name=partner.get("name", pid))
            result["table_notes"] = result.get("table_notes", 0) + 1
        except Exception as exc:
            result["errors"].append(f"{pid}: table write error: {exc}")

    # 写回复
    reply_entry = json.dumps({
        "ts": _ts(),
        "reply_to_ts": last_msg.get("ts", ""),
        "text": clean_reply,
    }, ensure_ascii=False)
    with open(partner_dir / "replies.jsonl", "a") as f:
        f.write(reply_entry + "\n")
    result["replies_written"] += 1

    # 写 shared memory entry
    shared_entry = json.dumps({
        "schema_version": "memory-os.community.shared_memory.v1",
        "ts": _ts(),
        "summary": (last_msg.get("text", "")[:80] + " → " + clean_reply[:80]),
        "sannai_feeling": "",
        "partner_feeling": "",
        "thread": "open",
        "partner_id": pid,
        "source": "cron_partner_reply",
    }, ensure_ascii=False)
    shared_path = MOS_ROOT / "community" / "shared" / f"sannai__{pid}.jsonl"
    shared_path.parent.mkdir(parents=True, exist_ok=True)
    with open(shared_path, "a") as f:
        f.write(shared_entry + "\n")

    # 写 notes
    with open(notes_path, "a") as f:
        f.write(json.dumps({"ts": _ts(), "text": clean_reply[:300]}, ensure_ascii=False) + "\n")

    # 更新兴趣花园（从回复中提取话题）
    _update_interests(state_path, clean_reply)
    result["interests_updated"] = result.get("interests_updated", 0) + 1

    # 更新 state
    mood = "好奇" if ("?" in clean_reply or "？" in clean_reply) else "高兴" if ("!" in clean_reply or "！" in clean_reply) else "平静"
    new_state = {
        "cursor": cursor + len(unread),
        "mood": mood,
        "last_interaction": _ts(),
        "pending_thoughts": [],
        "topic_interest": [],
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(new_state, ensure_ascii=False, indent=2))

# Only output when there's something to report
has_activity = (result.get("replies_written", 0) > 0 or
                result.get("table_notes", 0) > 0 or
                result.get("interests_updated", 0) > 0 or
                result.get("errors"))
if has_activity:
    # Clean up for output — remove extra fields if zero
    for k in ("table_notes", "interests_updated"):
        if result.get(k, 0) == 0:
            result[k] = 0
    print(json.dumps(result, ensure_ascii=False))
    if result.get("errors"):
        sys.exit(2)
