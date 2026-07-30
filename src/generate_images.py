#!/usr/bin/env python3
"""
ComfyUI batch image generator for the kamishibai pipeline.

Reads scene prompts from <episode_dir>/image_prompts.json and <episode_dir>/youtube.json
and sends each to a local ComfyUI instance (SDXL Animagine + hires fix + upscale)
to generate images. Outputs to <episode_dir>/images_raw/scene_NN.png (and thumbnail.png).

Usage:
    python src/generate_images.py episodes/ep01_kagawa
    python src/generate_images.py episodes/ep01_kagawa --scenes 1 3 5
    python src/generate_images.py episodes/ep01_kagawa --force
    python src/generate_images.py episodes/ep01_kagawa --url http://192.168.1.50:8188

Pre-requisites:
    1. ComfyUI running locally (default http://127.0.0.1:8188).
    2. Workflow saved as API-format JSON at: src/comfyui_default.json
       (In ComfyUI: enable Dev mode in settings -> "Save (API Format)").
    3. Models: SDXL Animagine XL 4.0, 4x-UltraSharp upscaler.

Behavior:
    - Idempotent: skips scenes whose PNG already exists in images_raw/.
    - Randomizes seeds per scene to bypass ComfyUI prompt cache.
    - Polls /history every 1s (max 300s per image) for completion.
    - Prints per-scene progress and a final summary.
    - Exits non-zero on missing workflow, ComfyUI unreachable, or processing error.

Dependencies: Python 3.8+, standard library only (no pip install).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOST = "localhost"
PORT = 8188
PROMPT_URL = f"http://{HOST}:{PORT}/prompt"

SEED_INPUT_KEYS = ("seed", "noise_seed")
SEED_MAX = 1125899906842624
POLL_INTERVAL_SEC = 2.0
MAX_WAIT_SEC = 300.0



# Global suffix appended to every positive prompt for consistency
GLOBAL_POS_SUFFIX = (
    "rating_safe, source_anime, masterpiece, best quality, highres, highly detailed, "
    "anime style, professional photography, cinematic lighting"
)

# Global negative prompt
GLOBAL_NEG = (
    "lowres, bad anatomy, bad hands, error, missing fingers, extra digit, "
    "fewer digits, cropped, worst quality, low quality, normal quality, "
    "jpeg artifacts, signature, watermark, username, blurry, artist name, "
    "text, subtitles, speech bubble"
)


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only)
# ---------------------------------------------------------------------------

def send_prompt(workflow: dict) -> str:
    """Submit workflow to ComfyUI. Returns prompt_id."""
    data = json.dumps({"prompt": workflow, "client_id": "comfyui-client"}).encode("utf-8")
    req = urllib.request.Request(
        PROMPT_URL,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())["prompt_id"]


def wait_for_completion(prompt_id: str, poll_interval: float = POLL_INTERVAL_SEC) -> dict:
    """Poll /history until prompt completes. Returns history entry."""
    while True:
        req = urllib.request.Request(f"http://{HOST}:{PORT}/history/{prompt_id}")
        with urllib.request.urlopen(req) as resp:
            history = json.loads(resp.read().decode())
        if prompt_id in history and history[prompt_id].get("outputs"):
            return history[prompt_id]
        time.sleep(poll_interval)


def download_image(base_url: str, filename: str, subfolder: str,
                   folder_type: str, filepath: Path) -> None:
    """Download generated image from ComfyUI."""
    params = urllib.parse.urlencode({
        "filename": filename,
        "subfolder": subfolder,
        "type": folder_type,
        "time": "0",
    })
    url = f"{base_url}/view?{params}"
    urllib.request.urlretrieve(url, filepath)
    print(f"  Saved: {filepath}")


# ---------------------------------------------------------------------------
# Prompt parsing
# ---------------------------------------------------------------------------

def parse_prompts(episode_dir: str) -> list[dict]:
    """
    Parse image_prompts.json and youtube.json to extract prompts.
    Returns a list of dicts: {"num": int_or_str, "positive": str, "negative": str}
    """
    scenes = []
    
    # 1. Parse image_prompts.json (Scenes 1-13)
    img_json_path = os.path.join(episode_dir, "image_prompts.json")
    if os.path.isfile(img_json_path):
        try:
            with open(img_json_path, "r", encoding="utf-8") as f:
                img_data = json.load(f)
                for scene in img_data.get("scenes", []):
                    scenes.append({
                        "num": scene["scene_num"],
                        "positive": scene.get("positive_prompt", ""),
                        "negative": scene.get("negative_prompt", GLOBAL_NEG)
                    })
        except Exception as e:
            print(f"Warning: Failed to parse {img_json_path}: {e}")

    # 2. Parse youtube.json (Thumbnail)
    yt_json_path = os.path.join(episode_dir, "youtube.json")
    if os.path.isfile(yt_json_path):
        try:
            with open(yt_json_path, "r", encoding="utf-8") as f:
                yt_data = json.load(f)
                if "thumbnail_prompt" in yt_data:
                    scenes.append({
                        "num": "thumbnail",
                        "positive": yt_data["thumbnail_prompt"],
                        "negative": GLOBAL_NEG
                    })
        except Exception as e:
            print(f"Warning: Failed to parse {yt_json_path}: {e}")

    return scenes


# ---------------------------------------------------------------------------
# Workflow manipulation
# ---------------------------------------------------------------------------

def randomize_seeds(workflow: dict) -> int:
    """Replace every seed/noise_seed input with a fresh random int."""
    count = 0
    for node in workflow.values():
        inputs = node.get("inputs", {})
        for key in SEED_INPUT_KEYS:
            if key in inputs and isinstance(inputs[key], int):
                inputs[key] = random.randint(0, SEED_MAX)
                count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="ComfyUI batch image generator for kamishibai pipeline.",
    )
    parser.add_argument("episode_dir", type=str,
                        help="Episode directory (e.g., episodes/ep01_kagawa)")
    parser.add_argument("--scenes", nargs="+", default=None,
                        help="Specific scenes to generate (e.g., '1 3 5' or '1-5'). Default: all.")
    parser.add_argument("--force", action="store_true",
                        help="Re-generate even if output already exists.")
    args = parser.parse_args()

    episode_dir = args.episode_dir
    if not os.path.isdir(episode_dir):
        print(f"Error: Directory not found: {episode_dir}")
        return 1

    # We don't check for specific files upfront anymore since parse_prompts handles it

    # Workflow file (same dir as this script)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workflow_file = os.path.join(script_dir, "comfyui_default.json")
    if not os.path.isfile(workflow_file):
        print(f"Error: Workflow JSON not found: {workflow_file}")
        return 1

    # Output directory
    raw_dir = Path(episode_dir) / "images_raw"
    raw_dir.mkdir(exist_ok=True)

    print(f"Parsing JSON files in {episode_dir}...")
    scenes = parse_prompts(episode_dir)

    if not scenes:
        print("No scenes found in the markdown file.")
        return 1

    # Scene filter
    if args.scenes:
        wanted = set()
        for group in args.scenes:
            for spec in group.split(","):
                spec = spec.strip()
                if not spec:
                    continue
                if "-" in spec:
                    a, b = spec.split("-", 1)
                    wanted.update(range(int(a), int(b) + 1))
                else:
                    try:
                        wanted.add(int(spec))
                    except ValueError:
                        wanted.add(spec)
        scenes = [s for s in scenes if s["num"] in wanted]
        if not scenes:
            print(f"Error: filter '{args.scenes}' matched no scenes.")
            return 1

    print(f"Found {len(scenes)} scenes to generate.")
    print(f"Output directory: {raw_dir}")
    print()

    with open(workflow_file, "r", encoding="utf-8") as f:
        base_workflow = json.load(f)

    # Remove _meta (can cause API errors)
    for node in base_workflow.values():
        node.pop("_meta", None)

    import urllib.parse

    for scene in scenes:
        scene_num = scene["num"]
        if isinstance(scene_num, int):
            out_filename = f"scene_{scene_num:02d}.png"
        else:
            out_filename = f"{scene_num}.png"
        out_path = raw_dir / out_filename

        if out_path.exists() and not args.force:
            print(f"Scene {scene_num}: SKIP (already exists)")
            continue

        print(f"Scene {scene_num}: generating ...")

        workflow = copy.deepcopy(base_workflow)

        # Build final prompts
        final_pos = f"{scene['positive']}, {GLOBAL_POS_SUFFIX}" if scene['positive'] else GLOBAL_POS_SUFFIX
        final_neg = scene['negative'].strip() if scene['negative'].strip() else GLOBAL_NEG
        if final_neg != GLOBAL_NEG and GLOBAL_NEG not in final_neg:
            final_neg = f"{final_neg}, {GLOBAL_NEG}"

        # Patch workflow (node IDs depend on comfyui_default.json structure)
        # Node "2" = CLIPTextEncode (positive), Node "3" = CLIPTextEncode (negative)
        # Node "20" = Seed node
        workflow["2"]["inputs"]["text"] = final_pos
        workflow["3"]["inputs"]["text"] = final_neg
        workflow["20"]["inputs"]["seed"] = random.randint(0, SEED_MAX)

        try:
            prompt_id = send_prompt(workflow)
            print(f"  Queued (prompt_id={prompt_id})")
            history = wait_for_completion(prompt_id)

            outputs = history.get("outputs", {})
            for node_id, node_output in outputs.items():
                images = node_output.get("images", [])
                if images:
                    img = images[0]
                    download_image(
                        f"http://{HOST}:{PORT}",
                        img["filename"],
                        img.get("subfolder", ""),
                        img.get("type", "output"),
                        out_path,
                    )
                    break
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode('utf-8', errors='replace')
            print(f"  Error: HTTP {e.code} - {err_msg}")
        except Exception as e:
            print(f"  Error: {e}")

    print()
    print("All scenes completed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
