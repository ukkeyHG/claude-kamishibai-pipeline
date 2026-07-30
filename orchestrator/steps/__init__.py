"""Step handlers for the pipeline."""
from .preflight import run_preflight
from .prep import run_prep
from .design import run_design
from .review_loop import run_review_loop
from .narration import run_narration
from .image_prompt import run_image_prompt
from .video_prompt import run_video_prompt
from .youtube import run_youtube
from .bgm import run_bgm
from .complete import run_complete

STEP_HANDLERS = {
    "preflight": run_preflight,
    "prep": run_prep,
    "design": run_design,
    "design_review": lambda ctx: run_review_loop(ctx, "design"),
    "narration": run_narration,
    "narration_review": lambda ctx: run_review_loop(ctx, "narration"),
    "image_prompt": run_image_prompt,
    "image_prompt_review": lambda ctx: run_review_loop(ctx, "image_prompt"),
    "video_prompt": run_video_prompt,
    "video_prompt_review": lambda ctx: run_review_loop(ctx, "video_prompt"),
    "youtube": run_youtube,
    "youtube_review": lambda ctx: run_review_loop(ctx, "youtube"),
    "bgm": run_bgm,
    "bgm_review": lambda ctx: run_review_loop(ctx, "bgm"),
    "complete": run_complete,
}

__all__ = [
    "STEP_HANDLERS",
    "run_preflight",
    "run_prep",
    "run_design",
    "run_review_loop",
    "run_narration",
    "run_image_prompt",
    "run_video_prompt",
    "run_youtube",
    "run_bgm",
    "run_complete",
]
