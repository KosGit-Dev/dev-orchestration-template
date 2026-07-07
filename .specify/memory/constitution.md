# Horse Racing AI Constitution

> このファイルは GitHub spec-kit が利用する Spec-Driven Development の憲法 (constitution) です。
> 本プロジェクトの **Single Source of Truth は `CLAUDE.md`** と `docs/{plan,design,requirements,policies,constraints,architecture,runbook}.md` です。本ファイルはそこから抜粋同期したものであり、矛盾時は SSOT が優先されます。
> 同期元 CLAUDE.md コミット SHA: `3ebc0ce0` (2026-05-29)

## Core Principles

### I. Language First（言語）

すべての成果物（PR タイトル/本文、Issue 本文、コメント、ADR、docs 更新要約）は **日本語で書く**。コードの識別子は英語でよいが、コメント・docstring・説明文は日本語で書く。PR 本文は必ず `.github/PULL_REQUEST_TEMPLATE.md` の構成に合わせる。

### II. Scope & Safety（最優先・NON-NEGOTIABLE）

- **P-001**: 禁止操作を実装しない（destructive operations、本番ブランチ直接 commit 等）
- **P-002**: API キー / トークン / 認証情報 / 個人情報 / 実データを **リポジトリにコミットしない**（GitHub Secrets / 環境変数経由は許可）
- **P-003**: 制約は常に優先する。制約回避のコードを書かない
- **P-010**: 判断不能な場合は安全側に倒す（フェイルクローズ）

### III. Test-First & Validation Gate（テストファースト・検証ゲート）

- 変更を加えたら必ずローカルまたは CI でテストを通す
- CI が失敗する PR は提出しない
- PR には検証手順と結果を必ず記載する（AC-040）
- ML モデル変更時は時系列リーク防止と再現性検証（NFR-001、NFR-051）

### IV. Single Source of Truth（正本・SSOT）

| 正本 | ファイル |
| --- | --- |
| 要件 | `docs/requirements.md` |
| 詳細設計 | `docs/design.md` |
| ポリシー | `docs/policies.md` |
| 制約仕様 | `docs/constraints.md` |
| アーキテクチャ | `docs/architecture.md` |
| 運用手順 | `docs/runbook.md` |
| 重要判断 | `docs/adr/` |
| 計画 | `docs/plan.md` |

会話ログではなく、必要な前提・決定は正本 docs へ反映する。`docs/plan.md` の「Next」以外に勝手に着手しない。正本に矛盾がある場合は修正を提案し、暗黙に無視しない。

### V. Review Loop Discipline（レビューループ規律）

- Copilot レビューは **最大 3 ラウンドまで**対応する
- Round 3 後の非ブロッキング Must/Should は Backlog 化、即時ブロッカーは fail-close
- Round 4 以降の自動 push / review request は禁止
- 同一指摘 3 回繰り返し / 再トリガー 3 回超過 / ポリシー違反 / 認証不能 で停止
- **B-366 Claude Code 内部レビュー fallback**: Copilot 不能時は auditor-spec / auditor-security / auditor-reliability の Must 0 marker comment で fallback 可能

## Branching Strategy（ブランチ戦略）

- 個人開発のコスト削減のため、長命ブランチは **`main` のみ** とする
- feature/fix ブランチは必ず `main` から作成し、`main` へ直接 PR する（`develop` は廃止）
- `main` への直接コミットは禁止（全プラン実行モードの `docs/plan.md` タスク移動のみ、ADR とポリシーで許可された範囲で例外）
- `release_to_main` は別工程ではなく通常の `main` 宛 PR に統合し、`ai/operation-policy.yml` の green / yellow / red risk tier に従う

## Subagent Roles（サブエージェント役割）

| 役割 | モデル | 用途 |
| --- | --- | --- |
| Orchestrator | Opus 4.7 | メインセッション・マルチツール統括 |
| release-manager | Opus 4.7 | 最終 Ship 判定（全 AC 横断検証） |
| implementer | Sonnet 4.6 | 多ファイルリファクタ・実装 |
| auditor-spec | Sonnet 4.6 | コード ↔ AC 照合監査 |
| auditor-reliability | Sonnet 4.6 | 静的解析・境界値・Serena セマンティック分析 |
| test-engineer | Haiku 4.5 | テスト作成・実行（ダミーデータのみ） |
| auditor-security | Haiku 4.5 | セキュリティ監査（P-001/P-002/P-040） |

## Autonomous Execution Triggers（自動実行モード）

以下のトリガーフレーズで承認確認なしに自動実行パイプラインを開始する：

- 「計画に従い作業を実施して」「Next を実行して」「plan.md に従って進めて」「作業を開始して」「タスクを実行して」（**単発モード**：Next 先頭 1 件のみ）
- 「プランをすべて実施して」「全タスクを実行して」「計画を全部実行して」（**全プラン実行モード**：Next 完了まで継続）

停止条件：

- ポリシー違反（P-001〜P-003）の検出
- 修正ループが 3 回を超えた場合
- Copilot レビュー対応で同一指摘への修正試行が 3 回を超えた場合
- plan.md の Next が空の場合

## Quality Gates（受入条件 AC-001〜080 抜粋）

- AC-001: 変更は要件・ポリシー・計画のいずれかに整合する
- AC-010: 必要なテストが追加または更新されている
- AC-020: CI（lint/type/test/policy_check）が成功している
- AC-030: 変更に応じて正本 docs を更新した
- AC-040: 検証手順と結果を PR に記載した
- AC-050: 禁止操作や秘密情報の混入がない

## Governance

- 本 constitution は CLAUDE.md と各正本 SSOT から派生する **抜粋同期** であり、編集権限を持つのは Orchestrator + release-manager のみ
- 不一致が発生した場合は `CLAUDE.md` / `docs/policies.md` / `docs/constraints.md` を優先し、本 constitution を更新する
- spec-kit slash commands (`/speckit.*`) は本リポジトリの自動実行モードとは独立して動作する（Phase 2 以降で衝突回避ルールを明文化予定）
- 本 constitution の更新時は `docs/spec-kit-bridge.md` の「最終同期日時」「同期元 CLAUDE.md コミット SHA」を併せて更新する

**Version**: 1.0.1 | **Ratified**: 2026-05-19 | **Last Amended**: 2026-05-29
**同期元 CLAUDE.md SHA**: `3ebc0ce0`
