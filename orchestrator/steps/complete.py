"""Step 8: Complete - final report and cleanup."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from ..config import PROJECT_ROOT, EPISODES_DIR
from ..state import (
    log_progress, clear_checkpoint, update_episode_status,
    append_jsonl_log, get_episode,
)

logger = logging.getLogger(__name__)


def run_complete(ctx: dict) -> bool:
    """Generate final report and clean up."""
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    ep_dir = PROJECT_ROOT / "episodes" / episode_slug

    log_progress(
        episode_slug, country_ja, "pipeline",
        "step_complete_start",
        "完了レポート生成",
        "8/7",
    )

    # Clear checkpoint
    clear_checkpoint(episode_slug)

    # Update episode status
    update_episode_status(episode_slug, "completed")

    # HTML timeline generation removed as the script is deprecated.

    # Log completion
    log_progress(
        episode_slug, country_ja, "pipeline",
        "pipeline_complete",
        f"エピソード {episode_slug}（{country_ja}）生成完了",
        "8/7",
    )

    append_jsonl_log(
        episode_slug, "pipeline", "pipeline_complete",
        f"Pipeline completed: {episode_slug}",
    )

    # Print final report
    print()
    print("=" * 60)
    print(f"[SUCCESS] エピソード {episode_slug}（{country_ja}）の生成が完了しました！")
    print("=" * 60)
    print()
    print("生成ファイル:")
    for f in sorted(ep_dir.glob("*.md")):
        size = f.stat().st_size
        print(f"   - {f.name} ({size:,} bytes)")
    print()
    print("紙芝居制作フロー（テキスト生成完了後の手順）:")
    print()
    print("   1. 画像生成 (ComfyUI): python src/generate_images.py episodes/{episode_slug}")
    print("   2. 動画生成 (手動): episodes/{episode_slug}/video_prompt.json を参考にKling等で生成")
    print("   3. 音声合成＆AviUtlタイムライン生成: python src/txt2aup2_for_gourmet.py episodes/{episode_slug}/narration.json")
    print()

    return True
