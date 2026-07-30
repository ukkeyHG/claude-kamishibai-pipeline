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
実行すると、ダッシュボードの表示がリアルタイムで更新され、GeneratorとReviewerの対話が始まります。全フェーズが緑色（Completed）になればテキスト（JSON）の生成完了です！

### 4. 生成完了後の紙芝居制作フロー
パイプラインが完走し各種プロンプトのJSONが出力されたら、以下の順序で実際のメディアファイルを生成します。

1. **画像生成 (ComfyUI)**:
   ローカルでComfyUIを立ち上げた状態で、以下のコマンドを実行します。
   ```bash
   python src/generate_images.py episodes/ep01_熊本
   ```
   ※生成された画像は自動的に `images` フォルダに保存されます。既に生成済みのシーンはスキップされます。
   
   **よくある使い方（ガチャの引き直し）**:
   一通り全シーンを生成した後、「シーン5、6、7だけイマイチだから再生成したい」という場合は、`--scenes` と `--force`（上書き）を組み合わせて実行します。
   ```bash
   python src/generate_images.py episodes/ep01_熊本 --scenes 5 6 7 --force
   ```
   ※カンマ区切り（`5,6,7`）やスペース区切り（`5 6 7`）で指定可能です。
   
   **その他のオプション**:
   - ComfyUIのURLを指定する場合: `--url http://192.168.1.50:8188`

2. **動画生成 (手動)**:
   出力された `video_prompts.json` と生成された画像を元に、Kling等の動画生成AIを使って手動で動画素材を作成し、`videos` フォルダに配置します。

3. **音声合成＆AviUtlタイムライン生成**:
   以下のコマンドを実行し、ナレーション音声の生成とAviUtl用プロジェクトファイル（`.aup2`）の組み立てを行います。
   ```bash
   python src/txt2aup2_for_gourmet.py episodes/ep01_熊本
   ```
   出力されたプロジェクトファイルをAviUtl等で読み込めば、一気に動画のベースが完成します！

## ⚠️ トラブルシューティング
- **プログラムを書き換えたのに反映されない**: オーケストレーター（`main.py`）が実行中の場合、メモリ上のコードが使われ続けます。コード修正を反映させるには一度プロセスを終了し、再起動してください。
- **ダッシュボードの表示がおかしい**: WebブラウザがHTMLをキャッシュしている可能性があります。**スーパーリロード（Ctrl+F5）**を行って最新のUIを読み込んでください。

---
*本リポジトリは、YouTubeの解説動画用に作成されたプロジェクトです。システムの詳しい仕組みやAI同士の対話の様子は動画本編をご覧ください！*
