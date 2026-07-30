"""
Utility functions for the pipeline orchestrator.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def slugify(text: str) -> str:
    """Convert text to a safe slug for directory names.

    For ASCII input, returns as-is (lowercased).
    For Japanese input, keeps the original characters (they work in filenames).

    Examples:
        香川 -> kagawa (if romanized) or 香川 (if Japanese)
        fukuoka -> fukuoka
    """
    text = text.strip().lower()
    # Replace spaces and common separators with underscores
    text = re.sub(r"[\s]+", "_", text)
    # Remove characters that are problematic in filenames (but keep Japanese)
    text = re.sub(r"[^a-zA-Z0-9_぀-ゟ゠-ヿ一-鿿\-]", "", text)
    # Collapse multiple underscores
    text = re.sub(r"_+", "_", text)
    return text.strip("_")



def parse_verdict(review_file: Path) -> str:
    """Parse the Verdict from a review file.

    Returns one of: "GO", "Revise", "GO with minor revisions"
    """
    if not review_file.exists():
        return "unknown"

    content = review_file.read_text(encoding="utf-8")

    # Look for ## Verdict section
    verdict_match = re.search(
        r"##\s*Verdict\s*\n\s*(.+)",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    if verdict_match:
        verdict = verdict_match.group(1).strip().lower()
        if "go" in verdict and "revise" not in verdict:
            return "GO"
        elif "revise" in verdict:
            return "Revise"
        elif "go" in verdict:
            return "GO with minor revisions"

    return "unknown"


def has_critical_issues(review_file: Path) -> bool:
    """Check if a review file has critical issues."""
    if not review_file.exists():
        return False

    content = review_file.read_text(encoding="utf-8")

    # Look for ## Critical issues section
    crit_match = re.search(
        r"##\s*Critical issues\s*\n(.*?)(?=\n##|\Z)",
        content,
        re.DOTALL,
    )
    if crit_match:
        section = crit_match.group(1).strip()
        return len(section) > 0

    return False


def count_words(text: str) -> int:
    """Count words in text (Japanese-compatible).

    For Japanese text, counts characters since word boundaries are ambiguous.
    """
    # If mostly Japanese, count characters
    jp_chars = sum(1 for c in text if "぀" <= c <= "ゟ" or
                              "゠" <= c <= "ヿ" or
                              "一" <= c <= "鿿")
    if jp_chars > len(text) * 0.3:
        return jp_chars
    # Otherwise count whitespace-separated words
    return len(text.split())


def check_word_count(output_file: Path, min_words: int, max_words: int | None = None) -> bool:
    """Check if output file meets word count requirements."""
    if not output_file.exists():
        return False

    content = output_file.read_text(encoding="utf-8")
    words = count_words(content)

    if words < min_words:
        logger.warning(
            "Word count %d < minimum %d for %s", words, min_words, output_file
        )
        return False

    if max_words is not None and words > max_words:
        logger.warning(
            "Word count %d > maximum %d for %s", words, max_words, output_file
        )
        return False

    return True


def read_file_lines(filepath: Path, min_lines: int = 0) -> str | None:
    """Read a file and return its content, or None if it doesn't meet min_lines."""
    if not filepath.exists():
        return None
    content = filepath.read_text(encoding="utf-8")
    if min_lines > 0:
        line_count = sum(1 for line in content.split("\n") if line.strip())
        if line_count < min_lines:
            return None
    return content


def generate_claude_command(
    step_name: str,
    agent_name: str,
    output_file: str,
    input_files: list[str],
    episode_slug: str,
    instructions: str = "",
    is_review: bool = False,
    is_revision: bool = False,
) -> str:
    """Generate a command to send to Claude Code for a pipeline step.

    Args:
        step_name: Step identifier (e.g., "design")
        agent_name: Claude Code agent name (e.g., "kamishibai-generator")
        output_file: Output filename
        input_files: List of input file paths
        episode_slug: Episode identifier
        instructions: Additional instructions
        is_review: Whether this is a review step
        is_revision: Whether this is a revision (auto-fix) step

    Returns:
        Command string to send to Claude Code
    """
    inputs_str = "\n".join(f"- {f}" for f in input_files)

    mode = "generate"
    if is_review:
        mode = "review"
    elif is_revision:
        mode = "revise"

    return f"""# Pipeline Step: {step_name}

## Mode: {mode}

You are executing step `{step_name}` of the kamishibai pipeline.

## Agent: {agent_name}

## Task
Use the `{agent_name}` agent to {f"review and provide verdict" if is_review else f"revise based on review feedback" if is_revision else "generate"}.

## Input Files
{inputs_str}

## Output
Save result as: `episodes/{episode_slug}/{output_file}`

## Guidelines
- Read all input files first
- Follow the agent's system prompt (loaded from .claude/agents/)
- For generation: create the output file with proper format
- For review: analyze the output and provide Verdict (GO / Revise)
- For revision: apply review feedback to the output file
- Do NOT ask the user questions — this is an autonomous pipeline
- Report progress briefly after completion

{instructions}

## Important
- Use the Agent tool with run_in_background: true to spawn the {agent_name} agent
- The agent's instructions are in .claude/agents/ matching this step
- After the agent completes, verify the output file exists
- Log progress using: bash .claude/lib/log_progress.sh {episode_slug} "" pipeline "{step_name}_{'review' if is_review else 'write'}" "{mode} complete" ""
"""
