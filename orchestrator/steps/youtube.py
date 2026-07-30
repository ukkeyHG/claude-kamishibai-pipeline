"""Step 6: youtube."""
from __future__ import annotations

import logging
from pathlib import Path
import json

from src.schemas_local import YouTubeMetadataOutput
from ..config import PROJECT_ROOT, STEP_DEFS, Timeouts
from ..state import log_progress, set_checkpoint, complete_step

logger = logging.getLogger(__name__)

def run_youtube(ctx: dict) -> bool:
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug
    output_file = ep_dir / "youtube.json"
    design_file = ep_dir / "design.json"

    timeout = Timeouts().youtube

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_youtube_start",
        "YouTubeメタデータ開始（JSON）",
        "6/7",
    )

    if not design_file.exists():
        logger.error(f"Required file {design_file} not found.")
        return False

    command = _build_youtube_command(ctx, design_file)

    client = ctx.get("claude_client")
    if not client:
        print("[WARNING] No Claude Code client. Skipping.")
        return False

    try:
        output_obj = client.run_json_step(
            command=command,
            schema=YouTubeMetadataOutput,
            timeout=timeout,
            episode_slug=episode_slug,
            step_label="6/7",
        )
    except Exception as e:
        logger.error(f"youtube generation failed: {e}")
        log_progress(
            episode_slug, country_ja, "pipeline",
            "pipeline_aborted",
            f"YouTubeメタデータフェーズが失敗しました: {e}",
            "6/7",
        )
        return False

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_obj.model_dump_json(indent=2))

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_youtube_done",
        f"YouTubeメタデータ完了",
        "6/7",
    )

    set_checkpoint(episode_slug, 6)
    if ctx.get("episode_id"):
        complete_step(ctx["episode_id"], "youtube")

    print(f"[YouTubeメタデータ] youtube.json 完成。")
    return True

def _build_youtube_command(ctx: dict, design_file: Path) -> str:
    episode_slug = ctx["episode_slug"]
    country = ctx["country_ja"]
    design_text = design_file.read_text(encoding="utf-8")
    
    return f"""# Pipeline Step: youtube
    
## Task
Generate youtube for episode {episode_slug} ({country}出張編).

## Input Content
【Design JSON】
{design_text}

## Requirements
Format as JSON matching the schema.
"""
