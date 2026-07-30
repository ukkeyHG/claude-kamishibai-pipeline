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
| 1-A | prep | Create episode directory | - |
| 1-B | design | Generate kamishibai script | 8 min |
| 2 | design_review | Review + auto-fix loop | 5 min/review |
| 3-A | narration | Generate narration | 3 min |
| 3-B | narration_review | Review narration | 5 min/review |
| 4-A | image_prompt | Generate image prompts | 5 min |
| 4-B | image_prompt_review | Review image prompts | 8 min/review |
| 5-A | video_prompt | Generate video prompts | 5 min |
| 5-B | video_prompt_review | Review video prompts | 5 min/review |
| 6-A | youtube | Generate YouTube assets | 5 min |
| 6-B | youtube_review | Review YouTube assets | 5 min/review |
| 7-A | bgm | Generate BGM prompts | 10 min |
| 7-B | bgm_review | Review BGM prompts | 5 min/review |
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

All state is stored in SQLite (`orchestrator/pipeline.db`):

- **episodes**: Episode metadata (slug, country, status)
- **steps**: Step tracking (status, retry count, output file)
- **pipeline_state**: Checkpoints (last completed step)

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


