"""Isolated host-side worker for one auxiliary no-tool LLM request.

Executed with PYTHONPATH pointing only at the Hermes Agent source root so its
``plugins`` package cannot collide with the Memory-OS repository package.
"""
from __future__ import annotations

import json
import sys

from agent.auxiliary_client import call_llm, extract_content_or_reasoning


def main() -> int:
    request = json.loads(sys.stdin.read())
    if not isinstance(request, dict) or set(request) != {
        "provider", "model", "messages", "tools", "temperature", "max_tokens", "timeout"
    }:
        return 2
    if request.get("tools") != [] or not isinstance(request.get("messages"), list):
        return 2
    response = call_llm(
        provider=str(request["provider"]),
        model=str(request["model"]),
        messages=request["messages"],
        tools=[],
        temperature=float(request["temperature"]),
        max_tokens=int(request["max_tokens"]),
        timeout=float(request["timeout"]),
    )
    result = {
        "content": str(extract_content_or_reasoning(response) or ""),
        "model": str(getattr(response, "model", "") or ""),
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
