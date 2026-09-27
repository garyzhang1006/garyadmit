"""LLM backend that shells out to the Claude Code CLI (`claude -p`).

Using the CLI means reviews run on the user's Claude subscription, so there is
no API key to manage and no per-call bill. Every call runs in `--safe-mode`
with all tools disabled, so the user's hooks, plugins, MCP servers, and
CLAUDE.md files never see (or leak) the essay and never pollute the prompt.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

DEFAULT_MODEL = os.environ.get("GARYADMIT_MODEL", "opus")
FAST_MODEL = os.environ.get("GARYADMIT_FAST_MODEL", "sonnet")


class LLMError(RuntimeError):
    pass


# Tests swap this for a fake so the suite never calls a real model.
_backend: Callable[..., dict] | None = None
_usage_lock = threading.Lock()
usage = {"calls": 0, "api_equivalent_usd": 0.0}


def set_backend(fn: Callable[..., dict] | None) -> None:
    global _backend
    _backend = fn


def _clean_env() -> dict:
    env = dict(os.environ)
    # An exported ANTHROPIC_API_KEY makes the CLI bill that key instead of the
    # subscription, which would break the "free" promise.
    if os.environ.get("GARYADMIT_ALLOW_API_KEY") != "1":
        env.pop("ANTHROPIC_API_KEY", None)
    return env


def ask_json(
    system: str,
    prompt: str,
    schema: dict,
    *,
    model: str | None = None,
    effort: str | None = None,
    timeout: int = 420,
    retries: int = 2,
) -> dict:
    """Run one structured-output call and return the validated JSON object."""
    model = model or DEFAULT_MODEL
    if _backend is not None:
        return _backend(system=system, prompt=prompt, schema=schema, model=model, effort=effort)

    exe = shutil.which("claude")
    if not exe:
        raise LLMError(
            "The `claude` CLI was not found on PATH. Install Claude Code "
            "(https://docs.claude.com/en/docs/claude-code) and log in with `claude` once."
        )
    cmd = [
        exe, "-p",
        "--safe-mode",
        "--tools", "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system,
        "--json-schema", json.dumps(schema),
    ]
    if effort:
        cmd += ["--effort", effort]

    last_err = ""
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(4 * attempt)
        # A neutral cwd keeps the CLI from picking up any project context.
        with tempfile.TemporaryDirectory(prefix="garyadmit-") as cwd:
            try:
                proc = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True,
                    timeout=timeout, cwd=cwd, env=_clean_env(),
                )
            except subprocess.TimeoutExpired:
                last_err = f"claude timed out after {timeout}s"
                continue
        out = proc.stdout.strip()
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            last_err = f"exit {proc.returncode}; stdout={out[:400]!r}; stderr={proc.stderr.strip()[:400]!r}"
            continue
        with _usage_lock:
            usage["calls"] += 1
            usage["api_equivalent_usd"] += float(data.get("total_cost_usd") or 0)
        if data.get("is_error") or not isinstance(data.get("structured_output"), dict):
            last_err = f"claude returned an error: {str(data.get('result') or data.get('subtype'))[:400]}"
            continue
        return data["structured_output"]
    raise LLMError(f"Claude call failed after {retries + 1} attempts: {last_err}")
