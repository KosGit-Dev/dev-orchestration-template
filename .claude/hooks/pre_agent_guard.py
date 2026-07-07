#!/usr/bin/env python3
"""PreToolUse hook: release-manager 呼び出し前に CI と全プラン安全床を検査する。

Claude Code の Agent ツール呼び出しをインターセプトし、
description や prompt に "release-manager" が含まれる場合に
ci/final-gate 未完了または全プラン安全床未達なら実行を拒否する。
レビュー未到着・未返信・Round 予算・review state lookup 失敗は transient lookup の
fail-open 方針により非ブロッキングのリマインドへ降格する。

これは Copilot の pre_task_complete_guard.py の Claude Code 移植版。
task_complete が存在しない Claude Code では Agent(release-manager) を
完了ゲートとして扱う。

transient な PR / review 状態取得失敗は fail-open とする。
"""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _github_api import gh_subprocess_env, has_claude_code_review_marker  # noqa: E402

_COPILOT_LOGINS: frozenset[str] = frozenset(
    {
        "copilot-pull-request-reviewer[bot]",
        "copilot-pull-request-reviewer",
        "Copilot",
    }
)
_AI_REVIEW_LOGINS: frozenset[str] = _COPILOT_LOGINS | frozenset(
    {
        "chatgpt-codex-connector",
        "chatgpt-codex-connector[bot]",
        "claude",
        "claude[bot]",
        "claude-code[bot]",
    }
)
_AI_REVIEW_MARKERS: tuple[str, ...] = (
    "## AI レビュー結果",
    "### 💡 Codex Review",
    "Codex Review",
    "engine: `codex`",
    "engine: `claude`",
)
_TRUSTED_MARKER_LOGINS: frozenset[str] = _AI_REVIEW_LOGINS | frozenset({"github-actions[bot]"})
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _trusted_marker_logins(current_user: str | None = None) -> frozenset[str]:
    if current_user:
        return _TRUSTED_MARKER_LOGINS | frozenset({current_user})
    return _TRUSTED_MARKER_LOGINS


def _is_ai_review(login: object, body: object, current_user: str | None = None) -> bool:
    if isinstance(login, str) and login in _AI_REVIEW_LOGINS:
        return True
    if (
        isinstance(login, str)
        and isinstance(body, str)
        and login in _trusted_marker_logins(current_user)
    ):
        return any(marker in body for marker in _AI_REVIEW_MARKERS)
    return False


def run(
    cmd: list[str],
    timeout: int = 15,
    *,
    allow_nonzero: bool = False,
) -> str | None:
    """コマンドを実行して stdout を返す。失敗時は None。

    gh 未認証環境でも gh 呼び出しが認証されるよう gh_subprocess_env() の env を渡す。
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=gh_subprocess_env() if cmd[:1] == ["gh"] else None,
        )
        if result.returncode != 0 and not allow_nonzero:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def fetch_reviews(pr_number: str) -> list[dict[str, object]] | None:
    reviews: list[dict[str, object]] = []
    for page in range(1, 101):
        output = run(
            [
                "gh",
                "api",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews?per_page=100&page={page}",
            ],
            timeout=20,
        )
        if output is None or output == "":
            return None
        try:
            page_reviews = json.loads(output)
        except json.JSONDecodeError:
            return None
        if not isinstance(page_reviews, list) or not all(
            isinstance(review, dict) for review in page_reviews
        ):
            return None
        reviews.extend(page_reviews)
        if len(page_reviews) < 100:
            return reviews
    return None


def check_ci(pr_number: str) -> str | None:
    """CI ステータスを確認する。戻り値は release-manager 前の blocking failure のみ。

    戻り値: None=取得失敗, ""=blocking failure なし, 文字列=実 CI 失敗
    """
    checks_json = run(
        ["gh", "pr", "checks", pr_number, "--json", "name,state"],
        allow_nonzero=True,
    )
    if not checks_json:
        return None
    try:
        checks = json.loads(checks_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(checks, list):
        return None

    failure_states = {"FAILURE", "CANCELLED", "TIMED_OUT", "ERROR"}
    pending_states = {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}
    final_gate_state = ""

    for c in checks:
        if not isinstance(c, dict):
            return "CI 状態の形式が不正"
        name = str(c.get("name") or "?")
        raw_state = c.get("state")
        state = str(raw_state).strip().upper() if raw_state is not None else ""
        if not state:
            return f"CI '{name}' の状態が未定義"
        if name == "ci/final-gate" or name.endswith(" / ci/final-gate"):
            final_gate_state = state
            break
    if final_gate_state == "SUCCESS":
        return ""
    if final_gate_state in failure_states:
        return f"CI 'ci/final-gate' が {final_gate_state}"
    if final_gate_state in pending_states:
        return f"CI 'ci/final-gate' が未完了（{final_gate_state}）"
    if final_gate_state:
        return f"CI 'ci/final-gate' が未完了（{final_gate_state}）"

    for c in checks:
        if not isinstance(c, dict):
            return "CI 状態の形式が不正"
        name = str(c.get("name") or "?")
        state = str(c.get("state") or "").strip().upper()
        if state in failure_states:
            return f"CI '{name}' が {state}"
    if checks:
        return "CI 'ci/final-gate' が見つからない"
    return "CI 'ci/final-gate' が未作成"


def _full_plan_load_failure_reason(message: str) -> Callable[..., str]:
    flag_path = _REPO_ROOT / ".github" / "full-plan-execution.flag"
    return lambda *args, **kwargs: message if flag_path.exists() else ""


def _load_full_plan_completion_block_reason() -> Callable[..., str]:
    module_path = _REPO_ROOT / "scripts" / "hooks" / "full_plan_completion.py"
    spec = importlib.util.spec_from_file_location(
        "full_plan_completion_for_claude_pre_agent",
        module_path,
    )
    if spec is None or spec.loader is None:
        return _full_plan_load_failure_reason("全プラン完了認証モジュールを読み込めません")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        return _full_plan_load_failure_reason(
            f"全プラン完了認証モジュールの実行に失敗しました: {exc}"
        )
    return module.full_plan_completion_block_reason


full_plan_completion_block_reason = _load_full_plan_completion_block_reason()


def _full_plan_completion_reason(*, require_delivery_state: bool) -> str | None:
    """旧シグネチャのテスト差し替えにも耐えて完了認証を呼ぶ。"""
    try:
        return full_plan_completion_block_reason(require_delivery_state=require_delivery_state)
    except TypeError as exc:
        if "require_delivery_state" not in str(exc):
            raise
        return full_plan_completion_block_reason()


def get_copilot_latest_review_info(pr_number: str) -> tuple[str | None, str | None]:
    """Copilot / Codex / Claude の最新レビューの (submitted_at, review_id) を返す。"""
    reviews = fetch_reviews(pr_number)
    if reviews is None:
        return None, None
    current_user = run(["gh", "api", "user", "--jq", ".login"], timeout=10)
    latest_dt: datetime | None = None
    latest_date = ""
    latest_id = ""
    for review in reviews:
        user = review.get("user") or {}
        login = user.get("login") if isinstance(user, dict) else None
        if not _is_ai_review(login, review.get("body"), current_user):
            continue
        review_date = review.get("submitted_at")
        if not isinstance(review_date, str) or not review_date:
            continue
        try:
            dt = datetime.fromisoformat(review_date.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
        if latest_dt is None or dt > latest_dt:
            latest_dt = dt
            latest_date = review_date
            latest_id = str(review.get("id") or "")
    if not latest_id:
        return None, None
    return latest_date, latest_id


def count_copilot_reviews(pr_number: str) -> int | None:
    """Copilot / Codex / Claude レビュー数を返す。取得失敗時は None。"""
    reviews = fetch_reviews(pr_number)
    if reviews is None:
        return None
    if not reviews:
        return 0
    current_user = run(["gh", "api", "user", "--jq", ".login"], timeout=10)
    count = 0
    for review in reviews:
        user = review.get("user") or {}
        login = user.get("login") if isinstance(user, dict) else None
        if _is_ai_review(login, review.get("body"), current_user):
            count += 1
    return count


def count_unreplied_copilot_threads(pr_number: str) -> int | None:
    """Copilot / Codex / Claude の未返信スレッド数を返す。取得失敗時は None。"""
    current_user = run(["gh", "api", "user", "--jq", ".login"], timeout=10)
    if not current_user:
        return None
    repo_info = run(["gh", "repo", "view", "--json", "owner,name"], timeout=10)
    if not repo_info:
        return None
    try:
        repo_data = json.loads(repo_info)
        owner = repo_data["owner"]["login"]
        repo_name = repo_data["name"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    query = (
        "{"
        f'  repository(owner: "{owner}", name: "{repo_name}") {{'
        f"    pullRequest(number: {pr_number}) {{"
        "      reviewThreads(first: 100) {"
        "        pageInfo { hasNextPage }"
        "        nodes {"
        "          isResolved isOutdated"
        "          comments(first: 50) {"
        "            pageInfo { hasNextPage }"
        "            nodes { author { login } body }"
        "          }"
        "        }"
        "      }"
        "    }"
        "  }"
        "}"
    )
    output = run(["gh", "api", "graphql", "-f", f"query={query}"], timeout=20)
    if not output:
        return None
    try:
        data = json.loads(output)
        review_threads_data = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        if review_threads_data.get("pageInfo", {}).get("hasNextPage"):
            return None
        threads = review_threads_data["nodes"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if not isinstance(threads, list):
        return None

    unreplied = 0
    for thread in threads:
        if not isinstance(thread, dict):
            return None
        if thread.get("isResolved") or thread.get("isOutdated"):
            continue
        comments_data = thread.get("comments", {})
        if comments_data.get("pageInfo", {}).get("hasNextPage"):
            return None
        comments = comments_data.get("nodes", [])
        if not comments:
            continue
        has_ai_review = any(
            _is_ai_review((c.get("author") or {}).get("login"), c.get("body"), current_user)
            for c in comments
            if isinstance(c, dict)
        )
        if not has_ai_review:
            continue
        has_reply = any(
            isinstance(c, dict) and (c.get("author") or {}).get("login") == current_user
            for c in comments
        )
        if not has_reply:
            unreplied += 1
    return unreplied


def _block(branch: str, pr_number: str, reasons: list[str]) -> None:
    """Agent(release-manager) の呼び出しをブロックする（Claude Code 形式）。"""
    reason = (
        f"【Agent 実行ブロック】PR #{pr_number} "
        f"(ブランチ: {branch}) に未完了事項があります: " + "; ".join(reasons) + "。\n"
        "■ release-manager を呼ぶ前に必ず実施:\n"
        "1. CI 全 pass を確認 (gh pr checks)\n"
        "2. Copilot レビューまたは Codex / Claude fallback を明示リクエスト\n"
        "3. レビュー到着確認（同期 sleep ループは禁止。短い状態確認を最大20回相当）\n"
        "4. レビューコメント取得・分類 → plan.md の AC と照合 → Must/Should 修正\n"
        "5. 【必須】各コメントに GitHub 上で返信する\n"
        "6. CI 実行・検証 → コミット・ push\n"
        "7. 次ラウンドを明示リクエストして再レビュー\n"
        "8. 最大 3 ラウンドまで継続。"
        "Round 3 後の非ブロッキング Must/Should は Backlog 化、"
        "即時ブロッカーは fail-close。"
        "停止条件: Round 3 到達・同一指摘3回繰り返し・再トリガー3回超過・"
        "ポリシー違反・認証不能\n"
        "■ 参照: .github/instructions/review-loop.instructions.md"
    )
    json.dump({"decision": "block", "reason": reason}, sys.stdout, ensure_ascii=False)


def _allow(message: str | None = None) -> None:
    """Claude Code PreToolUse の allow 応答を出力する。"""
    payload: dict[str, object] = {"decision": "allow"}
    if message:
        payload["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        }
    json.dump(payload, sys.stdout, ensure_ascii=False)


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        json.dump({}, sys.stdout)
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Agent ツール以外はスキップ
    if tool_name != "Agent":
        json.dump({}, sys.stdout)
        return

    # release-manager を呼ぼうとしているか確認
    # description または prompt に "release-manager" が含まれる場合にインターセプト
    description = str(tool_input.get("description", "")).lower()
    prompt = str(tool_input.get("prompt", "")).lower()
    subagent_type = str(tool_input.get("subagent_type", "")).lower()

    is_release_manager = (
        "release-manager" in description
        or "release-manager" in prompt
        or "release-manager" in subagent_type
        or "release manager" in description
        or "release manager" in prompt
    )

    if not is_release_manager:
        json.dump({}, sys.stdout)
        return

    # main/master ブランチなら許可
    branch = run(["git", "branch", "--show-current"])
    if not branch or branch in ("main", "master"):
        json.dump({}, sys.stdout)
        return

    try:
        full_plan_reason = _full_plan_completion_reason(require_delivery_state=False)
    except Exception as exc:
        _block(
            branch,
            "未確認",
            [
                "全プラン完了認証モジュールの実行時エラーにより、"
                f"P-010 fail-close でブロックします: {exc}"
            ],
        )
        return
    if full_plan_reason:
        _block(branch, "未確認", [f"全プラン完了未認証: {full_plan_reason}"])
        return

    # OPEN な PR を確認
    pr_json = run(["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number"])
    if pr_json is None:
        _allow(
            f"【レビュー状態 reminder / PR lookup エラー】ブランチ {branch} の OPEN PR 一覧を"
            "取得できません。transient lookup 失敗は fail-open とします。"
        )
        return

    try:
        pr_list = json.loads(pr_json)
    except json.JSONDecodeError:
        _allow(
            f"【レビュー状態 reminder / PR lookup エラー】ブランチ {branch} の OPEN PR 一覧の"
            "パースに失敗しました。transient lookup 失敗は fail-open とします。"
        )
        return

    if not isinstance(pr_list, list) or not pr_list:
        # PR なし → 許可
        json.dump({}, sys.stdout)
        return

    first_pr = pr_list[0]
    if not isinstance(first_pr, dict) or "number" not in first_pr:
        _allow(
            f"【レビュー状態 reminder / PR lookup エラー】ブランチ {branch} の OPEN PR 情報に"
            "number がありません。transient lookup 失敗は fail-open とします。"
        )
        return

    pr_number = str(first_pr["number"])
    reminders: list[str] = []

    # チェック 0: Draft 状態
    is_draft = run(["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr_number}", "--jq", ".draft"])
    if is_draft is None:
        reminders.append("PR の Draft/Ready 状態を取得できない")
    elif is_draft == "true":
        reminders.append(
            "PR が Draft 状態。AIレビューは発火しないため、"
            "Ready for review へ変更してから Round 1 または "
            "fallback AIレビューを明示リクエストしてください"
        )

    # チェック 1: CI ステータス
    ci_issue = check_ci(pr_number)
    if ci_issue:
        _block(branch, pr_number, [ci_issue])
        return
    elif ci_issue is None:
        reminders.append("CI 状態を取得できない（Hook では fail-open）")

    # チェック 2: レビュワーが pending
    jq_reviewer = (
        "[.requested_reviewers[]?"
        " | select("
        '.login == "copilot-pull-request-reviewer[bot]"'
        ' or .login == "copilot-pull-request-reviewer"'
        ' or .login == "Copilot"'
        ")] | length"
    )
    reviewer_count = run(
        ["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr_number}", "--jq", jq_reviewer]
    )
    if reviewer_count is None:
        reminders.append("Copilot レビュワー情報を取得できない")

    # チェック 2b: Round 数（後続の発火ヒントにも使用）
    review_count = count_copilot_reviews(pr_number)
    if review_count is None:
        reminders.append("AIレビュー数を取得できない（review state lookup 失敗は fail-open）")
    elif review_count > 3:
        reminders.append(
            f"AIレビューが {review_count} 回到達（Round 4 相当）。"
            "非ブロッキング指摘は Backlog 化してください"
        )

    # チェック 3: 最新コミットにレビューが到着しているか
    head_sha = run(
        ["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr_number}", "--jq", ".head.sha"]
    )
    if not head_sha:
        reminders.append("レビュー状態を取得できない（head SHA 不明）")
    else:
        commit_date = run(
            [
                "gh",
                "api",
                f"repos/{{owner}}/{{repo}}/commits/{head_sha}",
                "--jq",
                ".commit.committer.date",
            ]
        )
        if not commit_date:
            reminders.append("レビュー状態を取得できない（コミット日時不明）")
        else:
            latest_review_date, _latest_review_id = get_copilot_latest_review_info(pr_number)
            _review_after_commit = False
            if latest_review_date and latest_review_date not in ("", "null"):
                try:
                    review_dt = datetime.fromisoformat(latest_review_date.replace("Z", "+00:00"))
                    commit_dt = datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
                    _review_after_commit = review_dt.astimezone(UTC) >= commit_dt.astimezone(UTC)
                except ValueError:
                    pass
            if not _review_after_commit:
                # AI レビュー fallback: Codex / Claude の AI レビュー marker があれば OK
                has_fallback_marker = (
                    has_claude_code_review_marker(int(pr_number), commit_date)
                    if commit_date
                    else False
                )
                if has_fallback_marker:
                    _review_after_commit = True
                else:
                    already = any("AIレビュー" in r or "Copilot" in r for r in reminders)
                    if not already:
                        if review_count == 0:
                            trigger_hint = (
                                "Round 1 または fallback AIレビューを明示リクエストしてください"
                            )
                        else:
                            trigger_hint = (
                                "次のラウンドを明示リクエストするか、"
                                "Codex / Claude fallback AIレビューを投稿してください"
                            )
                        reminders.append(
                            f"最新コミット ({head_sha[:7]}) に対する AIレビューが未到着。"
                            f"{trigger_hint}"
                        )
    # チェック 4: 未返信スレッド
    unreplied = count_unreplied_copilot_threads(pr_number)
    if unreplied is None:
        reminders.append("未返信コメント数を取得できない（GraphQL エラー）")
    elif unreplied > 0:
        reminders.append(f"AIレビューコメントに {unreplied} 件の未返信スレッドがある")

    if reminders:
        _allow(
            f"【レビュー状態 reminder / release-manager 前確認】PR #{pr_number}: "
            + "; ".join(reminders)
            + ". Claude pre_agent_guard は ci/final-gate と full-plan safety だけをブロックします。"
        )
    else:
        _allow()


if __name__ == "__main__":
    main()
