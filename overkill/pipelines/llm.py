"""Groq chat client, standard library only.

Owns: retries, exponential backoff, polite rate limiting, daily-cap detection, usage parsing.
Does NOT own: timing or pricing (the harness), prompts (prompts.py).
Why not the groq SDK: the SDK retries on its own, which would hide retries from our measurements.
Here every retry is visible and every token is counted.
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .base import MODEL, ROOT

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMError(RuntimeError):
    pass


class DailyLimitReached(LLMError):
    """Free-tier daily cap (RPD/TPD). Waiting minutes won't help: checkpoint, stop, resume tomorrow."""


class MissingKey(LLMError):
    pass


def load_env(path: Path | None = None) -> None:
    """Twelve-line .env loader instead of a python-dotenv dependency. Never overrides real env vars."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


@dataclass
class Completion:
    message: dict
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    tool_args: dict | None      # parsed arguments of the forced tool call; None = parse failure
    elapsed_ms: float           # diagnostic only (trace waterfall). Never used for reported latency.
    started_at: float           # epoch seconds, for hosted traces
    retries: int = 0


class RateLimiter:
    """Sliding 60 s window over requests and tokens: wait politely instead of collecting 429s."""

    def __init__(self, rpm: int, tpm: int, clock=time.monotonic, sleep=time.sleep):
        self.rpm, self.tpm = rpm, tpm
        self.clock, self.sleep = clock, sleep
        self.events: deque[list] = deque()  # [timestamp, tokens]
        self.lock = threading.Lock()

    def acquire(self, est_tokens: int) -> list:
        with self.lock:
            while True:
                now = self.clock()
                while self.events and now - self.events[0][0] >= 60:
                    self.events.popleft()
                used = sum(e[1] for e in self.events)
                if not self.events or (len(self.events) < self.rpm and used + est_tokens <= self.tpm):
                    event = [now, est_tokens]
                    self.events.append(event)
                    return event
                self.sleep(max(0.05, 60 - (now - self.events[0][0])))


def _retry_after(headers: dict, message: str) -> float | None:
    for k, v in headers.items():
        if k.lower() == "retry-after":
            try:
                return float(v)
            except ValueError:
                pass
    m = re.search(r"try again in (?:(\d+)m)?(?:([\d.]+)s)?(?:([\d.]+)ms)?", message)
    if m and any(m.groups()):
        mins, secs, ms = m.groups()
        return int(mins or 0) * 60 + float(secs or 0) + float(ms or 0) / 1000
    return None


def _json_in(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class GroqClient:
    def __init__(self, api_key: str | None = None, model: str = MODEL, transport=None,
                 sleep=time.sleep, max_retries: int = 6):
        load_env()
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        if not self.api_key and transport is None:
            raise MissingKey("GROQ_API_KEY is not set. Copy .env.example to .env and add a free key "
                             "from https://console.groq.com/keys")
        self.model = model
        self.transport = transport or self._http
        self.sleep = sleep
        self.max_retries = max_retries
        self.limiter = RateLimiter(int(os.environ.get("GROQ_RPM", 30)),
                                   int(os.environ.get("GROQ_TPM", 12000)), sleep=sleep)

    def _http(self, body: dict) -> tuple[int, dict, dict]:
        req = urllib.request.Request(
            GROQ_URL, data=json.dumps(body).encode(), method="POST",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                     "User-Agent": "overkill-harness/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, dict(r.headers), json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read())
            except Exception:
                payload = {"error": {"message": str(e)}}
            return e.code, dict(e.headers or {}), payload
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            return 0, {}, {"error": {"message": f"network: {e}"}}

    def chat(self, messages: list[dict], tool: dict | None = None, temperature: float = 0.0,
             max_tokens: int = 300) -> Completion:
        body = {"model": self.model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens}
        if tool:  # force the schema: the model must call this tool, so output is always an enum value
            body["tools"] = [tool]
            body["tool_choice"] = {"type": "function", "function": {"name": tool["function"]["name"]}}
        est = sum(len(m["content"]) for m in messages) // 4 + max_tokens  # throttle estimate only
        delay, retries = 2.0, 0
        for attempt in range(self.max_retries + 1):
            event = self.limiter.acquire(est)
            started, t0 = time.time(), time.perf_counter()
            status, headers, data = self.transport(body)
            elapsed = (time.perf_counter() - t0) * 1000
            if status == 200:
                c = self._parse(data, tool, elapsed, started)
                event[1] = c.tokens_in + c.tokens_out  # replace the estimate with the measured count
                c.retries = retries
                return c
            err = data.get("error") or {}
            msg, code = err.get("message", ""), err.get("code", "")
            if status == 429:
                if re.search(r"per day|\(RPD\)|\(TPD\)", msg):
                    raise DailyLimitReached(msg)
                wait = _retry_after(headers, msg) or delay
            elif status == 400 and code == "tool_use_failed":
                # Malformed tool call. Retry once; then report a parse failure (scored, counted, not hidden).
                # Groq returns no usage on this error, so those tokens are invisible: a known undercount.
                if attempt >= 1:
                    return Completion({}, 0, 0, 0, None, elapsed, started, retries)
                wait = 0.0
            elif status in (0, 408, 500, 502, 503, 504):
                wait = delay
            else:
                raise LLMError(f"Groq HTTP {status}: {msg}")
            if attempt == self.max_retries:
                raise LLMError(f"gave up after {attempt + 1} attempts: HTTP {status} {msg}")
            retries += 1
            self.sleep(wait + random.uniform(0, 0.25 * wait))
            delay = min(delay * 2, 60.0)
        raise LLMError("unreachable")

    @staticmethod
    def _parse(data: dict, tool: dict | None, elapsed: float, started: float) -> Completion:
        usage = data.get("usage") or {}
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        args = None
        if tool:
            want = tool["function"]["name"]
            for call in msg.get("tool_calls") or []:
                fn = call.get("function") or {}
                if fn.get("name") == want:
                    raw = fn.get("arguments")
                    try:
                        args = raw if isinstance(raw, dict) else json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        args = None
                    break
            if args is None:
                args = _json_in(msg.get("content") or "")
        return Completion(msg, int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)),
                          int(cached), args, elapsed, started)
