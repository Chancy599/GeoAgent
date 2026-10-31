"""Unified OpenAI-compatible LLM client.

Centralises request handling, timeouts, exponential-backoff retries, image
encoding (with caching), structured JSON validation, and token accounting.
API keys and authorization headers are never written to logs.
"""
from __future__ import annotations

import base64
import io
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from PIL import Image

from ..config import ModelSettings


@dataclass
class LLMResult:
    text: str
    message: Any
    tool_calls: list[Any] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    latency_s: float = 0.0
    has_images: bool = False
    tag: str = ""
    model: str = ""


class LLMClient:
    """One client for all agents; callers pass a semantic ``tag`` for tracing."""

    def __init__(self, settings: ModelSettings, log_path: Path | None = None):
        if not settings.api_key:
            raise ValueError("API key is missing. Set OPENAI_API_KEY in .env")
        if not settings.base_url:
            raise ValueError("Base URL is missing. Set OPENAI_BASE_URL in .env")
        self.settings = settings
        self.model = settings.model
        self._client = OpenAI(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=settings.request_timeout,
            max_retries=0,  # retries are handled here so they are recorded
        )
        self.log_path = log_path
        self.records: list[dict[str, Any]] = []
        self._image_cache: dict[str, str] = {}
        self._totals: dict[str, float] = {
            "calls": 0.0,
            "visual_calls": 0.0,
            "prompt_tokens": 0.0,
            "completion_tokens": 0.0,
            "total_tokens": 0.0,
            "cached_tokens": 0.0,
            "cache_write_tokens": 0.0,
            "latency_s": 0.0,
        }
        self._by_tag: dict[str, dict[str, float]] = {}

    # ------------------------------------------------------------------ #
    # images
    # ------------------------------------------------------------------ #
    def encode_image(self, image_path: str | Path) -> str:
        """Return a cached data URI, downscaled to keep visual calls cheap."""
        path = Path(image_path)
        stat = path.stat()
        key = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}|{self.settings.image_max_dim}"
        if key in self._image_cache:
            return self._image_cache[key]

        with Image.open(path) as im:
            im = im.convert("RGB")
            max_dim = max(1, int(self.settings.image_max_dim))
            if max(im.size) > max_dim:
                im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=int(self.settings.jpeg_quality), optimize=True)
        uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
        self._image_cache[key] = uri
        return uri

    def build_content(self, text: str, image_paths: Iterable[str | Path] | None = None) -> Any:
        paths = [str(p) for p in (image_paths or [])]
        if not paths:
            return text
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        for p in paths:
            parts.append({"type": "image_url", "image_url": {"url": self.encode_image(p)}})
        return parts

    # ------------------------------------------------------------------ #
    # chat
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
        max_tokens: int | None = None,
        temperature: float | None = None,
        tag: str = "llm",
        timeout: float | None = None,
    ) -> LLMResult:
        """Chat with retries/backoff and token accounting."""
        max_attempts = max(1, self.settings.max_retries + 1)
        last_error: Exception | None = None
        has_images = _messages_have_images(messages)

        for attempt in range(1, max_attempts + 1):
            started = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": int(max_tokens or self.settings.max_tokens),
                    "timeout": float(timeout or self.settings.request_timeout),
                }
                temp = self.settings.temperature if temperature is None else temperature
                if temp is not None:
                    kwargs["temperature"] = float(temp)
                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = tool_choice
                response = self._client.chat.completions.create(**kwargs)
                latency = time.perf_counter() - started
                result = self._to_result(response, latency, has_images, tag)
                self._record(result, attempt=attempt)
                return result
            except (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError) as exc:
                last_error = exc
                retryable = True
            except APIStatusError as exc:
                last_error = exc
                retryable = exc.status_code >= 500 or exc.status_code == 429
            except Exception as exc:  # proxy-specific transient failures
                last_error = exc
                text = str(exc).lower()
                retryable = any(
                    token in text
                    for token in ("timeout", "timed out", "connection", "temporarily", "overloaded", "rate limit")
                )
            if not retryable or attempt == max_attempts:
                break
            delay = min(30.0, (1.6 ** attempt) + random.uniform(0.0, 0.6))
            time.sleep(delay)

        raise RuntimeError(f"LLM request failed after {max_attempts} attempts: {type(last_error).__name__}: {last_error}")

    def _to_result(self, response: Any, latency: float, has_images: bool, tag: str) -> LLMResult:
        choice = response.choices[0]
        message = choice.message
        usage_obj = getattr(response, "usage", None)
        usage: dict[str, Any] = {}
        if usage_obj is not None:
            usage = {
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage_obj, "completion_tokens", 0) or 0,
                "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
            }
            details = getattr(usage_obj, "prompt_tokens_details", None)
            if details is not None:
                usage["cached_tokens"] = getattr(details, "cached_tokens", 0) or 0
                usage["cache_write_tokens"] = getattr(details, "cache_write_tokens", 0) or 0
        return LLMResult(
            text=message.content or "",
            message=message,
            tool_calls=list(getattr(message, "tool_calls", None) or []),
            finish_reason=getattr(choice, "finish_reason", None),
            usage=usage,
            latency_s=round(latency, 3),
            has_images=has_images,
            tag=tag,
            model=self.model,
        )

    def _record(self, result: LLMResult, attempt: int) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "tag": result.tag,
            "model": result.model,
            "finish_reason": result.finish_reason,
            "has_images": result.has_images,
            "latency_s": result.latency_s,
            "attempt": attempt,
            "usage": result.usage,
        }
        self.records.append(record)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "cache_write_tokens"):
            self._totals[key] += float(result.usage.get(key, 0) or 0)
        self._totals["calls"] += 1
        if result.has_images:
            self._totals["visual_calls"] += 1
        self._totals["latency_s"] += result.latency_s
        tag_stats = self._by_tag.setdefault(
            result.tag, {"calls": 0.0, "visual_calls": 0.0, "total_tokens": 0.0, "latency_s": 0.0}
        )
        tag_stats["calls"] += 1
        tag_stats["total_tokens"] += float(result.usage.get("total_tokens", 0) or 0)
        tag_stats["latency_s"] += result.latency_s
        if result.has_images:
            tag_stats["visual_calls"] += 1
        if self.log_path is not None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ #
    # structured output
    # ------------------------------------------------------------------ #
    def _chat_untruncated(
        self,
        messages: list[dict[str, Any]],
        *,
        tag: str,
        max_tokens: int | None,
    ) -> LLMResult:
        """Chat, retrying once with a wider budget if the reply hits the cap.

        A ``finish_reason`` of ``length`` means the JSON was cut mid-object;
        accepting it (or a stray fragment parsed out of it) would silently
        degrade downstream scores, so this is an error if the retry also truncates.
        """
        result = self.chat(messages, tag=tag, max_tokens=max_tokens)
        if result.finish_reason != "length":
            return result
        base = int(max_tokens or self.settings.max_tokens)
        wider = min(16384, max(base * 2, base + 2048))
        result = self.chat(messages, tag=f"{tag}:length_retry", max_tokens=wider)
        if result.finish_reason == "length":
            raise ValueError(f"Model reply truncated at max_tokens={wider}; refusing partial output")
        return result

    def complete_json(
        self,
        system: str,
        user: str,
        *,
        images: Iterable[str | Path] | None = None,
        tag: str = "json",
        max_tokens: int | None = None,
        retry_on_parse_failure: bool = True,
    ) -> dict[str, Any]:
        """Ask for a JSON object and validate it, retrying once on parse errors."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": self.build_content(user, images)},
        ]
        result = self._chat_untruncated(messages, tag=tag, max_tokens=max_tokens)
        parsed, error = parse_json_object(result.text)
        if parsed is not None:
            return parsed
        if not retry_on_parse_failure:
            raise ValueError(f"Invalid JSON from model: {error}")

        correction = (
            "Your previous reply could not be parsed as a JSON object. "
            f"Parse error: {error}. Reply again with ONLY one valid JSON object, "
            "no markdown fences, no commentary."
        )
        messages.append({"role": "assistant", "content": result.text[:4000]})
        messages.append({"role": "user", "content": correction})
        retry = self._chat_untruncated(messages, tag=f"{tag}:json_retry", max_tokens=max_tokens)
        parsed, error = parse_json_object(retry.text)
        if parsed is None:
            raise ValueError(f"Invalid JSON from model after retry: {error}")
        return parsed

    # ------------------------------------------------------------------ #
    # statistics
    # ------------------------------------------------------------------ #
    def usage_summary(self) -> dict[str, Any]:
        totals = dict(self._totals)
        totals["calls"] = int(totals["calls"])
        totals["visual_calls"] = int(totals["visual_calls"])
        totals["total_tokens"] = int(totals["total_tokens"])
        totals["prompt_tokens"] = int(totals["prompt_tokens"])
        totals["completion_tokens"] = int(totals["completion_tokens"])
        totals["latency_s"] = round(totals["latency_s"], 2)
        return {
            "totals": totals,
            "by_agent": {
                tag: {
                    "calls": int(v["calls"]),
                    "visual_calls": int(v["visual_calls"]),
                    "total_tokens": int(v["total_tokens"]),
                    "latency_s": round(v["latency_s"], 2),
                }
                for tag, v in self._by_tag.items()
            },
            "records": list(self.records),
        }


def _messages_have_images(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        content = message.get("content")
        if isinstance(content, list) and any(
            isinstance(part, dict) and part.get("type") == "image_url" for part in content
        ):
            return True
    return False


def parse_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract the first JSON object from a model reply, tolerating fences."""
    if not text:
        return None, "empty response"
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    decoder = json.JSONDecoder()
    start_positions = [i for i, ch in enumerate(cleaned) if ch == "{"]
    for start in start_positions:
        try:
            obj, _ = decoder.raw_decode(cleaned[start:])
            if isinstance(obj, dict):
                return obj, None
        except json.JSONDecodeError:
            continue
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj, None
        return None, f"expected object, got {type(obj).__name__}"
    except json.JSONDecodeError as exc:
        return None, str(exc)
