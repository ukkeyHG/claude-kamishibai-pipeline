"""Step 2: Narration - convert kamishibai script to aup2 format."""
from __future__ import annotations

import logging
from pathlib import Path
import json

from ..schemas import NarrationOutput
from ..config import PROJECT_ROOT, STEP_DEFS, Timeouts
from ..state import log_progress, set_checkpoint, complete_step

logger = logging.getLogger(__name__)

def run_narration(ctx: dict) -> bool:
    """Generate the narration script using Claude Code."""
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug
    output_file = ep_dir / "narration.json"
    design_file = ep_dir / "design.json"

    timeout = Timeouts().narration

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_narration_start",
        "ナレーション生成開始（JSON）",
        "2/7",
    )

    if not design_file.exists():
        logger.error(f"Required file {design_file} not found.")
        return False

    command = _build_narration_command(ctx, design_file)

    client = ctx.get("claude_client")
    if not client:
        print("[WARNING] No Claude Code client. Skipping narration generation.")
        return False

    try:
        narration_output = client.run_json_step(
            command=command,
            schema=NarrationOutput,
            timeout=timeout,
            episode_slug=episode_slug,
            step_label="2/7",
        )
    except Exception as e:
        logger.error(f"Narration generation failed: {e}")
        log_progress(
            episode_slug, country_ja, "pipeline",
            "pipeline_aborted",
            f"ナレーションフェーズが失敗しました: {e}",
            "2/7",
        )
        return False

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(narration_output.model_dump_json(indent=2))

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_narration_done",
        f"ナレーション完了（{len(narration_output.scenes)}シーン）",
        "2/7",
    )

    set_checkpoint(episode_slug, 2)
    if ctx.get("episode_id"):
        complete_step(ctx["episode_id"], "narration")

    print(f"[ナレーション] narration.json 完成（{len(narration_output.scenes)}シーン）。")
    return True

def _build_narration_command(ctx: dict, design_file: Path) -> str:
    episode_slug = ctx["episode_slug"]
    country = ctx["country_ja"]
    
    design_text = design_file.read_text(encoding="utf-8")
    
    return f"""# Pipeline Step: narration

You are the kamishibai narrator for the 出張キャリアウーマンご当地グルメ series.

## Task
Generate the narration script for episode {episode_slug} ({country}出張編).

## Agent
Use the `narration-generator` agent.

## Input Content
【Design JSON】
{design_text}

## Requirements
- Convert the scenes into a narration script
- Incorporate appropriate pauses
- Format as JSON matching the schema
"""
