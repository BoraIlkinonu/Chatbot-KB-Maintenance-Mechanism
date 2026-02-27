"""
LLM client abstraction: CLI subprocess and Anthropic SDK backends.

Auto-detects the best available backend. CLI for local development,
SDK for GitHub Actions CI.
"""

import base64
import json
import mimetypes
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Protocol


class LLMClient(Protocol):
    """Protocol for LLM backends."""

    calls_made: int
    budget: int

    def is_available(self) -> bool: ...
    def has_budget(self) -> bool: ...
    def call(self, prompt: str) -> dict: ...
    def image_call(self, prompt: str, image_path: str) -> dict: ...


class CliClient:
    """Claude CLI subprocess client (local development)."""

    def __init__(self, model: str = "sonnet", timeout: int = 300,
                 max_retries: int = 3, budget: int = 0):
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.budget = budget  # 0 = unlimited
        self.calls_made = 0
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            env = self._clean_env()
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True, text=True, timeout=10, env=env,
            )
            self._available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._available = False
        return self._available

    def has_budget(self) -> bool:
        return self.budget == 0 or self.calls_made < self.budget

    def call(self, prompt: str) -> dict:
        if not self.has_budget():
            raise RuntimeError(f"LLM budget exhausted ({self.calls_made}/{self.budget})")

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._single_call(prompt)
                self.calls_made += 1
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"All {self.max_retries} attempts failed: {last_error}")

    def image_call(self, prompt: str, image_path: str) -> dict:
        """Send an image + text prompt to the LLM via CLI.

        Encodes the image as base64 inline in the prompt since the CLI
        doesn't have a native --image flag for multimodal input.
        """
        if not self.has_budget():
            raise RuntimeError(f"LLM budget exhausted ({self.calls_made}/{self.budget})")

        img_path = Path(image_path)
        img_data = base64.b64encode(img_path.read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(image_path)[0] or "image/png"

        # Embed as data URI in markdown-style image reference
        multimodal_prompt = (
            f"[Image (base64-encoded {mime}, filename: {img_path.name})]\n"
            f"data:{mime};base64,{img_data}\n\n"
            f"{prompt}"
        )

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._single_call(multimodal_prompt)
                self.calls_made += 1
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"All {self.max_retries} image_call attempts failed: {last_error}")

    def _single_call(self, prompt: str) -> dict:
        cmd = ["claude", "-p", "--model", self.model, "--output-format", "json"]
        env = self._clean_env()
        result = subprocess.run(
            cmd, input=prompt,
            capture_output=True, text=True,
            timeout=self.timeout, encoding="utf-8", env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"CLI exit {result.returncode}: {result.stderr[:300]}")
        return _extract_json(result.stdout)

    def _clean_env(self):
        env = {**os.environ}
        env.pop("CLAUDECODE", None)
        return env


class SdkClient:
    """Anthropic SDK client (CI / GitHub Actions)."""

    def __init__(self, model: str = "claude-sonnet-4-6", timeout: int = 300,
                 max_retries: int = 3, budget: int = 0):
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.budget = budget
        self.calls_made = 0
        self._client = None

    def is_available(self) -> bool:
        if "ANTHROPIC_API_KEY" not in os.environ:
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def has_budget(self) -> bool:
        return self.budget == 0 or self.calls_made < self.budget

    def _ensure_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()

    def call(self, prompt: str) -> dict:
        if not self.has_budget():
            raise RuntimeError(f"LLM budget exhausted ({self.calls_made}/{self.budget})")

        self._ensure_client()

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=8192,
                    messages=[{"role": "user", "content": prompt}],
                )
                self.calls_made += 1
                text = response.content[0].text
                return _extract_json(text)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"All {self.max_retries} attempts failed: {last_error}")

    def image_call(self, prompt: str, image_path: str) -> dict:
        """Send an image + text prompt via the Anthropic SDK multimodal API."""
        if not self.has_budget():
            raise RuntimeError(f"LLM budget exhausted ({self.calls_made}/{self.budget})")

        self._ensure_client()

        img_path = Path(image_path)
        img_data = base64.b64encode(img_path.read_bytes()).decode("ascii")
        mime = mimetypes.guess_type(image_path)[0] or "image/png"

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime,
                                    "data": img_data,
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }],
                )
                self.calls_made += 1
                text = response.content[0].text
                return {"description": text}
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"All {self.max_retries} image_call attempts failed: {last_error}")


def _extract_json(text: str) -> dict:
    """Extract JSON from LLM output with 3 fallback strategies."""
    # Strategy 1: Direct parse
    try:
        parsed = json.loads(text)
        # Handle CLI wrapper format {"type":"result", "result": "...", ...}
        if isinstance(parsed, dict) and "result" in parsed:
            inner = parsed["result"]
            if isinstance(inner, dict):
                return inner
            if isinstance(inner, str):
                # Try parsing the inner result string as JSON
                extracted = _extract_json_from_text(inner)
                if extracted is not None:
                    return extracted
        # If no result key, or result wasn't useful, check if parsed itself
        # looks like a judgment (has field keys, not CLI metadata)
        if isinstance(parsed, dict) and "type" not in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # Fall through to text-based extraction on the raw string
    extracted = _extract_json_from_text(text)
    if extracted is not None:
        return extracted

    raise RuntimeError(f"Could not extract JSON from output: {text[:200]}")


def _extract_json_from_text(text: str) -> dict | None:
    """Extract JSON dict from a text string using code blocks or brace-finding."""
    # Strategy A: Direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Strategy B: Code block extraction
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Strategy C: Brace-finding
    start = text.find('{')
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start:i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        break

    return None


def create_client(backend: str = "auto", budget: int = 0) -> CliClient | SdkClient:
    """Create the best available LLM client.

    Args:
        backend: "cli", "sdk", or "auto" (detect best available)
        budget: Maximum number of LLM calls allowed
    """
    if backend == "cli":
        client = CliClient(budget=budget)
        if not client.is_available():
            raise RuntimeError("Claude CLI not available")
        return client

    if backend == "sdk":
        client = SdkClient(budget=budget)
        if not client.is_available():
            raise RuntimeError("Anthropic SDK not available (missing API key or package)")
        return client

    # Auto-detect: prefer CLI locally, SDK in CI
    cli = CliClient(budget=budget)
    if cli.is_available():
        return cli

    sdk = SdkClient(budget=budget)
    if sdk.is_available():
        return sdk

    raise RuntimeError(
        "No LLM backend available. Install Claude CLI or set ANTHROPIC_API_KEY."
    )
