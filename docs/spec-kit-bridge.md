# spec-kit ↔ 既存 SSOT bridge document

> spec-kit 導入（Phase 1 統合）で導入された GitHub spec-kit と本リポジトリの既存 SSOT（`docs/{plan,design,requirements,policies,constraints,architecture,runbook}.md` + `CLAUDE.md`）の対応関係・運用ルールを定義する。

## 1. 適用範囲（Phase 1）

- spec-kit は **補助ツール** として導入する
- 既存 SSOT（plan.md / design.md / requirements.md 等）は **そのまま正本** として維持する
- `.specify/` 配下は spec-kit が生成する補助構造であり、`.gitignore` 除外せずコミットする
- `/speckit.*` slash commands は Claude Code から利用可能（`.claude/skills/speckit-*/SKILL.md` 経由）
- 本ドキュメントは spec-kit と SSOT の整合管理の Single Source of Truth

## 2. 正本優先順位

| 種別 | 正本 | spec-kit 側 | 備考 |
| --- | --- | --- | --- |
| プロジェクト原則・ポリシー | `CLAUDE.md` / `docs/policies.md` / `docs/constraints.md` | `.specify/memory/constitution.md` | constitution.md は CLAUDE.md からの **抜粋同期** |
| 計画・タスク管理 | `docs/plan.md`（Next / Backlog / Done） | `.specify/specs/<feature>/spec.md` | plan.md が常に優先。spec.md は Phase 2 以降の試験運用で生成 |
| 詳細設計 | `docs/design.md` | `.specify/specs/<feature>/plan.md` | design.md が正本 |
| 要件 | `docs/requirements.md`（FR / NFR） | `.specify/specs/<feature>/spec.md` の Requirements セクション | requirements.md が正本 |
| 実装手順 | `docs/runbook.md` | `.specify/specs/<feature>/quickstart.md` | runbook が正本 |

矛盾発生時は **正本** を優先し、spec-kit 側を本ドキュメントの「同期記録」セクションで再同期する。

## 3. 同期記録

CLAUDE.md や `.specify/memory/constitution.md` を再同期するたびに、日付・同期元 SHA・更新内容・実施者を追記する。

| 日付 | 同期元 CLAUDE.md SHA | spec-kit 側更新内容 | 実施者 |
| --- | --- | --- | --- |
| （記入例）2026-01-01 | `0000000` | `.specify/memory/constitution.md` 初版作成（spec-kit 導入 Phase 1） | Orchestrator |

## 4. 対象タスク一覧

| Phase | 対象タスク | spec-kit 適用範囲 | 状態 |
| --- | --- | --- | --- |
| Phase 1 | spec-kit 導入タスク | `.specify/` セットアップのみ。spec-kit ワークフローでの管理対象タスクは **なし** | 完了 |
| Phase 2 | TBD | 新規 1 件のタスクを `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` で試験運用 | Backlog |
| Phase 3 | TBD | Phase 2 評価に基づき bridge 方針確定（SSOT 移行 / 補助併用継続 / 撤退） | Backlog |

## 5. 運用ルール

### 5.1. spec-kit slash commands 利用時の遵守事項

`/speckit.specify` / `/speckit.plan` / `/speckit.tasks` / `/speckit.implement` 等を利用する場合：

1. **plan.md の更新を必ず併せて実施**：spec-kit が生成した spec.md / plan.md / tasks.md の要点を `docs/plan.md` の対応タスクセクションへ反映する
2. **既存 SSOT を spec-kit で上書きしない**：`/speckit.implement` が `docs/{plan,design,requirements}.md` を編集しないことを確認する
3. **`.specify/specs/<feature>/` は補助情報**：詳細追加情報のみ。AC や受入条件は `docs/plan.md` / `docs/requirements.md` が正本
4. **constitution.md 更新時は本 bridge document の同期記録を追記**

### 5.2. CLAUDE.md / docs/policies.md / docs/constraints.md 変更時

CLAUDE.md または policies.md / constraints.md の不変条項を変更した場合：

1. `.specify/memory/constitution.md` を必要に応じて再同期
2. 本 bridge document の §3 同期記録に追記（日付、同期元 SHA、更新内容）
3. spec-kit の `/speckit.constitution` を使用する場合も上記手順を遵守

### 5.3. 自動実行モードとの関係

- 本リポジトリの **自動実行モード**（`ai/command-router.yml` の全プラン実行トリガー等）は spec-kit と **独立**して動作する
- `/speckit.implement` は本リポジトリの自動実行モードの代替ではない
- 衝突回避：自動実行モード起動中は `/speckit.implement` を呼び出さない

## 6. ロールバック手順

spec-kit 導入を撤退する場合：

1. `.specify/` 配下を削除（`git rm -rf .specify`）
2. `.claude/skills/speckit-*` を削除
3. 本 bridge document を削除
4. `docs/plan.md` / `docs/design.md` / `docs/requirements.md` の該当タスクを Done / アーカイブへ移動
5. `uv tool uninstall specify-cli`（任意、グローバル install のため）

## 7. 参照

- spec-kit 公式: <https://github.com/github/spec-kit>
- 対応する要件・設計・計画のタスクは `docs/plan.md` / `docs/design.md` / `docs/requirements.md` の該当セクションを参照する
