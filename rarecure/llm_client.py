"""LLM client. [C5] sanitize [C6] retry jitter [H6] token tracking."""
import json
import logging
import re
from typing import Optional
from rarecure.config import (
    LLM_PROVIDER, LLMProvider, ANTHROPIC_API_KEY,
    CLAUDE_MODEL, CLAUDE_MAX_TOKENS, CLAUDE_TEMPERATURE,
    LOCAL_LLAMA_ENDPOINT, LOCAL_LLAMA_MODEL,
)

logger = logging.getLogger(__name__)


def sanitize_for_prompt(text, max_len=500):
    if not text:
        return "not specified"
    s = re.sub(r"[^\w\s.,;:()\-/'\"#+%&]", "", str(text)[:max_len])
    return s.strip() or "not specified"


class LLMClient:
    def __init__(self, provider=None):
        self.provider = provider or LLM_PROVIDER
        self._client = None
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_calls = 0
        self._init()

    def _init(self):
        if self.provider == LLMProvider.CLAUDE:
            import anthropic
            self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        elif self.provider == LLMProvider.LOCAL_LLAMA:
            import httpx
            self._client = httpx.Client(base_url=LOCAL_LLAMA_ENDPOINT, timeout=120)

    @property
    def total_cost_usd(self):
        return self.total_input_tokens * 3.0 / 1e6 + self.total_output_tokens * 15.0 / 1e6

    def complete(self, prompt, system="", temperature=None, max_tokens=CLAUDE_MAX_TOKENS):
        t = temperature if temperature is not None else CLAUDE_TEMPERATURE
        self.total_calls += 1
        sys_msg = system or "You are a precision oncology AI assistant."
        if self.provider == LLMProvider.CLAUDE:
            m = self._client.messages.create(
                model=CLAUDE_MODEL, max_tokens=max_tokens,
                temperature=t, system=sys_msg,
                messages=[{"role": "user", "content": prompt}])
            self.total_input_tokens += m.usage.input_tokens
            self.total_output_tokens += m.usage.output_tokens
            return m.content[0].text
        elif self.provider == LLMProvider.LOCAL_LLAMA:
            r = self._client.post("/chat/completions", json={
                "model": LOCAL_LLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": prompt}],
                "temperature": t, "max_tokens": max_tokens})
            r.raise_for_status()
            d = r.json()
            u = d.get("usage", {})
            self.total_input_tokens += u.get("prompt_tokens", 0)
            self.total_output_tokens += u.get("completion_tokens", 0)
            return d["choices"][0]["message"]["content"]
        raise ValueError(f"Unknown provider: {self.provider}")

    def complete_json(self, prompt, system="", temperature=None):
        sj = (system or "") + "\nRespond with ONLY valid JSON. No markdown, no preamble."
        base = temperature if temperature is not None else CLAUDE_TEMPERATURE
        err = ""
        for attempt in range(3):
            t = base + attempt * 0.15
            note = f"\nPrevious JSON failed ({err}). Return ONLY JSON." if attempt > 0 else ""
            raw = self.complete(prompt + note, sj, t)
            try:
                c = raw.strip()
                if c.startswith("```"):
                    c = c.split("\n", 1)[1] if "\n" in c else c[3:]
                if c.endswith("```"):
                    c = c.rsplit("```", 1)[0]
                return json.loads(c.strip())
            except json.JSONDecodeError as e:
                err = str(e)[:80]
                logger.warning(f"JSON fail {attempt + 1}: {err}")
        raise ValueError(f"No valid JSON after 3 tries: {err}")


_client = None


def get_llm_client():
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
