"""whisky_build.py のデータ検証ロジックの単体テスト。

問題バンク統合時の検証（validate_question / read_jsonl）が
不正データを確実に弾くことを、ダミーデータのみで確認する。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO = Path(__file__).resolve().parent.parent


def _load_module() -> ModuleType:
    src = REPO / "scripts" / "whisky_build.py"
    spec = importlib.util.spec_from_file_location("whisky_build", src)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["whisky_build"] = mod
    spec.loader.exec_module(mod)
    return mod


wb = _load_module()


def _valid_question() -> dict[str, object]:
    return {
        "id": "T-001",
        "level": "expert",
        "category": "distillery",
        "question": "ダミー設問",
        "choices": ["a", "b", "c", "d"],
        "answer": 1,
        "explanation": "ダミー解説",
    }


def test_valid_question_passes() -> None:
    assert wb.validate_question(_valid_question(), "t") is None


@pytest.mark.parametrize(
    ("patch", "reason_part"),
    [
        ({"level": "beginner"}, "level"),
        ({"answer": 4}, "answer"),
        ({"answer": "1"}, "answer"),
        ({"answer": True}, "answer"),
        ({"answer": False}, "answer"),
        ({"choices": ["a", "b", "c"]}, "choices"),
        ({"choices": ["a", "a", "b", "c"]}, "重複"),
        ({"explanation": ""}, "必須キー"),
    ],
)
def test_invalid_question_rejected(patch: dict[str, object], reason_part: str) -> None:
    q = _valid_question()
    q.update(patch)
    reason = wb.validate_question(q, "t")
    assert reason is not None
    assert reason_part in reason


def test_missing_key_rejected() -> None:
    q = _valid_question()
    del q["question"]
    assert wb.validate_question(q, "t") is not None


def test_read_jsonl_skips_broken_lines(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\nこれはJSONではない\n\n{"b": 2},\n', encoding="utf-8")
    items = wb.read_jsonl(p)
    assert items == [{"a": 1}, {"b": 2}]


def test_read_jsonl_skips_non_dict_lines(tmp_path: Path) -> None:
    p = tmp_path / "x.jsonl"
    p.write_text('{"a": 1}\n[]\n"x"\n1\nnull\n{"b": 2}\n', encoding="utf-8")
    items = wb.read_jsonl(p)
    assert items == [{"a": 1}, {"b": 2}]
