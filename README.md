# Claude Kamishibai Pipeline (Python Orchestrator版)

ローカルLLM（Qwen / Gemma等）とClaude Codeを連携させ、YouTube用の紙芝居動画アセット（シナリオ、画像プロンプト、動画プロンプト、BGMプロンプト、YouTubeメタデータ）を全自動生成する究極のストーリー・パイプラインです。

以前のBashベースのスクリプトから進化し、堅牢な**Pythonオーケストレーター**と**Webダッシュボード**を備えた次世代アーキテクチャに生まれ変わりました。

## 🌟 主な特徴

- **完全自律のフェーズ進行 (Python Orchestrator)**
  `pipeline.py` が中心となり、Preparation → Design → Narration → Image Prompt → Video Prompt → BGM → YouTube Metadata の全7フェーズを自動で進行します。進行状況やリトライ回数はすべて **SQLiteデータベース (`pipeline.db`)** に正確に記録されるため、途中でクラッシュしても途中から安全・確実に再開可能です。
- **堅牢な状態管理 (Source of Truth)**
  ダッシュボードの表示やパイプラインの再開ロジックは、ログファイル（JSONL）の文字列解析に頼らず、SQLiteの `episodes` テーブルや `steps` テーブルを正（Source of Truth）として利用しています。これにより、複雑な自己修復ループや再試行時にもステータスが崩れることはありません。
- **Generator × Reviewer の自己修復ループ**
  各フェーズにおいて「生成エージェント (Generator)」と「審査エージェント (Reviewer)」が対話。LLMが生成した出力（JSON）を自動でパース・検証し、ルール違反があれば最大3回の修正ループ（R=1〜3）を回して自己修復します。
- **Suno AI / AviUtl 等への厳格なプロンプト制約**
  BGM生成における「ボーカル禁止 (no vocals)」や「400-600文字制限」、画像生成における「ネガティブプロンプトの厳密な指定」など、外部ツールに合わせた高度な制約をシステムレベルで組み込んでいます。
- **リアルタイムWebダッシュボード**
  FastAPIとVanilla JSで構築された美麗なローカルダッシュボード（`index.html`）を搭載。各フェーズの進捗、現在のイテレーション数、生成・修正状況をブラウザからリアルタイムで監視できます。

## 📁 ディレクトリ構成

```text
claude-kamishibai-pipeline/
├── orchestrator/          # パイプラインの中核となるPythonプログラム
│   ├── pipeline.py        # メインコントローラー
│   ├── claude_client.py   # Claude（LLM）との通信・JSONパース処理
│   └── steps/             # 各フェーズの処理定義 (design.py, bgm.py 等)
├── src/
│   ├── dashboard_server.py # ダッシュボード用FastAPIサーバー
│   └── static/index.html   # リアルタイム監視用UI
├── episodes/              # 自動生成されたエピソードごとの成果物（JSON等）
├── pipeline.db            # パイプラインの状態やリトライ回数を管理するSQLiteデータベース
└── docs/                  # 開発ログや引継ぎドキュメント（handover等）
```

## 🚀 使い方

### 1. 必要な環境
- Python 3.10+
- 必要なPythonパッケージ: `pip install fastapi uvicorn pydantic requests`
- ローカルLLMサーバー (LM Studio, Ollama などで OpenAI互換APIを提供)

### 2. ダッシュボードの起動
ターミナルを開き、以下のコマンドで監視用サーバーを立ち上げます。
```bash
python -m uvicorn dashboard_server:app --host 0.0.0.0 --port 8000 --app-dir src
```
起動後、ブラウザで `http://localhost:8000` にアクセスするとダッシュボードが表示されます。

### 3. パイプライン（エピソード生成）の開始
別のターミナルを開き、テーマ（例: 秋田）を指定してオーケストレーターを実行します。
```bash
python -m orchestrator.main 秋田
```
実行すると、ダッシュボードの表示がリアルタイムで更新され、GeneratorとReviewerの対話が始まります。全フェーズが緑色（Completed）になれば生成完了です！

## ⚠️ トラブルシューティング
- **プログラムを書き換えたのに反映されない**: オーケストレーター（`main.py`）が実行中の場合、メモリ上のコードが使われ続けます。コード修正を反映させるには一度プロセスを終了し、再起動してください。
- **ダッシュボードの表示がおかしい**: WebブラウザがHTMLをキャッシュしている可能性があります。**スーパーリロード（Ctrl+F5）**を行って最新のUIを読み込んでください。

---
*本リポジトリは、YouTubeの解説動画用に作成されたプロジェクトです。システムの詳しい仕組みやAI同士の対話の様子は動画本編をご覧ください！*
