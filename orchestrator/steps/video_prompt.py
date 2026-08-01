"""Step 4: video_prompt."""
from __future__ import annotations

import logging
from pathlib import Path
import json

from ..schemas import VideoPromptOutput
from ..config import PROJECT_ROOT, STEP_DEFS, Timeouts
from ..state import log_progress, set_checkpoint, complete_step

logger = logging.getLogger(__name__)

def run_video_prompt(ctx: dict) -> bool:
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug
    output_file = ep_dir / "video_prompts.json"
    design_file = ep_dir / "design.json"

    timeout = Timeouts().video_prompt

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_video_prompt_start",
        "動画プロンプト開始（JSON）",
        "4/7",
    )

    if not design_file.exists():
        logger.error(f"Required file {design_file} not found.")
        return False

    command = _build_video_prompt_command(ctx, design_file)

    client = ctx.get("claude_client")
    if not client:
        print("[WARNING] No Claude Code client. Skipping.")
        return False

    try:
        output_obj = client.run_json_step(
            command=command,
            schema=VideoPromptOutput,
            timeout=timeout,
            episode_slug=episode_slug,
            step_label="4/7",
        )
    except Exception as e:
        logger.error(f"video_prompt generation failed: {e}")
        log_progress(
            episode_slug, country_ja, "pipeline",
            "pipeline_aborted",
            f"動画プロンプトフェーズが失敗しました: {e}",
            "4/7",
        )
        return False

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_obj.model_dump_json(indent=2))

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_video_prompt_done",
        f"動画プロンプト完了",
        "4/7",
    )

    set_checkpoint(episode_slug, 4)
    if ctx.get("episode_id"):
        complete_step(ctx["episode_id"], "video_prompt")

    print(f"[動画プロンプト] video_prompts.json 完成。")
    return True

def _build_video_prompt_command(ctx: dict, design_file: Path) -> str:
    episode_slug = ctx["episode_slug"]
    country = ctx["country_ja"]
    design_text = design_file.read_text(encoding="utf-8")
    
    return f"""Use the `video-prompt-generator` agent.
# Pipeline Step: video_prompt
    
## Task
Generate video_prompt for episode {episode_slug} ({country}出張編).

## Input Content
【Design JSON】
{design_text}

## Requirements
Format as JSON matching the schema.
- IMPORTANT: For 'expression', you MUST only describe ONE single expression change (e.g. "subtle smile"). Multiple transitions (e.g. "eyes widen then narrow") are STRICTLY FORBIDDEN.
- IMPORTANT: You MUST use the exact series default negative prompt for EVERY scene: `worst quality, inconsistent, blurry, text, watermark, logo, jump cut, deformed, child, loli`
"""
