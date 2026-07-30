#!/usr/bin/env python3
"""
Main entry point for the kamishibai pipeline orchestrator.

Usage:
    python -m orchestrator.main 香川          # New episode
    python -m orchestrator.main 香川 --resume  # Resume previous
    python -m orchestrator.main --help         # Show help
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .pipeline import run_pipeline
from .config import PROJECT_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Kamishibai Pipeline Orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m orchestrator.main 香川          # Generate new episode
  python -m orchestrator.main 香川 --resume  # Resume interrupted run
  python -m orchestrator.main fukuoka       # English prefecture name
        """,
    )
    parser.add_argument(
        "country",
        nargs="?",
        default=None,
        help="Prefecture/country name (Japanese or English)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume a previous interrupted run",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root directory (default: parent of orchestrator/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if not args.country:
        parser.print_help()
        return 1

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Resolve project root
    project_root = args.project_root or PROJECT_ROOT

    print("=" * 60)
    print("  出張キャリアウーマンご当地グルメ - Pipeline Orchestrator")
    print("=" * 60)
    print()
    print(f"  Country: {args.country}")
    print(f"  Project: {project_root}")
    print(f"  Resume:  {'Yes' if args.resume else 'No'}")
    print()

    try:
        success = run_pipeline(
            country=args.country,
            project_root=project_root,
            resume=args.resume,
        )
        return 0 if success else 1

    except KeyboardInterrupt:
        print("\n\n⚠️ User interrupted (Ctrl+C)")
        return 130
    except Exception as e:
        logging.exception("Unhandled error")
        print(f"\n[!] Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
