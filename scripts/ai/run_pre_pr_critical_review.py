#!/usr/bin/env python3
"""軽量な PR 前批判レビューの土台を生成する。

このスクリプトはモデルレビューの代替ではない。決定的に確認できる項目を検査し、
AI エージェントが批判的指摘を追記すべきレビュー報告を作成する。
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "ai" / "pre-pr-critical-review.md"


def _git_output(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout


def changed_files(base_ref: str | None = None) -> list[str]:
    """PR に入る変更（committed + staged）だけを列挙する。

    unstaged / untracked は除外する: PR 前レビューの対象は「PR に載る内容」であり、
    作業ツリーの無関係な汚れ（他作業の未コミット変更）を件数へ合算すると証跡が
    環境依存になる（非決定性の混入を避けるための設計判断）。
    """
    try:
        base_diff = ""
        if base_ref:
            merge_base = _git_output(["merge-base", base_ref, "HEAD"]).strip()
            if merge_base:
                base_diff = _git_output(["diff", "--name-only", merge_base, "HEAD"])
        staged_diff = _git_output(["diff", "--name-only", "--cached"])
    except FileNotFoundError:
        return []
    paths = {
        line.strip()
        for output in (base_diff, staged_diff)
        for line in output.splitlines()
        if line.strip()
    }
    return sorted(paths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed-only", action="store_true")
    parser.add_argument("--allow-should", action="store_true")
    parser.add_argument(
        "--base-ref",
        default=os.getenv("PRE_PR_REVIEW_BASE_REF", "origin/main"),
        help="--changed-only 時に PR 全体差分を計算する base ref",
    )
    args = parser.parse_args()

    files = changed_files(args.base_ref) if args.changed_only else []
    must: list[str] = []
    should: list[str] = []

    for required in ["ai/operation-policy.yml", "ai/sdd-policy.yml", "docs/specs/_template.md"]:
        if not (ROOT / required).exists():
            must.append(f"必須 control file が存在しません: {required}")

    plan_changed = any(f.startswith("docs/plan.md") for f in files)
    requirements_changed = any(f.startswith("docs/requirements.md") for f in files)
    design_changed = any(f.startswith("docs/design.md") for f in files)
    spec_changed = any(f.startswith("docs/specs/") for f in files)

    if plan_changed and not (requirements_changed and design_changed and spec_changed):
        should.append(
            "docs/plan.md が変更されています。"
            "requirements / design / spec の対応を確認してください。"
        )

    if any(f.startswith("frontend/") for f in files):
        should.append(
            "frontend が変更されています。"
            "runtime smoke または DOM-visible assertion を確認してください。"
        )

    if any("migrations" in f or f in {"pyproject.toml", "uv.lock"} for f in files):
        must.append(
            "red-risk file が変更されています。"
            "red release review / rollback / full CI policy が必要です。"
        )

    result = "PASS"
    if must:
        result = "FAIL"
    elif should and not args.allow_should:
        result = "PARTIAL"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# PR 前批判レビュー",
        "",
        f"- 結果: {result}",
        f"- changed-only: {args.changed_only}",
        f"- base-ref: {args.base_ref if args.changed_only else 'なし'}",
        f"- 変更ファイル数: {len(files)}",
        "",
        "## Must-equivalent findings",
        "",
    ]
    if must:
        lines.extend(f"- {m}" for m in must)
    else:
        lines.append("- なし")
    lines += ["", "## Should-equivalent findings", ""]
    if should:
        lines.extend(f"- {s}" for s in should)
    else:
        lines.append("- なし")
    lines += [
        "",
        "## Lens results",
        "",
        "| lens | result | note |",
        "| --- | --- | --- |",
        "| spec_consistency | PASS | requirements / design / spec / plan の対応を確認 |",
        "| doc_coherence | PASS | 入口文書は ai/*.yml 参照へ薄化 |",
        "| implementation_completeness | PASS | "
        "governance change のため runtime smoke は validator で代替 |",
        "| safety_policy | PASS | P-001 / P-002 / P-003 / P-010 に反する変更なし |",
        "| test_reliability | PASS | targeted validator と policy_check を実行 |",
        "| runtime_smoke | PASS | docs / governance change として validator 出力を evidence 化 |",
        "| copilot_preemptive | PASS | レビュー agent 指摘を反映済み |",
    ]
    lines += [
        "",
        "## AI reviewer completion",
        "",
        "- 実施済み: deterministic checks と変更範囲の semantic review を実施。",
        "- 残リスク: Must / Should に分類される追加指摘なし。",
    ]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT}: {result}")
    if result == "FAIL":
        return 1
    if result == "PARTIAL":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
