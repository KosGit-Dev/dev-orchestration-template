#!/usr/bin/env python3
"""AI Operating Model と 3 ハーネス対称性の準備状態を検証する。"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
# テンプレートに実在する（＝移植済みの）必須ファイルのみを列挙する。
# 多プロバイダレビュー証跡ゲート系（ci_final_gate.py / review_report_gate.py /
# acceptance_audit.py / run_ci_fallback_review.py / ci-final-gate.yml /
# ai-review-fallback.yml 等）は個人開発の既定には過剰なため同梱しない。
REQUIRED = [
    "ai/command-router.yml",
    "ai/operation-policy.yml",
    "ai/context-index.yml",
    "ai/document-governance.yml",
    "ai/coherence-workflow.yml",
    "ai/sdd-policy.yml",
    "ai/pre-pr-review-policy.yml",
    "ai/capability-registry.yml",
    "docs/ai/operating-model.md",
    "docs/ai/expectation-ledger.md",
    "docs/ai/execution-ledger.md",
    "docs/ai/decision-ledger.md",
    "docs/ai/human-required.md",
    "scripts/ai/audit_document_inventory.py",
    "scripts/ai/validate_context_index.py",
    "scripts/ai/run_pre_pr_critical_review.py",
    "scripts/ai/collect_review_context.py",
    ".github/workflows/ci.yml",
    "docs/ai/review-result.schema.json",
]

# core control files（ai/*.yml）へドメイン固有語彙が漏れていないか検査するための
# 禁止語リスト。テンプレートはドメイン非依存のため既定は空。導入先プロジェクトが
# 自プロジェクトの禁止語（特定機能名・内部 ID 等）を追記して使う。
CORE_POLICY_FORBIDDEN_TERMS: list[str] = []

# roster 正本は Copilot / Codex 共通が .github/agents/*.agent.md、
# Claude Code 側が .claude/agents/*.md。トップレベル agents/ は正本一本化のため持たない。
ROSTER_PATHS = {
    "copilot": {
        "orchestrator": ".github/agents/orchestrator.agent.md",
        "implementer": ".github/agents/implementer.agent.md",
        "implementer-single-file": ".github/agents/implementer-single-file.agent.md",
        "test-engineer": ".github/agents/test-engineer.agent.md",
        "auditor-spec": ".github/agents/auditor-spec.agent.md",
        "auditor-security": ".github/agents/auditor-security.agent.md",
        "auditor-reliability": ".github/agents/auditor-reliability.agent.md",
        "release-manager": ".github/agents/release-manager.agent.md",
        "pre-pr-critical-reviewer": ".github/agents/pre-pr-critical-reviewer.agent.md",
    },
    "claude": {
        "orchestrator": ".claude/agents/orchestrator.md",
        "implementer": ".claude/agents/implementer.md",
        "implementer-single-file": ".claude/agents/implementer-single-file.md",
        "test-engineer": ".claude/agents/test-engineer.md",
        "auditor-spec": ".claude/agents/auditor-spec.md",
        "auditor-security": ".claude/agents/auditor-security.md",
        "auditor-reliability": ".claude/agents/auditor-reliability.md",
        "release-manager": ".claude/agents/release-manager.md",
        "pre-pr-critical-reviewer": ".claude/agents/pre-pr-critical-reviewer.md",
    },
}

ORCHESTRATOR_CONTRACT_MARKERS = (
    "Caveman Lite contract v1:",
    "Delegation contract v1:",
    "ASI security contract v1:",
    "Full-plan delivery contract v1:",
)

ENTRYPOINTS = ("AGENTS.md", "CLAUDE.md", ".github/copilot-instructions.md")
ENTRYPOINT_MARKERS = (
    "ai/operation-policy.yml",
    "reporter_communication",
    "subagent_delegation",
    "full_plan_delivery_pipeline",
    "docs/orchestration.md",
)

ORCHESTRATION_SCHEMA_FIELDS = (
    "`role`",
    "`task_id`",
    "`status`",
    "`summary`",
    "`changed_files[]`",
    "`evidence[]`",
    "`next_actions[]`",
    "`risks[]`",
)

FULL_PLAN_EXECUTION_REQUIRED_STEPS = (
    "load_context_index",
    "load_execution_ledger",
    "select_current_queue_head",
    "load_task_spec",
    "reference_requirements_design_spec_completion_conditions",
    "verify_requirements_design_spec_completion_conditions_alignment",
    "implement",
    "run_targeted_tests",
    "run_static_checks",
    "propagate_to_related_docs_and_types",
    "run_runtime_smoke",
    "run_pre_pr_critical_review",
    "verify_completion_conditions_via_critical_review_and_independent_peer",
    "record_evidence",
    "update_execution_ledger",
    "classify_release_if_needed",
    "commit_changes",
    "push_branch",
    "create_pr_with_template",
    "request_ai_review_or_repo_aware_fallback",
    "monitor_ci_final_gate",
    "address_ci_and_review_findings",
    "run_release_manager",
    "merge_pr_when_full_plan_mode",
    "pull_main_after_merge",
    "update_plan_after_merge",
    "update_execution_ledger_after_merge",
    "proceed_to_next_task",
)

FULL_PLAN_COMPLETION_GATE_MARKERS = (
    "pr_required_before_task_done",
    "push_review_loop_required",
    "ci_final_gate_required",
    "release_manager_required",
    "full_plan_mode_requires_merge_before_next_task",
)


def _read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _is_ordered_subsequence(expected: tuple[str, ...], actual: list[object]) -> bool:
    """expected が actual 内に同順で含まれるか検査する。"""
    start = 0
    actual_values = [str(item) for item in actual]
    for item in expected:
        try:
            found = actual_values.index(item, start)
        except ValueError:
            return False
        start = found + 1
    return True


def validate_core_files() -> list[str]:
    """AI Operating Model の必須ファイルと禁止語を検査する。"""
    issues: list[str] = []
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    if missing:
        issues.append("必須ファイルが存在しません: " + ", ".join(missing))
        return issues

    control_text = "\n".join(
        _read_text(p) for p in REQUIRED if p.startswith("ai/") and (ROOT / p).exists()
    )
    hits = [s for s in CORE_POLICY_FORBIDDEN_TERMS if s in control_text]
    if hits:
        issues.append("core control files に特定機能の語彙があります: " + ", ".join(hits))
    return issues


def validate_harness_symmetry() -> list[str]:
    """Claude / Codex / Copilot の agent roster と共通契約を検査する。"""
    issues: list[str] = []
    direct_read_paths = ["docs/orchestration.md", *ENTRYPOINTS]
    missing_direct_reads = [path for path in direct_read_paths if not (ROOT / path).exists()]
    if missing_direct_reads:
        issues.append("必須ファイルが存在しません: " + ", ".join(missing_direct_reads))
        return issues

    expected_roster = set(ROSTER_PATHS["copilot"])
    for harness, roster in ROSTER_PATHS.items():
        actual_roster = set(roster)
        if actual_roster != expected_roster:
            missing = sorted(expected_roster - actual_roster)
            extra = sorted(actual_roster - expected_roster)
            issues.append(f"{harness} roster が不一致です: missing={missing}, extra={extra}")
        for role, path in roster.items():
            if not (ROOT / path).exists():
                issues.append(f"{harness} の {role} agent が存在しません: {path}")

    for harness, roster in ROSTER_PATHS.items():
        path = roster["orchestrator"]
        if not (ROOT / path).exists():
            continue
        text = _read_text(path)
        for marker in ORCHESTRATOR_CONTRACT_MARKERS:
            if marker not in text:
                issues.append(f"{harness} orchestrator に共通契約がありません: {marker}")

    operation_policy = _read_text("ai/operation-policy.yml")
    for marker in (
        "reporter_communication:",
        "subagent_delegation:",
        "full_plan_delivery_pipeline:",
    ):
        if marker not in operation_policy:
            issues.append(f"ai/operation-policy.yml に {marker} がありません")

    orchestration = _read_text("docs/orchestration.md")
    if "## 4. サブエージェント応答スキーマ" not in orchestration:
        issues.append("docs/orchestration.md に §4 サブエージェント応答スキーマがありません")
    for field in ORCHESTRATION_SCHEMA_FIELDS:
        if field not in orchestration:
            issues.append(f"docs/orchestration.md の応答スキーマに {field} がありません")

    for path in ENTRYPOINTS:
        text = _read_text(path)
        for marker in ENTRYPOINT_MARKERS:
            if marker not in text:
                issues.append(f"{path} が端的報告/委譲正本を参照していません: {marker}")

    return issues


def validate_full_plan_delivery_workflow() -> list[str]:
    """execute_current_queue が PR delivery loop まで含むことを検査する。"""
    issues: list[str] = []

    workflow_path = ROOT / "ai" / "coherence-workflow.yml"
    data = yaml.safe_load(workflow_path.read_text(encoding="utf-8")) or {}
    workflows = data.get("workflows")
    if not isinstance(workflows, dict):
        return ["ai/coherence-workflow.yml に workflows がありません"]
    execute_workflow = workflows.get("execute_current_queue")
    if not isinstance(execute_workflow, dict):
        return ["ai/coherence-workflow.yml に execute_current_queue がありません"]

    steps = execute_workflow.get("steps")
    if not isinstance(steps, list):
        issues.append("execute_current_queue.steps が list ではありません")
    elif not _is_ordered_subsequence(FULL_PLAN_EXECUTION_REQUIRED_STEPS, steps):
        missing_steps = [step for step in FULL_PLAN_EXECUTION_REQUIRED_STEPS if step not in steps]
        issues.append(
            "execute_current_queue.steps に full-plan delivery loop が不足しています: "
            + ", ".join(missing_steps)
        )

    completion_gate = execute_workflow.get("completion_gate")
    if not isinstance(completion_gate, dict):
        issues.append("execute_current_queue.completion_gate がありません")
    else:
        for marker in FULL_PLAN_COMPLETION_GATE_MARKERS:
            if completion_gate.get(marker) is not True:
                issues.append(
                    f"execute_current_queue.completion_gate.{marker} が true ではありません"
                )

    delivery_loop = execute_workflow.get("full_plan_delivery_loop")
    if not isinstance(delivery_loop, dict):
        issues.append("execute_current_queue.full_plan_delivery_loop がありません")
    else:
        if delivery_loop.get("pr_body_source") != ".github/PULL_REQUEST_TEMPLATE.md":
            issues.append("full_plan_delivery_loop.pr_body_source が PR template を指していません")
        if (
            delivery_loop.get("review_loop_source")
            != ".github/instructions/review-loop.instructions.md"
        ):
            issues.append(
                "full_plan_delivery_loop.review_loop_source が "
                "review-loop instructions を指していません"
            )
        if delivery_loop.get("merge_after_release_manager_approval") is not True:
            issues.append(
                "full_plan_delivery_loop.merge_after_release_manager_approval が "
                "true ではありません"
            )

    return issues


# 版つきモデル名 + provider 修飾つき版なし名を検出（provider ID・tier 語・素の alias は対象外）。
# 素の alias（sonnet 等の単独小文字）は frontmatter の正規値のため本文言及を禁止しない
MODEL_NAME_IN_BODY_RE = (
    r"(?i)(sonnet|haiku|opus|fable)[ -]?[0-9]|gpt-[0-9]|claude-[a-z-]*[0-9]"
    r"|(Claude|Anthropic) (Sonnet|Haiku|Opus|Fable)"
)

# 恒久文書（入口 3 文書・ai/*.yml）にもプロバイダ固有モデル名を書かない。
# ai/capability-registry.yml の current_resolution は closed list 上の許容場所のため除外
MODEL_NAME_BAN_FILES = (
    "CLAUDE.md",
    "AGENTS.md",
    ".github/copilot-instructions.md",
    "ai/command-router.yml",
    "ai/operation-policy.yml",
    "ai/context-index.yml",
    "ai/document-governance.yml",
    "ai/coherence-workflow.yml",
    "ai/sdd-policy.yml",
    "ai/pre-pr-review-policy.yml",
)


def _frontmatter_model(path: Path) -> str | None:
    """roster ファイルの frontmatter から model 値を返す（無ければ None）。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith("model:"):
            # 値内のコロン（将来の ARN 形式等）を保持し、両種の引用符を除去する
            return line[len("model:") :].strip().strip("\"'")
    return None


def _body_text(path: Path) -> str:
    """frontmatter を除いた本文を返す。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return "\n".join(lines)
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[i + 1 :])
    return ""


def validate_model_tier_consistency(root: Path = ROOT) -> list[str]:
    """roster frontmatter と project-config ai_models の整合を機械検証する。

    テンプレートの設計では各エージェントファイルの frontmatter `model:` が正本であり、
    project-config.yml の ai_models は任意の生成入力（省略時は各ハーネス既定に委ねる）。
    そのため次の方針で検証する（fail-close の anti-leak 検査は弱めない）。

    - roster 各エージェント: frontmatter に model 宣言があること（tier 正本の readiness）。
    - project-config が role の model を明示指定している場合のみ（copilot/codex は
      ai_models.overrides、claude は ai_models.claude_overrides）frontmatter と一致するか
      （drift）を検証する。明示指定が無い role は一致を強制しない（default は advisory）。
    - agent 本文・恒久文書: プロバイダ固有モデル名を含まない（closed list 違反の検出）。
    """
    import re

    issues: list[str] = []
    config_path = root / "project-config.yml"
    if not config_path.exists():
        return ["project-config.yml が存在しません"]
    ai_models = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}).get("ai_models", {})
    overrides = ai_models.get("overrides", {}) or {}
    claude_overrides = ai_models.get("claude_overrides", {}) or {}

    for harness, roster in ROSTER_PATHS.items():
        for role, rel in roster.items():
            path = root / rel
            if not path.exists():
                continue  # 存在チェックは validate_harness_symmetry が担う
            actual = _frontmatter_model(path)
            key = role.replace("-", "_")
            if harness == "claude":
                expected = str(claude_overrides.get(key, "")) or None
            else:
                expected = str(overrides.get(key, "")) or None
            if expected is not None:
                # project-config が明示指定している role のみ drift を検証する
                if actual != expected:
                    issues.append(
                        f"{harness}/{role} の model が project-config と不一致: "
                        f"frontmatter={actual!r} expected={expected!r}"
                    )
            elif not (actual or "").strip():
                # 明示指定が無い role は frontmatter の model 宣言（tier 正本）を必須にする
                issues.append(
                    f"{harness}/{role} の frontmatter に model 宣言がありません"
                    "（tier 正本の readiness 不足）"
                )
            body = _body_text(path)
            if re.search(MODEL_NAME_IN_BODY_RE, body):
                issues.append(
                    f"{rel} の本文にプロバイダ固有モデル名が残っています"
                    "（capability-registry の agent_body_rule 違反）"
                )

    for rel in MODEL_NAME_BAN_FILES:
        path = root / rel
        if not path.exists():
            continue
        if re.search(MODEL_NAME_IN_BODY_RE, path.read_text(encoding="utf-8")):
            issues.append(
                f"{rel} にプロバイダ固有モデル名が残っています"
                "（恒久文書の禁止対象・capability-registry の closed list 違反）"
            )

    # capability-registry はファイル全体を除外せず、許容場所である current_resolution
    # だけを除いた恒久ポリシー部（capability_roles / selection_criteria /
    # resolution_rules 等）を走査する
    registry_path = root / "ai/capability-registry.yml"
    if registry_path.exists():
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        registry.pop("current_resolution", None)
        permanent_text = yaml.safe_dump(registry, allow_unicode=True)
        if re.search(MODEL_NAME_IN_BODY_RE, permanent_text):
            issues.append(
                "ai/capability-registry.yml の恒久ポリシー部（current_resolution 以外）に"
                "プロバイダ固有モデル名が残っています（closed list 違反）"
            )
    return issues


def main() -> int:
    issues = validate_core_files()
    if not issues:
        issues.extend(validate_harness_symmetry())
        issues.extend(validate_full_plan_delivery_workflow())
        issues.extend(validate_model_tier_consistency())
    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        return 1

    print("AI operating model ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
