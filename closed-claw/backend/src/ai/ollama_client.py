"""Local Ollama proxy for the news-predictor-3b model."""
from __future__ import annotations

import json
import os
import re
from typing import AsyncIterator

import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
MODEL = os.getenv("NEWS_MODEL", "news-predictor-3b")


def build_prompt(headline: str, event_name: str, consensus: str, actual: str) -> str:
    return (f"Event: {event_name}\nHeadline: {headline}\nConsensus forecast: {consensus}\n"
            f"Actual print: {actual}\nReturn the gold reaction JSON.")


def parse_prediction(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"model returned no JSON: {text[:200]}")
    d = json.loads(m.group(0))
    bias = str(d.get("gold_bias", "")).lower()
    if bias not in ("bullish", "bearish", "neutral"):
        raise ValueError(f"invalid gold_bias {bias!r}")
    return {"event": d.get("event"), "actual_vs_forecast": d.get("actual_vs_forecast"),
            "gold_bias": bias, "confidence": round(min(1.0, max(0.0, float(d.get("confidence", 0)))), 2),
            "expected_expansion_points": float(d.get("expected_expansion_points", 0.0))}


async def predict(headline: str, event_name: str, consensus: str, actual: str) -> dict:
    body = {"model": MODEL, "prompt": build_prompt(headline, event_name, consensus, actual),
            "stream": False, "format": "json", "options": {"temperature": 0.0, "seed": 42}}
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{OLLAMA_URL}/api/generate", json=body)
        r.raise_for_status()
        return parse_prediction(r.json()["response"])


async def chat_stream(messages: list[dict], model: str | None = None) -> AsyncIterator[str]:
    body = {"model": model or MODEL, "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=None) as c:
        async with c.stream("POST", f"{OLLAMA_URL}/api/chat", json=body) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line:
                    chunk = json.loads(line)
                    yield chunk.get("message", {}).get("content", "")
                    if chunk.get("done"):
                        break


async def health() -> dict:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"up": True, "models": models, "news_model_loaded": any(m.startswith(MODEL) for m in models)}
    except httpx.HTTPError:
        return {"up": False, "models": [], "news_model_loaded": False}
