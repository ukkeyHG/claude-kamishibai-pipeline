"""Review loop handler - generic review + auto-fix loop."""
from __future__ import annotations

import logging
import json
from pathlib import Path

from ..config import PROJECT_ROOT, STEP_DEFS, Timeouts, MAX_REVIEW_RETRIES
from ..state import (
    log_progress, set_checkpoint, append_jsonl_log,
    complete_step, increment_retry,
)
from src.schemas_local import (
    ReviewOutput,
    DesignOutput,
    NarrationOutput,
    ImagePromptOutput,
    VideoPromptOutput,
    YouTubeMetadataOutput,
    BGMPromptOutput
)

logger = logging.getLogger(__name__)

# Map step category to schemas and filenames
REVIEW_STEP_MAP = {
    "design": ("design.json", "design_review.json", "design_review", DesignOutput),
    "narration": ("narration.json", "narration_review.json", "narration_review", NarrationOutput),
    "image_prompt": ("image_prompts.json", "image_prompt_review.json", "image_prompt_review", ImagePromptOutput),
    "video_prompt": ("video_prompts.json", "video_prompt_review.json", "video_prompt_review", VideoPromptOutput),
    "youtube": ("youtube.json", "youtube_review.json", "youtube_review", YouTubeMetadataOutput),
    "bgm": ("bgm_prompts.json", "bgm_review.json", "bgm_review", BGMPromptOutput),
}

def _get_step_number(step_name: str) -> str:
    mapping = {
        "design_review": "1",
        "narration_review": "2",
        "image_prompt_review": "3",
        "video_prompt_review": "4",
        "bgm_review": "5",
        "youtube_review": "6",
    }
    return mapping.get(step_name, "?")

def run_review_loop(ctx: dict, step_category: str) -> bool:
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug

    if step_category not in REVIEW_STEP_MAP:
        logger.error("Unknown step category: %s", step_category)
        return False

    gen_file, rev_file, step_name, schema = REVIEW_STEP_MAP[step_category]

    timeout_key = step_name.replace("_review", "") + ("_review" if "review" in step_name else "")
    timeouts = Timeouts()
    timeout = timeouts.for_step(timeout_key)
    if timeout == 300 and "review" in step_name:
        timeout = getattr(timeouts, step_name, 300)

    max_retries = ctx.get("max_reviews", MAX_REVIEW_RETRIES)

    log_progress(
        episode_slug, country_ja, "pipeline",
        f"step_{step_name}_start",
        f"{step_category} review loop start (JSON)",
        f"{_get_step_number(step_name)}/7",
    )

    review_count = 0
    history_file = ep_dir / "review_history.md"

    while review_count <= max_retries:
        if review_count == 0:
            log_progress(episode_slug, country_ja, "reviewer", "reviewer_iter", f"Review R=1", f"{_get_step_number(step_name)}/7")
        else:
            log_progress(episode_slug, country_ja, "generator", "designer_revise", f"Auto-fix R={review_count + 1}", f"{_get_step_number(step_name)}/7")

        # 1. Review
        review_obj = _run_review(ctx, step_category, step_name, gen_file, rev_file, timeout)
        
        if not review_obj:
            log_progress(episode_slug, country_ja, "pipeline", "pipeline_aborted", f"{step_category} review failed", f"{_get_step_number(step_name)}/7")
            return False
            
        with open(history_file, "a", encoding="utf-8") as f:
            if review_count == 0:
                f.write(f"## Phase: {step_category}\n\n")
            f.write(f"### イテレーション {review_count+1} のレビュー結果\n")
            if not review_obj.feedback:
                f.write("- 問題なし（承認されました）\n")
            else:
                for fb in review_obj.feedback:
                    f.write(f"- {fb}\n")

        status = review_obj.status
        
        if status == "approve":
            log_progress(episode_slug, country_ja, "pipeline", f"step_{step_name}_done", f"GO (R={review_count + 1})", f"{_get_step_number(step_name)}/7")
            step_def = STEP_DEFS.get(step_name)
            if step_def:
                set_checkpoint(episode_slug, step_def.checkpoint_value)
                if ctx.get("episode_id"):
                    complete_step(ctx["episode_id"], step_name, retry_count=review_count)
            return True

        elif status == "revise":
            review_count += 1
            if ctx.get("episode_id"):
                increment_retry(ctx["episode_id"], step_name)
            if review_count > max_retries:
                _abort_review_loop(ctx, step_name, review_count)
                return False
            
            # Revision
            fix_passed = _run_revision(ctx, step_category, step_name, gen_file, rev_file, timeout, schema)
            if not fix_passed:
                _abort_review_loop(ctx, step_name, review_count)
                return False

        else:
            logger.warning("Unknown status: %s", status)
            _abort_review_loop(ctx, step_name, review_count)
            return False

    return False

def _run_review(ctx, step_category, step_name, gen_file, rev_file, timeout):
    client = ctx.get("claude_client")
    if not client: return None
    
    ep_dir = PROJECT_ROOT / "episodes" / ctx["episode_slug"]
    gen_path = ep_dir / gen_file
    gen_text = gen_path.read_text(encoding="utf-8") if gen_path.exists() else ""
    
    command = f"""# Pipeline Step: {step_category}_review
    
## Task
Review the generated {gen_file}.

## Generated JSON Content
{gen_text}

## Requirements
Please review based on the series bible.
Format your output as JSON matching the ReviewOutput schema.
"""
    try:
        obj = client.run_json_step(
            command=command,
            schema=ReviewOutput,
            timeout=timeout,
            episode_slug=ctx["episode_slug"],
            step_label=f"{_get_step_number(step_name)}/7",
            agent_role="reviewer"
        )
        # save review file
        with open(ep_dir / rev_file, "w", encoding="utf-8") as f:
            f.write(obj.model_dump_json(indent=2))
        return obj
    except Exception as e:
        logger.error(f"Review failed: {e}")
        return None

def _run_revision(ctx, step_category, step_name, gen_file, rev_file, timeout, schema):
    client = ctx.get("claude_client")
    if not client: return False
    
    ep_dir = PROJECT_ROOT / "episodes" / ctx["episode_slug"]
    gen_text = (ep_dir / gen_file).read_text(encoding="utf-8") if (ep_dir / gen_file).exists() else ""
    rev_text = (ep_dir / rev_file).read_text(encoding="utf-8") if (ep_dir / rev_file).exists() else ""
    
    agent_name = "youtube-generator" if step_category == "youtube" else "kamishibai-generator"
    
    command = f"""# Pipeline Step: {step_category}_revise
    
## Agent
Use the `{agent_name}` agent.

## Task
Revise {gen_file} based on the review feedback.

## Current JSON
{gen_text}

## Review Feedback
{rev_text}

## Requirements
Output the REVISED JSON matching the exact schema required for this step.
"""
    try:
        obj = client.run_json_step(
            command=command,
            schema=schema,
            timeout=timeout,
            episode_slug=ctx["episode_slug"],
            step_label=f"{_get_step_number(step_name)}/7",
            agent_role="generator"
        )
        with open(ep_dir / gen_file, "w", encoding="utf-8") as f:
            f.write(obj.model_dump_json(indent=2))
        return True
    except Exception as e:
        logger.error(f"Revision failed: {e}")
        return False

def _abort_review_loop(ctx, step_name, retry_count):
    log_progress(
        ctx["episode_slug"], ctx["country_ja"], "pipeline",
        "pipeline_aborted",
        f"Review loop aborted after {retry_count} retries",
        f"{_get_step_number(step_name)}/7",
    )
