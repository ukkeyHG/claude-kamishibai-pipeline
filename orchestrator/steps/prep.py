"""Step 1-A: Preparation - create episode directory."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from ..config import EPISODES_DIR, PROJECT_ROOT, determine_next_episode_number
from ..state import log_progress, set_checkpoint, append_jsonl_log


def run_prep(ctx: dict) -> bool:
    """Create the episode directory and subdirectories.

    Steps:
    1. Determine episode number (NN)
    2. Create episode directory: episodes/ep<NN>_<slug>/
    3. Create subdirectories: audio, images_raw, images, videos, bgm
    4. Clean up empty stubs from previous failed runs
    """
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]
    nn = ctx["nn"]
    slug = ctx["slug"]

    ep_dir = EPISODES_DIR / episode_slug

    # Clean up empty stubs from previous failed runs
    _cleanup_stubs(nn)

    # Create directories
    subdirs = ["audio", "images_raw", "images", "videos", "bgm"]
    ep_dir.mkdir(parents=True, exist_ok=True)
    for subdir in subdirs:
        (ep_dir / subdir).mkdir(exist_ok=True)

    # Log
    log_progress(
        episode_slug, country_ja, "pipeline",
        "pipeline_start",
        f"新エピソード生成パイプライン開始 ({country_ja})",
        "0/7",
    )
    log_progress(
        episode_slug, country_ja, "pipeline",
        "prep_done",
        f"準備フェーズ完了 (ep{nn}_{slug})",
        "0/7",
    )

    append_jsonl_log(
        episode_slug, "pipeline", "prep_done",
        f"Episode directory created: {ep_dir}",
    )

    print(f"[準備] ep{nn}_{slug} として開始。")
    return True


def _cleanup_stubs(nn: str) -> None:
    """Clean up empty stub directories from previous failed runs.

    Checks the directory immediately before the new episode number.
    If it exists but has no 01_kamishibai.md and minimal log entries,
    removes it as an empty stub.
    """
    prev_nn = str(int(nn) - 1).zfill(2)

    # Find directories matching ep<prev_nn>_
    for d in EPISODES_DIR.iterdir():
        if not d.is_dir():
            continue
        if not re.match(rf"^ep{re.escape(prev_nn)}_", d.name):
            continue

        # Check if it's an empty stub
        kamishibai_file = d / "01_kamishibai.md"
        jsonl_file = d / "status.log.jsonl"

        if kamishibai_file.exists():
            continue  # Has content, not a stub

        # Check log line count
        log_lines = 0
        last_phase = ""
        if jsonl_file.exists():
            lines = jsonl_file.read_text(encoding="utf-8").strip().split("\n")
            log_lines = len([l for l in lines if l.strip()])
            # Get last phase
            for line in reversed(lines):
                if '"phase"' in line:
                    phase_match = re.search(r'"phase":"([^"]+)"', line)
                    if phase_match:
                        last_phase = phase_match.group(1)
                    break

        # Remove if minimal activity (<=2 lines and only pipeline_start or prep_done)
        if log_lines <= 2 and last_phase in ("pipeline_start", "prep_done", ""):
            print(f"[クリーンアップ] 空スタブを削除: {d.name}")
            import shutil
            shutil.rmtree(d)
            break
