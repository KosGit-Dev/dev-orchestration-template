#!/usr/bin/env python3
"""Claude Code CLI を run_ai_review.py の provider command 形式で実行する。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

SCRIPT_ROOT = Path(__file__).resolve().parents[2]
TARGET_ROOT = Path(os.getenv("AI_REVIEW_TARGET_ROOT", str(SCRIPT_ROOT))).resolve()
SCHEMA = SCRIPT_ROOT / "docs" / "ai" / "review-result.schema.json"
ALLOWED_TOOLS = "Read,Glob,Grep,Bash(git diff *),Bash(git grep *),Bash(rg *)"


def _extract_review_json(raw_output: str) -> str:
    stripped = raw_output.strip()
    if not stripped:
        return stripped
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(payload, dict) and "summary" in payload and "issues" in payload:
        return json.dumps(payload, ensure_ascii=False)
    structured_output = payload.get("structured_output") if isinstance(payload, dict) else None
    if isinstance(structured_output, dict):
        return json.dumps(structured_output, ensure_ascii=False)
    if isinstance(payload, dict) and isinstance(payload.get("result"), str):
        return cast("str", payload["result"]).strip()
    content = payload.get("content") if isinstance(payload, dict) else None
    if isinstance(content, list):
        texts = [
            item.get("text")
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        ]
        if texts:
            return "\n".join(cast("list[str]", texts)).strip()
    return stripped


def main() -> int:
    prompt = sys.stdin.read()
    if not prompt.strip():
        print("prompt is empty", file=sys.stderr)
        return 2
    claude = shutil.which("claude")
    if claude is None:
        print("claude CLI is not on PATH", file=sys.stderr)
        return 127
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix="-claude-review-prompt.md",
        delete=False,
    ) as handle:
        prompt_path = Path(handle.name)
        os.chmod(prompt_path, 0o600)
        handle.write(prompt)
    try:
        prompt_instruction = (
            "次のファイルにあるレビュー指示を読み、その内容だけに従って"
            f" JSON レビューを返してください: {prompt_path}"
        )
        result = subprocess.run(
            [
                claude,
                "-p",
                prompt_instruction,
                "--output-format",
                "json",
                "--json-schema",
                SCHEMA.read_text(encoding="utf-8"),
                "--allowedTools",
                ALLOWED_TOOLS,
            ],
            cwd=TARGET_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=1800,
        )
        if result.returncode != 0:
            print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
            return result.returncode
        print(_extract_review_json(result.stdout))
        return 0
    finally:
        prompt_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
