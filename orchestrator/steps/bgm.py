"""Step 5: bgm."""
from __future__ import annotations

import logging
from pathlib import Path
import json

from src.schemas_local import BGMPromptOutput
from ..config import PROJECT_ROOT, STEP_DEFS, Timeouts
from ..state import log_progress, set_checkpoint, complete_step

logger = logging.getLogger(__name__)

def run_bgm(ctx: dict) -> bool:
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug
    output_file = ep_dir / "bgm_prompts.json"
    design_file = ep_dir / "design.json"

    timeout = Timeouts().bgm

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_bgm_start",
        "BGMプロンプト開始（JSON）",
        "5/7",
    )

    if not design_file.exists():
        logger.error(f"Required file {design_file} not found.")
        return False

    command = _build_bgm_command(ctx, design_file)

    client = ctx.get("claude_client")
    if not client:
        print("[WARNING] No Claude Code client. Skipping.")
        return False

    try:
        output_obj = client.run_json_step(
            command=command,
            schema=BGMPromptOutput,
            timeout=timeout,
            episode_slug=episode_slug,
            step_label="5/7",
        )
    except Exception as e:
        logger.error(f"bgm generation failed: {e}")
        log_progress(
            episode_slug, country_ja, "pipeline",
            "pipeline_aborted",
            f"BGMプロンプトフェーズが失敗しました: {e}",
            "5/7",
        )
        return False

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_obj.model_dump_json(indent=2))

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_bgm_done",
        f"BGMプロンプト完了",
        "5/7",
    )

    set_checkpoint(episode_slug, 5)
    if ctx.get("episode_id"):
        complete_step(ctx["episode_id"], "bgm")

    print(f"[BGMプロンプト] bgm_prompts.json 完成。")
    return True

def _build_bgm_command(ctx: dict, design_file: Path) -> str:
    episode_slug = ctx["episode_slug"]
    country = ctx["country_ja"]
    design_text = design_file.read_text(encoding="utf-8")
    
    return f"""# Pipeline Step: bgm
    
## Task
Generate bgm for episode {episode_slug} ({country}出張編).

## Input Content
【Design JSON】
{design_text}

## Requirements
- Format as JSON matching the schema.
- IMPORTANT: To ensure Suno AI constraints are met, you MUST include 'no vocals, no lyrics, no singing' in all BGM prompts.
- IMPORTANT: Each style_prompt MUST be between 400 and 600 characters in length. Expand your descriptions (instruments, mood, tempo, genre) to ensure it reaches at least 400 characters, but do not exceed 600 characters.
- IMPORTANT: For Pattern A, explicitly write the specific region name in English (e.g. "{country} traditional music", "{country} instruments") instead of using generic placeholders like "[Region]" or "local setting".
"""
