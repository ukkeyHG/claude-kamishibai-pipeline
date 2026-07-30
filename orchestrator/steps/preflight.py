"""Step 0: Preflight validation."""
from __future__ import annotations

from pathlib import Path

from ..config import PROJECT_ROOT, SERIES_BIBLE, CLAUDE_AGENTS_DIR
from ..state import log_progress


def run_preflight(ctx: dict) -> bool:
    """Validate that the project root is correct.

    Checks for required files/directories:
    - series_bible.md
    - .claude/agents/
    """
    episode_slug = ctx["episode_slug"]
    country_ja = ctx["country_ja"]

    log_progress(
        episode_slug, country_ja, "pipeline",
        "preflight_start",
        "プリフライト検証開始",
        "0/7",
    )

    required = [
        SERIES_BIBLE,
        CLAUDE_AGENTS_DIR,
    ]

    missing = [str(r.relative_to(PROJECT_ROOT)) for r in required if not r.exists()]

    if missing:
        log_progress(
            episode_slug, country_ja, "pipeline",
            "preflight_failed",
            f"プロジェクトルート検証失敗: {', '.join(missing)}",
            "0/7",
        )
        print(f"\n[!] プロジェクトルートで起動されていません。")
        print(f"現在の cwd: {PROJECT_ROOT}")
        print(f"missing: {', '.join(missing)}")
        print("paper-kamishibai project root (series_bible.md and .claude/ must exist) not found.")
        return False

    log_progress(
        episode_slug, country_ja, "pipeline",
        "preflight_done",
        "プリフライト検証完了（プロジェクトルート確認済み）",
        "0/7",
    )
    return True
