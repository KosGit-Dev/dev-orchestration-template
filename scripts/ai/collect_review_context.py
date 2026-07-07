from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_MAX_RELATED_FILES = 40
DEFAULT_MAX_CONTEXT_CHARS = 180_000
DEFAULT_MAX_FILE_EXCERPT_CHARS = 12_000
DEFAULT_MAX_CONTEXT_COMMANDS = 12

VALID_CONTEXT_MODES = {"diff_only", "related_context", "full_repo_agentic"}
LOW_RISK_PREFIXES = ("docs/", "data/")
LOW_RISK_SUFFIXES = (".md", ".txt")


@dataclass(frozen=True)
class ReviewContextBudget:
    max_related_files: int = DEFAULT_MAX_RELATED_FILES
    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS
    max_file_excerpt_chars: int = DEFAULT_MAX_FILE_EXCERPT_CHARS
    max_context_commands: int = DEFAULT_MAX_CONTEXT_COMMANDS

    @classmethod
    def from_env(cls) -> ReviewContextBudget:
        return cls(
            max_related_files=_env_int("AI_REVIEW_MAX_RELATED_FILES", DEFAULT_MAX_RELATED_FILES),
            max_context_chars=_env_int("AI_REVIEW_MAX_CONTEXT_CHARS", DEFAULT_MAX_CONTEXT_CHARS),
            max_file_excerpt_chars=_env_int(
                "AI_REVIEW_MAX_FILE_EXCERPT_CHARS",
                DEFAULT_MAX_FILE_EXCERPT_CHARS,
            ),
            max_context_commands=_env_int(
                "AI_REVIEW_MAX_CONTEXT_COMMANDS",
                DEFAULT_MAX_CONTEXT_COMMANDS,
            ),
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class RelatedFile:
    path: str
    reason: str
    score: int
    excerpt: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextCommand:
    command: str
    exit_code: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewContextManifest:
    repository_context_mode: str
    diff_only_reason: str
    changed_files: list[str]
    related_files: list[RelatedFile]
    scanned_paths: list[str]
    commands_run: list[ContextCommand]
    context_fingerprint: str
    context_budget: ReviewContextBudget
    context_truncated: bool
    context_truncated_reason: str
    context_budget_override_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_context_mode": self.repository_context_mode,
            "diff_only_reason": self.diff_only_reason,
            "changed_files": self.changed_files,
            "related_files": [item.to_dict() for item in self.related_files],
            "scanned_paths": [str(p) for p in self.scanned_paths],
            "commands_run": [item.to_dict() for item in self.commands_run],
            "context_fingerprint": self.context_fingerprint,
            "context_budget": self.context_budget.to_dict(),
            "context_truncated": self.context_truncated,
            "context_truncated_reason": self.context_truncated_reason,
            "context_budget_override_reason": self.context_budget_override_reason,
        }


def _env_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def _run_command(args: list[str], *, cwd: Path, timeout: int = 30) -> tuple[int, str, str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def _record_command(
    commands: list[ContextCommand],
    *,
    command: str,
    exit_code: int,
    summary: str,
    budget: ReviewContextBudget,
    truncation_reasons: list[str],
) -> bool:
    if len(commands) >= budget.max_context_commands:
        if "context command budget exceeded" not in truncation_reasons:
            truncation_reasons.append("context command budget exceeded")
        return False
    commands.append(ContextCommand(command=command, exit_code=exit_code, summary=summary))
    return True


def parse_diff_changed_files(diff: str) -> list[str]:
    paths: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3]
                if path.startswith("b/"):
                    paths.add(path[2:].replace("\\", "/"))
            continue
        if line.startswith("+++ b/"):
            paths.add(line[6:].replace("\\", "/"))
    return sorted(path for path in paths if path and path != "/dev/null")


def is_low_risk_diff_only(changed_files: list[str]) -> bool:
    if not changed_files:
        return False
    for path in changed_files:
        normalized = path.replace("\\", "/")
        if normalized.startswith(LOW_RISK_PREFIXES):
            continue
        if normalized.endswith(LOW_RISK_SUFFIXES):
            continue
        return False
    return True


def _git_files(
    root: Path,
    commands: list[ContextCommand],
    budget: ReviewContextBudget,
    truncation_reasons: list[str],
) -> list[str]:
    exit_code, stdout, stderr = _run_command(["git", "ls-files"], cwd=root)
    summary = f"{len(stdout.splitlines())} tracked files"
    if exit_code != 0:
        summary = stderr.strip() or "git ls-files failed"
    _record_command(
        commands,
        command="git ls-files",
        exit_code=exit_code,
        summary=summary,
        budget=budget,
        truncation_reasons=truncation_reasons,
    )
    if exit_code != 0:
        return []
    return sorted(line.strip().replace("\\", "/") for line in stdout.splitlines() if line.strip())


def _read_excerpt(path: Path, limit: int) -> tuple[str, bool]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", False
    if len(text) <= limit:
        return text, False
    marker = "\n[excerpt truncated]\n"
    return text[: max(0, limit - len(marker))] + marker, True


def _module_to_paths(module: str) -> list[str]:
    module_path = module.replace(".", "/")
    return [
        f"{module_path}.py",
        f"{module_path}/__init__.py",
        f"src/{module_path}.py",
        f"src/{module_path}/__init__.py",
    ]


def _first_party_import_prefixes(root: Path) -> tuple[str, ...]:
    """このリポジトリの first-party トップレベルパッケージ名を解決する。

    stdlib / サードパーティの import を除外し、リポジトリ内モジュールだけを
    関連ファイル候補に含めるための prefix を動的に決める。`src/` 配下の各
    パッケージ名（`__init__.py` を持つディレクトリ、または .py 単体モジュール）に
    加えて `scripts` / `tests` / `src` を常に含める。`src/` が存在しない構成でも
    一般的な既定 prefix で動作する（プロジェクト非依存）。
    """
    prefixes: set[str] = {"scripts", "tests", "src"}
    src_dir = root / "src"
    if src_dir.is_dir():
        for entry in src_dir.iterdir():
            if entry.is_dir() and (entry / "__init__.py").exists():
                prefixes.add(entry.name)
            elif entry.suffix == ".py" and entry.stem != "__init__":
                prefixes.add(entry.stem)
    return tuple(sorted(prefixes))


def _python_import_candidates(root: Path, changed_file: str) -> list[tuple[str, str, int]]:
    path = root / changed_file
    if path.suffix != ".py" or not path.exists():
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []

    first_party_prefixes = _first_party_import_prefixes(root)
    candidates: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        for module in modules:
            top_level = module.split(".", 1)[0]
            if top_level not in first_party_prefixes:
                continue
            for candidate in _module_to_paths(module):
                if (root / candidate).exists() and candidate != changed_file:
                    candidates.append((candidate, f"imported module {module}", 80))
    return candidates


def _test_pair_candidates(files: list[str], changed_file: str) -> list[tuple[str, str, int]]:
    stem = Path(changed_file).stem
    if not stem or stem.startswith("__"):
        return []
    candidates = []
    for file_path in files:
        normalized = file_path.replace("\\", "/")
        if not normalized.startswith("tests/"):
            continue
        if stem in Path(normalized).stem or stem in normalized:
            candidates.append((normalized, f"test paired with {changed_file}", 90))
    return candidates


def _policy_candidates(changed_file: str) -> list[tuple[str, str, int]]:
    normalized = changed_file.replace("\\", "/")
    candidates: list[tuple[str, str, int]] = []
    if normalized.startswith(".github/workflows/") or normalized.startswith("scripts/hooks/"):
        candidates.extend(
            [
                ("docs/runbook.md", f"operation docs related to {normalized}", 55),
                (
                    ".github/instructions/review-loop.instructions.md",
                    f"review loop instructions related to {normalized}",
                    70,
                ),
            ]
        )
    if normalized.startswith("docs/") or normalized.startswith("ai/"):
        candidates.extend(
            [
                ("ai/context-index.yml", f"context policy related to {normalized}", 55),
                ("ai/document-governance.yml", f"document governance related to {normalized}", 55),
            ]
        )
    if normalized == "scripts/run_ai_review.py" or normalized.startswith("scripts/ai/"):
        candidates.extend(
            [
                (
                    "docs/ai/copilot-independent-review.md",
                    f"review gate spec related to {normalized}",
                    80,
                ),
                ("docs/requirements.md", f"requirements related to {normalized}", 50),
                ("docs/design.md", f"design related to {normalized}", 50),
            ]
        )
    return candidates


def _reference_candidates(
    root: Path,
    changed_file: str,
    commands: list[ContextCommand],
    budget: ReviewContextBudget,
    truncation_reasons: list[str],
) -> list[tuple[str, str, int]]:
    stem = Path(changed_file).stem
    if len(stem) < 4:
        return []
    if len(commands) >= budget.max_context_commands:
        if "context command budget exceeded" not in truncation_reasons:
            truncation_reasons.append("context command budget exceeded")
        return []
    if shutil.which("rg") is not None:
        command = f"rg -l --glob !data/** --glob !outputs/** {stem}"
        exit_code, stdout, stderr = _run_command(
            ["rg", "-l", "--glob", "!data/**", "--glob", "!outputs/**", stem],
            cwd=root,
        )
    else:
        command = f"git grep -l -e {stem} -- . :(exclude)data/** :(exclude)outputs/**"
        exit_code, stdout, stderr = _run_command(
            [
                "git",
                "grep",
                "-l",
                "-e",
                stem,
                "--",
                ".",
                ":(exclude)data/**",
                ":(exclude)outputs/**",
            ],
            cwd=root,
        )
    summary = f"{len(stdout.splitlines())} files reference {stem}"
    if exit_code not in {0, 1}:
        summary = stderr.strip() or f"reference search failed for {stem}"
    _record_command(
        commands,
        command=command,
        exit_code=exit_code,
        summary=summary,
        budget=budget,
        truncation_reasons=truncation_reasons,
    )
    if exit_code not in {0, 1}:
        return []
    candidates = []
    for line in stdout.splitlines():
        path = line.strip().replace("\\", "/")
        if path and path != changed_file:
            candidates.append((path, f"references symbol/path stem {stem}", 45))
    return candidates


def _candidate_key(candidate: tuple[str, str, int]) -> str:
    return candidate[0].replace("\\", "/")


def collect_review_context(
    *,
    repo_root: Path,
    diff: str,
    mode: str = "related_context",
    budget: ReviewContextBudget | None = None,
    context_budget_override_reason: str = "",
    diff_only_reason: str = "",
) -> ReviewContextManifest:
    if mode not in VALID_CONTEXT_MODES:
        msg = f"invalid repository context mode: {mode}"
        raise ValueError(msg)

    budget = budget or ReviewContextBudget.from_env()
    changed_files = parse_diff_changed_files(diff)
    commands: list[ContextCommand] = []
    truncation_reasons: list[str] = []
    scanned_paths: set[str] = set(changed_files)

    if mode == "diff_only":
        if not diff_only_reason and not is_low_risk_diff_only(changed_files):
            truncation_reasons.append("diff_only used without low-risk reason")
        return _build_manifest(
            mode=mode,
            changed_files=changed_files,
            related_files=[],
            scanned_paths=sorted(scanned_paths),
            commands=commands,
            budget=budget,
            diff=diff,
            truncation_reasons=truncation_reasons,
            budget_override_reason=context_budget_override_reason,
            diff_only_reason=diff_only_reason,
        )

    files = _git_files(repo_root, commands, budget, truncation_reasons)
    scanned_paths.add(".")

    candidates: dict[str, tuple[str, str, int]] = {}
    for changed_file in changed_files:
        for candidate in _test_pair_candidates(files, changed_file):
            key = _candidate_key(candidate)
            candidates[key] = _merge_candidate(candidates.get(key), candidate)
        for candidate in _python_import_candidates(repo_root, changed_file):
            key = _candidate_key(candidate)
            candidates[key] = _merge_candidate(candidates.get(key), candidate)
        for candidate in _policy_candidates(changed_file):
            if (repo_root / candidate[0]).exists():
                key = _candidate_key(candidate)
                candidates[key] = _merge_candidate(candidates.get(key), candidate)
        if mode == "full_repo_agentic":
            for candidate in _reference_candidates(
                repo_root,
                changed_file,
                commands,
                budget,
                truncation_reasons,
            ):
                if (repo_root / candidate[0]).exists():
                    candidates[_candidate_key(candidate)] = _merge_candidate(
                        candidates.get(_candidate_key(candidate)),
                        candidate,
                    )

    ordered = sorted(candidates.values(), key=lambda item: (-item[2], item[0]))
    if len(ordered) > budget.max_related_files:
        truncation_reasons.append(
            f"related files truncated: {len(ordered)} > {budget.max_related_files}"
        )
        ordered = ordered[: budget.max_related_files]

    related_files: list[RelatedFile] = []
    context_chars = 0
    for path_text, reason, score in ordered:
        path = repo_root / path_text
        excerpt, file_truncated = _read_excerpt(path, budget.max_file_excerpt_chars)
        if file_truncated:
            truncation_reasons.append(f"file excerpt truncated: {path_text}")
        remaining = budget.max_context_chars - context_chars
        if remaining <= 0:
            truncation_reasons.append("context character budget exceeded")
            break
        if len(excerpt) > remaining:
            marker = "\n[context budget truncated]\n"
            if remaining <= len(marker):
                excerpt = marker[:remaining]
            else:
                excerpt = excerpt[: remaining - len(marker)] + marker
            truncation_reasons.append("context character budget exceeded")
        context_chars += len(excerpt)
        related_files.append(
            RelatedFile(path=path_text, reason=reason, score=score, excerpt=excerpt)
        )
        scanned_paths.add(path_text)

    return _build_manifest(
        mode=mode,
        changed_files=changed_files,
        related_files=related_files,
        scanned_paths=sorted(scanned_paths),
        commands=commands,
        budget=budget,
        diff=diff,
        truncation_reasons=truncation_reasons,
        budget_override_reason=context_budget_override_reason,
        diff_only_reason=diff_only_reason,
    )


def _merge_candidate(
    current: tuple[str, str, int] | None,
    candidate: tuple[str, str, int],
) -> tuple[str, str, int]:
    if current is None:
        return candidate
    path, reason, score = current
    _, new_reason, new_score = candidate
    reasons = reason.split("; ")
    if new_reason not in reasons:
        reasons.append(new_reason)
    return path, "; ".join(reasons), max(score, new_score)


def _build_manifest(
    *,
    mode: str,
    changed_files: list[str],
    related_files: list[RelatedFile],
    scanned_paths: list[str],
    commands: list[ContextCommand],
    budget: ReviewContextBudget,
    diff: str,
    truncation_reasons: list[str],
    budget_override_reason: str,
    diff_only_reason: str,
) -> ReviewContextManifest:
    fingerprint_input = {
        "mode": mode,
        "changed_files": changed_files,
        "related_files": [
            {"path": item.path, "reason": item.reason, "score": item.score, "excerpt": item.excerpt}
            for item in related_files
        ],
        "scanned_paths": scanned_paths,
        "commands_run": [item.to_dict() for item in commands],
        "diff_sha256": hashlib.sha256(diff.encode("utf-8")).hexdigest(),
        "budget": budget.to_dict(),
        "diff_only_reason": diff_only_reason,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_input, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    unique_reasons = sorted(set(reason for reason in truncation_reasons if reason))
    return ReviewContextManifest(
        repository_context_mode=mode,
        diff_only_reason=diff_only_reason,
        changed_files=changed_files,
        related_files=related_files,
        scanned_paths=scanned_paths,
        commands_run=commands,
        context_fingerprint=fingerprint,
        context_budget=budget,
        context_truncated=bool(unique_reasons),
        context_truncated_reason="; ".join(unique_reasons),
        context_budget_override_reason=budget_override_reason,
    )
