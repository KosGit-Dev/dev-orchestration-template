#!/usr/bin/env python3
"""Codex CLI を run_ai_review.py の provider command 形式で実行する。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[2]
TARGET_ROOT = Path(os.getenv("AI_REVIEW_TARGET_ROOT", str(SCRIPT_ROOT))).resolve()


def main() -> int:
    prompt = sys.stdin.read()
    if not prompt.strip():
        print("prompt is empty", file=sys.stderr)
        return 2
    codex = shutil.which("codex")
    if codex is None:
        print("codex CLI is not on PATH", file=sys.stderr)
        return 127
    with tempfile.NamedTemporaryFile(
        mode="w+",
        encoding="utf-8",
        suffix="-codex-review.json",
        delete=False,
    ) as handle:
        output_path = Path(handle.name)
    try:
        result = subprocess.run(
            [
                codex,
                "--ask-for-approval",
                "never",
                "exec",
                "--cd",
                str(TARGET_ROOT),
                "--sandbox",
                "read-only",
                "--output-last-message",
                str(output_path),
                "-",
            ],
            input=prompt,
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
        output = output_path.read_text(encoding="utf-8").strip()
        if not output:
            output = result.stdout.strip()
        print(output)
        return 0
    finally:
        output_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
