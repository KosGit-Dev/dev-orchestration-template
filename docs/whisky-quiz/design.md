# ウイスキーコニサー道場 設計

## 全体構成

```text
app/                     # Web アプリ本体（依存なしの素の HTML/CSS/JS）
  index.html             # エントリ。PWA メタ・データ/JS の読込順を定義
  css/style.css          # ダーク・バーカウンターテーマ
  js/
    util.js              # 定数（級・分類・地域ラベル）、Miller 図法、共通関数
    storage.js           # localStorage 永続化と苦手スコア計算
    quiz.js              # 出題エンジン（演習/模試/復習/苦手克服/官能を共通駆動）
    map.js               # 世界地図（SVG viewBox によるパン・ピンチズーム）
    sensory.js           # 官能トレーニング（色見本帳）
    essay.js             # 論文対策（一覧・執筆・タイマー・模範解答）
    stats.js             # 苦手分析ダッシュボード
    app.js               # ハッシュルーター・ホーム・演習設定
  data/                  # 生成物（whisky_build.py が出力）
    questions.js         # 統合問題バンク → window.WCQ_QUESTIONS
    essays.js            # 論文50テーマ → window.WCQ_ESSAYS
    mapdata.js           # 地図36ポイント → window.WCQ_MAP
    sensory.js           # 色調12段階スケール → window.WCQ_SENSORY
    worldmap.js          # 世界地図 SVG パス → window.WCQ_WORLD
    raw/                 # AI 生成の原本（JSONL/JSON。監査済み）
  icons/ manifest.webmanifest sw.js   # PWA（ホーム画面追加・オフライン）
native/                  # Capacitor iOS ラッパー（App Store 提出用）
  capacitor.config.json  # appId: com.whiskydojo.app（提出時に自分の ID へ変更）
  ios/App/App.xcodeproj  # Xcode プロジェクト（SPM ベース、CocoaPods 不要）
release/whisky-connoisseur.html  # 全アセットをインライン化した単一ファイル版
scripts/
  whisky_map_convert.py  # Natural Earth GeoJSON → Miller 図法 SVG パス
  whisky_build.py        # raw 検証・統合 → data/*.js、単一ファイル、native/www 同期
```

データはすべて `<script src>` でグローバル変数として読み込む。fetch を使わないため `file://` 直開きでも動き、単一ファイル化も正規表現によるインライン展開だけで済む。

## 問題データのスキーマ

```json
{"id":"SPE-001","domain":"spey","level":"expert","category":"distillery",
 "tags":["speyside","macallan","sherry-cask"],"region":"scotland-speyside",
 "question":"…","choices":["…","…","…","…"],"answer":0,
 "explanation":"…","difficulty":2,
 "type":"color","color_hex":"#C97B2D"}
```

- `level`: expert / professional / master（試験の3階級に対応）
- `category`: 14分類（産地・蒸留所・製造・原料・熟成・ブレンド・法規・歴史・人物・ブランド・テイスティング・香味成分・文化・業界）
- `tags`: 苦手分析の最小単位。蒸留所名・工程名・法規名などを英語ケバブケースで3〜6個
- `region`: 世界地図モードとの連結キー（18地域）
- `type` / `color_hex`: 官能問題のみ。`color` の場合は出題時にグラス CG を描画

## 苦手分析の設計

- 回答のたびに qid・タグ・分類・級ごとの正誤カウンタを更新する（storage.js）。
- 苦手克服モードの出題スコア: 自問題の誤答率×2 ＋ 所属タグの平均誤答率（試行2回以上のタグのみ）＋ 所属分野の誤答率×0.5。スコア上位から乱択する。
- 復習リストは誤答で追加、正解で除去。「間違いだけ再挑戦」はセッション内の誤答からも組める。

## 世界地図の設計（v2: 産地ドリルダウン）

- 世界ビュー: Natural Earth 110m land（パブリックドメイン）を Miller 図法で投影した SVG パス（約48KB）に、10産地の「塗りエリア」（ぼかし楕円＋破線縁）を重ねる。タップで産地ページへ。
- 産地ビュー: Natural Earth 50m を産地ごとの矩形で Sutherland–Hodgman クリップした高精細海岸線（`data/areamaps.js`、計約110KB）。同一の Miller 座標系なので viewBox の切替だけで遷移できる。スコットランドは6産地区分の簡易ポリゴン／島サークルを重ねる（学習用の目安であり厳密な境界ではない）。
- エリアパック（`data/areas.js`）: 産地ごとの背景読み物・年表（era/icon 付き 10〜18件）・蒸留所詳細（歴史・代表銘柄・豆知識）。raw は `app/data/raw/areas/*.json`、生成は sonnet・監査は opus。
- スクロール年表: 5つの時代（origins/smuggling/industrial/crisis/renaissance）で色分けした縦スパイン＋線画アイコン12種（mapmeta.js に内蔵）。IntersectionObserver でカードのフェードインと時代バナーの切替を行う。
- 入力: pointer capture に依存しないタップ判定（移動閾値 7px）。クライアント座標→SVG 座標は `getScreenCTM()` で変換し、`preserveAspectRatio` の切り抜き・余白があっても正確。ラベルのフォントサイズも実描画倍率基準で決め、衝突する蒸留所ラベルはズームアウト時に間引く。

## データ生成パイプライン

並列サブエージェント（生成16体＋独立監査16体。生成は主に sonnet、論文と監査は opus）で構築した。

1. 生成（sonnet、論文のみ opus）: 12ドメイン×90問 + 論文25×2 + 地図36 + 官能（色12段階+60問）。スキーマ・難度配分・事実性ルールをプロンプトで固定し、JSONL で出力、python3 で妥当性検証。
2. 監査（opus）: 各ファイルを独立に事実確認。誤りは修正、確信の持てない問題は削除。
3. 統合（whisky_build.py）: スキーマ検証・重複除去・ID 一意化のうえ data/*.js を生成。

## 主要な設計判断

- **ネイティブより Web を正**とし、iOS は Capacitor で同一資産を包む。理由: 配布の速さ（URL/ファイルで渡せる）、この環境で実機ビルド不能な Xcode 依存を最小化、コード一本化。
- **依存ライブラリゼロ**。ビルド道具が消えても index.html は動き続ける。10年後も開ける形を優先した。
- **localStorage のみ**で同期なし。個人情報・通信なしで「人に渡せる」を最短で満たす。端末をまたぐ同期は将来課題。
