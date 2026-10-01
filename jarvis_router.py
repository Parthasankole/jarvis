"""
jarvis_router.py — Multi-Model Auto-Routing System for Jarvis
Intelligently routes every request to the optimal local Ollama AI model:
  - FAST / TOOL DISPATCH: qwen2.5:3b (Snappy, ultra-low latency, instant tool calling)
  - CODING / PROGRAMMING: qwen2.5-coder:7b (Dedicated code generation specialist)
  - DEEP REASONING / CHAT: mistral-nemo:12b / llama3.1:8b-instruct-q8_0 (Nuanced, witty, high intelligence)
  - VISION: moondream:latest (Screen perception & image understanding)

Includes automatic model discovery, fallback handling, and model pre-warming.
"""

import time
import json
import threading
import requests
from typing import Dict, Any, Optional

import jarvis_profile as profile

OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_TAGS_URL = f"{OLLAMA_API_BASE}/api/tags"
OLLAMA_CHAT_URL = f"{OLLAMA_API_BASE}/api/chat"

# Roster preferences (highest priority first)
CANDIDATES = {
    "fast": [
        "qwen2.5:3b",
        "llama3.2:3b",
        "qwen2.5:7b",
        "llama3.1:8b-instruct-q8_0"
    ],
    "coder": [
        "qwen2.5-coder:7b",
        "qwen2.5:7b",
        "mistral-nemo:12b",
        "llama3.1:8b-instruct-q8_0"
    ],
    "reasoning": [
        "mistral-nemo:12b",
        "llama3.1:8b-instruct-q8_0",
        "gemma2:9b",
        "qwen2.5:7b"
    ],
    "vision": [
        "moondream:latest",
        "moondream",
        "llama3.2-vision:latest"
    ]
}

_active_models = {
    "fast": "qwen2.5:3b",
    "coder": "qwen2.5-coder:7b",
    "reasoning": "mistral-nemo:12b",
    "vision": "moondream:latest"
}
_discovery_lock = threading.Lock()
_discovered = False


def discover_available_models() -> Dict[str, str]:
    """Inspects Ollama tags and assigns the best installed model for each category."""
    global _active_models, _discovered
    with _discovery_lock:
        try:
            r = requests.get(OLLAMA_TAGS_URL, timeout=4)
            if r.status_code == 200:
                installed_raw = [m.get("name", "") for m in r.json().get("models", [])]
                installed = set(installed_raw)
                # Also add bare names without tags
                for name in installed_raw:
                    if ":" in name:
                        installed.add(name.split(":")[0])

                cfg = profile.load_config()

                for role, options in CANDIDATES.items():
                    # Check if user has an explicit preference in config
                    pref_key = f"preferred_{role}_model"
                    pref = cfg.get(pref_key)
                    if pref and (pref in installed or pref.split(":")[0] in installed):
                        _active_models[role] = pref
                        continue

                    # Otherwise pick the best installed candidate
                    assigned = False
                    for candidate in options:
                        if candidate in installed or candidate.split(":")[0] in installed:
                            _active_models[role] = candidate
                            assigned = True
                            break
                    if not assigned and installed_raw:
                        # Fallback to any installed model
                        _active_models[role] = installed_raw[0]

                _discovered = True
                print(f"[Router] Model assignments: {_active_models}")
        except Exception as e:
            print(f"[Router] Could not query Ollama tags ({e}), using defaults.")

    return _active_models


def get_model_for_role(role: str) -> str:
    global _discovered
    if not _discovered:
        discover_available_models()
    return _active_models.get(role, "qwen2.5:3b")


def is_coding_intent(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in (
        "write a program", "write code", "write a script", "write a function",
        "write me a program", "write me code", "write me a script",
        "write python", "write java", "write c++", "write html", "write javascript",
        "make a program", "create a program", "create a script",
        "code that", "code to", "code for", "program to", "program for",
        "script to", "script for", "function to", "function for",
        "algorithm for", "calculate odd numbers", "print even numbers", "generate code"
    ))


def is_reasoning_intent(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in (
        "explain in detail", "explain why", "why does", "how does", "what is the difference",
        "summarize", "analyze", "deep dive", "philosophy", "compare and contrast",
        "tell me a story", "what do you think about", "philosophical", "pros and cons",
        "write an essay", "scientific explanation", "detailed breakdown", "give me advice on"
    ))


def is_vision_intent(text: str) -> bool:
    low = text.lower()
    return any(p in low for p in (
        "see screen", "see my screen", "look at screen", "look at my screen",
        "what is on my screen", "what's on my screen", "describe my screen",
        "what do you see on the screen", "inspect my screen"
    ))


def route_request(text: str) -> tuple[str, str]:
    """
    Returns (model_name, role_name).
    Categories: 'coder', 'reasoning', 'vision', 'fast'
    """
    if not _discovered:
        discover_available_models()

    if is_vision_intent(text):
        return get_model_for_role("vision"), "vision"

    if is_coding_intent(text):
        return get_model_for_role("coder"), "coder"

    if is_reasoning_intent(text):
        return get_model_for_role("reasoning"), "reasoning"

    return get_model_for_role("fast"), "fast"


def prewarm_models():
    """
    Sends a lightweight keep_alive warmup call to the primary fast & coder models
    in a background thread so they are hot in memory before the user speaks.
    """
    def _warmup():
        discover_available_models()
        for role in ("fast", "coder"):
            model = get_model_for_role(role)
            try:
                requests.post(
                    OLLAMA_CHAT_URL,
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": False,
                        "keep_alive": "60m",
                        "options": {"num_predict": 1}
                    },
                    timeout=30
                )
                print(f"[Router] Pre-warmed model '{model}' ({role}).")
            except Exception as e:
                print(f"[Router] Warmup skipped for '{model}': {e}")

    threading.Thread(target=_warmup, daemon=True).start()


def chat_routed(
    messages,
    model: Optional[str] = None,
    session: Optional[requests.Session] = None,
    format: Optional[str] = "json",
    temperature: float = 0.2,
    num_predict: int = 150,
    timeout: int = 120
) -> str:
    """
    Executes a chat call with the routed model, applying speed optimizations
    (keep_alive, controlled token budget, temperature).
    """
    target_model = model or get_model_for_role("fast")
    caller = session if session is not None else requests

    payload = {
        "model": target_model,
        "messages": messages,
        "stream": False,
        "keep_alive": "60m",
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
        }
    }
    if format:
        payload["format"] = format

    try:
        r = caller.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()["message"]["content"]
    except requests.exceptions.HTTPError as e:
        # Fallback to fast model if specialized model failed
        if target_model != get_model_for_role("fast"):
            print(f"[Router] Model '{target_model}' failed, falling back to fast model...")
            payload["model"] = get_model_for_role("fast")
            r = caller.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()["message"]["content"]
        raise e
