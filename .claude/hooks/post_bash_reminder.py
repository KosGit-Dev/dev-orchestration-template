#!/usr/bin/env python3
"""PostToolUse hook: Bash で git push 後にレビューループの実施をリマインドする。

Claude Code の Bash ツールで git push が実行された直後に
additionalContext を注入し、CI 確認 + Copilot レビュー待機を
エージェントに通知する。

これは Copilot の post_push_reminder.py の Claude Code 移植版。
PostToolUse では "block" による強制停止はできないため、
強いリマインドメッセージを additionalContext として注入する。

PR 状態確認には _github_api ヘルパーを使用し、gh 不在環境でも
GITHUB_TOKEN があれば動作する。両方とも利用不可の場合はリマインドのみ
注入する（フェイルクローズ的だが PostToolUse はブロックできないので影響限定）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# 同一ディレクトリの _github_api を import するため sys.path に追加
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _github_api import (  # noqa: E402
    gh_subprocess_env,
    has_credentials,
    is_claude_code_remote,
    list_open_prs_for_branch,
)


def _run_git(cmd: list[str], timeout: int = 10) -> str | None:
    """git コマンドを実行して stdout を返す。失敗時は None。"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def main() -> None:
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        json.dump({}, sys.stdout)
        return

    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Bash ツール以外は即スキップ
    if tool_name != "Bash":
        json.dump({}, sys.stdout)
        return

    command = tool_input.get("command", "")

    # git push を含まないコマンドはスキップ
    if "git push" not in command:
        json.dump({}, sys.stdout)
        return

    # main/master ブランチならスキップ
    branch = _run_git(["git", "branch", "--show-current"])
    if not branch or branch in ("main", "master"):
        json.dump({}, sys.stdout)
        return

    # Claude Code 公式リモート環境（Web SDK / claude.ai/code 等）では
    # gh / GITHUB_TOKEN が無く、また MCP github ツールと webhook 購読が利用可能。
    # シェルポーリング（gh pr checks ループ）は機能しないため、
    # webhook ベースの運用案内に差し替える。
    if is_claude_code_remote():
        remote_context = (
            f"【git push 検出 / Claude Code Remote 環境】ブランチ: {branch}\n"
            "この環境では gh CLI / sleep ベースのポーリングは利用できません。"
            "代わりに以下の MCP github ツールと webhook 購読を使ってください:\n"
            "1. PR 検索: mcp__github__list_pull_requests または mcp__github__search_pull_requests "
            f"(head={branch}) で OPEN な PR を特定\n"
            "2. レビュワー設定: mcp__github__pull_request_read で requested_reviewers を確認し、"
            "未設定なら mcp__github__request_copilot_review を呼ぶ\n"
            "3. webhook 購読: mcp__github__subscribe_pr_activity を一度呼び、"
            "<github-webhook-activity> イベントで CI 結果・レビューコメントを受信する"
            "（シェルでの sleep ポーリング禁止）\n"
            "4. レビューコメント対応: 受信したイベントから対応すべき指摘を抽出し、"
            "mcp__github__add_reply_to_pull_request_comment で各スレッドに返信、"
            "必要に応じてコード修正→commit→push\n"
            "5. 完了確認: mcp__github__pull_request_read でコメント未解決数を確認し、"
            "ゼロになるまで上記をループ\n"
            "■ 参照: .github/instructions/review-loop.instructions.md "
            "（シェル前提部分は MCP/webhook に読み替え）"
        )
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": remote_context,
                }
            },
            sys.stdout,
            ensure_ascii=False,
        )
        return

    # 認証情報が両方とも無い場合は PR 状態確認をスキップしてリマインドのみ注入
    auth_warning = ""
    if not has_credentials():
        auth_warning = (
            "\n\n⚠️ 注意: gh CLI 未インストール かつ GITHUB_TOKEN/GH_TOKEN 未設定のため、"
            "PR 状態の自動確認はスキップしました。手動で確認してください。"
        )
    else:
        # OPEN な PR が存在するか確認（gh 経路 → API 経路の順にフォールバック）
        pr_list = list_open_prs_for_branch(branch)
        if pr_list is not None:
            if not pr_list:
                # OPEN な PR が存在しない場合はリマインド不要
                json.dump({}, sys.stdout)
                return
            try:
                first_pr = pr_list[0]
                state = str(first_pr.get("state", "")).upper()
                if state != "OPEN":
                    json.dump({}, sys.stdout)
                    return
            except (KeyError, IndexError, TypeError):
                pass  # パース失敗時もリマインドを注入（フェイルクローズ）

    pr_number = "?"
    is_draft = False
    review_count = None
    pr_list_for_context = list_open_prs_for_branch(branch) if has_credentials() else None
    if isinstance(pr_list_for_context, list) and pr_list_for_context:
        first = pr_list_for_context[0]
        if isinstance(first, dict):
            pr_number = str(first.get("number", "?"))
            is_draft = bool(first.get("isDraft", False))

    # review_count を取得して Round 4 以降の警告を出す
    def _run_for_review_count(cmd: list[str], timeout: int = 15) -> str | None:
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=gh_subprocess_env() if cmd[:1] == ["gh"] else None,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    if pr_number != "?" and has_credentials():
        # gh 経由で review_count を取得（fail-safe）
        output = _run_for_review_count(
            [
                "gh",
                "api",
                "--paginate",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews",
                "--jq",
                ".[] | .user.login",
            ]
        )
        if output:
            copilot_logins = {
                "copilot-pull-request-reviewer[bot]",
                "copilot-pull-request-reviewer",
                "Copilot",
            }
            review_count = sum(1 for line in output.splitlines() if line.strip() in copilot_logins)

    # Round 4 相当の警告メッセージ
    round_warning = ""
    if review_count is not None and review_count >= 3:
        round_warning = (
            "\n\n⚠️ 【レビュー状態 reminder / Round 4 相当】\n"
            f"この PR は既に {review_count} 回のレビューが到達しています。\n"
            "Hook は push / review request をブロックしませんが、以下を確認してください:\n"
            "- Round 3 後の非ブロッキング Must/Should は Backlog に記録する\n"
            "- 即時ブロッカー（P-001/P-002/P-003、秘密情報、重大操作の安全、"
            "CI failure、データ破壊等）のみ fail-close で対応する\n"
            "- Backlog ID と残リスクを PR コメントに返信し、"
            "release-manager 承認を経て継続可能にする\n"
        )

    trigger_step = (
        "3. 【レビュー発火】Copilot レビューを明示リクエスト\n"
        "4. Copilot レビュー到着確認（同期 sleep ループは禁止）\n"
    )
    if is_draft:
        trigger_step = (
            "3. 【Draft 検出】PR が Draft のためレビューは発火しません\n"
            "   先に Ready for review に変更し、その後レビューを明示リクエスト\n"
            "4. Copilot レビュー到着確認（同期 sleep ループは禁止）\n"
        )

    context = (
        "【git push 検出】レビューループを開始してください:\n"
        f"対象PR: #{pr_number} / draft={str(is_draft).lower()}\n"
        "1. CI 通過確認（gh pr checks で全チェック success。同期 sleep ループは禁止）\n"
        + trigger_step
        + "5. レビューコメントを取得・分類し plan.md の AC と照合、Must/Should を修正\n"
        "6. 【必須】各コメントに GitHub 上で返信する\n"
        "7. CI 実行・検証 → コミット・ push\n"
        "8. 【次ラウンド発火】Copilot レビューを明示再リクエスト\n"
        "9. 最大 3 ラウンドまで継続。"
        "Round 3 後の非ブロッキング Must/Should は Backlog 化。"
        "停止条件: Round 3 到達・同一指摘3回繰り返し・再トリガー3回超過・"
        "ポリシー違反・認証不能\n"
        "   （返信済み≠完了。スレッド解決確認が必要）\n"
        "10. release-manager は未解決・未返信スレッド0件確認後にのみ呼出可\n"
        "■ 参照: .github/instructions/review-loop.instructions.md" + auth_warning + round_warning
    )

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
