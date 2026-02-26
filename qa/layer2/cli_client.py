"""
Claude CLI wrapper with fixed timeouts, retry, and robust JSON extraction.
"""

import os
import json
import time
import re
import subprocess
from qa.config import LLM_DEFAULTS


class ClaudeCliClient:
    """Reliable Claude CLI client with retry and budget control."""

    def __init__(self, model=None, timeout=None, max_retries=None, budget=None):
        self.model = model or LLM_DEFAULTS["model"]
        self.timeout = timeout or LLM_DEFAULTS["timeout"]
        self.max_retries = max_retries or LLM_DEFAULTS["max_retries"]
        self.budget = budget or LLM_DEFAULTS["budget"]
        self.calls_made = 0
        self._available = None

    def is_available(self) -> bool:
        """Check if claude CLI is available."""
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
        return self.calls_made < self.budget

    def call(self, prompt: str, json_schema=None) -> dict | str:
        """Call Claude CLI with retry and exponential backoff.

        Returns parsed JSON dict if json_schema provided, otherwise raw text.
        Raises RuntimeError if all retries exhausted.
        """
        if not self.has_budget():
            raise RuntimeError(f"LLM budget exhausted ({self.calls_made}/{self.budget})")

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                result = self._single_call(prompt, json_schema)
                self.calls_made += 1
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    wait = LLM_DEFAULTS["backoff_base"] ** attempt
                    time.sleep(wait)

        raise RuntimeError(f"All {self.max_retries} attempts failed. Last error: {last_error}")

    def _single_call(self, prompt: str, json_schema=None):
        """Execute a single Claude CLI call."""
        cmd = ["claude", "-p", "--model", self.model, "--output-format", "json"]
        if json_schema:
            cmd.extend(["--json-schema", json.dumps(json_schema)])

        env = self._clean_env()
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self.timeout,
            encoding="utf-8",
            env=env,
        )

        if result.returncode != 0:
            raise RuntimeError(f"CLI returned {result.returncode}: {result.stderr[:300]}")

        return self._extract_json(result.stdout, json_schema is not None)

    def _extract_json(self, stdout: str, expect_json: bool):
        """Extract JSON from CLI output with 3 fallback strategies."""
        # Strategy 1: Direct parse
        try:
            output = json.loads(stdout)
            if isinstance(output, dict) and "result" in output:
                inner = output["result"]
                if expect_json:
                    try:
                        return json.loads(inner)
                    except (json.JSONDecodeError, TypeError):
                        pass
                return inner
            return output
        except json.JSONDecodeError:
            pass

        if not expect_json:
            return stdout.strip()

        # Strategy 2: Code block extraction
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', stdout, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 3: Brace-finding
        start = stdout.find('{')
        if start >= 0:
            depth = 0
            for i in range(start, len(stdout)):
                if stdout[i] == '{':
                    depth += 1
                elif stdout[i] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(stdout[start:i + 1])
                        except json.JSONDecodeError:
                            break

        raise RuntimeError(f"Could not extract JSON from output: {stdout[:200]}")

    def _clean_env(self):
        """Remove CLAUDECODE env var for nested invocation."""
        env = {**os.environ}
        env.pop("CLAUDECODE", None)
        return env
