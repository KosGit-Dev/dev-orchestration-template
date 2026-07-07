#!/usr/bin/env python3
"""リポジトリ文書の軽量な棚卸しを生成する。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "ai" / "document-inventory.md"

PATTERNS = [
    "AGENTS.md",
    "CLAUDE.md",
    ".github/**/*.md",
    ".claude/**/*.md",
    ".agents/**/*.md",
    "docs/**/*.md",
    "ai/**/*.yml",
    ".shogun/**/*.md",
]


def classify(path: Path) -> tuple[str, str, str, bool]:
    s = path.as_posix()
    if s.startswith("ai/"):
        return "CORE_CONTROL", "keep", "AI 制御面", True
    # Shogun 運用モデル。正本 2 本は ai/context-index.yml の shogun_dispatch モードで
    # required 指定（第 4 要素の bool は「毎セッション既定読込（read_by_default）」の意で
    # あり、モード required とは別概念のため False）。
    if s == "docs/ai/shogun-operating-model.md":
        return "DOMAIN_SSOT", "keep", "Shogun 運用モデル正本（shogun_dispatch モードで読込）", False
    if s == "docs/ai/shogun-safety-boundary.md":
        return (
            "DOMAIN_SSOT",
            "keep",
            "Shogun 安全境界正本（既存安全床への参照のみ・shogun_dispatch モードで読込）",
            False,
        )
    if s == "docs/ai/shogun-multi-session-protocol.md":
        return (
            "DOMAIN_SSOT",
            "keep",
            "Shogun 複数セッション層プロトコル正本（任意層・単一セッションでは不使用）",
            False,
        )
    if s.startswith(".claude/output-styles/"):
        return "AGENT_SPECIFIC", "keep", "行動仕様の Claude Code 写像（output style）", False
    # Skills / MCP allowlist: keep は agmsg / stop-ai-slop-jp のみ。
    # speckit 群は外部由来（Spec Kit）で vetting 未了かつ agent/skill 二重管理のため
    # VENDOR_REVIEW_REQUIRED（削除判断は人間承認を挟む・初回は分類のみ）
    if s.startswith((".claude/skills/speckit-", ".github/agents/speckit.git.")):
        return (
            "VENDOR_REVIEW_REQUIRED",
            "review",
            "外部由来（Spec Kit）・vetting 未了・二重管理",
            False,
        )
    if s.startswith((".agents/skills/agmsg/", ".agents/skills/stop-ai-slop-jp/")):
        return "AGENT_SPECIFIC", "keep", "Skills allowlist（共通正本）", False
    if s.startswith((".claude/skills/agmsg", ".claude/skills/stop-ai-slop-jp")):
        return "AGENT_SPECIFIC", "keep", "Skills allowlist（ハーネス側参照）", False
    if s.startswith(".shogun/"):
        return "REFERENCE", "keep", "Shogun skeleton（README・雛形のみコミット）", False
    if s in {
        "AGENTS.md",
        "CLAUDE.md",
        ".github/copilot-instructions.md",
        ".github/instructions/review-loop.instructions.md",
    }:
        return "AGENT_SPECIFIC", "revise", "ツール別入口。薄く保つ", True
    if s.startswith(".github/agents/") or s.startswith(".claude/agents/"):
        return "AGENT_SPECIFIC", "keep", "エージェント定義", False
    if s.startswith("docs/specs/"):
        return "TASK_SPEC", "keep", "タスク単位の仕様", False
    if s.startswith("docs/archive/"):
        return "ARCHIVE", "keep", "履歴アーカイブ", False
    if s.startswith("docs/research/") or s.startswith("docs/adr/"):
        return "REFERENCE", "keep", "参照資料", False
    if s in {
        "docs/requirements.md",
        "docs/design.md",
        "docs/policies.md",
        "docs/constraints.md",
        "docs/architecture.md",
        "docs/runbook.md",
        "docs/plan.md",
    }:
        return "DOMAIN_SSOT", "keep", "ドメイン正本", False
    if "prompt" in s.lower() or s.startswith("prompts/"):
        return "ARCHIVE", "move_or_keep_out_of_default_context", "一回限りプロンプト素材", False
    return "REFERENCE", "review", "手動または AI による分類精査が必要", False


def main() -> int:
    paths: set[Path] = set()
    for pattern in PATTERNS:
        # `.claude/worktrees/` はサブエージェント用の untracked な nested worktree。
        # 走査すると環境依存の行が混入して出力が再現不能になるため除外する
        paths.update(
            p
            for p in ROOT.glob(pattern)
            if p.is_file() and ".claude/worktrees/" not in p.relative_to(ROOT).as_posix()
        )
    rows = []
    for p in sorted(paths):
        rel = p.relative_to(ROOT)
        classification, action, reason, read = classify(rel)
        rows.append((rel.as_posix(), classification, action, reason, "yes" if read else "no"))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 文書棚卸し",
        "",
        "`scripts/ai/audit_document_inventory.py` により生成。",
        "",
        "| path | classification | action | reason | read_by_default |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
