# ai-dev-template（旧: dev-orchestration-template）

AI ハーネス（Claude Code / GitHub Copilot / Codex・Cursor）を横断して同じ運用モデルで開発できる、個人開発向けの AI 駆動開発テンプレートリポジトリ。

「AI Operating Model」（`ai/*.yml` を正本とする決定的な運用規約）と、整合性駆動＋仕様駆動開発のワークフロー、完了事故を防ぐ hooks を備え、計画→実装→監査→リリースまでを AI エージェントに委譲できる。

> **初めての方へ**: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md) にセットアップ手順をまとめています。
>
> **コマンドの使い方**: [docs/MODE_GUIDE.md](docs/MODE_GUIDE.md) に、日常開発で使う3つのコマンドと運用ルール変更時の扱いをまとめています。
>
> **テンプレートの更新**: [docs/UPGRADE_GUIDE.md](docs/UPGRADE_GUIDE.md) に、アップデート機構（check/apply/export）の使い方をまとめています。

## リポジトリ名について

このテンプレートの表示名は **ai-dev-template**（旧称: dev-orchestration-template）である。GitHub 上のリポジトリ名自体は、必要な場合に以下の手順で変更できる。

1. GitHub の対象リポジトリを開き、**Settings** → **Repository name** を選択する
2. 新しい名前（例: `ai-dev-template`）を入力して **Rename** する
3. 旧 URL（`.../dev-orchestration-template`）への参照は GitHub が自動的にリダイレクトするため、既存の clone・ブックマーク・CI 連携は壊れない

テンプレート内の自己参照（`template-catalog.yml` の `template.repository`）は現行の実 URL を正本として維持しており、リネーム後もリダイレクト経由で動作する。

## 特徴

- **AI Operating Model**（`ai/*.yml` が正本）: コマンド解釈・運用方針・モデル階層・仕様駆動開発・文書読込範囲・文書統治・PR 前批判レビューを決定的なルールとして定義し、AI エージェントの判断のブレを抑える
- **3ハーネス対応**: Claude Code / GitHub Copilot / Codex・Cursor のいずれでも同じ `ai/*.yml` を正本として参照できるよう、`.claude/`・`.github/agents/`・`.cursor/` にハーネス固有の薄い適応層を用意
- **整合性駆動＋仕様駆動開発**: 日常コマンド3種（プラン見直し／バックログ昇格／プラン全実施）と全プラン実行モードにより、User Intent → Requirements → Design → Spec → Implementation → Tests → Verification → Evidence の鎖を飛ばさない
- **hooks による完了事故ガード**: push 後のレビュー未対応・CI 未通過・全プラン未完了のまま終了しようとする状態を検知し、フェイルクローズで押し戻す
- **モデル階層委譲（トークン節約）**: `ai/capability-registry.yml` の capability role → 論理 tier 割当と roster の `model:` frontmatter に従い、単調作業は下位 tier のサブエージェントへ委譲する
- **アップデート機構 v2**: `template-catalog.yml`（feature カタログ）と `docs/TEMPLATE_CHANGELOG.md`（版ログ）を正本に、`scripts/template_update.py` の `check` / `apply` / `export` サブコマンドでテンプレートとの差分確認・取込・逆反映ができる。トリガーフレーズ「アップデートを確認」「アップデートを適用」「テンプレートに変更を反映」で各ハーネスから起動できる
- **個人開発向け最適化**: main 一本化運用、CODEOWNERS 等の重い承認ルートは持たず、review loop は最大3ラウンド・Round 3後の非ブロッキング指摘は Backlog 化する軽量既定
- **CI 品質ゲート**: ポリシーチェック（禁止操作・秘密情報検出）・lint・型チェック・テスト・gitleaks によるシークレットスキャンを含む

## クイックスタート

### 1. テンプレートからリポジトリを作成

```bash
gh repo create my-project --template KosGit-Dev/dev-orchestration-template --clone
cd my-project
```

GitHub の **Use this template** ボタンから作成してもよい。

### 2. プロジェクト設定を編集

```bash
# project-config.yml を開き、プロジェクトの情報を入力する
code project-config.yml
```

主な設定項目：

| セクション  | 説明                                             |
| ----------- | ------------------------------------------------ |
| `project`   | プロジェクト名、目的（`purpose`）、説明、オーナー |
| `toolchain` | 言語、パッケージマネージャ、lint/test コマンド   |
| `source`    | ソースディレクトリ、パッケージ名、モジュール構成 |
| `roadmap`   | フェーズ構成（Phase 0〜4）                       |
| `policies`  | 禁止パターン（CI で自動検査）                    |
| `github`    | Labels、Project 名                               |
| `ai_models` | capability role の tier 割当・roster への反映元  |

### 3. ブートストラップを実行

```bash
# プロジェクト構造の初期化（ディレクトリ作成、設定ファイル生成、テンプレート変数置換）
bash scripts/bootstrap.sh

# GitHub Labels / Milestones / Issues / Project の自動作成
bash scripts/setup_github.sh
```

### 4. docs を編集

`docs/` 配下のテンプレートをプロジェクトに合わせて編集する：

```text
docs/
├── plan.md           # ロードマップ、Next タスク、Backlog
├── requirements.md   # 要件定義・受入条件
├── policies.md       # ポリシー（禁止事項等）
├── constraints.md    # 制約仕様（しきい値等）
├── architecture.md   # アーキテクチャ・責務境界
├── runbook.md        # 実行・復旧手順
└── adr/
    └── ADR-TEMPLATE.md  # 重要判断の記録テンプレート
```

### 5. 開発を開始

使用するハーネス（Claude Code / Copilot Chat / Codex・Cursor）を開き、日常コマンドを伝える。

```text
プランの全実施。
```

`docs/plan.md` の Next タスクを Orchestrator が自動的に分解・実行する。コマンドの詳細は [docs/MODE_GUIDE.md](docs/MODE_GUIDE.md) を参照する。

## ディレクトリ構成

```text
.
├── project-config.yml              # プロジェクト設定（ブートストラップ用）
│
├── ai/                              # AI Operating Model 正本（8 yml）
│   ├── command-router.yml          # 日常コマンドの分類
│   ├── operation-policy.yml        # AI 運用方針・モデル階層委譲
│   ├── capability-registry.yml     # capability role → 論理 tier の割当
│   ├── sdd-policy.yml              # 仕様駆動開発ポリシー
│   ├── coherence-workflow.yml      # 整合性駆動ワークフロー
│   ├── context-index.yml           # 文書読込範囲
│   ├── document-governance.yml     # 文書統治
│   └── pre-pr-review-policy.yml    # PR 前批判レビュー方針
│
├── docs/                           # 正本ドキュメント（SSOT）
│   ├── plan.md                     # 計画・ロードマップ
│   ├── requirements.md             # 要件定義
│   ├── policies.md                 # ポリシー
│   ├── constraints.md              # 制約仕様
│   ├── architecture.md             # アーキテクチャ
│   ├── runbook.md                  # 運用手順
│   ├── adr/                        # Architecture Decision Records
│   └── ai/                         # 仕様駆動開発の台帳（decision-ledger 等）
│
├── .claude/                        # Claude Code ハーネス
│   ├── agents/                     # サブエージェント（frontmatter のみ Claude Code 固有）
│   ├── hooks/                      # 完了事故ガード hooks
│   ├── output-styles/              # Orchestrator 行動仕様の写像
│   └── settings.json
│
├── .github/
│   ├── agents/                     # roster 共通正本（*.agent.md）
│   ├── instructions/                # review-loop / docs / security / tests
│   ├── prompts/                     # 監査・実装プロンプト
│   ├── ISSUE_TEMPLATE/             # Issue テンプレート
│   ├── PULL_REQUEST_TEMPLATE.md    # PR テンプレート
│   ├── workflows/
│   │   ├── ci.yml                  # CI ワークフロー（quality-gate + secret-scan）
│   │   └── issue-lifecycle.yml     # PR マージ時の Issue 自動 Close
│   ├── copilot-instructions.md     # Copilot 全体ルール（薄い入口）
│   └── copilot-code-review-instructions.md
│
├── .agents/skills/                 # 第三者スキル（agmsg, stop-ai-slop-jp）
├── .specify/                       # spec-kit 導入物
├── .cursor/                        # Cursor / Codex 向け設定
│
├── ci/
│   └── policy_check.py             # ポリシーチェッカー
│
├── scripts/
│   ├── bootstrap.sh                # プロジェクト初期化
│   ├── setup_github.sh             # GitHub Labels/Milestones/Issues/Project 作成
│   ├── template_update.py          # アップデート機構 v2（check/apply/export）
│   ├── hooks/                      # hook 実装（Claude Code から呼び出し）
│   └── ai/                         # レビュー・整合性検証スクリプト
│
├── configs/                        # 実行設定
├── data/                           # データ（git 管理外）
├── outputs/                        # 生成物（git 管理外）
└── notebooks/                      # 実験用ノートブック
```

## エージェント構成

```text
ユーザー
  │
  ▼
Orchestrator（司令塔）
  │  自らコードは書かない。分解・委譲・統合に専念する。
  │
  ├──→ Implementer（実装担当）
  ├──→ Test Engineer（テスト担当）
  ├──→ Auditor Spec（仕様監査）
  ├──→ Auditor Security（セキュリティ監査）
  ├──→ Auditor Reliability（信頼性監査）
  │
  └──→ Release Manager（リリース判定）
```

エージェント定義の共通正本は `.github/agents/*.agent.md` であり、各ハーネス固有の frontmatter やツール権限だけをハーネス側（`.claude/agents/*.md` 等）に置く。

### ワークフロー

1. **計画確認**: `docs/plan.md` の Next から対象タスクを特定
2. **実装委譲**: Implementer にコード実装を指示
3. **テスト委譲**: Test Engineer にテスト作成を指示
4. **三重監査**: Spec / Security / Reliability の独立監査
5. **修正ループ**: Must 指摘がゼロになるまで繰り返し（最大3ラウンド）
6. **リリース判定**: Release Manager が AC チェックしてマージ可否を判定
7. **計画更新**: 完了した Next を削除、必要なら Backlog を昇格

## 受入条件（全PR共通）

| ID     | 条件                                            |
| ------ | ----------------------------------------------- |
| AC-001 | 変更は要件・ポリシー・計画のいずれかに整合する  |
| AC-010 | 必要なテストが追加または更新されている          |
| AC-020 | CI（lint/type/test/policy_check）が成功している |
| AC-030 | 変更に応じて正本（docs）が更新されている        |
| AC-040 | 検証手順と結果が PR 本文に記載されている        |
| AC-050 | プロジェクト固有の制約に反する変更がない        |

## カスタマイズガイド

### ポリシーチェックの拡張

`ci/policy_check.py` の定数を編集して、プロジェクト固有のルールを追加する：

```python
# 例: HTTP ライブラリの import を禁止
FORBIDDEN_IMPORT_PATTERNS = [
    r"^\s*import\s+requests",
    r"^\s*from\s+requests\s+import",
]

# 例: 本番 URL の直書きを禁止
FORBIDDEN_PATTERNS = [
    r"https://api\.production\.example\.com",
]
```

### エージェントのカスタマイズ

`.github/agents/` 配下のエージェント定義を編集して、プロジェクト固有の指示を追加する。モデルの割当は `project-config.yml` の `ai_models` と `ai/capability-registry.yml` を正本とし、実行時の反映先は各ハーネス roster の `model:` frontmatter である。

### 制約の追加

`docs/constraints.md` に制約を定義し、テストで境界値をカバーする。

## ライセンス

MIT License
