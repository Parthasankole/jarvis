"""
jarvis_profile.py — User Profile, Voice Personalization & Configuration
Manages user identity (Partha), voice settings, and persona attributes.
"""

import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "jarvis_config.json"
VOICES_DIR = Path(__file__).parent / "piper" / "voices"

DEFAULT_CONFIG = {
    "user_name": "Partha",
    "assistant_name": "JARVIS",
    "title": "Sir",
    "personality": "Refined, loyal, sophisticated, and attentive British high-tech AI companion. Speak with warmth, elegance, and quiet confidence, addressing Partha directly.",
    "voice_model": "en_GB-alan-medium.onnx",
    "voice_speed": 0.95,
    "preferred_fast_model": "qwen2.5:3b",
    "preferred_coder_model": "qwen2.5-coder:7b",
    "preferred_reasoning_model": "mistral-nemo:12b",
    "preferred_vision_model": "moondream:latest"
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            # Ensure all default keys exist
            for k, v in DEFAULT_CONFIG.items():
                if k not in cfg:
                    cfg[k] = v
            return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")


def get_user_name() -> str:
    return load_config().get("user_name", "Partha")


def get_voice_paths():
    cfg = load_config()
    voice_name = cfg.get("voice_model", "en_GB-alan-medium.onnx")
    onnx_path = VOICES_DIR / voice_name
    json_path = VOICES_DIR / (voice_name + ".json")
    
    # Fallback to lessac if alan is missing
    if not onnx_path.exists():
        onnx_path = VOICES_DIR / "en_US-lessac-low.onnx"
        json_path = VOICES_DIR / "en_US-lessac-low.onnx.json"
        
    speed = float(cfg.get("voice_speed", 0.95))
    return onnx_path, json_path, speed


def list_available_voices():
    if not VOICES_DIR.exists():
        return []
    return [f.name for f in VOICES_DIR.glob("*.onnx")]


def set_user_name(name: str):
    cfg = load_config()
    cfg["user_name"] = name.strip()
    save_config(cfg)
    try:
        import jarvis_memory as m
        m.save_memory("name", name.strip())
        m.save_memory("boss", name.strip())
    except Exception:
        pass


def set_voice(voice_filename: str, speed: float = 0.95):
    cfg = load_config()
    cfg["voice_model"] = voice_filename
    cfg["voice_speed"] = speed
    save_config(cfg)
