#!/usr/bin/env python3
"""ウイスキーコニサー道場のデータ統合・単一ファイルビルド。

1. app/data/raw/ の生成物（JSONL/JSON）を検証・統合し、app/data/*.js を生成する
2. app/index.html に CSS/JS/データをインライン展開した release/whisky-connoisseur.html を生成する

使い方:
  python3 scripts/whisky_build.py            # データ統合 + 単一ファイルビルド
  python3 scripts/whisky_build.py --dist-only  # 単一ファイルビルドのみ
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
RAW = APP / "data" / "raw"
DIST = ROOT / "release"

LEVELS = {"expert", "professional", "master"}
Q_REQUIRED = ("id", "level", "category", "question", "choices", "answer", "explanation")


def read_jsonl(path: Path) -> list[dict]:
    items = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as e:
            print(f"  WARN {path.name}:{i + 1} JSON エラーのため行を除外: {e}")
    return items


def validate_question(q: dict, src: str) -> str | None:
    """不正な問題は理由を返す（None なら合格）。"""
    for k in Q_REQUIRED:
        if k not in q or q[k] in (None, ""):
            return f"必須キー欠落: {k}"
    if q["level"] not in LEVELS:
        return f"不正な level: {q['level']}"
    if not isinstance(q["choices"], list) or len(q["choices"]) != 4:
        return "choices が4件でない"
    if q["answer"] not in (0, 1, 2, 3):
        return f"不正な answer: {q['answer']}"
    if len({str(c).strip() for c in q["choices"]}) != 4:
        return "選択肢に重複がある"
    return None


def build_questions() -> list[dict]:
    questions: list[dict] = []
    seen_ids: set[str] = set()
    seen_texts: set[str] = set()
    dropped = 0
    files = sorted((RAW / "questions").glob("*.jsonl"))
    for f in files:
        n_ok = 0
        for q in read_jsonl(f):
            reason = validate_question(q, f.name)
            if reason:
                print(f"  WARN {f.name} {q.get('id', '?')} 除外: {reason}")
                dropped += 1
                continue
            key = re.sub(r"\s", "", str(q["question"]))
            if q["id"] in seen_ids or key in seen_texts:
                dropped += 1
                continue
            seen_ids.add(q["id"])
            seen_texts.add(key)
            q.setdefault("tags", [])
            q.setdefault("region", None)
            q.setdefault("difficulty", 3)
            questions.append(q)
            n_ok += 1
        print(f"  {f.name}: {n_ok}問")
    # 官能問題も統合プールへ（type/color_hex 付き）
    sensory_path = RAW / "sensory.json"
    if sensory_path.exists():
        sen = json.loads(sensory_path.read_text(encoding="utf-8"))
        n_ok = 0
        for q in sen.get("questions", []):
            q.setdefault("category", "tasting")
            q.setdefault("domain", "sen")
            reason = validate_question(q, "sensory.json")
            if reason or q["id"] in seen_ids:
                dropped += 1
                continue
            seen_ids.add(q["id"])
            q.setdefault("tags", [])
            q.setdefault("region", None)
            q.setdefault("difficulty", 3)
            questions.append(q)
            n_ok += 1
        print(f"  sensory.json: {n_ok}問")
    print(f"統合: {len(questions)}問（除外 {dropped}件）")
    return questions


def build_essays() -> list[dict]:
    essays = []
    seen = set()
    for f in sorted((RAW / "essays").glob("*.jsonl")):
        for e in read_jsonl(f):
            if not e.get("id") or not e.get("question") or e["id"] in seen:
                continue
            seen.add(e["id"])
            essays.append(e)
    essays.sort(key=lambda e: e["id"])
    print(f"論文テーマ: {len(essays)}本")
    return essays


def write_js(path: Path, var: str, data: object, header: str) -> None:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"// {header}\nwindow.{var} = {body};\n", encoding="utf-8")
    print(f"  -> {path.relative_to(ROOT)} ({path.stat().st_size // 1024} KB)")


def integrate() -> None:
    print("== データ統合 ==")
    qs = build_questions()
    if qs:
        write_js(
            APP / "data" / "questions.js",
            "WCQ_QUESTIONS",
            qs,
            "生成物: scripts/whisky_build.py（問題バンク統合）",
        )
        c = Counter(q["level"] for q in qs)
        print(f"  レベル別: expert={c['expert']} pro={c['professional']} master={c['master']}")
    else:
        print("  WARN 問題データなし。既存 questions.js を維持")

    essays = build_essays()
    if essays:
        write_js(
            APP / "data" / "essays.js",
            "WCQ_ESSAYS",
            essays,
            "生成物: scripts/whisky_build.py（論文テーマ統合）",
        )

    map_path = RAW / "map.json"
    if map_path.exists():
        m = json.loads(map_path.read_text(encoding="utf-8"))
        print(f"地図ポイント: {len(m.get('points', []))}箇所")
        write_js(
            APP / "data" / "mapdata.js",
            "WCQ_MAP",
            m,
            "生成物: scripts/whisky_build.py（地図データ）",
        )

    sen_path = RAW / "sensory.json"
    if sen_path.exists():
        sen = json.loads(sen_path.read_text(encoding="utf-8"))
        write_js(
            APP / "data" / "sensory.js",
            "WCQ_SENSORY",
            {"color_scale": sen.get("color_scale", [])},
            "生成物: scripts/whisky_build.py（色調スケール）",
        )


def build_dist() -> None:
    print("== 単一ファイルビルド ==")
    html = (APP / "index.html").read_text(encoding="utf-8")

    def inline_css(match: re.Match) -> str:
        css = (APP / match.group(1)).read_text(encoding="utf-8")
        return f"<style>\n{css}\n</style>"

    def inline_js(match: re.Match) -> str:
        js = (APP / match.group(1)).read_text(encoding="utf-8")
        return f"<script>\n{js}\n</script>"

    html = re.sub(r'<link rel="stylesheet" href="([^"]+)">', inline_css, html)
    html = re.sub(r'<script src="([^"]+)"></script>', inline_js, html)
    DIST.mkdir(exist_ok=True)
    out = DIST / "whisky-connoisseur.html"
    out.write_text(html, encoding="utf-8")
    print(f"  -> {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


def sync_native() -> None:
    """native/（Capacitor）の www へ app/ を同期する。native が無ければ何もしない。"""
    native_www = ROOT / "native" / "www"
    if not (ROOT / "native").exists():
        return
    import shutil

    if native_www.exists():
        shutil.rmtree(native_www)
    shutil.copytree(APP, native_www, ignore=shutil.ignore_patterns("raw"))
    print("  -> native/www 同期完了（Mac で `npx cap sync ios` を実行して反映）")


if __name__ == "__main__":
    if "--dist-only" not in sys.argv:
        integrate()
    build_dist()
    sync_native()
