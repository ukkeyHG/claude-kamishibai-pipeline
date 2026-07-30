# Kamishibai Pipeline Orchestrator

Python-based orchestrator for the 出張キャリアウーマンご当地グルメ paper-theater pipeline.

## Overview

Replaces the fragile Markdown-based state machine with a robust Python orchestrator that:

- **Manages state** via SQLite (checkpoints, step tracking, resume capability)
- **Controls Claude Code** as a subprocess (sends commands, monitors progress)
- **Enforces timeouts** precisely (Python subprocess.TimeoutExpired)
- **Handles review loops** programmatically (parse verdict → decide → revise or proceed)
- **Logs progress** to status.log.jsonl (compatible with existing timeline generator)

## Directory Structure

```
orchestrator/
├── __init__.py          # Package exports
├── main.py              # CLI entry point
├── config.py            # Configuration (timeouts, step defs, agent names)
├── state.py             # SQLite state management
├── claude_client.py     # Claude Code subprocess control
├── pipeline.py          # Main pipeline orchestrator
├── utils.py             # Utility functions
├── prompts/             # Command templates
│   └── pipeline_command.md
├── steps/               # Step handlers
│   ├── __init__.py
│   ├── preflight.py     # Step 0: Validate project
│   ├── prep.py          # Step 1-A: Create episode dir
│   ├── design.py        # Step 1-B: Generate kamishibai
│   ├── review_loop.py   # Generic review + auto-fix loop
│   ├── narration.py     # Step 3-A: Generate narration
│   ├── image_prompt.py  # Step 4-A: Generate image prompts
│   ├── video_prompt.py  # Step 5-A: Generate video prompts
│   ├── youtube.py       # Step 6-A: Generate YouTube assets
│   ├── bgm.py           # Step 7-A: Generate BGM prompts
│   └── complete.py      # Step 8: Final report
```

## Usage

### New episode

```bash
python -m orchestrator.main 香川
```

### Resume interrupted run

```bash
python -m orchestrator.main 香川 --resume
```

### Debug mode

```bash
python -m orchestrator.main 香川 --verbose
```

## Pipeline Steps

| Step | Name | Description | Timeout |
|------|------|-------------|---------|
| 0 | preflight | Validate project root | - |
| 1 | prep | Create episode directory | - |
| 2-A | design | Generate kamishibai script | 8 min |
| 2-B | design_review | Review + auto-fix loop | 5 min/review |
| 3-A | narration | Generate narration | 3 min |
| 3-B | narration_review | Review narration | 5 min/review |
| 4-A | image_prompt | Generate image prompts | 5 min |
| 4-B | image_prompt_review | Review image prompts | 8 min/review |
| 5-A | video_prompt | Generate video prompts | 5 min |
| 5-B | video_prompt_review | Review video prompts | 5 min/review |
| 6-A | bgm | Generate BGM prompts | 10 min |
| 6-B | bgm_review | Review BGM prompts | 5 min/review |
| 7-A | youtube | Generate YouTube assets | 5 min |
| 7-B | youtube_review | Review YouTube assets | 5 min/review |
| 8 | complete | Final report + cleanup | - |

## Architecture

```
/main.py (CLI)
    │
    ▼
/pipeline.py (PipelineOrchestrator)
    │
    ├─ StateManager (SQLite)
    │    └─ episodes, steps, checkpoints, logs
    │
    ├─ ClaudeClient (subprocess)
    │    └─ launches claude, sends commands, monitors progress
    │
    └─ Step Handlers (steps/*.py)
         ├─ run_preflight()
         ├─ run_prep()
         ├─ run_design()
         ├─ run_review_loop(category)  ← shared by all review steps
         ├─ run_narration()
         ├─ run_image_prompt()
         ├─ run_video_prompt()
         ├─ run_youtube()
         ├─ run_bgm()
         └─ run_complete()
```

## State Management

### `episodes` テーブル
エピソード全体のメタデータと進行状態を管理します。

| カラム名 | 型 | 説明 |
|----------|----|------|
| `id` | INTEGER | 主キー |
| `episode_slug` | TEXT | エピソードの一意な識別子（例: `ep100_愛媛`） |
| `country_ja` | TEXT | エピソードのテーマ/都道府県名（例: `愛媛`） |
| `status` | TEXT | エピソード全体のステータス (`running`, `completed`, `aborted`) |
| `created_at` | TEXT | 作成日時 (ISO 8601フォーマット) |
| `updated_at` | TEXT | 最終更新日時 (ISO 8601フォーマット) |

### `steps` テーブル
各エピソード内の「ステップ（工程）」ごとの進行状態やリトライ回数を管理します。ダッシュボードの表示における情報の源泉（Source of Truth）となります。

| カラム名 | 型 | 説明 |
|----------|----|------|
| `id` | INTEGER | 主キー |
| `episode_id` | INTEGER | `episodes` テーブルへの外部キー |
| `step_name` | TEXT | ステップ名（例: `design`, `design_review`） |
| `status` | TEXT | ステップの進行状態 (`pending`, `running`, `completed`, `failed`) |
| `retry_count` | INTEGER | 修正ループ（Revise）に入った回数。ダッシュボードのイテレーション数として使用 |
| `timeout_sec` | INTEGER | このステップに許容される最大実行時間（秒） |
| `output_file` | TEXT | 生成される期待される出力ファイル名 |
| `checkpoint_value` | INTEGER | 成功時に記録されるチェックポイントの数値 |
| `started_at` | TEXT | ステップの開始日時 (ISO 8601フォーマット) |
| `completed_at` | TEXT | ステップの完了日時 (ISO 8601フォーマット) |
| `tokens_in` | INTEGER | このステップで消費された入力トークン数 |
| `tokens_out` | INTEGER | このステップで消費された出力トークン数 |
| `active_agent` | TEXT | 現在実行中のエージェント名 (`pipeline`, `generator`, `reviewer` など) |
| `error_message` | TEXT | 失敗時のエラーメッセージやタイムアウト理由 |

### `pipeline_state` テーブル
パイプライン全体のグローバルな設定やチェックポイントを保存するKVS（キーバリューストア）です。

| カラム名 | 型 | 説明 |
|----------|----|------|
| `key` | TEXT | キー名（主キー）。現在は `checkpoint` のみが使用される |
| `value` | TEXT | 格納される値。`checkpoint` の場合は最後に成功したステップの数値 |

Plus backward-compatible file-based checkpoints:
- `.pipeline_checkpoint` in each episode directory
- `status.json` in project root
- `status.log.jsonl` in each episode directory

## Review Loop Pattern

All review steps follow the same pattern:

```python
for iteration in range(max_reviews + 1):
    1. Run reviewer agent → generates .review.md
    2. Parse Verdict (GO / Revise / GO with minor revisions)
    3. If GO → done, set checkpoint
    4. If Revise or has critical issues → run generator with review feedback
    5. If max reviews exceeded → abort
```


