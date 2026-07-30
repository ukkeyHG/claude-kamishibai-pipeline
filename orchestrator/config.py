"""
Orchestrator configuration for the kamishibai pipeline.

All timeouts, step definitions, and agent mappings are defined here.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

def resolve_project_root() -> Path:
    """Resolve the project root directory.

    Priority:
    1. KAMISHIBAI_PROJECT_ROOT env var
    2. Parent of this file's directory (orchestrator/ is a subdirectory)
    3. Current working directory
    """
    env = os.environ.get("KAMISHIBAI_PROJECT_ROOT")
    if env:
        return Path(env)
    # orchestrator/ is a subdirectory of the project root
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = resolve_project_root()
EPISODES_DIR = PROJECT_ROOT / "episodes"
SERIES_BIBLE = PROJECT_ROOT / "series_bible.md"
CLAUDE_AGENTS_DIR = PROJECT_ROOT / ".claude" / "agents"
CLAUDE_COMMANDS_DIR = PROJECT_ROOT / ".claude" / "commands" / "pipeline"
DB_PATH = PROJECT_ROOT / "orchestrator" / "pipeline.db"


def determine_next_episode_number(episodes_dir: Path | None = None) -> str:
    """Determine the next episode number.

    Uses the same logic as the original pipeline:
    - Scan episodes/ directory
    - Extract numbers from ep<NN>_* patterns
    - Return max + 1, zero-padded to 2 digits
    """
    if episodes_dir is None:
        episodes_dir = EPISODES_DIR
    if not episodes_dir.exists():
        return "01"

    import re as _re
    nums = []
    for d in episodes_dir.iterdir():
        if d.is_dir():
            m = _re.match(r"^ep(\d+)_", d.name)
            if m:
                nums.append(int(m.group(1)))

    next_num = (max(nums) if nums else 0) + 1
    return f"{next_num:02d}"

# ---------------------------------------------------------------------------
# Timeout configuration (in seconds)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Timeouts:
    """Timeout for each step (in seconds)."""
    design: int = 600        # 10 min
    review: int = 600        # 10 min
    narration: int = 300     # 5 min
    image_prompt: int = 600  # 10 min
    video_prompt: int = 600  # 10 min
    youtube: int = 600       # 10 min
    bgm: int = 600           # 10 min
    narration_review: int = 600  # 10 min
    image_prompt_review: int = 600   # 10 min
    video_prompt_review: int = 600   # 10 min
    youtube_review: int = 600        # 10 min
    bgm_review: int = 600            # 10 min

    # Max total pipeline duration
    total: int = 3600 * 3  # 3 hours max

    def for_step(self, step: str) -> int:
        return getattr(self, step, 300)


# ---------------------------------------------------------------------------
# Review loop configuration
# ---------------------------------------------------------------------------

MAX_REVIEW_RETRIES = 3  # Maximum auto-fix attempts per review loop

# ---------------------------------------------------------------------------
# Agent name mappings
# These must match the `name:` field in .claude/agents/*.md files
# ---------------------------------------------------------------------------

AGENT_NAMES = {
    "design": "kamishibai-generator",
    "design_review": "kamishibai-reviewer",
    "narration": "narration-generator",
    "narration_review": "narration-reviewer",
    "image_prompt": "image-prompt-generator",
    "image_prompt_review": "image-prompt-reviewer",
    "video_prompt": "video-prompt-generator",
    "video_prompt_review": "video-prompt-reviewer",
    "youtube": "youtube-generator",
    "youtube_review": "youtube-reviewer",
    "bgm": "bgm-prompt-generator",
    "bgm_review": "bgm-prompt-reviewer",
}

# ---------------------------------------------------------------------------
# Step definitions
# Each step has: agent name, output file, inputs, timeout key
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StepDef:
    name: str                # Step identifier (e.g., "design")
    agent: str               # Claude Code agent name
    output_file: str         # Output filename (relative to episode dir)
    inputs: list[str]        # Input files (relative paths)
    timeout_key: str         # Key in Timeouts
    checkpoint_value: int    # Checkpoint value on success
    max_reviews: int = MAX_REVIEW_RETRIES


STEP_DEFS: dict[str, StepDef] = {
    "design": StepDef(
        name="design",
        agent=AGENT_NAMES["design"],
        output_file="01_kamishibai.md",
        inputs=["series_bible.md"],
        timeout_key="design",
        checkpoint_value=1,
    ),
    "design_review": StepDef(
        name="design_review",
        agent=AGENT_NAMES["design_review"],
        output_file="02_kamishibai.review.md",
        inputs=["series_bible.md", "01_kamishibai.md"],
        timeout_key="review",
        checkpoint_value=2,
    ),
    "narration": StepDef(
        name="narration",
        agent=AGENT_NAMES["narration"],
        output_file="03_narration.md",
        inputs=["series_bible.md", "01_kamishibai.md", "02_kamishibai.review.md"],
        timeout_key="narration",
        checkpoint_value=3,
    ),
    "narration_review": StepDef(
        name="narration_review",
        agent=AGENT_NAMES["narration_review"],
        output_file="04_narration.review.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md"],
        timeout_key="narration_review",
        checkpoint_value=3,
    ),
    "image_prompt": StepDef(
        name="image_prompt",
        agent=AGENT_NAMES["image_prompt"],
        output_file="05_image-prompt.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md"],
        timeout_key="image_prompt",
        checkpoint_value=4,
    ),
    "image_prompt_review": StepDef(
        name="image_prompt_review",
        agent=AGENT_NAMES["image_prompt_review"],
        output_file="06_image-prompt.review.md",
        inputs=["series_bible.md", "01_kamishibai.md", "05_image-prompt.md"],
        timeout_key="image_prompt_review",
        checkpoint_value=4,
    ),
    "video_prompt": StepDef(
        name="video_prompt",
        agent=AGENT_NAMES["video_prompt"],
        output_file="07_video-prompt.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md", "05_image-prompt.md"],
        timeout_key="video_prompt",
        checkpoint_value=5,
    ),
    "video_prompt_review": StepDef(
        name="video_prompt_review",
        agent=AGENT_NAMES["video_prompt_review"],
        output_file="08_video-prompt.review.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md", "05_image-prompt.md", "07_video-prompt.md"],
        timeout_key="video_prompt_review",
        checkpoint_value=5,
    ),
    "bgm": StepDef(
        name="bgm",
        agent=AGENT_NAMES["bgm"],
        output_file="09_bgm-prompt.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md"],
        timeout_key="bgm",
        checkpoint_value=6,
    ),
    "bgm_review": StepDef(
        name="bgm_review",
        agent=AGENT_NAMES["bgm_review"],
        output_file="10_bgm-prompt.review.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md", "09_bgm-prompt.md"],
        timeout_key="bgm_review",
        checkpoint_value=6,
    ),
    "youtube": StepDef(
        name="youtube",
        agent=AGENT_NAMES["youtube"],
        output_file="11_youtube.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md", "05_image-prompt.md"],
        timeout_key="youtube",
        checkpoint_value=7,
    ),
    "youtube_review": StepDef(
        name="youtube_review",
        agent=AGENT_NAMES["youtube_review"],
        output_file="12_youtube.review.md",
        inputs=["series_bible.md", "01_kamishibai.md", "03_narration.md", "11_youtube.md"],
        timeout_key="youtube_review",
        checkpoint_value=7,
    ),
}

# Pipeline step order (for execution)
PIPELINE_ORDER = [
    "preflight",    # Step 0: Validate project root
    "prep",         # Step 1-A: Create episode dir
    "design",       # Step 1-B: Design kamishibai
    "design_review", # Step 2: Review + auto-fix loop
    "narration",    # Step 3-A: Generate narration
    "narration_review", # Step 3-B: Review narration
    "image_prompt", # Step 4-A: Generate image prompts
    "image_prompt_review", # Step 4-B: Review image prompts
    "video_prompt", # Step 5-A: Generate video prompts
    "video_prompt_review", # Step 5-B: Review video prompts
    "bgm",          # Step 6-A: Generate BGM prompts
    "bgm_review",   # Step 6-B: Review BGM prompts
    "youtube",      # Step 7-A: Generate YouTube assets
    "youtube_review", # Step 7-B: Review YouTube assets
    "complete",     # Step 8: Final report
]

# Steps that have a review loop (generate → review → (revise → review)*)
REVIEW_STEPS = [
    "design", "design_review",
    "narration", "narration_review",
    "image_prompt", "image_prompt_review",
    "video_prompt", "video_prompt_review",
    "youtube", "youtube_review",
    "bgm", "bgm_review",
]

# Steps that are simple (generate only, no review loop)
SIMPLE_STEPS = ["preflight", "prep", "complete"]
