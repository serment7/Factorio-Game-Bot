"""Claude CLI subprocess wrapper."""

import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def _clean_env() -> dict[str, str]:
    """Return a copy of os.environ without CLAUDECODE to allow nested calls."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env


class ClaudeClient:
    """Runs Claude CLI as subprocess for strategic queries."""

    DEFAULT_PATH = os.path.expandvars(r"%APPDATA%\npm\claude.cmd")

    def __init__(self, cli_path: str | None = None, max_turns: int = 1):
        cli_path = cli_path or self.DEFAULT_PATH
        self.cli_path = cli_path
        self.max_turns = max_turns

    def query(self, prompt: str, system_prompt: str | None = None) -> str:
        """Send a prompt to Claude CLI via temp file to avoid cmd length limits."""
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"

        # Write prompt to temp file, pass path to -p
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        )
        try:
            tmp.write(full_prompt)
            tmp.close()

            cmd = [
                self.cli_path,
                "-p", f"@{tmp.name}",
                "--output-format", "text",
                "--max-turns", str(self.max_turns),
                "--model", "haiku",
            ]

            logger.info("Running Claude CLI (prompt %d chars)...", len(full_prompt))
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                env=_clean_env(),
            )
            if result.returncode != 0:
                err = result.stderr.strip()[:300] or result.stdout.strip()[:300]
                logger.error("Claude CLI error (rc=%d): %s", result.returncode, err)
                return f"__ERROR__: rc={result.returncode} {err}"
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI timed out after 120s")
            return "__ERROR__: timeout 120s"
        except FileNotFoundError:
            logger.error("Claude CLI not found at '%s'", self.cli_path)
            return "__ERROR__: claude not found"
        except Exception as e:
            logger.error("Claude CLI unexpected error: %s", e)
            return f"__ERROR__: {e}"
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                [self.cli_path, "--version"],
                capture_output=True, text=True, timeout=10,
                env=_clean_env(),
            )
            return result.returncode == 0
        except Exception:
            return False
