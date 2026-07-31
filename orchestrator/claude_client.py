"""
Claude Code client for the pipeline orchestrator.

Launches Claude Code as a subprocess and sends pipeline commands.
Monitors progress through stdout and status.log.jsonl.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import threading
import time
import queue
from pathlib import Path
from typing import Type, TypeVar, Optional
from pydantic import BaseModel, ValidationError

from .config import PROJECT_ROOT, CLAUDE_AGENTS_DIR
from .state import append_jsonl_log, log_progress

logger = logging.getLogger(__name__)

T = TypeVar('T', bound=BaseModel)


class ClaudeCodeTimeoutError(Exception):
    """Raised when a Claude Code step times out."""
    pass


class ClaudeCodeError(Exception):
    """Raised when Claude Code encounters an error."""
    pass


class ClaudeClient:
    """Manages a Claude Code subprocess for pipeline execution.

    Usage:
        client = ClaudeClient()
        client.launch()
        try:
            result = client.run_step(step_command)
            # ... process result ...
            result = client.run_step(next_step_command)
        finally:
            client.close()
    """

    def __init__(self, project_root: Path | None = None):
        self.project_root = project_root or PROJECT_ROOT
        self.process: subprocess.Popen | None = None
        self._output_buffer: list[str] = []
        self._step_complete = False
        self._output_queue = queue.Queue()
        self._reader_thread = None

    def launch(self) -> None:
        """Verify Claude Code is available."""
        logger.info("Verifying Claude Code installation...")
        self._find_claude_command()
        logger.info("Claude Code is ready.")

    def _spawn_process(self, agent_name: Optional[str] = None, command: Optional[str] = None, output_format: str = "text", json_schema: Optional[str] = None) -> subprocess.Popen:
        """Spawn a new Claude Code process."""
        claude_cmd = self._find_claude_command()
        
        # Only output to debug.log if debug mode is active (logger level is DEBUG)
        if logger.getEffectiveLevel() <= logging.DEBUG:
            debug_log_path = self.project_root / "debug.log"
            claude_cmd.extend(["--debug-file", str(debug_log_path)])
        
        if command is not None:
            # Use argument for print mode
            claude_cmd.extend(["-p", command, "--dangerously-skip-permissions"])
            if output_format != "text":
                claude_cmd.extend(["--output-format", output_format])
            if json_schema:
                claude_cmd.extend(["--json-schema", json_schema])
        else:
            if "-p" not in claude_cmd:
                claude_cmd.append("-p")
            
        if agent_name:
            claude_cmd.extend(["--agent", agent_name])
            
        env = os.environ.copy()
        env["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:8080"
        env["ANTHROPIC_AUTH_TOKEN"] = "dummy"
        
        return subprocess.Popen(
            claude_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            env=env,
            encoding="utf-8",
            text=True,
            cwd=str(self.project_root),
            bufsize=1,
        )

    def _read_stdout(self):
        if not self.process or not self.process.stdout:
            return
        for line in iter(self.process.stdout.readline, ''):
            if not line:
                break
            self._output_queue.put(line)

    def _find_claude_command(self) -> list[str]:
        """Find the Claude Code command."""
        # Try common commands
        for cmd in ["claude", "npx @anthropic-ai/claude-code"]:
            try:
                subprocess.run(
                    cmd.split(),
                    capture_output=True,
                    timeout=5,
                )
                return cmd.split()
            except (subprocess.FileNotFoundError, subprocess.TimeoutExpired):
                continue

        raise RuntimeError(
            "Claude Code not found. Please ensure 'claude' is installed "
            "(npm install -g @anthropic-ai/claude-code)"
        )

    def close(self) -> None:
        """Close the client."""
        pass

    def run_step(self, command: str, timeout: int = 300) -> str:
        """Run a single step and return the output."""
        logger.info("Sending step command (timeout=%ds)...", timeout)

        # Extract agent name from command if present
        agent_match = re.search(r"Use the `?([a-zA-Z0-9_-]+)`? agent", command)
        agent_name = agent_match.group(1) if agent_match else None
        
        process = self._spawn_process(agent_name=agent_name)
        
        # Send the command and close stdin to send EOF
        process.stdin.write(command + "\n\n")
        process.stdin.close()

        # Wait for response
        start_time = time.time()
        output_lines: list[str] = []

        while time.time() - start_time < timeout:
            if process.poll() is not None:
                # Process exited, read remaining output
                for line in process.stdout:
                    output_lines.append(line)
                break

            import select
            import sys
            
            # Non-blocking read
            if sys.platform != "win32":
                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if ready:
                    line = process.stdout.readline()
                    if line: output_lines.append(line)
            else:
                line = process.stdout.readline()
                if line: output_lines.append(line)

            # Check for step completion markers
            if self._is_step_complete(line):
                logger.info("Step completed (%.1fs)", time.time() - start_time)
                break

            # Check for errors
            if self._is_error(line):
                error_msg = self._extract_error(line)
                raise ClaudeCodeError(error_msg)

        result = "\n".join(output_lines)

        # Check timeout
        if time.time() - start_time >= timeout - 2:
            raise ClaudeCodeTimeoutError(
                f"Step timed out after {timeout}s"
            )

        return result

    def run_with_file_watch(
        self,
        command: str,
        watch_file: str,
        min_lines: int = 10,
        timeout: int = 300,
        episode_slug: str = "",
        step_label: str = "",
    ) -> bool:
        """Run a step and watch for output file creation.

        This is the primary method for steps that generate files.

        Args:
            command: Command to send to Claude Code.
            watch_file: Filename to watch for in the episode directory.
            min_lines: Minimum lines in the file before considering it complete.
            timeout: Maximum seconds to wait.
            episode_slug: Episode identifier for logging.
            step_label: Step label for logging.

        Returns:
            True if the file was generated successfully.

        Raises:
            ClaudeCodeTimeoutError: If the file is not generated in time.
        """
        # Extract agent name from command if present
        agent_match = re.search(r"Use the `?([a-zA-Z0-9_-]+)`? agent", command)
        agent_name = agent_match.group(1) if agent_match else None
        
        process = self._spawn_process(agent_name=agent_name)
        
        # Send command and close stdin
        process.stdin.write(command + "\n\n")
        process.stdin.close()

        # Watch for file in background while draining stdout
        start_time = time.time()
        ep_dir = self.project_root / "episodes" / episode_slug
        
        import threading
        
        tokens = {"in": 0, "out": 0}
        
        def drain_stdout():
            for line in process.stdout:
                if line.strip():
                    safe_line = line.strip().encode('cp932', errors='replace').decode('cp932')
                    logger.info("ClaudeCode> %s", safe_line)
                    
                    token_match = re.search(r"Tokens used:\s*(\d+)\s*in,\s*(\d+)\s*out", safe_line)
                    if token_match:
                        tokens["in"] += int(token_match.group(1))
                        tokens["out"] += int(token_match.group(2))
                        
        threading.Thread(target=drain_stdout, daemon=True).start()

        while time.time() - start_time < timeout:
            time.sleep(1.0)

            # Check if file exists and has enough lines
            file_path = ep_dir / watch_file
            if file_path.exists():
                try:
                    line_count = sum(1 for _ in file_path.open(encoding="utf-8"))
                    if line_count >= min_lines:
                        elapsed = time.time() - start_time
                        logger.info(
                            "File %s generated (%d lines) in %.1fs",
                            watch_file, line_count, elapsed,
                        )
                        if episode_slug:
                            if tokens["in"] == 0 and tokens["out"] == 0:
                                tokens["in"] = len(command) // 2
                                try:
                                    tokens["out"] = len(file_path.read_text(encoding="utf-8")) // 2
                                except OSError:
                                    pass
                            log_progress(
                                episode_slug, "", "pipeline",
                                f"output_written",
                                f"{watch_file} generated",
                                step_label,
                                tokens=tokens
                            )
                        return True
                except OSError:
                    pass

            # Check for output_written in JSONL log
            jsonl_path = ep_dir / "status.log.jsonl"
            if jsonl_path.exists():
                try:
                    content = jsonl_path.read_text(encoding="utf-8")
                    if '"phase":"output_written"' in content:
                        elapsed = time.time() - start_time
                        logger.info(
                            "output_written detected in %.1fs", elapsed,
                        )
                        return True
                except OSError:
                    pass

            # Check if process died
            if process.poll() is not None:
                if file_path.exists():
                    line_count = sum(1 for _ in file_path.open(encoding="utf-8"))
                    if process.poll() == 0 or line_count >= min_lines:
                        return True
                raise ClaudeCodeError(
                    f"Claude Code subprocess exited unexpectedly (exit code {process.poll()})"
                )

        raise ClaudeCodeTimeoutError(
            f"File {watch_file} not generated within {timeout}s"
        )



    def run_json_step(
        self,
        command: str,
        schema: Type[T],
        timeout: int = 300,
        max_retries: int = 3,
        episode_slug: str = "",
        step_label: str = "",
        agent_role: str = "generator",
    ) -> T:
        """Run a step and return the parsed JSON matching the Pydantic schema."""
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
        
        full_command = (
            f"{command}\n\n"
            f"【重要指示】\n"
            f"必ず以下のJSONスキーマに従ったJSON文字列のみを出力してください。\n"
            f"余計な挨拶やMarkdownブロック (```json など) は不要ですが、もし付与する場合は必ず正しいJSONを含めてください。\n\n"
            f"【JSON Schema】\n{schema_json}\n"
        )
        
        max_retries = 3
        for attempt in range(max_retries):
            # Record attempt in DB and Optional logging
            if episode_slug:
                from orchestrator.state import set_generation_attempt
                
                # We need episode_id, which we don't directly have in run_json_step kwargs,
                # but we can look it up or use a helper that updates by slug.
                # Wait, getting episode_id by slug is needed. Let's do it via state module.
                from orchestrator.state import _get_conn
                conn = _get_conn()
                try:
                    ep_row = conn.execute("SELECT id FROM episodes WHERE episode_slug = ?", (episode_slug,)).fetchone()
                    if ep_row:
                        step_map = {"1/7": "design", "2/7": "narration", "3/7": "image_prompt", "4/7": "video_prompt", "5/7": "bgm", "6/7": "youtube"}
                        base_step = step_map.get(step_label.split(" ")[0], "unknown")
                        actual_step = f"{base_step}_review" if "reviewer" in agent_role else base_step
                        set_generation_attempt(ep_row["id"], step_name=actual_step, attempt=attempt + 1)
                except Exception:
                    pass
                finally:
                    conn.close()
                    
                log_progress(
                    episode_slug, "", agent_role,
                    f"json_generation",
                    f"Start (Attempt {attempt + 1})",
                    step_label
                )
            
            # Extract agent name from command if present
            agent_match = re.search(r"Use the `?([a-zA-Z0-9_-]+)`? agent", command)
            agent_name = agent_match.group(1) if agent_match else None
            
            # Pass schema and request json format to claude natively
            schema_arg = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            process = self._spawn_process(agent_name=agent_name, command=full_command, output_format="json", json_schema=schema_arg)
            process.stdin.close()
            
            start_time = time.time()
            output_lines = []
            tokens = {"in": 0, "out": 0}
            
            import threading
            
            def drain_stdout():
                for line in process.stdout:
                    if line.strip():
                        safe_line = line.strip().encode('cp932', errors='replace').decode('cp932')
                        logger.debug("ClaudeCode> %s", safe_line)
                        output_lines.append(safe_line)
                        
                        token_match = re.search(r"Tokens used:\s*(\d+)\s*in,\s*(\d+)\s*out", safe_line)
                        if token_match:
                            tokens["in"] += int(token_match.group(1))
                            tokens["out"] += int(token_match.group(2))
                            
            threading.Thread(target=drain_stdout, daemon=True).start()
            
            try:
                while time.time() - start_time < timeout:
                    time.sleep(1.0)
                    if process.poll() is not None:
                        break
                        
                if process.poll() is None:
                    raise ClaudeCodeTimeoutError(f"JSON Step timed out after {timeout}s")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                
            result_str = "\n".join(output_lines)
            
            try:
                data = None
                try:
                    # Parse native claude json payload
                    claude_result = json.loads(result_str)
                    if isinstance(claude_result, dict):
                        if "status" in claude_result:
                            if claude_result["status"] != "SUCCESS":
                                raise ValueError(f"claude execution failed: {claude_result.get('error')}")
                            
                            # Set precise token usage directly from claude output!
                            usage = claude_result.get("usage", {})
                            if "input_tokens" in usage: tokens["in"] = usage["input_tokens"]
                            if "output_tokens" in usage: tokens["out"] = usage["output_tokens"]
                            
                            if "structured_output" in claude_result and claude_result["structured_output"]:
                                data = claude_result["structured_output"]
                            else:
                                # Fallback if no structured output was parsed
                                result_str = claude_result.get("response", "")
                        elif claude_result.get("type") == "result" or "result" in claude_result:
                            if claude_result.get("is_error"):
                                raise ValueError(f"claude execution failed: {claude_result.get('error')}")
                                
                            usage = claude_result.get("usage", {})
                            if "input_tokens" in usage: tokens["in"] = usage["input_tokens"]
                            if "output_tokens" in usage: tokens["out"] = usage["output_tokens"]
                            
                            if "structured_output" in claude_result and claude_result["structured_output"]:
                                data = claude_result["structured_output"]
                            else:
                                result_str = claude_result.get("result", "")
                except json.JSONDecodeError:
                    pass

                if data is None:
                    # Fallback to regex extraction
                    match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', result_str)
                    if match:
                        json_str = match.group(1)
                    else:
                        json_str = result_str
                        
                    start_idx = json_str.find('{')
                    end_idx = json_str.rfind('}')
                    if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                        json_str = json_str[start_idx:end_idx+1]
                    else:
                        raise ValueError("No JSON object found in output")
                        
                    data = json.loads(json_str)
                    
                validated_data = schema(**data)
                
                # Log success and tokens if episode_slug is provided
                # Fallback token estimation if local LLM didn't output tokens
                if tokens["in"] == 0 and tokens["out"] == 0:
                    tokens["in"] = len(full_command) // 2
                    tokens["out"] = len("\n".join(output_lines)) // 2

                if episode_slug:
                    log_progress(
                        episode_slug, "", agent_role,
                        f"json_parsed",
                        f"Successfully generated JSON (Attempt {attempt + 1})",
                        step_label,
                        tokens=tokens
                    )
                    
                # Pretty print the final JSON result
                try:
                    pretty_json = json.dumps(validated_data.model_dump(), indent=2, ensure_ascii=False)
                    logger.info("Generated JSON Result:\n%s", pretty_json)
                except Exception as e:
                    logger.debug("Could not pretty print JSON: %s", e)
                    
                return validated_data
            except (json.JSONDecodeError, ValueError, Exception) as e:
                logger.error("JSON parse/validation failed on attempt %d: %s", attempt + 1, e)
                if attempt == max_retries - 1:
                    raise ClaudeCodeError(f"Failed to generate valid JSON after {max_retries} attempts: {e}")
                    
        raise ClaudeCodeError("Unexpected exit from run_json_step loop")

    def _read_line_with_timeout(
        self, fileobj, timeout: float = 2.0
    ) -> Optional[str]:
        """Read a line from a file object with a timeout."""
        try:
            return self._output_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _is_step_complete(self, line: str) -> bool:
        """Check if a line indicates step completion."""
        markers = [
            "PIPELINE_STEP_COMPLETE",
            "STEP_DONE",
            "step completed",
        ]
        return any(m in line for m in markers)

    def _is_error(self, line: str) -> bool:
        """Check if a line indicates an error."""
        markers = [
            "ERROR",
            "error:",
            "failed",
            "exception",
        ]
        return any(m.lower() in line.lower() for m in markers)

    def _extract_error(self, line: str) -> str:
        """Extract error message from a line."""
        # Try to extract a meaningful error message
        match = re.search(r"(error|failed|exception):\s*(.+)", line, re.IGNORECASE)
        if match:
            return match.group(2).strip()
        return line.strip()


# ---------------------------------------------------------------------------
# Context manager usage
# ---------------------------------------------------------------------------

class ClaudeClientSession:
    """Context manager for Claude Code lifecycle."""

    def __init__(self, project_root: Path | None = None):
        self._client = ClaudeClient(project_root)

    def __enter__(self) -> ClaudeClient:
        self._client.launch()
        return self._client

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._client.close()
        return False
