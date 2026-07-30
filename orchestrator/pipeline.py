"""
Main pipeline orchestrator.

Coordinates all steps: preflight → prep → design → review loops → complete.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

from . import config
from .claude_client import ClaudeClient, ClaudeCodeTimeoutError, ClaudeCodeError
from .config import (
    PROJECT_ROOT, EPISODES_DIR, PIPELINE_ORDER,
    STEP_DEFS, SIMPLE_STEPS,
)
from .state import (
    init_db, create_episode, get_episode, get_resume_info, _get_conn, get_step,
    create_step, set_checkpoint, update_episode_status,
    log_progress, append_jsonl_log, complete_step,
)
from .steps import STEP_HANDLERS
from .utils import slugify

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Raised when the pipeline encounters a fatal error."""
    pass


class PipelineOrchestrator:
    """Coordinates the kamishibai pipeline execution."""

    def __init__(
        self,
        country_ja: str,
        project_root: Path | None = None,
        resume: bool = False,
    ):
        self.country_ja = country_ja
        self.project_root = project_root or PROJECT_ROOT
        self.is_resume = resume
        self.episode_slug: str = ""
        self.nn: str = ""
        self.slug: str = ""
        self.episode_id: int = 0
        self.client: Optional[ClaudeClient] = None
        self.start_time: float = 0

        # Initialize database before resolving
        init_db()

        # Resolve episode number and slug
        self._resolve_episode()

    def _resolve_episode(self) -> None:
        """Resolve episode number (NN) and slug from country name."""
        # 1. Calculate the slug first
        self.slug = slugify(self.country_ja)

        # 2. Check if there's an existing incomplete episode with this slug in the DB
        if self.is_resume:
            conn = _get_conn()
            try:
                row = conn.execute(
                    "SELECT id, status, episode_slug FROM episodes WHERE episode_slug LIKE ? AND status != 'completed'",
                    (f"%_{self.slug}",)
                ).fetchone()
                if row:
                    # Found an incomplete episode! Use its ID/number logic?
                    existing_slug = row["episode_slug"]
                    match = re.match(r"^ep(\d+)_", existing_slug)
                    if match:
                        self.nn = int(match.group(1))
                        self.episode_slug = existing_slug
                        return
            finally:
                conn.close()

        # 3. If no incomplete episode, find the next number from directories
        self.nn = config.determine_next_episode_number(EPISODES_DIR)
        self.episode_slug = f"ep{self.nn}_{self.slug}"

    def run(self) -> bool:
        """Execute the full pipeline.

        Returns:
            True if the pipeline completed successfully.
        """
        self.start_time = time.time()

        # Check for resume
        resume_info = get_resume_info(self.episode_slug)
        if resume_info and resume_info["is_resume"]:
            logger.info("Resuming episode: %s (checkpoint=%s)",
                       self.episode_slug, resume_info["checkpoint"])
            self.episode_id = resume_info["episode"]["id"]
        else:
            # Create new episode
            self.episode_id = create_episode(self.episode_slug, self.country_ja)
            logger.info("Created new episode: %s (id=%d)",
                       self.episode_slug, self.episode_id)

        # Build context
        ctx = {
            "episode_slug": self.episode_slug,
            "country_ja": self.country_ja,
            "nn": self.nn,
            "slug": self.slug,
            "episode_id": self.episode_id,
            "claude_client": None,  # Set after launch
            "max_reviews": config.MAX_REVIEW_RETRIES,
        }

        # Launch Claude Code client
        try:
            self.client = ClaudeClient(self.project_root)
            self.client.launch()
            ctx["claude_client"] = self.client
        except Exception as e:
            logger.error("Failed to launch Claude Code: %s", e)
            print(f"\n⚠️ Claude Code の起動に失敗しました: {e}")
            print("npm install -g @anthropic-ai/claude-code でインストールしてください。")
            return False

        try:
            # Execute pipeline steps
            for step_name in PIPELINE_ORDER:
                current_step = get_step(self.episode_id, step_name)
                if current_step and current_step["status"] == "completed":
                    logger.info("Skipping already completed step: %s", step_name)
                    continue

                if step_name in ("preflight", "prep"):
                    # Simple setup steps
                    handler = STEP_HANDLERS.get(step_name)
                    if not handler:
                        logger.error("Missing handler for step: %s", step_name)
                        continue

                    # Create step record if it doesn't exist
                    step_def = STEP_DEFS.get(step_name)
                    if step_def and not current_step:
                        create_step(
                            self.episode_id, step_name,
                            output_file=step_def.output_file,
                            timeout_sec=config.Timeouts().for_step(step_def.timeout_key),
                            checkpoint_value=step_def.checkpoint_value,
                        )

                    if not handler(ctx):
                        self._abort(f"Step {step_name} failed")
                        return False

                elif step_name in ("design", "narration", "image_prompt", "video_prompt", "bgm", "youtube"):
                    # Generation steps
                    handler = STEP_HANDLERS.get(step_name)
                    if not handler:
                        continue

                    if not current_step:
                        step_def = STEP_DEFS.get(step_name)
                        if step_def:
                            create_step(
                                self.episode_id, step_name,
                                output_file=step_def.output_file,
                                timeout_sec=config.Timeouts().for_step(step_def.timeout_key),
                                checkpoint_value=step_def.checkpoint_value,
                            )

                    if not handler(ctx):
                        self._abort(f"{step_name} step failed")
                        return False

                elif step_name.endswith("_review"):
                    # Review loop steps
                    category = step_name.replace("_review", "")
                    handler = STEP_HANDLERS.get(step_name)
                    if not handler:
                        continue

                    step_def = STEP_DEFS.get(step_name)
                    if step_def and not current_step:
                        create_step(
                            self.episode_id, step_name,
                            output_file=step_def.output_file,
                            timeout_sec=config.Timeouts().for_step(step_def.timeout_key),
                            checkpoint_value=step_def.checkpoint_value,
                        )

                    if not handler(ctx):
                        self._abort(f"Review loop {step_name} failed")
                        return False

                elif step_name == "complete":
                    handler = STEP_HANDLERS.get("complete")
                    if not handler:
                        continue

                    if not handler(ctx):
                        self._abort("Complete step failed")
                        return False

            # Pipeline completed successfully
            elapsed = time.time() - self.start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            logger.info(
                "Pipeline completed in %dmin %ds", minutes, seconds,
            )
            return True

        except ClaudeCodeTimeoutError as e:
            logger.error("Claude Code timeout: %s", e)
            self._abort(f"Timeout: {e}")
            return False
        except ClaudeCodeError as e:
            logger.error("Claude Code error: %s", e)
            self._abort(f"Error: {e}")
            return False
        except Exception as e:
            logger.exception("Pipeline failed with unexpected error")
            self._abort(f"Unexpected error: {e}")
            return False
        finally:
            if self.client:
                self.client.close()

    def _abort(self, reason: str) -> None:
        """Abort the pipeline with a reason."""
        update_episode_status(self.episode_slug, "aborted")
        log_progress(
            self.episode_slug, self.country_ja, "pipeline",
            "pipeline_aborted",
            reason,
        )
        append_jsonl_log(
            self.episode_slug, "pipeline", "pipeline_aborted", reason,
        )
        print(f"\n[!] パイプライン中止: {reason}")

    def __del__(self):
        """Ensure Claude Code client is closed."""
        if self.client:
            self.client.close()


def run_pipeline(
    country: str,
    project_root: Path | None = None,
    resume: bool = False,
) -> bool:
    """Entry point for the pipeline.

    Args:
        country: Country/prefecture name in Japanese (e.g., "香川")
        project_root: Project root directory (defaults to parent of orchestrator/)
        resume: Whether to resume a previous run

    Returns:
        True if pipeline completed successfully.
    """
    orchestrator = PipelineOrchestrator(
        country_ja=country,
        project_root=project_root,
        resume=resume,
    )
    return orchestrator.run()
