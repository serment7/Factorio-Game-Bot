"""Ollama API client for vision LLM inference."""

import logging
import re

import requests

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "gemma3:4b"
DEFAULT_TIMEOUT = 120


class OllamaClient:
    """Sends chat messages (with optional images) to Ollama."""

    def __init__(self, url: str = DEFAULT_URL, model: str = DEFAULT_MODEL,
                 timeout: int = DEFAULT_TIMEOUT):
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, system_prompt: str, user_text: str,
             image_b64: str | None = None) -> str:
        """Send a chat request and return the assistant's response text."""
        messages = [
            {"role": "system", "content": system_prompt},
        ]
        user_msg: dict = {"role": "user", "content": user_text}
        if image_b64:
            user_msg["images"] = [image_b64]
        messages.append(user_msg)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": 1024},
            "think": False,
        }

        try:
            resp = requests.post(
                f"{self.url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message", {})
            content = msg.get("content", "")
            # Some models (qwen3-vl) put response in 'thinking' when images are used
            if not content.strip():
                thinking = msg.get("thinking", "")
                if thinking:
                    # Strip <think> tags and use thinking content
                    content = re.sub(r"</?think>", "", thinking).strip()
                    logger.info("Using thinking field as response (%d chars)", len(content))
            logger.debug("Ollama response (%d chars): %s", len(content), content[:200])
            return content
        except requests.Timeout:
            logger.warning("Ollama request timed out after %ds", self.timeout)
            return "THOUGHT: Request timed out.\nACTION: wait 2"
        except requests.RequestException as e:
            logger.error("Ollama request failed: %s", e)
            return "THOUGHT: LLM connection error.\nACTION: wait 2"

    def is_available(self) -> bool:
        """Check if Ollama is reachable."""
        try:
            resp = requests.get(f"{self.url}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False


if __name__ == "__main__":
    client = OllamaClient()
    if client.is_available():
        print("Ollama is available.")
        result = client.chat("You are a test.", "Say hello.", None)
        print(f"Response: {result}")
    else:
        print("Ollama is not reachable.")
