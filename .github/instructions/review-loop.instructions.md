---
description: "Use when: working on PRs, pushing code, handling AI review, Copilot/Codex/Claude レビュー対応, review loop, CI monitoring, git push, PR作成, レビューコメント対応, review feedback, pull request workflow. CRITICAL workflow rule for PR completion pipeline."
applyTo: "**"
---
# AI レビューループ — 絶対スキップ禁止ルール

> **プロジェクトオーナー決定。変更はオーナーの明示認可がある場合のみ（認可記録は `docs/ai/decision-ledger.md` を参照）。**

## 最重要ルール（5つ）

1. **PR に push したら、必ず AI レビュー（Copilot または Codex / Claude repo-aware fallback）の到着を待つ**（最大20回・最大20分相当。同期 `sleep` ループは禁止）
2. **AI レビューは最大 3 ラウンドまで対応する**（Round 3 後の非ブロッキング Must/Should は Backlog 化、即時ブロッカーだけ fail-close。各 push 後に Copilot を明示発火し、Copilot 不可時は Codex / Claude repo-aware review を実行する）
3. **「レビュー待ちは省略」「次に進む」は絶対禁止**（下記「ラウンド外 push」の 2 例外を除く）
4. **push 直後にレビュワー設定確認を必ず行う**（Copilot AI が reviewer に設定されているか確認。未設定または利用不能なら `request_copilot_review` または Codex / Claude repo-aware fallback を即実行）
5. **レビュー検出は `commit_id` ではなくスレッドベースで行う**（`get_review_comments` で未解決・未返信スレッド数を確認。`commit_id` フィルタリングは禁止）

## ラウンド外 push（オーナー認可がある場合のみ有効な例外）

次の push は**ラウンドを消費せず、レビュー再リクエスト・証跡再 pin も不要**とする:

- **レビュー証跡（`docs/ai/reviews/**`）のみの push**（diff fingerprint は証跡除外で計算され、`review_head_is_compatible` が証跡専用 commit を許容するため。実測: 証跡再 pin が再レビューを誘発する往復が発生した事例がある）
- **green tier（`ai/operation-policy.yml` の `release_to_main` 分類で green と判定された PR。red_if_touches 非接触であっても yellow 判定の変更は対象外）で、Round 1 のレビューが Must/Should 0 件かつ未解決スレッド 0 件のとき**は、以降のラウンド発火は不要（CI 全チェック green（`gh pr checks` 全 pass）はこの短絡と無関係に必須のまま）。**短絡後に `docs/ai/reviews/**` 以外の差分を push した場合は短絡は失効し、その push からラウンドを再開する（Round 2 扱い・通常の再リクエスト必須）**。yellow / red は本短絡の対象外。

## 長時間待機の実行制約（停止事故防止）

- VS Code / Copilot Chat / Orchestrator 環境では、`sleep` を含むシェルポーリングループを同期実行してはならない。
- CI / AI レビュー待機は省略しない。ただし実行方法は、1回ごとの状態確認コマンドを短いタイムアウトで実行し、次回確認はエージェント側の進行管理で行う。
- 端末コマンドが失敗した場合は、読み込み状態を継続せず即座に exit code・stderr・対象コマンドを報告し、原因修正へ戻る。
- 5分以上同じ待機状態が続く場合は、プロセス一覧と直近ログを確認し、滞留プロセスを止めてから再開する。
- Claude Code Remote 等の webhook 対応環境では、`subscribe_pr_activity` 等のイベント受信を優先し、シェル滞留を作らない。

## レビュワー設定確認ルーチン（push 後に毎回実行）

```text
push 後:
  1. PR が Draft 状態でないことを確認する（Draft 状態ではレビューが発火しない）
     - Draft の場合: gh pr ready <PR番号> で Ready for review に変更してからリクエスト
  2. 【Round 1】request_copilot_review で明示的にレビューをリクエストする。Copilot が利用不能なら Codex / Claude repo-aware review を実行する
  3. ポーリング初回（1回目）と以降5回ごと（5, 10, 15, 20回目）にレビュワー設定を再確認する
```

> **なぜ必要か**: Copilot AI は push イベントでは自動発火しない（2026年5月以降のルール変更）。
> 各 push 後に必ず `request_copilot_review` で明示リクエストを実行すること。
> PR が Draft 状態のままではレビューが発火しないため、状態確認が必須。

Codex / Claude repo-aware fallback を実行する場合、通常実装では `repository_context_mode=related_context` 以上、
workflow / security / release / red risk では `full_repo_agentic` を満たすレビュー証跡を要求する。
`diff_only` は docs-only / data-only / typo 等の低リスク変更で理由を記録した場合だけ許可する。
同一 `head_sha` / diff fingerprint / context fingerprint で同一 provider の repo-aware fallback を再実行しない。
context budget は related files 40 件、prompt context 180000 文字、file excerpt 12000 文字、
探索 command 12 件を既定上限とし、超過時は relevance score 順に切り詰めて証跡化する。

## レビュー検出ルーチン（2段階検出）

```text
ポーリングループ各回:
  段階1: gh api --paginate（CLI）または pull_request_read（MCP, perPage=100）で AI レビュー総数（Copilot / Codex / Claude）が増加したか確認
    - CLI: gh api --paginate を使う / MCP: perPage=100 を指定する（デフォルト per_page=30 でページネーション漏れが発生する）
    - commit_id でフィルタリングしない（API 仕様で一致しないことがある）
    - ユーザー名: Copilot は copilot-pull-request-reviewer[bot]、Codex は chatgpt-codex-connector、fallback は本文 `## AI レビュー結果` を検出対象にする
  段階2: get_review_comments（スレッドベース）で未対応コメントを確認
    - 条件: isResolved=false, isOutdated=false, AI レビューコメントあり, 自分の返信なし
    - ユーザー名: Copilot / Codex / Claude repo-aware fallback の author または `## AI レビュー結果` marker を検索対象にする
  → いずれかで検出されれば「レビュー到着」と判定
```

> **なぜ必要か**: `get_reviews` + `commit_id` フィルタリングだけでは、ページネーションや
> API 仕様の問題でレビューを見落とすことがある。実際にレビューが届いていたのに
> デフォルト per_page=30 のページネーション漏れで検出できず、「未到着」と誤判定した。
> また、レビュー本体(`copilot-pull-request-reviewer[bot]`)とコメント(`Copilot`)で
> ユーザー名が異なるため、両方を検索対象にすること。

## レビューループの手順（Round 1〜3）

```text
push 後（Round N, N=1..3）:
  0. 【必須】PR が Draft でないことを確認する（Draft なら gh pr ready で変更）
  1. 【Round N レビュー発火】request_copilot_review で明示的にレビューをリクエストする。Copilot が 422 / quota / timeout / 未到着の場合は Codex / Claude repo-aware fallback を実行する
     → push 後の自動発火は期待しない。必ず明示リクエストまたは fallback review を実行すること
  1b. AI レビュー到着を確認（最大20回、2段階検出。同期 `sleep` ループは禁止）
  2. レビューコメントを取得・分類（Must/Should/Nice）
  3. plan.md の AC と照合し、AC と矛盾する指摘は AC 優先で対応不要と判定
  4. Must/Should を修正（AC 準拠）
  5. 【必須・Hookリマインド】各コメントに GitHub 上で返信する
     - add_reply_to_pull_request_comment で全スレッドに対し修正内容・見解を返信
     - 返信なしのまま `task_complete` / セッション終了 / release-manager 呼び出しに
       進もうとした場合、Hook（pre_task_complete_guard, stop_review_guard）が
       未返信スレッド数を検出してリマインドする。
       block は実 CI 失敗と full-plan safety の fail-close 判定に限定する
     - 「修正済み」「対応不要と判断（理由:〜）」等、簡潔でよいので必ず返信すること
  6. targeted test / lint / typecheck を実行（フル CI は Round 3 後または Must/Should 0 件の最終ゲートへ集約）
  7. コミット・プッシュ（N < 3 かつ Must/Should > 0 の場合のみ）
  8. N < 3 なら次ラウンド（N+1）へ、N = 3 なら Round 3 処理へ

Round 3 処理:
  - Must/Should が残る場合は即時ブロッカーか非ブロッキングかを分類
  - 即時ブロッカー（P-001/P-002/P-003、秘密情報、重大な安全制約違反、CI failure、データ破壊等）は fail-close で停止
  - 非ブロッキング指摘は Backlog に記録し、PR コメントに Backlog ID と残リスクを返信
  - フル CI を実行し、release-manager 承認を経て継続可能
  - Round 4 以降の自動 push / review request は禁止
```

## ラウンド予算と停止条件

**最大 3 ラウンド**を PR 単位で適用する。以下の条件で自動対応を停止し人間にエスカレーションする：

- **Round 3 到達**: Round 3 のレビュー処理後に Must/Should が残る場合、即時ブロッカーは fail-close で停止。非ブロッキング指摘は Backlog に記録して PR コメントに返信し、最終 CI + release-manager 承認を経て継続可能
- **Round 4 以降の自動継続禁止**: Round 3 を超える CI 発火・push・review request は自動実行しない
- **同一指摘の繰り返し**: 同じコメントへの修正試行が3回を超えた場合
- **連続再トリガー**: タイムアウト時の再トリガーが3回を超えた場合
- **ポリシー違反**: P-001〜P-003 違反を検出した場合
- **コンフリクト/認証不能**: マージコンフリクトまたは認証エラーで継続不能な場合
- **進捗ゼロ override 要求の繰り返し**: 「直近の状態取得結果 == 前回の状態取得結果」かつ「直近の応答 == ユーザへの override 要求」を **2 回連続**検出した場合、3 回目は override 要求を出さず、(a) 具体的な不足作業の自動実施、(b) escalation reason への従順、(c) `AskUserQuestion` での選択肢提示 のいずれかへ切替える

## よくある間違い（過去10回以上発生）

- ❌ 「レビューコメントに返信したので完了」→ 返信後も新レビューを待つ
- ❌ 「CI が通ったので完了」→ CI 通過後も AI レビューを待つ
- ❌ 「push したので次のステップへ」→ push 後は必ずレビュー待ち
- ❌ 「時間がかかるので省略」→ 省略は絶対禁止
- ❌ 「commit_id でフィルタしたらレビュー0件」→ commit_id フィルタは禁止。スレッドベースで確認する
- ❌ 「push したら自動でレビューが来る」→ Copilot は push 自動発火しない。必ず `request_copilot_review` または Codex / Claude repo-aware fallback で明示実行
- ❌ 「Draft PR にレビューをリクエストした」→ Draft 状態ではレビューが発火しない。`gh pr ready <PR番号>` で Ready に変更してからリクエスト
- ❌ 「20分待ってもレビューが来ない」→ Draft 状態でないか確認。Draft なら Ready に変更してリクエスト
- ❌ 「修正だけして返信せずに push」→ 返信は必須。Hook はレビュー儀式をリマインドするが、返信なしを完了扱いにしてよいという意味ではない
- ❌ 「Must/Should が残っているので自動修正を停止した」→ Round 3 到達時は非ブロッキング指摘を Backlog 化、即時ブロッカーは fail-close で停止。同一指摘3回繰り返し・再トリガー3回超過・ポリシー違反・認証不能でも停止。Round 4 以降の自動 push/review request は禁止
- ❌ 「状態が変わらないのに同じ override 文言を3回以上要求」→ 進捗ゼロでの override 要求は **2 回まで**。3 回目は不足作業の自動実施・escalation reason 従順・選択肢提示へ切替える

## 自動 Hooks（`.github/hooks/review-loop-guard.json`）

以下の Agent Hooks は、安全床の fail-close とレビュー儀式のリマインドを担当する。レビュー未到着・未返信・Round 予算超過・一時的な lookup 失敗は block せず、追加コンテキストで継続手順を促す。

| Hook | イベント | 動作 |
| ---- | -------- | ---- |
| `pre_task_complete_guard.py` | **PreToolUse** | `task_complete` / release-manager 呼び出し時に PR 状態をチェック。実 CI 失敗または full-plan safety 未達なら `permissionDecision: "deny"` でブロックし、レビュー未完了はリマインド |
| `post_push_reminder.py` | **PostToolUse** | `git push` 後に `decision: "allow"` で CI 確認 + レビュー待機をリマインド |
| `stop_review_guard.py` | **Stop** | 実 CI 失敗または full-plan safety 未達ならセッション終了をブロックし、レビュー未完了はリマインド |
| `pre_compact_context.py` | **PreCompact** | コンテキスト圧縮前にレビューループルールを systemMessage として注入 |

追加の全プラン実行モード強制:

- `.github/full-plan-execution.flag` が存在し `active=false` でない場合、`pre_task_complete_guard.py` と `stop_review_guard.py` は `full_plan_completion` の安全判定（plan 状態・成果証跡・完了デモ）を fail-close で確認する。OPEN PR のレビュー儀式状態はリマインド扱いとする。
- 全プラン実行モードでは、未解決・未返信スレッド0件・CI全pass・release-manager 承認だけでは完了ではない。自動マージ、main pull、`docs/plan.md` 更新、次タスク遷移までが完了条件である。

> **注意**: Stop hook には `stop_hook_active` による無限ループ防止が組み込まれている。
> VS Code は Stop hook がブロック → エージェント続行 → 再度 Stop の場合、2回目の入力に
> `stop_hook_active: true` を **自動付与** する。2回目は必ず終了を許可する。
> 2回目の Stop では終了が許可される。

## メモリ参照

persistent memory はハーネスが自動提供するもの（Claude Code の auto-memory 等）を用いる。旧 `/memories/repo/` / `/memories/session/` パスは本リポジトリの標準環境に存在しない（`/memories/` マウントを持つ環境でのみ配下を確認する）。
