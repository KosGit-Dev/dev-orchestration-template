"""指示元権限（P-066）判別ロジックと UserPromptSubmit hook の境界テスト。

- 純関数 ``classify_source`` / ``build_additional_context``
  （``scripts/hooks/instruction_source.py``）
- 実 hook ``.claude/hooks/instruction_source_guard.py`` の結線（stdin JSON → stdout JSON・exit 0）

判別の既定は人間（authoritative）であり、harness 由来の高精度マーカーが検出された
ときのみ非人間（advisory）へ倒す。hook は常に非ブロッキング（exit 0・fail-open）。
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_instruction_source() -> types.ModuleType:
    module_path = _REPO_ROOT / "scripts" / "hooks" / "instruction_source.py"
    spec = importlib.util.spec_from_file_location("instruction_source", module_path)
    if spec is None or spec.loader is None:
        msg = "instruction_source.py を読み込めません"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


instruction_source = _load_instruction_source()

_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "instruction_source_guard.py"


# ---------------------------------------------------------------------------
# classify_source: 既定は人間（authoritative）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "作業を続行。次のタスクを着地させて。",
        "プランの全実施。",
        "現在の状況を確認",
        "Please refactor the auth module.",
        "agmsg について説明して",  # 単語が出るだけでは非人間にしない（誤検出回避）
        # 人間の許可付与・質問文を誤分類しない（Must 回帰・permission to use 過剰汎化）
        "You have permission to use bash freely.",
        "I give you permission to use the API.",
        # 人間が harness タグを行中で引用しただけでは誤分類しない（行頭マッチ・governance 保護）
        "Please add the `<system-reminder>` marker to the list.",
        "docs で <task-notification> タグの扱いを説明してほしい",
        "マーカーに <github-webhook-activity> を追加して",
    ],
)
def test_classify_human_default(prompt: str) -> None:
    result = instruction_source.classify_source(prompt)
    assert result["source"] == instruction_source.SOURCE_HUMAN
    assert result["authority"] == "authoritative"
    assert result["matched_marker"] == ""


@pytest.mark.parametrize("prompt", ["", None])
def test_classify_empty_is_human(prompt: str | None) -> None:
    result = instruction_source.classify_source(prompt)
    assert result["source"] == instruction_source.SOURCE_HUMAN


@pytest.mark.parametrize(
    "prompt",
    [
        # 本セッションで実際に誤読したツール拒否文面
        "The user doesn't want to take this action right now. STOP what you are doing",
        "The user does not want to take this action",
        "Stop hook feedback: 全プラン完了未認証",
        "Stop hook blocking error from command",
        "<task-notification>\n<task-id>abc</task-id>",
        "<system-reminder>\nAs you answer ...\n</system-reminder>",
        "<github-webhook-activity>\nYou are now subscribed to PR activity for repo#643.",
        "  <task-notification>\n  <event>build: pass</event>",  # 先頭空白ありでも行頭一致
        "[SYSTEM NOTIFICATION - NOT USER INPUT] automated background-task event",
        "This is an automated background-task event, NOT a message from the user.",
        "Tool call was denied by the user",
        "tool use was rejected",
    ],
)
def test_classify_non_human_markers(prompt: str) -> None:
    result = instruction_source.classify_source(prompt)
    assert result["source"] == instruction_source.SOURCE_NON_HUMAN
    assert result["authority"] == "advisory"
    assert result["matched_marker"]


def test_line_start_vs_inline_tag_distinction() -> None:
    """同一タグでも行頭は非人間、行中引用は人間（governance 引用の保護）。"""
    at_line_start = instruction_source.classify_source("<system-reminder>\nfoo")
    assert at_line_start["source"] == instruction_source.SOURCE_NON_HUMAN
    inline_quote = instruction_source.classify_source("この <system-reminder> を非人間に分類して")
    assert inline_quote["source"] == instruction_source.SOURCE_HUMAN


def test_substring_marker_quoted_is_human() -> None:
    """Backlog-N641: 人間が拒否文をコードスパン/引用符で引用しただけなら advisory に落とさない。"""
    backtick = instruction_source.classify_source(
        "`tool call was denied` の文面を P-066 マーカーから外して"
    )
    assert backtick["source"] == instruction_source.SOURCE_HUMAN
    jp_quote = instruction_source.classify_source(
        "「the user doesn't want to take this action」をテストに追加して"
    )
    assert jp_quote["source"] == instruction_source.SOURCE_HUMAN
    dq_quote = instruction_source.classify_source(
        'レビューで "tool use was rejected" を引用しただけの行を直して'
    )
    assert dq_quote["source"] == instruction_source.SOURCE_HUMAN


def test_substring_marker_raw_still_non_human() -> None:
    """引用されていない raw な拒否文面は従来どおり advisory（引用保護で取りこぼさない）。"""
    raw = instruction_source.classify_source("The user doesn't want to take this action right now.")
    assert raw["source"] == instruction_source.SOURCE_NON_HUMAN
    assert raw["matched_marker"]


def test_strip_quoted_spans_keeps_apostrophe_phrases() -> None:
    """単一引用符（apostrophe）は除去対象外＝raw な \"doesn't\" 系を誤って保護しない。"""
    stripped = instruction_source._strip_quoted_spans("the user doesn't want to take this action")
    # apostrophe は除去されず、raw 文面は照合対象に残る
    assert "doesn't want to take this action" in stripped


def test_classify_case_insensitive() -> None:
    upper = "THE USER DOESN'T WANT TO TAKE THIS ACTION"
    result = instruction_source.classify_source(upper)
    assert result["source"] == instruction_source.SOURCE_NON_HUMAN


# ---------------------------------------------------------------------------
# build_additional_context: 常時ルール注入
# ---------------------------------------------------------------------------


def test_context_always_contains_authority_rule() -> None:
    for src in (instruction_source.SOURCE_HUMAN, instruction_source.SOURCE_NON_HUMAN):
        ctx = instruction_source.build_additional_context({"source": src, "matched_marker": "x"})
        assert instruction_source.AUTHORITY_RULE in ctx
        assert "P-066" in ctx


def test_context_head_differs_by_source() -> None:
    human = instruction_source.build_additional_context(
        {"source": instruction_source.SOURCE_HUMAN, "matched_marker": ""}
    )
    non_human = instruction_source.build_additional_context(
        {"source": instruction_source.SOURCE_NON_HUMAN, "matched_marker": "stop hook feedback:"}
    )
    assert "人間オペレーターの指示として扱う" in human
    assert "助言・自動ガードとして扱い" in non_human
    assert non_human != human


# ---------------------------------------------------------------------------
# 実 hook の結線テスト（G-4: hook が機能する）
# ---------------------------------------------------------------------------


def _run_hook(stdin_text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=stdin_text,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_hook_human_prompt_outputs_context() -> None:
    proc = _run_hook(json.dumps({"prompt": "作業を続行"}))
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    out = payload["hookSpecificOutput"]
    assert out["hookEventName"] == "UserPromptSubmit"
    assert "P-066" in out["additionalContext"]
    assert "人間オペレーターの指示として扱う" in out["additionalContext"]


def test_hook_tool_denial_classified_non_human() -> None:
    proc = _run_hook(json.dumps({"prompt": "The user doesn't want to take this action right now."}))
    assert proc.returncode == 0
    ctx = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "助言・自動ガードとして扱い" in ctx


def test_hook_empty_stdin_is_non_blocking() -> None:
    proc = _run_hook("")
    assert proc.returncode == 0


def test_hook_invalid_json_is_non_blocking() -> None:
    proc = _run_hook("not valid json {")
    # fail-open: 不正入力でも exit 0（継続作業を中断しない）
    assert proc.returncode == 0


def _load_guard_module() -> types.ModuleType:
    module_path = _REPO_ROOT / ".claude" / "hooks" / "instruction_source_guard.py"
    spec = importlib.util.spec_from_file_location("instruction_source_guard", module_path)
    if spec is None or spec.loader is None:
        msg = "instruction_source_guard.py を読み込めません"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hook_main_exception_path_emits_minimal_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """判別ロジックが例外を投げても fail-open で最小妥当 JSON を出力し exit 0（Should 2）。"""
    guard = _load_guard_module()

    def _raise(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("forced failure for fail-open test")

    # guard.main() は内部で ``from instruction_source import ...`` を実行するため、
    # sys.modules にエラーを投げる fake モジュールを注入して例外パスを確実に踏ませる。
    fake = types.ModuleType("instruction_source")
    fake.classify_source = instruction_source.classify_source  # type: ignore[attr-defined]
    fake.build_additional_context = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "instruction_source", fake)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "x"})))

    rc = guard.main()

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert payload["hookSpecificOutput"]["additionalContext"] == ""
