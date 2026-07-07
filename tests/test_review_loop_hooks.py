"""レビューループ Hook の主要挙動を検証する。"""

from __future__ import annotations

import importlib.util
import io
import json
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_DIR = REPO_ROOT / "scripts" / "hooks"
CLAUDE_HOOK_DIR = REPO_ROOT / ".claude" / "hooks"


def _load_hook_module(path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Hook スクリプトをテスト用モジュールとして読み込む。"""
    monkeypatch.syspath_prepend(str(path.parent.resolve()))
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, path.stem, module)
    spec.loader.exec_module(module)
    return module


def _run_hook_main(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> dict[str, object]:
    """Hook の main() を JSON 入出力で実行する。"""
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    module.main()
    return cast("dict[str, object]", json.loads(out.getvalue()))


def _release_gate_payloads() -> tuple[dict[str, object], ...]:
    """VS Code の完了ゲート payload 群を返す。"""
    return (
        {"toolName": "task_complete"},
        {"toolName": "runSubagent", "toolInput": {"agentName": "release-manager"}},
    )


def _patch_vscode_review_gate_state(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    review_count: int | None = 1,
    ci_failure: bool = False,
    latest_review_arrived: bool | None = True,
    latest_review_error: str | None = None,
    reviewer_count: int | None = 1,
    unreplied_threads: int | None = 0,
    head_sha: str = "abcdef1234567890",
) -> None:
    """VS Code hook が見るレビュー状態をまとめて差し替える。"""
    monkeypatch.setattr(module, "_get_copilot_review_count", lambda pr_number: review_count)
    monkeypatch.setattr(module, "_has_ci_failure", lambda pr_number: ci_failure)
    monkeypatch.setattr(
        module,
        "_get_latest_copilot_review_status",
        lambda pr_number, review_count=None: (
            latest_review_arrived,
            head_sha,
            latest_review_error,
        ),
    )
    monkeypatch.setattr(module, "_get_copilot_reviewer_count", lambda pr_number: reviewer_count)
    monkeypatch.setattr(
        module,
        "_count_unreplied_copilot_threads",
        lambda pr_number: unreplied_threads,
    )


def _patch_claude_pre_bash_round_state(
    module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    branch: str = "feat/example",
    has_creds: bool = True,
    open_prs: list[dict[str, object]] | None = None,
    review_count: int | None = 3,
    remote: bool = False,
) -> None:
    """Claude pre_bash_round_guard の状態をまとめて差し替える。"""

    monkeypatch.setattr(module, "_run_git", lambda cmd, timeout=10: branch)
    monkeypatch.setattr(module, "has_credentials", lambda: has_creds)
    monkeypatch.setattr(module, "is_claude_code_remote", lambda: remote)
    monkeypatch.setattr(module, "list_open_prs_for_branch", lambda current_branch: open_prs)
    monkeypatch.setattr(module, "_count_copilot_reviews", lambda pr_number: review_count)


def test_gh_token_validator_returns_valid_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正常なトークンで VALID ステータスを返す。"""
    validator = _load_hook_module(HOOK_DIR / "gh_token_validator.py", monkeypatch)

    def _fake_run(cmd: list[str], *_: object, **__: object) -> tuple[int, str, str]:
        if cmd[1:3] == ["auth", "status"]:
            return 0, "Logged in to github.com", ""
        if cmd[1:4] == ["api", "/rate_limit", "--jq"] and cmd[-1] == ".rate.remaining":
            return 0, "4999", ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(validator, "_get_gh", lambda: "gh")
    monkeypatch.setattr(validator, "_run", _fake_run)

    result = validator.check_gh_token()
    assert result.status == validator.TokenStatus.VALID
    assert result.remaining_calls == 4999
    assert validator.is_token_valid() is True


def test_gh_token_validator_returns_invalid_on_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gh auth status が失敗したら INVALID を返す。"""
    validator = _load_hook_module(HOOK_DIR / "gh_token_validator.py", monkeypatch)

    def _fake_run(cmd: list[str], *_: object, **__: object) -> tuple[int, str, str]:
        if cmd[1:3] == ["auth", "status"]:
            return 1, "", "not logged in"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(validator, "_get_gh", lambda: "gh")
    monkeypatch.setattr(validator, "_run", _fake_run)

    result = validator.check_gh_token()
    assert result.status == validator.TokenStatus.INVALID
    assert validator.is_token_valid() is False


def test_post_push_allows_non_terminal_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """端末実行以外のツールは無条件で通過する。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    result = _run_hook_main(hook, monkeypatch, {"tool_name": "read_file"})

    assert result == {}


def test_post_push_reminds_git_push_for_open_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    """OPEN PR があるブランチの git push は fail-open 方針によりリマインドだけ返す。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    def _fake_run(cmd: list[str], timeout: int = 10) -> str | None:
        del timeout
        if cmd[1:] == ["branch", "--show-current"]:
            return "feat/example"
        if cmd[1:3] == ["pr", "list"]:
            return json.dumps([{"number": 182, "state": "OPEN", "isDraft": False}])
        if cmd[1:3] == ["api", "--paginate"]:
            return ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hook, "_run", _fake_run)
    monkeypatch.setattr(hook, "_check_token_status", lambda: "")
    monkeypatch.setattr(hook._review_loop_state, "get_ai_review_count", lambda pr_number: 0)

    result = _run_hook_main(
        hook,
        monkeypatch,
        {"tool_name": "run_in_terminal", "tool_input": {"command": "git push"}},
    )
    assert result["decision"] == "allow"
    assert "レビュー発火" in str(result["reason"])
    assert "対象PR: #182" in str(result["reason"])


def test_post_push_skips_non_string_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """command が文字列以外なら何もせず通過する。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    for command in (None, 123, ["git", "push"]):
        result = _run_hook_main(
            hook,
            monkeypatch,
            {
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
        )

        assert result == {}


def test_post_push_allows_echo_git_push_literal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PostToolUse は echo の文字列だけなら git push と誤検知しない。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    result = _run_hook_main(
        hook,
        monkeypatch,
        {
            "tool_name": "run_in_terminal",
            "tool_input": {"command": 'echo "git push"'},
        },
    )

    assert result == {}


def test_post_push_reminds_normalized_git_push_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PostToolUse は正規化後に実際の git push を検出して reminder を返す。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    def _fake_run(cmd: list[str], timeout: int = 10) -> str | None:
        del timeout
        if cmd[1:] == ["branch", "--show-current"]:
            return "feat/example"
        if cmd[1:3] == ["pr", "list"]:
            return json.dumps([{"number": 205, "state": "OPEN", "isDraft": False}])
        if cmd[1:3] == ["api", "--paginate"]:
            return ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hook, "_run", _fake_run)
    monkeypatch.setattr(hook, "_check_token_status", lambda: "")
    monkeypatch.setattr(hook._review_loop_state, "get_ai_review_count", lambda pr_number: 0)

    for command in ("git    push origin HEAD", "echo ok\ngit push origin HEAD"):
        result = _run_hook_main(
            hook,
            monkeypatch,
            {
                "tool_name": "run_in_terminal",
                "tool_input": {"command": command},
            },
        )

        assert result["decision"] == "allow", command
        assert "対象PR: #205" in str(result["reason"])


def test_full_plan_flag_detection_is_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """全プラン実行フラグは不正内容を active として扱う。"""
    module = _load_hook_module(HOOK_DIR / "full_plan_flag.py", monkeypatch)
    flag_path = tmp_path / "full-plan-execution.flag"

    assert module.is_full_plan_execution_active(flag_path) is False

    flag_path.write_text('{"active": true}', encoding="utf-8")
    assert module.is_full_plan_execution_active(flag_path) is True

    flag_path.write_text('{"active": false}', encoding="utf-8")
    assert module.is_full_plan_execution_active(flag_path) is False

    flag_path.write_text("{broken", encoding="utf-8")
    assert module.is_full_plan_execution_active(flag_path) is True


def test_pre_task_complete_allows_non_task_complete_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """task_complete 以外のツールは無条件で通過する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
    result = _run_hook_main(guard, monkeypatch, {"tool_name": "read_file"})
    assert result["permissionDecision"] == "allow"


def test_pre_task_complete_blocks_when_full_plan_completion_not_certified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """full_plan_completion_block_reason が文字列なら deny する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
    monkeypatch.setattr(
        guard,
        "full_plan_completion_block_reason",
        lambda: "release-manager 未実行",
    )

    result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

    assert result["permissionDecision"] == "deny"
    assert "release-manager 未実行" in str(result["message"])


def test_pre_task_complete_blocks_release_manager_tools_when_full_plan_not_certified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """release-manager 呼び出しも全プラン未認証なら deny する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
    monkeypatch.setattr(
        guard,
        "full_plan_completion_block_reason",
        lambda: "release-manager 未実行",
    )

    for tool_name in ("runSubagent", "agent"):
        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": tool_name,
                "toolInput": {"agentName": "release-manager"},
            },
        )

        assert result["permissionDecision"] == "deny"
        assert "release-manager 未実行" in str(result["message"])


def test_pre_task_complete_blocks_when_full_plan_completion_raises_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """full_plan_completion_block_reason が例外を投げたら P-010 fail-close で deny する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    def _raise_exception() -> str:
        raise RuntimeError("データベース接続エラー")

    monkeypatch.setattr(
        guard,
        "full_plan_completion_block_reason",
        _raise_exception,
    )

    result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

    assert result["permissionDecision"] == "deny"
    assert "全プラン完了認証エラー" in str(result["message"])
    assert "実行時エラー" in str(result["message"])
    assert "データベース接続エラー" in str(result["message"])


def test_pre_task_complete_blocks_release_manager_when_full_plan_completion_raises_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """release-manager 呼び出しで full_plan_completion_block_reason が例外を投げたら deny する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    def _raise_exception() -> str:
        raise ValueError("plan.md 読み込みエラー")

    monkeypatch.setattr(
        guard,
        "full_plan_completion_block_reason",
        _raise_exception,
    )

    result = _run_hook_main(
        guard,
        monkeypatch,
        {
            "toolName": "runSubagent",
            "toolInput": {"agentName": "release-manager"},
        },
    )

    assert result["permissionDecision"] == "deny"
    assert "全プラン完了認証エラー" in str(result["message"])
    assert "plan.md 読み込みエラー" in str(result["message"])


def test_pre_task_complete_allows_release_manager_when_no_open_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """release-manager 呼び出しで OPEN PR がなければ allow する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
    monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
    monkeypatch.setattr(
        guard,
        "_get_open_pr_number_result",
        lambda: (None, None),
    )

    result = _run_hook_main(
        guard,
        monkeypatch,
        {
            "toolName": "runSubagent",
            "toolInput": {"agentName": "release-manager"},
        },
    )

    assert result["permissionDecision"] == "allow"


def test_pre_task_complete_allows_when_no_open_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPEN PR がなければ allow する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
    monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
    monkeypatch.setattr(
        guard,
        "_get_open_pr_number_result",
        lambda: (None, None),
    )

    result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

    assert result["permissionDecision"] == "allow"


def test_pre_task_complete_blocks_when_ci_failure_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_has_ci_failure が True なら deny する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
    monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
    monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (182, None))
    _patch_vscode_review_gate_state(
        guard,
        monkeypatch,
        review_count=1,
        ci_failure=True,
    )

    result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

    assert result["permissionDecision"] == "deny"
    assert "PR #182" in str(result["message"])


def test_pre_task_complete_ci_failure_uses_final_gate_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ci/final-gate が success なら個別 check failure だけでは CI 失敗扱いにしない。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "quality-gate", "state": "FAILURE"},
                {"name": "ci/final-gate", "state": "SUCCESS"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is False


def test_pre_task_complete_ci_failure_blocks_final_gate_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ci/final-gate が failure なら CI 失敗扱いにする。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "quality-gate", "state": "SUCCESS"},
                {"name": "ci/final-gate", "state": "FAILURE"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_pre_task_complete_ci_failure_parses_nonzero_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gh pr checks が非0でも stdout の final gate failure は block する。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    class _Result:
        returncode = 1
        stdout = json.dumps(
            [
                {"name": "quality-gate", "state": "SUCCESS"},
                {"name": "ci/final-gate", "state": "FAILURE"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_pre_task_complete_ci_failure_checks_other_failures_while_final_gate_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ci/final-gate が pending の間は未完了として扱う。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "quality-gate", "state": "FAILURE"},
                {"name": "ci/final-gate", "state": "PENDING"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_pre_task_complete_ci_failure_blocks_pending_final_gate_without_other_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ci/final-gate pending は他 check が成功でも release 前に止める。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "quality-gate", "state": "SUCCESS"},
                {"name": "ci/final-gate", "state": "PENDING"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_pre_task_complete_ci_failure_blocks_missing_final_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ci/final-gate が無い check 一覧は release 前に未完了として扱う。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps([{"name": "quality-gate", "state": "SUCCESS"}])

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_pre_task_complete_ci_failure_checks_other_failures_when_final_gate_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ci/final-gate skipped は成功扱いしない。"""
    guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "quality-gate", "state": "FAILURE"},
                {"name": "ci/final-gate", "state": "SKIPPED"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_stop_review_guard_allows_when_stop_hook_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop_hook_active=True なら allow する。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)

    result = _run_hook_main(guard, monkeypatch, {"stop_hook_active": True})

    assert result["decision"] == "allow"


def test_stop_review_guard_blocks_when_full_plan_completion_not_certified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """full_plan_completion_block_reason が文字列なら block する。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
    monkeypatch.setattr(
        guard,
        "full_plan_completion_block_reason",
        lambda: "release-manager 未実行",
    )

    result = _run_hook_main(guard, monkeypatch, {})

    assert result["decision"] == "block"
    assert "release-manager 未実行" in str(result["reason"])


def test_stop_review_guard_blocks_when_full_plan_completion_raises_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """full_plan_completion_block_reason が例外を投げたら P-010 fail-close で block する。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)

    def _raise_exception() -> str:
        raise OSError("ファイルシステムエラー")

    monkeypatch.setattr(
        guard,
        "full_plan_completion_block_reason",
        _raise_exception,
    )

    result = _run_hook_main(guard, monkeypatch, {})

    assert result["decision"] == "block"
    assert "全プラン完了認証エラー" in str(result["reason"])
    assert "実行時エラー" in str(result["reason"])
    assert "ファイルシステムエラー" in str(result["reason"])


def test_stop_review_guard_allows_when_no_open_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OPEN PR がなければ allow する。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
    monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
    monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (None, None))

    result = _run_hook_main(guard, monkeypatch, {})

    assert result["decision"] == "allow"


def test_stop_review_guard_blocks_when_ci_failure_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_has_ci_failure が True なら block する。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
    monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
    monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (182, None))
    _patch_vscode_review_gate_state(
        guard,
        monkeypatch,
        review_count=1,
        ci_failure=True,
    )

    result = _run_hook_main(guard, monkeypatch, {})

    assert result["decision"] == "block"
    assert "PR #182" in str(result["reason"])


def test_stop_review_guard_ci_failure_uses_final_gate_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop hook も ci/final-gate success を最終 CI 判定に使う。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "secret-scan", "state": "FAILURE"},
                {"name": "ci/final-gate", "state": "SUCCESS"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is False


def test_stop_review_guard_ci_failure_checks_other_failures_while_final_gate_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop hook も ci/final-gate pending 中は他 check failure を見る。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "security-gate", "state": "FAILURE"},
                {"name": "ci/final-gate", "state": "PENDING"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_stop_review_guard_ci_failure_checks_other_failures_when_final_gate_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop hook も ci/final-gate skipped 中は他 check failure を見る。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)

    class _Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"name": "security-gate", "state": "FAILURE"},
                {"name": "ci/final-gate", "state": "SKIPPED"},
            ]
        )

    monkeypatch.setattr(guard.subprocess, "run", lambda *args, **kwargs: _Result())

    assert guard._has_ci_failure(182) is True


def test_claude_stop_check_ci_lookup_failure_is_fail_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude Stop hook は CI lookup 失敗を実 CI failure として block しない。"""
    guard = _load_hook_module(CLAUDE_HOOK_DIR / "stop_review_guard.py", monkeypatch)

    monkeypatch.setattr(guard, "run", lambda *args, **kwargs: "")

    assert guard.check_ci("182") == []


def test_claude_pre_agent_check_ci_blocks_pending_before_release_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """release-manager 呼び出し前は CI pending を未完了として止める。"""
    guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_agent_guard.py", monkeypatch)
    monkeypatch.setattr(
        guard,
        "run",
        lambda *args, **kwargs: json.dumps([{"name": "ci/final-gate", "state": "PENDING"}]),
    )

    assert guard.check_ci("182") == "CI 'ci/final-gate' が未完了（PENDING）"


def test_claude_pre_agent_check_ci_passes_allow_nonzero_for_final_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gh pr checks が非0でも stdout の final gate failure を解析する。"""
    guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_agent_guard.py", monkeypatch)
    calls: list[bool] = []

    def _fake_run(
        cmd: list[str],
        timeout: int = 15,
        *,
        allow_nonzero: bool = False,
    ) -> str:
        del cmd, timeout
        calls.append(allow_nonzero)
        return json.dumps([{"name": "ci/final-gate", "state": "FAILURE"}])

    monkeypatch.setattr(guard, "run", _fake_run)

    assert guard.check_ci("182") == "CI 'ci/final-gate' が FAILURE"
    assert calls == [True]


def test_claude_pre_agent_check_ci_blocks_missing_final_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude release-manager ゲートも ci/final-gate 欠落を未完了として止める。"""
    guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_agent_guard.py", monkeypatch)
    monkeypatch.setattr(
        guard,
        "run",
        lambda *args, **kwargs: json.dumps([{"name": "quality-gate", "state": "SUCCESS"}]),
    )

    assert guard.check_ci("182") == "CI 'ci/final-gate' が見つからない"


def test_claude_pre_agent_check_ci_blocks_skipped_final_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude release-manager ゲートも ci/final-gate skipped を成功扱いしない。"""
    guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_agent_guard.py", monkeypatch)
    monkeypatch.setattr(
        guard,
        "run",
        lambda *args, **kwargs: json.dumps([{"name": "ci/final-gate", "state": "SKIPPED"}]),
    )

    assert guard.check_ci("182") == "CI 'ci/final-gate' が未完了（SKIPPED）"


def test_claude_pre_agent_blocks_full_plan_safety_before_release_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude release-manager 呼び出し前も delivery 完了状態以外の安全床で block する。"""
    guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_agent_guard.py", monkeypatch)
    calls: list[bool] = []

    def _fake_full_plan_completion_reason(*, require_delivery_state: bool) -> str:
        calls.append(require_delivery_state)
        return "全プラン安全床未達（mode 不正）"

    def _fake_run(
        cmd: list[str],
        timeout: int = 15,
        *,
        allow_nonzero: bool = False,
    ) -> str | None:
        del timeout, allow_nonzero
        if cmd == ["git", "branch", "--show-current"]:
            return "feat/example"
        if cmd[1:3] == ["pr", "list"]:
            return json.dumps([{"number": 99}])
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(guard, "_full_plan_completion_reason", _fake_full_plan_completion_reason)
    monkeypatch.setattr(guard, "run", _fake_run)

    result = _run_hook_main(
        guard,
        monkeypatch,
        {"tool_name": "Agent", "tool_input": {"subagent_type": "release-manager"}},
    )

    assert calls == [False]
    assert result["decision"] == "block"
    assert "全プラン完了未認証" in str(result["reason"])
    assert "全プラン安全床未達（mode 不正）" in str(result["reason"])


def test_stop_review_guard_allows_when_pr_lookup_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop hook の PR lookup エラーは fail-open 方針により reminder にする。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
    monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
    monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (None, "gh コマンド失敗"))

    result = _run_hook_main(guard, monkeypatch, {})

    assert result["decision"] == "allow"
    hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
    reason = str(hook_output.get("additionalContext", ""))
    assert "PR lookup エラー" in reason
    assert "fail-open" in reason


def test_stop_review_guard_blocks_ci_failure_before_review_lookup_reminder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """review_count 取得不能でも CI failure は安全床として先に block する。"""
    guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
    monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
    monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
    monkeypatch.setattr(guard, "_has_ci_failure", lambda pr_number: True)
    monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: None)

    result = _run_hook_main(guard, monkeypatch, {})

    assert result["decision"] == "block"
    assert "CI失敗" in str(result["reason"])


# ---------------------------------------------------------------------------
# gh_token_validator.py: RATE_LIMITED / UNKNOWN / CLI exit code
# ---------------------------------------------------------------------------


def test_gh_token_validator_returns_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rate.remaining が 0 なら RATE_LIMITED を返す。"""
    validator = _load_hook_module(HOOK_DIR / "gh_token_validator.py", monkeypatch)

    def _fake_run(cmd: list[str], *_: object, **__: object) -> tuple[int, str, str]:
        if cmd[1:3] == ["auth", "status"]:
            return 0, "Logged in to github.com", ""
        if cmd[1:4] == ["api", "/rate_limit", "--jq"] and cmd[-1] == ".rate.remaining":
            return 0, "0", ""
        if cmd[1:4] == ["api", "/rate_limit", "--jq"] and cmd[-1] == ".rate.reset":
            return 0, "9999999999", ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(validator, "_get_gh", lambda: "gh")
    monkeypatch.setattr(validator, "_run", _fake_run)

    result = validator.check_gh_token()
    assert result.status == validator.TokenStatus.RATE_LIMITED
    assert result.remaining_calls == 0
    assert validator.is_token_valid() is False


def test_gh_token_validator_returns_unknown_on_non_integer_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """rate.remaining が非数値なら UNKNOWN を返す。"""
    validator = _load_hook_module(HOOK_DIR / "gh_token_validator.py", monkeypatch)

    def _fake_run(cmd: list[str], *_: object, **__: object) -> tuple[int, str, str]:
        if cmd[1:3] == ["auth", "status"]:
            return 0, "Logged in to github.com", ""
        if cmd[1:4] == ["api", "/rate_limit", "--jq"] and cmd[-1] == ".rate.remaining":
            return 0, "not-a-number", ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(validator, "_get_gh", lambda: "gh")
    monkeypatch.setattr(validator, "_run", _fake_run)

    result = validator.check_gh_token()
    assert result.status == validator.TokenStatus.UNKNOWN
    assert result.remaining_calls is None
    assert validator.is_token_valid() is False


def test_gh_token_validator_returns_invalid_on_cli_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gh CLI が exit code 非ゼロ（未インストール相当）なら INVALID を返す。"""
    validator = _load_hook_module(HOOK_DIR / "gh_token_validator.py", monkeypatch)

    def _fake_run(cmd: list[str], *_: object, **__: object) -> tuple[int, str, str]:
        # gh auth status が -1 で失敗（command not found 等）
        if cmd[1:3] == ["auth", "status"]:
            return -1, "", "command not found"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(validator, "_get_gh", lambda: "gh")
    monkeypatch.setattr(validator, "_run", _fake_run)

    result = validator.check_gh_token()
    assert result.status == validator.TokenStatus.INVALID
    assert validator.is_token_valid() is False


def test_gh_token_validator_cli_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() の終了コードが TokenStatus に対応している。"""
    validator = _load_hook_module(HOOK_DIR / "gh_token_validator.py", monkeypatch)

    def _result(status: object) -> object:
        return validator.TokenCheckResult(
            status=status,
            remaining_calls=None,
            message="test",
            recovery_hint="",
        )

    monkeypatch.setattr(
        validator,
        "check_gh_token",
        lambda: _result(validator.TokenStatus.VALID),
    )
    assert validator.main() == 0

    monkeypatch.setattr(
        validator,
        "check_gh_token",
        lambda: _result(validator.TokenStatus.INVALID),
    )
    assert validator.main() == 1

    monkeypatch.setattr(
        validator,
        "check_gh_token",
        lambda: _result(validator.TokenStatus.RATE_LIMITED),
    )
    assert validator.main() == 2

    monkeypatch.setattr(
        validator,
        "check_gh_token",
        lambda: _result(validator.TokenStatus.UNKNOWN),
    )
    assert validator.main() == 1


# ---------------------------------------------------------------------------
# scripts/gh_token_check.sh: source 安全性テスト
# ---------------------------------------------------------------------------


def test_gh_token_check_sh_source_preserves_shell_options() -> None:
    """source しても set -euo pipefail 等のシェルオプションを変えない。"""
    import subprocess

    import pytest

    sh_path = REPO_ROOT / "scripts" / "gh_token_check.sh"
    if not sh_path.exists():
        pytest.skip("scripts/gh_token_check.sh はテンプレート未同梱（導入先が任意で追加する）")
    sh = str(sh_path)
    script = (
        "set -euo pipefail; "
        "opts_before=$(set +o 2>&1); "
        f"source {shlex.quote(sh)}; "
        "opts_after=$(set +o 2>&1); "
        '[ "$opts_before" = "$opts_after" ] && echo SAME || echo DIFFER'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
    assert "SAME" in result.stdout, (
        f"シェルオプションが変更された\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_gh_token_check_sh_multiple_source_idempotent() -> None:
    """複数回 source しても readonly 再定義エラーで失敗しない。"""
    import subprocess

    import pytest

    sh_path = REPO_ROOT / "scripts" / "gh_token_check.sh"
    if not sh_path.exists():
        pytest.skip("scripts/gh_token_check.sh はテンプレート未同梱（導入先が任意で追加する）")
    sh = str(sh_path)
    script = f"set -euo pipefail; source {shlex.quote(sh)}; source {shlex.quote(sh)}; echo DONE"
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, (
        f"2回目 source で失敗\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "DONE" in result.stdout


def test_gh_token_check_sh_non_numeric_rate_limit_fails_close(
    tmp_path: Path,
) -> None:
    """rate_limit 残数が非数値なら fail-close（exit 1）する。"""
    import os
    import subprocess

    import pytest

    sh_path = REPO_ROOT / "scripts" / "gh_token_check.sh"
    if not sh_path.exists():
        pytest.skip("scripts/gh_token_check.sh はテンプレート未同梱（導入先が任意で追加する）")

    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"auth status"* ]]; then echo "Logged in"; exit 0; fi\n'
        'if [[ "$*" == *"/rate_limit"* ]]; then echo "not-a-number"; exit 0; fi\n'
        "exit 0\n"
    )
    fake_gh.chmod(0o755)

    sh = str(sh_path)
    script = f"source {shlex.quote(sh)}; gh_token_check"
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ.get('PATH', '')}"}
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert result.returncode == 1, (
        f"非数値 rate_limit で exit 1 を期待したが {result.returncode}\nstderr={result.stderr}"
    )
    assert "レート残数の解析に失敗" in result.stderr


# ---------------------------------------------------------------------------
# Must #1: review_count >= 2 でも固定上限ブロックにならない（全モード共通）
# ---------------------------------------------------------------------------


def test_post_push_does_not_block_round2_in_any_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """review_count >= 2 でも Hook は block せず reminder に留める。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    def _fake_run(cmd: list[str], timeout: int = 10) -> str | None:
        del timeout
        if cmd[1:] == ["branch", "--show-current"]:
            return "feat/example"
        if cmd[1:3] == ["pr", "list"]:
            return json.dumps([{"number": 99, "state": "OPEN", "isDraft": False}])
        if cmd[1:3] == ["api", "--paginate"]:
            return "copilot-pull-request-reviewer[bot]\ncopilot-pull-request-reviewer[bot]"
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hook, "_run", _fake_run)
    monkeypatch.setattr(hook, "_check_token_status", lambda: "")
    monkeypatch.setattr(hook._review_loop_state, "get_ai_review_count", lambda pr_number: 2)

    result = _run_hook_main(
        hook,
        monkeypatch,
        {"tool_name": "run_in_terminal", "tool_input": {"command": "git push"}},
    )

    assert result["decision"] == "allow"
    reason_str = str(result.get("reason", ""))
    fixed_round_limit_message = "Round " + "2 完了済み"
    assert fixed_round_limit_message not in reason_str
    assert "人間エスカレーション必須" not in reason_str
    assert "対象PR: #99" in reason_str


# ---------------------------------------------------------------------------
# Should #3: PR一覧取得失敗 → fail-open reminder
# ---------------------------------------------------------------------------


def test_post_push_fail_open_on_pr_list_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR一覧取得失敗時は transient lookup の fail-open 方針により fail-open reminder にする。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    def _fake_run(cmd: list[str], timeout: int = 10) -> str | None:
        del timeout
        if cmd[1:] == ["branch", "--show-current"]:
            return "feat/example"
        if cmd[1:3] == ["pr", "list"]:
            return None  # 取得失敗
        if cmd[1:3] == ["api", "--paginate"]:
            return ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hook, "_run", _fake_run)
    monkeypatch.setattr(hook, "_check_token_status", lambda: "")
    monkeypatch.setattr(hook._review_loop_state, "get_ai_review_count", lambda pr_number: 0)

    result = _run_hook_main(
        hook,
        monkeypatch,
        {"tool_name": "run_in_terminal", "tool_input": {"command": "git push"}},
    )

    assert result["decision"] == "allow"
    assert "fail-open" in str(result["reason"])


def test_post_push_fail_open_on_pr_list_json_parse_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR一覧のJSONパース失敗時も fail-open reminder にする。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    def _fake_run(cmd: list[str], timeout: int = 10) -> str | None:
        del timeout
        if cmd[1:] == ["branch", "--show-current"]:
            return "feat/example"
        if cmd[1:3] == ["pr", "list"]:
            return "{invalid-json"
        if cmd[1:3] == ["api", "--paginate"]:
            return ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hook, "_run", _fake_run)
    monkeypatch.setattr(hook, "_check_token_status", lambda: "")
    monkeypatch.setattr(hook._review_loop_state, "get_ai_review_count", lambda pr_number: 0)

    result = _run_hook_main(
        hook,
        monkeypatch,
        {"tool_name": "run_in_terminal", "tool_input": {"command": "git push"}},
    )

    reason_str = str(result["reason"])
    assert result["decision"] == "allow"
    assert "手動確認" in reason_str
    assert "JSON パース" in reason_str


def test_post_push_accepts_camel_case_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PostToolUse の camelCase payload でも git push を検知する。"""
    hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

    def _fake_run(cmd: list[str], timeout: int = 10) -> str | None:
        del timeout
        if cmd[1:] == ["branch", "--show-current"]:
            return "feat/example"
        if cmd[1:3] == ["pr", "list"]:
            return json.dumps([{"number": 189, "state": "OPEN", "isDraft": False}])
        if cmd[1:3] == ["api", "--paginate"]:
            return ""
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(hook, "_run", _fake_run)
    monkeypatch.setattr(hook, "_check_token_status", lambda: "")
    monkeypatch.setattr(hook._review_loop_state, "get_ai_review_count", lambda pr_number: 0)

    result = _run_hook_main(
        hook,
        monkeypatch,
        {"toolName": "run_in_terminal", "toolInput": {"command": "git push"}},
    )

    assert result["decision"] == "allow"
    assert "対象PR: #189" in str(result["reason"])


class TestCommandDetection:
    """レビューループコマンド検出の単体テスト。"""

    def test_detects_mutating_gh_api_reviewer_requests(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """変更系 gh api requested_reviewers は reviewer request として検出する。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)

        commands = [
            (
                "gh api repos/owner/repo/pulls/1/requested_reviewers -X POST "
                "-f reviewers[]=copilot-pull-request-reviewer[bot]"
            ),
            (
                "gh api -X POST repos/owner/repo/pulls/1/requested_reviewers "
                "-f reviewers[]=copilot-pull-request-reviewer[bot]"
            ),
            "gh api --method POST repos/owner/repo/pulls/1/requested_reviewers",
            "gh api --method=POST repos/owner/repo/pulls/1/requested_reviewers",
            "gh api --method PUT repos/owner/repo/pulls/1/requested_reviewers",
            "gh api --method=PATCH repos/owner/repo/pulls/1/requested_reviewers",
        ]

        for command in commands:
            result = module.detect_review_loop_actions(command)
            assert result.is_reviewer_request is True, command

    def test_ignores_read_only_gh_api_review_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """読み取り系 gh api は Copilot 文字列を含んでも reviewer request としない。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)

        commands = [
            "gh api repos/owner/repo/pulls/1/requested_reviewers --jq '.users[].login'",
            "gh api repos/owner/repo/pulls/1/comments --jq 'request_copilot_review'",
            (
                "gh api repos/owner/repo/pulls/1/reviews --jq "
                "'.[] | select(.user.login == \"copilot-pull-request-reviewer[bot]\")'"
            ),
            (
                "gh api repos/owner/repo/pulls/1/reviews --jq "
                '".[] | select(.body | contains(\\"request_copilot_review\\"))"'
            ),
            "gh api --method GET repos/owner/repo/pulls/1/requested_reviewers",
            "gh api -X DELETE repos/owner/repo/pulls/1/requested_reviewers",
        ]

        for command in commands:
            result = module.detect_review_loop_actions(command)
            assert result.is_reviewer_request is False, command

    def test_detects_non_api_reviewer_request_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gh pr edit と AI review request の検出を維持する。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)

        commands = [
            "gh pr edit 1 --add-reviewer copilot-pull-request-reviewer",
            "gh pr edit 1 --add-reviewer=copilot-pull-request-reviewer[bot]",
            "gh pr comment 1 --body '@codex review'",
            "gh pr comment 1 -b '@codex review'",
            "gh pr comment 1 --body 'please @claude review'",
            "gh workflow run ai-review-fallback.yml --ref feat/example -f pr_number=1",
            "gh --repo owner/repo workflow run .github/workflows/ai-review-fallback.yml",
            "request_ai_review --pr 1",
            "request_copilot_review --pr 1",
            "request_codex_review --pr 1",
            "request_claude_review --pr 1",
        ]

        for command in commands:
            result = module.detect_review_loop_actions(command)
            assert result.is_reviewer_request is True, command

    def test_detects_pr_comment_body_file_review_request(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """gh pr comment --body-file / -F の AI review request を検出する。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)
        body_file = tmp_path / "review-request.md"
        body_file.write_text("please @claude review\n", encoding="utf-8")

        commands = [
            f"gh pr comment 1 --body-file {body_file}",
            f"gh pr comment 1 -F {body_file}",
        ]

        for command in commands:
            result = module.detect_review_loop_actions(command)
            assert result.is_reviewer_request is True, command

    def test_ignores_request_copilot_review_as_non_executable_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """専用 executable 以外の文字列は reviewer request としない。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)

        commands = [
            "echo request_copilot_review",
            "not_request_copilot_review --pr 1",
            "cat request_copilot_review.log",
            "gh pr comment 1 --body '対応済みです'",
        ]

        for command in commands:
            result = module.detect_review_loop_actions(command)
            assert result.is_reviewer_request is False, command

    def test_preserves_git_push_detection_variants(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """既存の git push 正規化検出を維持する。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)

        commands = [
            "git push origin feat/example",
            "git -c key=value push origin feat/example",
            "command git push origin feat/example",
            "sudo git push origin feat/example",
        ]

        for command in commands:
            result = module.detect_review_loop_actions(command)
            assert result.is_git_push is True, command

    def test_detects_multiline_git_push(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非引用の改行後にある git push を検出する。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)

        result = module.detect_review_loop_actions("echo ok\ngit push origin HEAD")

        assert result.is_git_push is True

    def test_handles_unparseable_command_without_crashing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未閉じクォートでも hook 用検出が例外を投げない。"""
        module = _load_hook_module(HOOK_DIR / "_command_detection.py", monkeypatch)

        result = module.detect_review_loop_actions("echo 'unterminated")

        assert result.is_git_push is False
        assert result.is_reviewer_request is False


# ---------------------------------------------------------------------------
# レビューラウンド上限の統一
# ---------------------------------------------------------------------------


class TestReviewRoundBudget:
    """レビュー回数上限（最大 3 ラウンド）の検証。"""

    def test_pre_task_complete_allows_round_1_2_push(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Round 1/2 相当（review_count 0/1）で git push は allow する。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

        for review_count in (0, 1, 2):
            monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
            monkeypatch.setattr(
                guard,
                "_get_copilot_review_count",
                lambda pr_number, _rc=review_count: _rc,
            )

            result = _run_hook_main(
                guard,
                monkeypatch,
                {
                    "toolName": "run_in_terminal",
                    "toolInput": {"command": "git push origin feat/example"},
                },
            )

            assert result["permissionDecision"] == "allow", (
                f"Round {review_count + 1} で push が拒否された"
            )

    def test_pre_task_complete_reminds_round_4_push(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """review_count 3 で git push は allow + reminder にする（transient lookup fail-open）。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 3)

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": "run_in_terminal",
                "toolInput": {"command": "git push origin feat/example"},
            },
        )

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "Round 4" in message or "Round 予算" in message
        assert "ブロックしません" in message

    def test_pre_task_complete_reminds_round_4_for_normalized_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """正規化後に git push / reviewer request と判定できるコマンドは reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 3)

        commands = [
            "git    push origin feat/example",
            "git -c key=value push origin feat/example",
            "command git push origin feat/example",
            "gh api repos/owner/repo/pulls/99/requested_reviewers --method POST",
            "gh pr edit 99 --add-reviewer copilot-pull-request-reviewer",
            "gh pr edit 99 --add-reviewer copilot-pull-request-reviewer[bot]",
            "gh pr comment 99 --body '@codex review'",
            "gh workflow run ai-review-fallback.yml --ref feat/example -f pr_number=99",
            "request_ai_review --pr 99",
            "request_copilot_review --pr 99",
            "request_codex_review --pr 99",
            "request_claude_review --pr 99",
        ]

        for command in commands:
            result = _run_hook_main(
                guard,
                monkeypatch,
                {
                    "toolName": "run_in_terminal",
                    "toolInput": {"command": command},
                },
            )

            assert result["permissionDecision"] == "allow", command
            message = str(result.get("message", ""))
            assert "Round 4" in message or "Round 予算" in message

    def test_pre_task_complete_allows_echo_git_push_literal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """単なる文字列の echo は git push と誤検知しない。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": "run_in_terminal",
                "toolInput": {"command": 'echo "git push"'},
            },
        )

        assert result["permissionDecision"] == "allow"

    def test_pre_task_complete_reminds_round_4_reviewer_request(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 3 で reviewer request は allow + reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 3)

        for command in [
            "gh api repos/owner/repo/pulls/99/requested_reviewers --method POST",
            (
                "gh api --method=POST repos/owner/repo/pulls/99/requested_reviewers "
                "-f reviewers[]=copilot-pull-request-reviewer[bot]"
            ),
            "gh pr edit 99 --add-reviewer copilot-pull-request-reviewer",
            "gh pr comment 99 --body '@claude review'",
            "gh workflow run ai-review-fallback.yml --ref feat/example -f pr_number=99",
            "request_copilot_review --pr 99",
            "request_codex_review --pr 99",
        ]:
            result = _run_hook_main(
                guard,
                monkeypatch,
                {
                    "toolName": "run_in_terminal",
                    "toolInput": {"command": command},
                },
            )

            assert result["permissionDecision"] == "allow", command
            message = str(result.get("message", ""))
            assert "Round 4" in message or "Round 予算" in message

    def test_pre_task_complete_reminds_dedicated_review_request_tools_at_round_4(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """専用 review request tool も review_count 3 なら reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 3)

        payloads: tuple[dict[str, object], ...] = (
            {"toolName": "request_ai_review"},
            {"toolName": "request_copilot_review"},
            {"toolName": "request_codex_review"},
            {"toolName": "request_claude_review"},
            {"tool_name": "mcp__github__request_ai_review"},
            {"tool_name": "mcp__github__request_copilot_review"},
            {"tool_name": "mcp__github__request_codex_review"},
            {"tool_name": "mcp__github__request_claude_review"},
        )

        for payload in payloads:
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow", payload
            message = str(result.get("message", ""))
            assert "Round 4" in message or "Round 予算" in message

    def test_pre_task_complete_allows_dedicated_review_request_tools_before_round_4(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """専用 review request tool は review_count 2 以下なら allow する。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 2)

        payloads: tuple[dict[str, object], ...] = (
            {"toolName": "request_ai_review"},
            {"toolName": "request_copilot_review"},
            {"toolName": "request_codex_review"},
            {"toolName": "request_claude_review"},
            {"tool_name": "mcp__github__request_ai_review"},
            {"tool_name": "mcp__github__request_copilot_review"},
            {"tool_name": "mcp__github__request_codex_review"},
            {"tool_name": "mcp__github__request_claude_review"},
        )

        for payload in payloads:
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow", payload

    def test_pre_task_complete_ignores_partial_review_request_tool_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """専用 tool 名以外の部分一致は reviewer request としない。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 3)

        payloads: tuple[dict[str, object], ...] = (
            {"toolName": "not_request_copilot_review"},
            {"tool_name": "mcp__github__not_request_copilot_review"},
        )

        for payload in payloads:
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow", payload

    def test_pre_task_complete_allows_round_4_read_only_review_checks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 3 でも読み取り系 gh api は reviewer request として deny しない。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 3)

        commands = [
            "gh api repos/owner/repo/pulls/99/requested_reviewers --jq '.users[].login'",
            (
                "gh api repos/owner/repo/pulls/99/reviews --jq "
                "'.[] | select(.user.login == \"copilot-pull-request-reviewer[bot]\")'"
            ),
            "gh api --method GET repos/owner/repo/pulls/99/requested_reviewers",
        ]

        for command in commands:
            result = _run_hook_main(
                guard,
                monkeypatch,
                {
                    "toolName": "run_in_terminal",
                    "toolInput": {"command": command},
                },
            )

            assert result["permissionDecision"] == "allow", command

    def test_claude_pre_bash_round_guard_reminds_round_4_for_normalized_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude pre_bash_round_guard も Round 4 相当を reminder にする。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_bash_round_guard.py", monkeypatch)
        _patch_claude_pre_bash_round_state(
            guard,
            monkeypatch,
            open_prs=[{"number": 99, "state": "OPEN"}],
            review_count=3,
        )

        commands = [
            "git    push origin feat/example",
            "git -c key=value push origin feat/example",
            "sudo git push origin feat/example",
            "gh api repos/owner/repo/pulls/99/requested_reviewers --method POST",
            "gh pr edit 99 --add-reviewer copilot-pull-request-reviewer",
            "gh pr edit 99 --add-reviewer copilot-pull-request-reviewer[bot]",
            "gh pr comment 99 --body '@codex review'",
            "gh workflow run ai-review-fallback.yml --ref feat/example -f pr_number=99",
            "request_ai_review --pr 99",
            "request_copilot_review --pr 99",
            "request_codex_review --pr 99",
            "request_claude_review --pr 99",
        ]

        for command in commands:
            result = _run_hook_main(
                guard,
                monkeypatch,
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": command},
                },
            )

            assert result["decision"] == "allow", command
            hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
            reason = str(hook_output.get("additionalContext", ""))
            assert "Round 4" in reason or "review_count=3" in reason or "Round 予算" in reason

    def test_claude_pre_bash_round_guard_allows_echo_git_push_literal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude pre_bash_round_guard も echo 文字列を git push と誤検知しない。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_bash_round_guard.py", monkeypatch)

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "tool_name": "Bash",
                "tool_input": {"command": 'echo "git push"'},
            },
        )

        assert result["decision"] == "allow"

    def test_claude_pre_bash_round_guard_reminds_dedicated_review_request_tool_at_round_4(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude の専用 review request tool も review_count 3 なら reminder にする。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_bash_round_guard.py", monkeypatch)
        _patch_claude_pre_bash_round_state(
            guard,
            monkeypatch,
            open_prs=[{"number": 99, "state": "OPEN"}],
            review_count=3,
        )

        payloads: tuple[dict[str, object], ...] = (
            {"tool_name": "mcp__github__request_ai_review"},
            {"tool_name": "mcp__github__request_copilot_review"},
            {"tool_name": "mcp__github__request_codex_review"},
            {"tool_name": "mcp__github__request_claude_review"},
        )

        for payload in payloads:
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["decision"] == "allow", payload
            hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
            context = str(hook_output.get("additionalContext", ""))
            assert "review_count=3" in context or "Round 4" in context

    def test_claude_pre_bash_round_guard_allows_dedicated_review_request_tool_before_round_4(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude の専用 review request tool は review_count 2 以下なら allow する。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_bash_round_guard.py", monkeypatch)
        _patch_claude_pre_bash_round_state(
            guard,
            monkeypatch,
            open_prs=[{"number": 99, "state": "OPEN"}],
            review_count=2,
        )

        payloads: tuple[dict[str, object], ...] = (
            {"tool_name": "mcp__github__request_ai_review"},
            {"tool_name": "mcp__github__request_copilot_review"},
            {"tool_name": "mcp__github__request_codex_review"},
            {"tool_name": "mcp__github__request_claude_review"},
        )

        for payload in payloads:
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["decision"] == "allow", payload

    def test_claude_pre_bash_round_guard_reminds_review_request_on_develop_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """develop ブランチでも review request はブロックせず reminder にする。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_bash_round_guard.py", monkeypatch)
        _patch_claude_pre_bash_round_state(
            guard,
            monkeypatch,
            branch="develop",
            open_prs=[{"number": 99, "state": "OPEN"}],
            review_count=3,
        )

        result = _run_hook_main(
            guard,
            monkeypatch,
            {"tool_name": "mcp__github__request_copilot_review"},
        )

        assert result["decision"] == "allow"

    def test_claude_pre_bash_round_guard_allows_git_push_on_develop_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """develop ブランチの git push 単体は従来どおり allow する。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_bash_round_guard.py", monkeypatch)
        _patch_claude_pre_bash_round_state(
            guard,
            monkeypatch,
            branch="develop",
            open_prs=[{"number": 99, "state": "OPEN"}],
            review_count=3,
        )

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "tool_name": "Bash",
                "tool_input": {"command": "git push origin develop"},
            },
        )

        assert result["decision"] == "allow"

    def test_pre_task_complete_reminds_task_complete_when_review_count_exceeds_3(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 4 で task_complete は allow + reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 4)
        monkeypatch.setattr(guard, "_has_ci_failure", lambda pr_number: False)

        result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "Round 4" in message or "Round" in message

    def test_review_loop_state_counts_ai_review_markers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AIレビュー数は bot login と generic marker の両方を数える。"""
        state = _load_hook_module(HOOK_DIR / "_review_loop_state.py", monkeypatch)

        class FakeCompletedProcess:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        reviews = [
            {"user": {"login": "octocat"}, "body": "## AI レビュー結果\n- Must: 0"},
            {"user": {"login": "chatgpt-codex-connector"}, "body": "Codex Review"},
            {"user": {"login": "chatgpt-codex-connector[bot]"}, "body": "Codex Review"},
            {"user": {"login": "octocat"}, "body": "通常コメント"},
        ]

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            del args, kwargs
            if cmd[1] == "api" and "reviews" in cmd[-1]:
                return FakeCompletedProcess(0, json.dumps(reviews))
            if cmd[1:3] == ["api", "user"]:
                return FakeCompletedProcess(0, "octocat")
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(state.subprocess, "run", _fake_subprocess_run)

        assert state.get_ai_review_count(99) == 3

    def test_review_loop_state_rejects_untrusted_ai_review_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """generic marker は bot / current user 以外の author では数えない。"""
        state = _load_hook_module(HOOK_DIR / "_review_loop_state.py", monkeypatch)

        class FakeCompletedProcess:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        reviews = [
            {"user": {"login": "other-user"}, "body": "## AI レビュー結果\n- Must: 0"},
            {"user": {"login": "chatgpt-codex-connector"}, "body": "Codex Review"},
        ]

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            del args, kwargs
            if cmd[1] == "api" and "reviews" in cmd[-1]:
                return FakeCompletedProcess(0, json.dumps(reviews))
            if cmd[1:3] == ["api", "user"]:
                return FakeCompletedProcess(0, "octocat")
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(state.subprocess, "run", _fake_subprocess_run)

        assert state.get_ai_review_count(99) == 1

    def test_review_loop_state_fallback_marker_head_overrides_commit_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """fallback marker は GitHub commit_id より本文の reviewed_head_sha を優先する。"""
        state = _load_hook_module(HOOK_DIR / "_review_loop_state.py", monkeypatch)
        review = {
            "commit_id": "oldsha",
            "body": (
                "## AI レビュー結果\n"
                "reviewed_head_sha: `abcdef1234567890`\n"
                "- Must: 0\n"
                "- Should: 0\n"
            ),
        }

        assert state._review_matches_head(review, "abcdef1234567890") is True

    def test_review_loop_state_allows_review_report_only_commit_after_reviewed_head(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review report だけの後続 commit は直前 AI review と互換扱いする。"""
        state = _load_hook_module(HOOK_DIR / "_review_loop_state.py", monkeypatch)
        review = {
            "commit_id": "oldsha",
            "body": ("## AI レビュー結果\nreviewed_head_sha: `abc1234`\n- Must: 0\n- Should: 0\n"),
        }

        monkeypatch.setattr(
            state,
            "_changed_paths_between",
            lambda base_sha, head_sha: ["docs/ai/reviews/2026-05-30-pr360-codex.json"],
        )

        assert state._review_matches_head(review, "def5678") is True

    def test_review_loop_state_rejects_code_commit_after_reviewed_head(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """通常コード差分が後続する場合は stale review として扱う。"""
        state = _load_hook_module(HOOK_DIR / "_review_loop_state.py", monkeypatch)
        review = {
            "commit_id": "oldsha",
            "body": "## AI レビュー結果\nreviewed_head_sha: `abc1234`\n- Must: 0\n- Should: 0\n",
        }

        monkeypatch.setattr(
            state,
            "_changed_paths_between",
            lambda base_sha, head_sha: ["scripts/example.py"],
        )

        assert state._review_matches_head(review, "def5678") is False

    def test_pre_task_complete_reminds_when_review_count_empty_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 空出力なら task_complete は fail-open reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)

        class FakeCompletedProcess:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            del args, kwargs
            if cmd[1:3] == ["pr", "view"]:
                return FakeCompletedProcess(0, json.dumps({"number": 99, "state": "OPEN"}))
            if cmd[1] == "api" and "reviews" in cmd[-1]:
                return FakeCompletedProcess(0, "")
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)

        result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "レビュー数を取得" in message
        assert "fail-open" in message

    def test_stop_review_guard_reminds_when_review_count_exceeds_3(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 4 で Stop hook は allow + reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        monkeypatch.setattr(guard, "_get_copilot_review_count", lambda pr_number: 4)
        monkeypatch.setattr(guard, "_has_ci_failure", lambda pr_number: False)

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        reason = str(hook_output.get("additionalContext", ""))
        assert "Round 4" in reason or "Round" in reason

    def test_stop_review_guard_reminds_when_review_count_empty_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 空出力なら Stop hook は fail-open reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)

        class FakeCompletedProcess:
            def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
                self.returncode = returncode
                self.stdout = stdout
                self.stderr = stderr

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            del args, kwargs
            if cmd[1:3] == ["pr", "view"]:
                return FakeCompletedProcess(0, json.dumps({"number": 99, "state": "OPEN"}))
            if cmd[1] == "api" and "reviews" in cmd[-1]:
                return FakeCompletedProcess(0, "")
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        reason = str(hook_output.get("additionalContext", ""))
        assert "レビュー数を取得" in reason
        assert "fail-open" in reason

    def test_claude_pre_agent_guard_reminds_when_review_count_empty_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude release-manager ゲートで review_count 空出力なら reminder にする。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "pre_agent_guard.py", monkeypatch)
        monkeypatch.setattr(
            guard,
            "_full_plan_completion_reason",
            lambda *, require_delivery_state: None,
        )
        monkeypatch.setattr(guard, "check_ci", lambda pr_number: "")
        monkeypatch.setattr(
            guard,
            "get_copilot_latest_review_info",
            lambda pr_number: ("2026-01-01T00:00:01Z", "1"),
        )
        monkeypatch.setattr(guard, "count_unreplied_copilot_threads", lambda pr_number: 0)

        def _fake_run(
            cmd: list[str],
            timeout: int = 15,
            *,
            allow_nonzero: bool = False,
        ) -> str | None:
            del timeout, allow_nonzero
            if cmd == ["git", "branch", "--show-current"]:
                return "feat/example"
            if cmd[1:3] == ["pr", "list"]:
                return json.dumps([{"number": 99}])
            if cmd[1] == "api" and "reviews" in cmd[-1]:
                return ""
            if cmd[-1] == ".draft":
                return "false"
            if cmd[-1] == ".head.sha":
                return "abcdef1234567890"
            if cmd[-1] == ".commit.committer.date":
                return "2026-01-01T00:00:00Z"
            if "requested_reviewers" in cmd[-1]:
                return "1"
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(guard, "run", _fake_run)

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "tool_name": "Agent",
                "tool_input": {"subagent_type": "release-manager"},
            },
        )

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        reason = str(hook_output.get("additionalContext", ""))
        assert "レビュー数を取得" in reason

    def test_claude_github_api_accepts_generic_ai_review_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude Code hook は generic AI レビュー marker も fallback として扱う。"""
        github_api = _load_hook_module(CLAUDE_HOOK_DIR / "_github_api.py", monkeypatch)
        comments = [
            {
                "user": {"login": "example-owner"},
                "body": (
                    "## AI レビュー結果\n"
                    "- engine: `codex`\n"
                    "- reviewed_head_sha: `abcdef1234567890`\n"
                    "- Must: 0\n"
                    "- Should: 0\n"
                ),
                "created_at": "2026-01-01T00:00:01Z",
            }
        ]

        def _fake_gh_run(
            args: list[str],
            timeout: int = 10,
            *,
            allow_nonzero: bool = False,
        ) -> str | None:
            del timeout, allow_nonzero
            if args[:3] == ["pr", "view", "99"]:
                return "abcdef1234567890"
            if args == ["api", "user", "--jq", ".login"]:
                return "example-owner"
            if args[:2] == ["api", "--paginate"]:
                return json.dumps(comments)
            raise AssertionError(f"unexpected command: {args}")

        monkeypatch.setattr(github_api, "_gh_run", _fake_gh_run)

        assert github_api.has_claude_code_review_marker(99, "2026-01-01T00:00:00Z") is True

    def test_claude_github_api_rejects_stale_ai_review_marker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude Code hook は fallback marker の reviewed_head_sha も照合する。"""
        github_api = _load_hook_module(CLAUDE_HOOK_DIR / "_github_api.py", monkeypatch)
        comments = [
            {
                "user": {"login": "example-owner"},
                "body": (
                    "## AI レビュー結果\n"
                    "- engine: `codex`\n"
                    "- reviewed_head_sha: `oldbeef`\n"
                    "- Must: 0\n"
                    "- Should: 0\n"
                ),
                "created_at": "2026-01-01T00:00:01Z",
            }
        ]

        def _fake_gh_run(
            args: list[str],
            timeout: int = 10,
            *,
            allow_nonzero: bool = False,
        ) -> str | None:
            del timeout, allow_nonzero
            if args[:3] == ["pr", "view", "99"]:
                return "abcdef1234567890"
            if args == ["api", "user", "--jq", ".login"]:
                return "example-owner"
            if args[:2] == ["api", "--paginate"]:
                return json.dumps(comments)
            raise AssertionError(f"unexpected command: {args}")

        monkeypatch.setattr(github_api, "_gh_run", _fake_gh_run)

        assert github_api.has_claude_code_review_marker(99, "2026-01-01T00:00:00Z") is False

    def test_claude_github_api_rejects_generic_ai_review_marker_with_should_left(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude Code hook は Should が残る fallback marker を完了扱いしない。"""
        github_api = _load_hook_module(CLAUDE_HOOK_DIR / "_github_api.py", monkeypatch)
        comments = [
            {
                "user": {"login": "example-owner"},
                "body": (
                    "## AI レビュー結果\n"
                    "- engine: `codex`\n"
                    "- reviewed_head_sha: `abcdef1234567890`\n"
                    "- Must: 0\n"
                    "- Should: 1\n"
                ),
                "created_at": "2026-01-01T00:00:01Z",
            }
        ]

        def _fake_gh_run(
            args: list[str],
            timeout: int = 10,
            *,
            allow_nonzero: bool = False,
        ) -> str | None:
            del timeout, allow_nonzero
            if args[:3] == ["pr", "view", "99"]:
                return "abcdef1234567890"
            if args == ["api", "user", "--jq", ".login"]:
                return "example-owner"
            if args[:2] == ["api", "--paginate"]:
                return json.dumps(comments)
            raise AssertionError(f"unexpected command: {args}")

        monkeypatch.setattr(github_api, "_gh_run", _fake_gh_run)

        assert github_api.has_claude_code_review_marker(99, "2026-01-01T00:00:00Z") is False

    def test_claude_stop_review_guard_reminds_when_review_count_empty_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude Stop hook で review_count 空出力なら reminder にする。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: "")
        monkeypatch.setattr(guard, "is_claude_code_remote", lambda: False)
        monkeypatch.setattr(guard, "has_credentials", lambda: True)
        monkeypatch.setattr(guard, "gh_available", lambda: True)
        monkeypatch.setattr(
            guard,
            "list_open_prs_for_branch",
            lambda branch: [{"number": 99, "state": "OPEN"}],
        )
        monkeypatch.setattr(
            guard,
            "get_pr_check_runs",
            lambda pr_number: [{"name": "ci/final-gate", "state": "SUCCESS"}],
        )
        monkeypatch.setattr(guard, "check_ci", lambda pr_number: [])
        monkeypatch.setattr(
            guard,
            "get_copilot_latest_review_info",
            lambda pr_number: ("2026-01-01T00:00:01Z", "1"),
        )
        monkeypatch.setattr(guard, "count_unreplied_copilot_threads", lambda pr_number: 0)

        def _fake_run(
            cmd: list[str],
            timeout: int = 15,
            *,
            allow_nonzero: bool = False,
        ) -> str | None:
            del timeout, allow_nonzero
            if cmd == ["git", "branch", "--show-current"]:
                return "feat/example"
            if cmd[1] == "api" and "reviews" in cmd[-1]:
                return ""
            if cmd[-1] == ".draft":
                return "false"
            if cmd[-1] == ".head.sha":
                return "abcdef1234567890"
            if cmd[-1] == ".commit.committer.date":
                return "2026-01-01T00:00:00Z"
            if "requested_reviewers" in cmd[-1]:
                return "1"
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(guard, "run", _fake_run)

        result = _run_hook_main(guard, monkeypatch, {})

        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        reason = str(hook_output.get("additionalContext", ""))
        assert "レビュー数を取得" in reason

    def test_claude_stop_review_guard_reminds_without_credentials_in_normal_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """通常環境で認証情報が無ければ fail-open reminder にする。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: "")
        monkeypatch.setattr(guard, "is_claude_code_remote", lambda: False)
        monkeypatch.setattr(guard, "has_credentials", lambda: False)
        monkeypatch.setattr(
            guard,
            "run",
            lambda cmd, timeout=15, allow_nonzero=False: "feat/example",
        )

        result = _run_hook_main(guard, monkeypatch, {})

        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        reason = str(hook_output.get("additionalContext", ""))
        assert "GITHUB_TOKEN/GH_TOKEN 未設定" in reason or "確認できない" in reason

    def test_claude_stop_review_guard_allows_remote_with_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude Code Remote は現行どおり hookSpecificOutput で案内する。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: "")
        monkeypatch.setattr(guard, "is_claude_code_remote", lambda: True)
        monkeypatch.setattr(
            guard,
            "run",
            lambda cmd, timeout=15, allow_nonzero=False: "feat/example",
        )

        result = _run_hook_main(guard, monkeypatch, {})

        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        context = hook_output["additionalContext"]
        assert "Claude Code Remote" in str(context)
        assert "mcp__github__subscribe_pr_activity" in str(context)

    def test_claude_stop_review_guard_reminds_token_only_open_pr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """token-only で OPEN PR があるが詳細確認不能なら reminder にする。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: "")
        monkeypatch.setattr(guard, "is_claude_code_remote", lambda: False)
        monkeypatch.setattr(guard, "has_credentials", lambda: True)
        monkeypatch.setattr(guard, "gh_available", lambda: False)
        monkeypatch.setattr(
            guard,
            "list_open_prs_for_branch",
            lambda branch: [{"number": 99, "state": "OPEN"}],
        )
        monkeypatch.setattr(
            guard,
            "run",
            lambda cmd, timeout=15, allow_nonzero=False: "feat/example",
        )

        result = _run_hook_main(guard, monkeypatch, {})

        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        reason = str(hook_output.get("additionalContext", ""))
        assert "PR #99" in reason
        assert "レビュー詳細を確認できません" in reason

    def test_claude_stop_review_guard_blocks_token_only_ci_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """token-only でも GitHub API で取得した CI failure は block する。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: "")
        monkeypatch.setattr(guard, "is_claude_code_remote", lambda: False)
        monkeypatch.setattr(guard, "has_credentials", lambda: True)
        monkeypatch.setattr(guard, "gh_available", lambda: False)
        monkeypatch.setattr(
            guard,
            "list_open_prs_for_branch",
            lambda branch: [{"number": 99, "state": "OPEN"}],
        )
        monkeypatch.setattr(
            guard,
            "get_pr_check_runs",
            lambda pr_number: [{"name": "ci/final-gate", "state": "FAILURE"}],
        )
        monkeypatch.setattr(
            guard,
            "run",
            lambda cmd, timeout=15, allow_nonzero=False: "feat/example",
        )

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "block"
        assert "ci/final-gate" in str(result["reason"])

    def test_claude_stop_review_guard_allows_token_only_when_no_open_pr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """token-only でも OPEN PR が無いと判定できれば allow する。"""
        guard = _load_hook_module(CLAUDE_HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: "")
        monkeypatch.setattr(guard, "is_claude_code_remote", lambda: False)
        monkeypatch.setattr(guard, "has_credentials", lambda: True)
        monkeypatch.setattr(guard, "gh_available", lambda: False)
        monkeypatch.setattr(guard, "list_open_prs_for_branch", lambda branch: [])
        monkeypatch.setattr(
            guard,
            "run",
            lambda cmd, timeout=15, allow_nonzero=False: "feat/example",
        )

        result = _run_hook_main(guard, monkeypatch, {})

        assert result == {}

    def test_post_push_shows_round_4_reminder_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 3 で PostToolUse が Round 4 相当の reminder を出す。"""
        hook = _load_hook_module(HOOK_DIR / "post_push_reminder.py", monkeypatch)

        def _fake_run(cmd: list[str], timeout: int = 10) -> str | None:
            del timeout
            if cmd[1:] == ["branch", "--show-current"]:
                return "feat/example"
            if cmd[1:3] == ["pr", "list"]:
                return json.dumps([{"number": 99, "state": "OPEN", "isDraft": False}])
            if cmd[1:3] == ["api", "--paginate"]:
                return "\n".join(["copilot-pull-request-reviewer[bot]"] * 3)
            raise AssertionError(f"unexpected command: {cmd}")

        monkeypatch.setattr(hook, "_run", _fake_run)
        monkeypatch.setattr(hook, "_check_token_status", lambda: "")
        monkeypatch.setattr(hook._review_loop_state, "get_ai_review_count", lambda pr_number: 3)

        result = _run_hook_main(
            hook,
            monkeypatch,
            {"tool_name": "run_in_terminal", "tool_input": {"command": "git push"}},
        )

        assert result["decision"] == "allow"
        reason = str(result.get("reason", ""))
        assert "Round 4" in reason
        assert "ブロックしません" in reason
        assert "Backlog" in reason or "fail-close" in reason

    def test_pre_task_complete_allows_round_3_task_complete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_count 3 で task_complete は allow する（Round 3 後の最終ゲート用）。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=3,
            ci_failure=False,
            latest_review_arrived=True,
            reviewer_count=1,
            unreplied_threads=0,
        )

        for payload in _release_gate_payloads():
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow"

    def test_pre_task_complete_reminds_when_latest_review_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """task_complete / release-manager は最新 review 未到着を reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=1,
            latest_review_arrived=False,
            reviewer_count=1,
            unreplied_threads=0,
        )

        for payload in _release_gate_payloads():
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow"
            assert "最新コミット" in str(result.get("message", ""))

    def test_pre_task_complete_reminds_when_unreplied_threads_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """task_complete / release-manager は未返信スレッドを reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=1,
            latest_review_arrived=True,
            reviewer_count=1,
            unreplied_threads=2,
        )

        for payload in _release_gate_payloads():
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow"
            assert "未返信スレッド" in str(result.get("message", ""))

    def test_pre_task_complete_reminds_when_reviewer_missing_and_review_needed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """task_complete / release-manager は reviewer 未設定を reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=1,
            latest_review_arrived=False,
            reviewer_count=0,
            unreplied_threads=0,
        )

        for payload in _release_gate_payloads():
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow"
            assert "レビュワー未設定" in str(result.get("message", ""))

    def test_pre_task_complete_reminds_when_review_count_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """task_complete / release-manager は review_count 取得不能を reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=None,
        )

        for payload in _release_gate_payloads():
            result = _run_hook_main(guard, monkeypatch, payload)
            assert result["permissionDecision"] == "allow"
            assert "レビュー数を取得" in str(result.get("message", ""))

    def test_stop_review_guard_reminds_when_latest_review_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop hook は最新 review 未到着を reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=1,
            latest_review_arrived=False,
            reviewer_count=1,
            unreplied_threads=0,
        )

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        assert "最新コミット" in str(hook_output.get("additionalContext", ""))

    def test_stop_review_guard_reminds_when_unreplied_threads_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop hook は未返信スレッドを reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=1,
            latest_review_arrived=True,
            reviewer_count=1,
            unreplied_threads=2,
        )

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        assert "未返信スレッド" in str(hook_output.get("additionalContext", ""))

    def test_stop_review_guard_reminds_when_reviewer_missing_and_review_needed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop hook は reviewer 未設定を reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=1,
            latest_review_arrived=False,
            reviewer_count=0,
            unreplied_threads=0,
        )

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        assert "レビュワー未設定" in str(hook_output.get("additionalContext", ""))

    def test_stop_review_guard_reminds_when_review_count_is_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop hook は review_count 取得不能を reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=None,
        )

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        assert "レビュー数を取得" in str(hook_output.get("additionalContext", ""))

    def test_stop_review_guard_allows_when_round_3_review_gate_is_complete(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop hook は review_count 3 でも完了条件が揃えば allow する。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (99, None))
        _patch_vscode_review_gate_state(
            guard,
            monkeypatch,
            review_count=3,
            ci_failure=False,
            latest_review_arrived=True,
            reviewer_count=1,
            unreplied_threads=0,
        )

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"

    def test_git_push_reminds_when_pr_lookup_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """git push 時の PR lookup エラーは fail-open reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(
            guard, "_get_open_pr_number_result", lambda: (None, "gh pr view タイムアウト")
        )

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": "run_in_terminal",
                "toolInput": {"command": "git push origin feat/example"},
            },
        )

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "PR lookup エラー" in message
        assert "fail-open" in message

    def test_reviewer_request_reminds_when_pr_lookup_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reviewer request 時の PR lookup エラーは fail-open reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(
            guard, "_get_open_pr_number_result", lambda: (None, "JSON パースエラー")
        )

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": "run_in_terminal",
                "toolInput": {
                    "command": "gh api repos/owner/repo/pulls/99/requested_reviewers --method POST"
                },
            },
        )

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "PR lookup エラー" in message
        assert "fail-open" in message

    def test_task_complete_reminds_when_pr_lookup_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """task_complete 時の PR lookup エラーは fail-open reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(guard, "_get_open_pr_number_result", lambda: (None, "認証エラー"))

        result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "PR lookup エラー" in message
        assert "fail-open" in message

    def test_release_manager_reminds_when_pr_lookup_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """release-manager 呼び出し時の PR lookup エラーは fail-open reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)
        monkeypatch.setattr(
            guard, "_get_open_pr_number_result", lambda: (None, "ネットワークタイムアウト")
        )

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": "runSubagent",
                "toolInput": {"agentName": "release-manager"},
            },
        )

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "PR lookup エラー" in message
        assert "fail-open" in message

    def test_gh_pr_view_auth_error_is_detected_as_lookup_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gh pr view が HTTP 401 で失敗した場合は認証エラーとして lookup_error 扱いする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "HTTP 401: Bad credentials (https://api.github.com/)"

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            return FakeCompletedProcess()

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)

        pr_number, error = guard._get_open_pr_number_result()

        assert pr_number is None
        assert error is not None
        assert "gh pr view failed" in error
        assert "401" in error or "Bad credentials" in error.lower()

    def test_gh_pr_view_no_pr_found_is_treated_as_normal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gh pr view が 'no pull requests found' で失敗した場合は正常扱いする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "no pull requests found for branch feat/example"

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            return FakeCompletedProcess()

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)

        pr_number, error = guard._get_open_pr_number_result()

        assert pr_number is None
        assert error is None

    def test_git_push_reminds_when_gh_pr_view_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """git push 時に gh pr view が認証エラーで失敗した場合は reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "HTTP 401: Bad credentials (https://api.github.com/)"

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            return FakeCompletedProcess()

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": "run_in_terminal",
                "toolInput": {"command": "git push origin feat/example"},
            },
        )

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "PR lookup エラー" in message
        assert "fail-open" in message

    def test_git_push_allows_when_gh_pr_view_no_pr_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """git push 時に gh pr view が 'no pull requests found' で失敗した場合は allow する。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "no pull requests found for branch feat/example"

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            return FakeCompletedProcess()

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)

        result = _run_hook_main(
            guard,
            monkeypatch,
            {
                "toolName": "run_in_terminal",
                "toolInput": {"command": "git push origin feat/example"},
            },
        )

        assert result["permissionDecision"] == "allow"

    def test_task_complete_reminds_when_gh_pr_view_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """task_complete 時に gh pr view が認証エラーで失敗した場合は reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "pre_task_complete_guard.py", monkeypatch)

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "HTTP 401: Bad credentials (https://api.github.com/)"

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            return FakeCompletedProcess()

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)

        result = _run_hook_main(guard, monkeypatch, {"toolName": "task_complete"})

        assert result["permissionDecision"] == "allow"
        message = str(result.get("message", ""))
        assert "PR lookup エラー" in message
        assert "fail-open" in message

    def test_stop_hook_reminds_when_gh_pr_view_auth_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop hook で gh pr view が認証エラーで失敗した場合は reminder にする。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "HTTP 401: Bad credentials (https://api.github.com/)"

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            return FakeCompletedProcess()

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
        hook_output = cast("dict[str, object]", result["hookSpecificOutput"])
        reason = str(hook_output.get("additionalContext", ""))
        assert "PR lookup エラー" in reason
        assert "fail-open" in reason

    def test_stop_hook_allows_when_gh_pr_view_no_pr_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop hook で gh pr view が 'no pull requests found' で失敗した場合は allow する。"""
        guard = _load_hook_module(HOOK_DIR / "stop_review_guard.py", monkeypatch)

        class FakeCompletedProcess:
            returncode = 1
            stdout = ""
            stderr = "no pull requests found for branch feat/example"

        def _fake_subprocess_run(
            cmd: list[str],
            *args: object,
            **kwargs: object,
        ) -> FakeCompletedProcess:
            return FakeCompletedProcess()

        monkeypatch.setattr(guard.subprocess, "run", _fake_subprocess_run)
        monkeypatch.setattr(guard, "full_plan_completion_block_reason", lambda: None)

        result = _run_hook_main(guard, monkeypatch, {})

        assert result["decision"] == "allow"
