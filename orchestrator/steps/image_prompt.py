"""Step 3: image_prompt."""
from __future__ import annotations

import logging
from pathlib import Path
import json

from src.schemas_local import ImagePromptOutput
from ..config import PROJECT_ROOT, STEP_DEFS, Timeouts
from ..state import log_progress, set_checkpoint, complete_step

logger = logging.getLogger(__name__)

def run_image_prompt(ctx: dict) -> bool:
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug
    output_file = ep_dir / "image_prompts.json"
    design_file = ep_dir / "design.json"

    timeout = Timeouts().image_prompt

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_image_prompt_start",
        "画像プロンプト開始（JSON）",
        "3/7",
    )

    if not design_file.exists():
        logger.error(f"Required file {design_file} not found.")
        return False

    command = _build_image_prompt_command(ctx, design_file)

    client = ctx.get("claude_client")
    if not client:
        print("[WARNING] No Claude Code client. Skipping.")
        return False

    try:
        output_obj = client.run_json_step(
            command=command,
            schema=ImagePromptOutput,
            timeout=timeout,
            episode_slug=episode_slug,
            step_label="3/7",
        )
    except Exception as e:
        logger.error(f"image_prompt generation failed: {e}")
        log_progress(
            episode_slug, country_ja, "pipeline",
            "pipeline_aborted",
            f"画像プロンプトフェーズが失敗しました: {e}",
            "3/7",
        )
        return False

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_obj.model_dump_json(indent=2))

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_image_prompt_done",
        f"画像プロンプト完了",
        "3/7",
    )

    set_checkpoint(episode_slug, 3)
    if ctx.get("episode_id"):
        complete_step(ctx["episode_id"], "image_prompt")

    print(f"[画像プロンプト] image_prompts.json 完成。")
    return True

def _build_image_prompt_command(ctx: dict, design_file: Path) -> str:
    episode_slug = ctx["episode_slug"]
    country = ctx["country_ja"]
    design_text = design_file.read_text(encoding="utf-8")
    
    return f"""# Pipeline Step: image_prompt
    
## Task
Generate image_prompt for episode {episode_slug} ({country}出張編).

## Input Content
【Design JSON】
{design_text}

## Requirements
Format as JSON matching the schema.
"""
