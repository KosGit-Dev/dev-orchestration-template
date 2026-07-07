"""Stop hook ループ検出のテスト。

Stop hook が同一 reason で繰り返し block し、エージェントが同一の応答を
何十回も出力し続ける問題の再発防止を確認する。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_HOOK_DIR = REPO_ROOT / ".claude" / "hooks"
SCRIPTS_HOOK_DIR = REPO_ROOT / "scripts" / "hooks"


def _load_block_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """_block_history モジュールをテスト用に読み込む。"""
    monkeypatch.syspath_prepend(str(CLAUDE_HOOK_DIR))
    spec = importlib.util.spec_from_file_location(
        "_block_history", CLAUDE_HOOK_DIR / "_block_history.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "_block_history", module)
    spec.loader.exec_module(module)
    module.HISTORY_PATH = tmp_path / "history.json"
    return module


def _load_claude_stop_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Claude Stop hook をテスト用に読み込む。"""
    _load_block_history(tmp_path, monkeypatch)
    monkeypatch.syspath_prepend(str(CLAUDE_HOOK_DIR))
    spec = importlib.util.spec_from_file_location(
        "claude_stop_review_guard_test", CLAUDE_HOOK_DIR / "stop_review_guard.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "claude_stop_review_guard_test", module)
    spec.loader.exec_module(module)
    return module


def _load_scripts_stop_guard(monkeypatch: pytest.MonkeyPatch) -> Any:
    """scripts/hooks 側の Stop hook をテスト用に読み込む。"""
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location(
        "scripts_stop_review_guard_test", SCRIPTS_HOOK_DIR / "stop_review_guard.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "scripts_stop_review_guard_test", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def bh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """_block_history モジュールをロードして返す。"""
    return _load_block_history(tmp_path, monkeypatch)


# ---------------------------------------------------------------------------
# ケース 1: compute_fingerprint — 同一入力で同一 hash
# ---------------------------------------------------------------------------
def test_compute_fingerprint_same_input_same_hash(bh: object) -> None:
    """同一入力なら同一 fingerprint を返す。"""
    import _block_history as m

    fp1 = m.compute_fingerprint("325", ["id1", "id2"], ["quality-gate"])
    fp2 = m.compute_fingerprint("325", ["id1", "id2"], ["quality-gate"])
    assert fp1 == fp2


# ---------------------------------------------------------------------------
# ケース 2: compute_fingerprint — リスト順不同で同一 hash（sorted）
# ---------------------------------------------------------------------------
def test_compute_fingerprint_order_independent(bh: object) -> None:
    """リスト要素の順序が違っても同一 fingerprint を返す（sorted 保証）。"""
    import _block_history as m

    fp1 = m.compute_fingerprint("325", ["id2", "id1"], ["b", "a"])
    fp2 = m.compute_fingerprint("325", ["id1", "id2"], ["a", "b"])
    assert fp1 == fp2


# ---------------------------------------------------------------------------
# ケース 2b: compute_fingerprint — 別入力で別 hash
# ---------------------------------------------------------------------------
def test_compute_fingerprint_different_input_different_hash(bh: object) -> None:
    """入力が異なれば異なる fingerprint を返す。"""
    import _block_history as m

    fp1 = m.compute_fingerprint("325", ["id1"], ["quality-gate"])
    fp2 = m.compute_fingerprint("326", ["id1"], ["quality-gate"])
    assert fp1 != fp2

    fp3 = m.compute_fingerprint("325", [], ["quality-gate"])
    assert fp1 != fp3


# ---------------------------------------------------------------------------
# ケース 3: record_block_and_check_repeat — 1 回目 count=1 / exceeded=False
# ---------------------------------------------------------------------------
def test_record_block_first_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """1 回目の記録で count=1、exceeded=False を返す。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    count, exceeded = m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    assert count == 1
    assert exceeded is False


# ---------------------------------------------------------------------------
# ケース 4: record_block_and_check_repeat — 2 回目 count=2 / exceeded=False
# ---------------------------------------------------------------------------
def test_record_block_second_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """2 回目の記録で count=2、exceeded=False を返す（max_repeats=3 デフォルト）。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    count, exceeded = m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    assert count == 2
    assert exceeded is False


# ---------------------------------------------------------------------------
# ケース 5: 3 回目で exceeded=True（max_repeats=3 なら 3 回目で発火）
# ---------------------------------------------------------------------------
def test_record_block_third_call_exceeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """3 回目の記録で exceeded=True になる（max_repeats=3）。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    count, exceeded = m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    assert count == 3
    assert exceeded is True


# ---------------------------------------------------------------------------
# ケース 6: PR 番号が変わったら count リセット
# ---------------------------------------------------------------------------
def test_record_block_resets_on_pr_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PR 番号が変わったら count が 1 にリセットされる。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    # PR #325 で 2 回記録
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    # PR #326 に変更 → リセット
    count, exceeded = m.record_block_and_check_repeat("326", "fp_abc", path=hist_path)
    assert count == 1
    assert exceeded is False


# ---------------------------------------------------------------------------
# ケース 7: fingerprint が変わったら count リセット
# ---------------------------------------------------------------------------
def test_record_block_resets_on_fingerprint_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同じ PR でも fingerprint が変わったら count が 1 にリセットされる。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    # fingerprint 変更 → リセット
    count, exceeded = m.record_block_and_check_repeat("325", "fp_xyz", path=hist_path)
    assert count == 1
    assert exceeded is False


def test_record_block_resets_invalid_count_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """履歴 count が不正型でも例外にせず 1 回目として扱う。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    hist_path.write_text(
        json.dumps({"pr_number": "325", "fingerprint": "fp_abc", "count": None}),
        encoding="utf-8",
    )

    count, exceeded = m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)

    assert count == 1
    assert exceeded is False


# ---------------------------------------------------------------------------
# ケース 8: history file 破損時に空 dict を返す
# ---------------------------------------------------------------------------
def test_load_history_returns_empty_on_corruption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """破損した history ファイルで load_history が空 dict を返す。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    hist_path.write_text("{broken json!!!", encoding="utf-8")
    result = m.load_history(hist_path)
    assert result == {}


# ---------------------------------------------------------------------------
# ケース 9: history file 不在時に空 dict を返す
# ---------------------------------------------------------------------------
def test_load_history_returns_empty_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """存在しない history ファイルで load_history が空 dict を返す。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "nonexistent.json"
    result = m.load_history(hist_path)
    assert result == {}


# ---------------------------------------------------------------------------
# ケース 10: build_escalation_reason が unreplied_thread_ids / ci_failure_names を含む
# ---------------------------------------------------------------------------
def test_build_escalation_reason_contains_ids_and_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_escalation_reason が unreplied thread IDs と CI failure 名を含む。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    reason = m.build_escalation_reason(
        pr_number="325",
        fingerprint="ab12cd34",
        repeats=3,
        unreplied_thread_ids=["3263639434", "3263639470"],
        ci_failure_names=["quality-gate"],
    )
    assert "3263639434" in reason
    assert "3263639470" in reason
    assert "quality-gate" in reason
    assert "PR #325" in reason
    assert "ab12cd34" in reason


# ---------------------------------------------------------------------------
# ケース 11: build_escalation_reason が「override 禁止」言及を含む
# ---------------------------------------------------------------------------
def test_build_escalation_reason_mentions_override_prohibition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_escalation_reason が進捗ゼロでの override 要求禁止を明記する。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    reason = m.build_escalation_reason(
        pr_number="325",
        fingerprint="ab12cd34",
        repeats=3,
    )
    # 「override を要求する」が禁止されていることを示す文言を含む
    assert "override" in reason
    assert "禁止" in reason


# ---------------------------------------------------------------------------
# ケース 12: reset_history で履歴削除
# ---------------------------------------------------------------------------
def test_reset_history_deletes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """reset_history が履歴ファイルを削除する。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "history.json"
    # まず何か書き込む
    m.record_block_and_check_repeat("325", "fp_abc", path=hist_path)
    assert hist_path.exists()

    m.reset_history(hist_path)
    assert not hist_path.exists()


# ---------------------------------------------------------------------------
# 追加: reset_history は存在しないファイルでもエラーにならない
# ---------------------------------------------------------------------------
def test_reset_history_no_error_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reset_history はファイルが存在しなくてもエラーにならない。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    hist_path = tmp_path / "nonexistent.json"
    m.reset_history(hist_path)  # エラーなく終了すればよい


def test_build_escalation_reason_contains_other_reasons(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_escalation_reason が stop guard 由来の reason も含める。"""
    _load_block_history(tmp_path, monkeypatch)
    import _block_history as m

    reason = m.build_escalation_reason(
        pr_number="355",
        fingerprint="deadbeef",
        repeats=3,
        other_reasons=["CI 'ci/final-gate' が FAILURE"],
    )

    assert "other_reasons" in reason
    assert "ci/final-gate" in reason


def test_claude_stop_guard_block_escalates_on_repeated_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Claude Stop hook の _block が 3 回目で履歴 helper の reason に切り替わる。"""
    guard = _load_claude_stop_guard(tmp_path, monkeypatch)
    issues = ["CI 'ci/final-gate' が FAILURE"]

    guard._block("review-branch", "355", issues)
    first = json.loads(capsys.readouterr().out)
    assert "レビューループ未完了" in first["reason"]

    guard._block("review-branch", "355", issues)
    second = json.loads(capsys.readouterr().out)
    assert "レビューループ未完了" in second["reason"]

    guard._block("review-branch", "355", issues)
    third = json.loads(capsys.readouterr().out)
    assert "同一ブロック 3 回検出" in third["reason"]
    assert "other_reasons" in third["reason"]
    assert "ci/final-gate" in third["reason"]


def test_claude_stop_guard_block_falls_back_when_history_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """履歴記録が失敗しても Stop hook は通常 reason で block を返す。"""
    guard = _load_claude_stop_guard(tmp_path, monkeypatch)
    monkeypatch.setattr(
        guard,
        "record_block_and_check_repeat",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("broken history")),
    )

    guard._block("review-branch", "355", ["未返信コメント数を取得できない"])
    output = json.loads(capsys.readouterr().out)

    assert output["decision"] == "block"
    assert "レビューループ未完了" in output["reason"]
    assert "broken history" not in output["reason"]


def test_scripts_stop_guard_repeat_aware_reason_escalates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """scripts/hooks 側も 3 回目で履歴 helper の reason に切り替える。"""
    block_history = _load_block_history(tmp_path, monkeypatch)
    guard = _load_scripts_stop_guard(monkeypatch)
    monkeypatch.setattr(guard, "_load_block_history_module", lambda: block_history)
    issues = ["未返信コメント数を取得できない（GraphQL エラー）"]

    first = guard._build_repeat_aware_reason("355", issues, "default reason")
    second = guard._build_repeat_aware_reason("355", issues, "default reason")
    third = guard._build_repeat_aware_reason("355", issues, "default reason")

    assert first == "default reason"
    assert second == "default reason"
    assert "同一ブロック 3 回検出" in third
    assert "GraphQL エラー" in third


def test_claude_stop_guard_ci_issues_treats_skipped_and_neutral_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SKIPPED / NEUTRAL は条件付き job の正常終端であり blocking にしない。

    条件付き job（deploy=SKIPPED 等）を blocking 扱いした不具合の回帰テスト。
    scripts/hooks/ci_checks.py の success_conclusions と同一集合であることを確認する。
    """
    module = _load_claude_stop_guard(tmp_path, monkeypatch)
    checks: list[dict[str, object]] = [
        {"name": "build", "state": "SUCCESS"},
        {"name": "deploy", "state": "SKIPPED"},
        {"name": "lint", "state": "NEUTRAL"},
    ]
    assert module._ci_issues_from_checks(checks) == []

    failing = [{"name": "quality-gate", "state": "FAILURE"}]
    assert module._ci_issues_from_checks(failing) == ["CI 'quality-gate' が FAILURE"]

    pending = [{"name": "build", "state": "IN_PROGRESS"}]
    assert module._ci_issues_from_checks(pending) == ["CI 'build' が IN_PROGRESS"]
