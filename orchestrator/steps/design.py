"""Step 1-B: Design - generate kamishibai script."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from ..schemas import DesignOutput
from ..config import PROJECT_ROOT, STEP_DEFS, Timeouts
from ..state import (
    log_progress, set_checkpoint, append_jsonl_log,
    get_episode, complete_step, create_step,
)

logger = logging.getLogger(__name__)


def run_design(ctx: dict) -> bool:
    """Generate the kamishibai script using Claude Code."""
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug
    output_file = ep_dir / "design.json"

    timeout = Timeouts().design

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_designer_start",
        "設計フェーズ開始（JSON）",
        "1/7",
    )

    command = _build_design_command(ctx)

    client = ctx.get("claude_client")
    if not client:
        print("[WARNING] No Claude Code client. Skipping design generation.")
        return False

    try:
        design_output = client.run_json_step(
            command=command,
            schema=DesignOutput,
            timeout=timeout,
            episode_slug=episode_slug,
            step_label="1/7",
        )
    except Exception as e:
        logger.error(f"Design generation failed: {e}")
        log_progress(
            episode_slug, country_ja, "pipeline",
            "pipeline_aborted",
            f"設計フェーズが失敗しました: {e}",
            "1/7",
        )
        return False

    # Save to file
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(design_output.model_dump_json(indent=2))

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_designer_done",
        f"設計完了（{len(design_output.scenes)}シーン）",
        "1/7",
    )

    # Set checkpoint
    set_checkpoint(episode_slug, 1)
    if ctx.get("episode_id"):
        complete_step(ctx["episode_id"], "design")

    print(f"[設計] design.json 完成（{len(design_output.scenes)}シーン）。")
    return True


def _build_design_command(ctx: dict) -> str:
    """Build the Claude Code command for design generation."""
    episode_slug = ctx["episode_slug"]
    country = ctx["country_ja"]
    
    series_bible_path = PROJECT_ROOT / "series_bible.md"
    bible_text = series_bible_path.read_text(encoding="utf-8") if series_bible_path.exists() else ""

    return f"""# Pipeline Step: design

You are the kamishibai designer for the 出張キャリアウーマンご当地グルメ series.

## Task
Generate the kamishibai script for episode {episode_slug} ({country}出張編).

## Agent
Use the `kamishibai-generator` agent (run_in_background: true).

## Input Context
【シリーズ設定資料 (series_bible.md)】
{bible_text}

## Requirements
- Choose 1 prefecture in Japan (the user specified: {country})
- Select up to 3 local dishes (prioritize izakaya-friendly items)
- Create 10-15 scenes
- Use WebSearch to verify dish names and cultural accuracy
- Do NOT ask the user questions
- This is an autonomous pipeline execution
"""
