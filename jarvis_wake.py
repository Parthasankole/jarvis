import os
import sys
import json
import time
import queue
import threading
import subprocess
import winsound
from pathlib import Path

# Global interrupt flag — set this to stop TTS and abort the current response
_stop_event = threading.Event()
# Tracks the current Ollama requests.Session so we can abort it mid-request
_ollama_session = None
_ollama_session_lock = threading.Lock()

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

import requests
import numpy as np
import sounddevice as sd
from pydantic import BaseModel
from faster_whisper import WhisperModel
from openwakeword.model import Model as WakeModel

import jarvis_tools as tools
import jarvis_profile as profile
import jarvis_router as router
import jarvis_apps_control as app_ctrl

try:
    from jarvis_gui import JarvisHUD
except ImportError:
    from jarvis_gui import JarvisCinematicHUD as JarvisHUD

# CUDA DLLs setup for faster-whisper
nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
    dll_dir = nvidia_root / sub / "bin"
    if dll_dir.exists():
        try:
            os.add_dll_directory(str(dll_dir))
            os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ["PATH"]
        except Exception:
            pass

WAKE_MODEL_NAME = "hey_jarvis"
WAKE_TRIGGER_THRESHOLD = 0.55
TARGET_SR = 16000
CHUNK_16K = 1280
RMS_THRESHOLD = 0.010
SILENCE_SECONDS_TO_STOP = 1.5
MAX_SECONDS = 15
FOLLOWUP_WINDOW_SECONDS = 6.0

PIPER_EXE = Path(r"C:\jarvis-local\piper\piper_windows_amd64\piper\piper.exe")
TTS_WAV = Path(r"C:\jarvis-local\piper\jarvis_reply.wav")


def get_system_prompt() -> str:
    user_name = profile.get_user_name()
    return f"""You are JARVIS, a highly sophisticated, loyal, and intelligent AI companion running locally on Windows.
Your creator and user is {user_name}. Always address him warmly, respectfully, and naturally as {user_name} (or 'Sir' / '{user_name}').
You have direct access to see the screen, control the mouse cursor, type on the keyboard, and automate the browser.
Speak with refined elegance, warmth, and quiet confidence—like Tony Stark's JARVIS, but uniquely devoted to {user_name}. Keep spoken responses concise and natural.
Output ONLY valid JSON in ONE of these formats:
{{"type":"see_screen","args":{{"prompt":"what is visible?"}}}}
{{"type":"click_mouse","args":{{"button":"left","clicks":1}}}}
{{"type":"move_cursor","args":{{"x":"center"}}}}
{{"type":"scroll_mouse","args":{{"direction":"down","amount":3}}}}
{{"type":"type_text","args":{{"text":"hello world"}}}}
{{"type":"press_key","args":{{"key_name":"enter"}}}}
{{"type":"press_hotkey","args":{{"combo":"ctrl+c"}}}}
{{"type":"open_onscreen_keyboard","args":{{}}}}
{{"type":"close_onscreen_keyboard","args":{{}}}}
{{"type":"open_installed_app","args":{{"name":"Brave"}}}}
{{"type":"close_app","args":{{"name":"Brave"}}}}
{{"type":"close_current_tab","args":{{}}}}
{{"type":"close_current_window","args":{{}}}}
{{"type":"system_status","args":{{}}}}
{{"type":"get_time_date","args":{{}}}}
{{"type":"get_weather","args":{{"city":""}}}}
{{"type":"media_control","args":{{"action":"play"}}}}
{{"type":"set_volume","args":{{"action":"up"}}}}
{{"type":"take_screenshot","args":{{}}}}
{{"type":"get_active_window","args":{{}}}}
{{"type":"list_open_windows","args":{{}}}}
{{"type":"get_clipboard","args":{{}}}}
{{"type":"open_web","args":{{"query":"youtube..."}}}}
{{"type":"save_memory","args":{{"key":"pin","value":"21"}}}}
{{"type":"recall_memory","args":{{"query":"pin"}}}}
{{"type":"youtube_play","args":{{"query":"Believer by Imagine Dragons"}}}}
{{"type":"web_search","args":{{"query":"what is the capital of France"}}}}
{{"type":"browser_open","args":{{"url":"https://example.com"}}}}
{{"type":"browser_read_page","args":{{}}}}
{{"type":"browser_click","args":{{"text":"Sign in"}}}}
{{"type":"browser_fill","args":{{"field":"email","value":"user@example.com"}}}}
{{"type":"browser_scroll","args":{{"direction":"down","amount":3}}}}
{{"type":"browser_go_back","args":{{}}}}
{{"type":"browser_get_url","args":{{}}}}
{{"type":"browser_close","args":{{}}}}
{{"type":"final","text":"your normal response"}}
Rules:
- Output ONLY JSON. Keep spoken responses concise and natural. Never recite raw URLs or file paths.
- open_onscreen_keyboard is ONLY for showing a touch keyboard. NEVER use it for coding requests.
- For code/program/script requests, use type_text with the actual code. Assume a text editor is already open.
- For simple greetings and chat, use final with a short friendly reply addressing {user_name}.
"""


def get_code_system_prompt() -> str:
    user_name = profile.get_user_name()
    return f"""You are JARVIS, coding specialist for {user_name}.
{user_name} wants you to write code. Output ONLY this exact JSON:
{{"type":"type_text","args":{{"text":"<complete working code here>"}}}}
Write clean, complete, runnable code inside the text field. No markdown or conversational text inside the JSON text field—just the raw code itself.
Output ONLY valid JSON, nothing else.
"""


class Call(BaseModel):
    type: str
    args: dict | None = None
    text: str | None = None


def extract_json(text: str):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON")
    return json.loads(text[start:end + 1])


def ollama_chat(messages, model: str = None, format: str = "json", temperature: float = 0.2, num_predict: int = 150):
    global _ollama_session
    session = requests.Session()
    with _ollama_session_lock:
        _ollama_session = session
    try:
        return router.chat_routed(
            messages=messages,
            model=model,
            session=session,
            format=format,
            temperature=temperature,
            num_predict=num_predict,
            timeout=120
        )
    finally:
        with _ollama_session_lock:
            _ollama_session = None


def trim_history(messages, max_keep=10):
    if len(messages) > (max_keep + 1):
        return [messages[0]] + messages[-max_keep:]
    return messages


def direct_intent_override(text: str):
    t = text.strip()
    low = t.lower()
    user_name = profile.get_user_name()

    # 👤 Personal Identity & Greetings (Instant 0ms Latency)
    if any(p in low for p in ("who are you", "what is your name", "what's your name")):
        return Call(type="final", text=f"I am JARVIS, your personal artificial intelligence, {user_name}. Standing by.")
    if any(p in low for p in ("who am i", "what is my name", "what's my name", "do you know me", "do you know who i am")):
        return Call(type="final", text=f"You are {user_name}, my creator and boss.")
    if any(low == p for p in ("hello", "hi jarvis", "hey jarvis", "hello jarvis", "greetings")):
        return Call(type="final", text=f"Hello, {user_name}. How may I be of service?")
    if any(p in low for p in ("how are you", "how are you doing", "how do you feel")):
        return Call(type="final", text=f"All systems are operating at peak efficiency, {user_name}. Ready for your command.")
    if any(low == p or low.startswith(p + " ") for p in ("thank you", "thanks", "thanks jarvis", "thank you jarvis")):
        return Call(type="final", text=f"Always an absolute pleasure, {user_name}.")
    if any(p in low for p in ("good morning", "morning jarvis")):
        return Call(type="final", text=f"Good morning, {user_name}. All systems are initialized and standing by.")
    if any(p in low for p in ("good night", "night jarvis")):
        return Call(type="final", text=f"Good night, {user_name}. Power systems entering standby.")

    # 👁️ Screen Vision
    if any(p in low for p in ("see screen", "see my screen", "look at screen", "look at my screen", "what is on my screen", "what's on my screen", "describe my screen", "what do you see on the screen", "inspect my screen")):
        return Call(type="see_screen", args={"prompt": text})

    # ⌨️ On-screen Keyboard
    if any(p in low for p in ("open on-screen keyboard", "open on screen keyboard", "show on-screen keyboard", "show on screen keyboard", "open virtual keyboard", "show keyboard", "open keyboard")):
        return Call(type="open_onscreen_keyboard", args={})
    if any(p in low for p in ("close on-screen keyboard", "close on screen keyboard", "hide on-screen keyboard", "hide keyboard", "close virtual keyboard", "close keyboard")):
        return Call(type="close_onscreen_keyboard", args={})

    # 🖱️ Cursor & Mouse
    if any(low == p for p in ("click", "left click", "single click")):
        return Call(type="click_mouse", args={"button": "left", "clicks": 1})
    if any(low == p for p in ("right click", "context menu")):
        return Call(type="click_mouse", args={"button": "right", "clicks": 1})
    if any(low == p for p in ("double click", "double left click")):
        return Call(type="click_mouse", args={"button": "left", "clicks": 2})
    if any(p in low for p in ("scroll down", "page down")):
        return Call(type="scroll_mouse", args={"direction": "down", "amount": 3})
    if any(p in low for p in ("scroll up", "page up")):
        return Call(type="scroll_mouse", args={"direction": "up", "amount": 3})
    if any(p in low for p in ("center cursor", "move cursor to center", "move mouse to center", "cursor center")):
        return Call(type="move_cursor", args={"x": "center"})
    if any(p in low for p in ("where is my cursor", "cursor position", "mouse position")):
        return Call(type="get_cursor_position", args={})

    # ⌨️ Direct Typing & Key Presses
    if low.startswith("type "):
        return Call(type="type_text", args={"text": t[5:].strip()})
    if any(low == p for p in ("press enter", "hit enter")):
        return Call(type="press_key", args={"key_name": "enter"})
    if any(low == p for p in ("press space", "hit space")):
        return Call(type="press_key", args={"key_name": "space"})
    if any(low == p for p in ("press escape", "press esc")):
        return Call(type="press_key", args={"key_name": "esc"})
    if any(low == p for p in ("press tab", "hit tab")):
        return Call(type="press_key", args={"key_name": "tab"})

    # Time & Date
    if any(p in low for p in ("what time", "what's the time", "current time", "what day is", "today's date", "what is the date")):
        return Call(type="get_time_date", args={})

    # Weather
    if "weather" in low:
        city = ""
        if " in " in low:
            city = low.split(" in ", 1)[1].strip("?., ")
        return Call(type="get_weather", args={"city": city})

    # Media controls
    if any(low == p or low.startswith(p + " ") for p in ("pause", "resume", "play music", "pause music", "stop music", "toggle media")):
        return Call(type="media_control", args={"action": "play"})
    if any(p in low for p in ("next song", "next track", "skip track", "skip song")):
        return Call(type="media_control", args={"action": "next"})
    if any(p in low for p in ("previous song", "previous track", "last song")):
        return Call(type="media_control", args={"action": "prev"})

    # Volume
    if any(p in low for p in ("volume up", "increase volume", "louder")):
        return Call(type="set_volume", args={"action": "up"})
    if any(p in low for p in ("volume down", "decrease volume", "lower volume", "quieter")):
        return Call(type="set_volume", args={"action": "down"})
    if any(p in low for p in ("mute volume", "unmute volume", "mute sound", "mute", "unmute")):
        return Call(type="set_volume", args={"action": "mute"})

    # Screenshot
    if "screenshot" in low:
        return Call(type="take_screenshot", args={})

    # Active Window / Open Windows
    if any(p in low for p in ("active window", "what window is this", "current window", "foreground window")):
        return Call(type="get_active_window", args={})
    if any(p in low for p in ("list open windows", "what windows are open", "open windows", "list windows")):
        return Call(type="list_open_windows", args={})

    # Clipboard
    if any(p in low for p in ("what's in my clipboard", "what did i copy", "read clipboard", "clipboard content")):
        return Call(type="get_clipboard", args={})

    # System Status
    if any(p in low for p in ("system status", "cpu status", "ram status", "computer status")):
        return Call(type="system_status", args={})

    # Windows / Tabs Close
    if low in ("close tab", "close current tab", "close this tab"):
        return Call(type="close_current_tab", args={})
    if low in ("close window", "close this window"):
        return Call(type="close_current_window", args={})
    if low.startswith("close tab"):
        return Call(type="close_current_tab", args={})
    if low.startswith("close window"):
        return Call(type="close_current_window", args={})
    if low.startswith("close "):
        return Call(type="close_app", args={"name": t[6:].strip()})

    # App Open
    for verb in ("open ", "launch ", "start ", "run "):
        if low.startswith(verb):
            return Call(type="open_installed_app", args={"name": t[len(verb):].strip()})

    if "refresh app" in low:
        return Call(type="refresh_app_index", args={})

    # 🌐 Browser — YouTube
    if any(p in low for p in ("play ", "play on youtube", "youtube play")):
        # Extract the query after "play"
        for prefix in ("play on youtube ", "youtube play ", "play "):
            if low.startswith(prefix):
                query = t[len(prefix):].strip()
                if query:
                    return Call(type="youtube_play", args={"query": query})

    # 🔍 Browser — Web search / read
    if any(p in low for p in ("search for ", "google ", "look up ", "search the web for ")):
        for prefix in ("search the web for ", "search for ", "google ", "look up "):
            if low.startswith(prefix):
                query = t[len(prefix):].strip()
                if query:
                    return Call(type="web_search", args={"query": query})

    # 🌐 Browser — Read current page
    if any(p in low for p in ("read the page", "read this page", "what does this page say", "read the website")):
        return Call(type="browser_read_page", args={})

    # 🌐 Browser — Navigate back
    if low in ("go back", "browser back", "previous page", "go to previous page"):
        return Call(type="browser_go_back", args={})

    # 🌐 Browser — Scroll in browser
    if any(p in low for p in ("scroll down the page", "page down in browser", "scroll up the page", "page up in browser")):
        direction = "up" if "up" in low else "down"
        return Call(type="browser_scroll", args={"direction": direction, "amount": 3})

    # 🌐 Browser — Close browser
    if low in ("close browser", "close the browser", "quit browser"):
        return Call(type="browser_close", args={})

    # 🌐 Browser — Current URL
    if any(p in low for p in ("what page am i on", "what website is this", "current url", "what url")):
        return Call(type="browser_get_url", args={})


    # ─── 🎵 SPOTIFY ─────────────────────────────────────────────────────────
    # "play <song> on spotify" / "play <song> in spotify"
    for pfx in ("play on spotify ", "play in spotify ", "spotify play "):
        if low.startswith(pfx):
            return Call(type="spotify_play_song", args={"query": t[len(pfx):].strip()})
    if low.startswith("play ") and ("spotify" in low or not any(b in low for b in ("youtube", "vlc", "browser"))):
        q = t[5:].strip()
        if q:
            return Call(type="smart_play", args={"query": q})
    if any(p in low for p in ("spotify pause", "pause spotify")):
        return Call(type="spotify_pause", args={})
    if any(p in low for p in ("spotify resume", "resume spotify", "continue spotify")):
        return Call(type="spotify_resume", args={})
    if any(p in low for p in ("spotify next", "next on spotify", "skip on spotify")):
        return Call(type="spotify_next", args={})
    if any(p in low for p in ("spotify previous", "previous on spotify", "spotify back", "back on spotify")):
        return Call(type="spotify_prev", args={})
    if any(p in low for p in ("what's playing", "what is playing", "current song", "what song is this", "now playing")):
        return Call(type="spotify_what_playing", args={})

    # "play <artist> on spotify" / "play playlist <name>"
    for pfx in ("play artist ", "play music by ", "play songs by "):
        if low.startswith(pfx):
            return Call(type="spotify_play_artist", args={"query": t[len(pfx):].strip()})
    for pfx in ("play playlist ", "play my playlist ", "start playlist "):
        if low.startswith(pfx):
            return Call(type="spotify_play_playlist", args={"query": t[len(pfx):].strip()})

    # ─── 📺 VLC ──────────────────────────────────────────────────────────────
    for pfx in ("play in vlc ", "vlc play ", "open in vlc "):
        if low.startswith(pfx):
            return Call(type="vlc_play_file", args={"filepath": t[len(pfx):].strip()})
    if any(p in low for p in ("pause vlc", "vlc pause")):
        return Call(type="vlc_pause", args={})
    if any(p in low for p in ("stop vlc", "vlc stop")):
        return Call(type="vlc_stop", args={})
    if any(p in low for p in ("vlc next", "next in vlc")):
        return Call(type="vlc_next", args={})
    if any(p in low for p in ("vlc previous", "previous in vlc", "vlc back")):
        return Call(type="vlc_prev", args={})

    # ─── 📁 FILE EXPLORER ────────────────────────────────────────────────────
    for pfx in ("open folder ", "go to folder ", "navigate to ", "open ", "show me "):
        if low.startswith(pfx):
            remainder = t[len(pfx):].strip()
            if any(kw in remainder.lower() for kw in ("folder", "desktop", "documents", "downloads", "pictures", "music", "videos", "my computer", "this pc", "drive", ":\\")):
                return Call(type="explorer_open_folder", args={"path": remainder})
    for pfx in ("find file ", "search for file ", "locate file "):
        if low.startswith(pfx):
            return Call(type="find_file", args={"name": t[len(pfx):].strip()})

    # ─── 💻 VS CODE ──────────────────────────────────────────────────────────
    for pfx in ("open in vs code ", "open in vscode ", "vs code open ", "code open "):
        if low.startswith(pfx):
            return Call(type="vscode_open", args={"path": t[len(pfx):].strip()})

    # ─── 🪟 WINDOW FOCUS & IN-APP SEARCH ────────────────────────────────────
    for pfx in ("focus on ", "switch to ", "bring up "):
        if low.startswith(pfx):
            return Call(type="focus_window", args={"title": t[len(pfx):].strip()})
    for pfx in ("search in ", "find in "):
        if low.startswith(pfx):
            # "search in chrome for cats" → app=chrome, query=cats
            rest = t[len(pfx):].strip()
            if " for " in rest:
                parts = rest.split(" for ", 1)
                return Call(type="app_search_in", args={"app": parts[0].strip(), "query": parts[1].strip()})

    return None


def run_tool(tool_type: str, args: dict):
    args = args or {}
    # Screen & Vision
    if tool_type == "see_screen": return tools.see_screen(args.get("prompt", ""))
    # Cursor & Mouse
    if tool_type == "get_cursor_position": return tools.get_cursor_position()
    if tool_type == "move_cursor": return tools.move_cursor(args.get("x", "center"), args.get("y"))
    if tool_type == "move_cursor_relative": return tools.move_cursor_relative(args.get("dx", 0), args.get("dy", 0))
    if tool_type == "click_mouse": return tools.click_mouse(args.get("button", "left"), args.get("clicks", 1), args.get("x"), args.get("y"))
    if tool_type == "scroll_mouse": return tools.scroll_mouse(args.get("direction", "down"), args.get("amount", 3))
    # Keyboard & On-Screen
    if tool_type == "type_text": return tools.type_text(args.get("text", ""))
    if tool_type == "press_key": return tools.press_key(args.get("key_name", ""))
    if tool_type == "press_hotkey": return tools.press_hotkey(args.get("combo", ""))
    if tool_type == "open_onscreen_keyboard": return tools.open_onscreen_keyboard()
    if tool_type == "close_onscreen_keyboard": return tools.close_onscreen_keyboard()
    # Apps & Windows
    if tool_type == "open_installed_app": return tools.open_installed_app(args.get("name", ""))
    if tool_type == "close_app": return tools.close_app(args.get("name", ""))
    if tool_type == "close_current_tab": return tools.close_current_tab()
    if tool_type == "close_current_window": return tools.close_current_window()
    if tool_type == "search_installed_apps": return tools.search_installed_apps(args.get("query", ""))
    if tool_type == "refresh_app_index": return tools.refresh_app_index()
    if tool_type == "system_status": return tools.system_status()
    if tool_type == "get_time_date": return tools.get_time_date()
    if tool_type == "get_weather": return tools.get_weather(args.get("city", ""))
    if tool_type == "media_control": return tools.media_control(args.get("action", ""))
    if tool_type == "set_volume": return tools.set_volume(args.get("action", ""))
    if tool_type == "take_screenshot": return tools.take_screenshot()
    if tool_type == "get_active_window": return tools.get_active_window()
    if tool_type == "list_open_windows": return tools.list_open_windows()
    if tool_type == "get_clipboard": return tools.get_clipboard()
    if tool_type == "set_clipboard": return tools.set_clipboard(args.get("text", ""))
    if tool_type == "open_web": return tools.open_web(args.get("query", ""))
    if tool_type == "save_memory": return tools.save_memory(args.get("key", ""), args.get("value", ""))
    if tool_type == "recall_memory": return tools.recall_memory(args.get("query", ""))
    # 🌐 Browser tools
    if tool_type == "youtube_play": return tools.youtube_play(args.get("query", ""))
    if tool_type == "web_search": return tools.web_search(args.get("query", ""))
    if tool_type == "browser_open": return tools.browser_open(args.get("url", ""))
    if tool_type == "browser_read_page": return tools.browser_read_page()
    if tool_type == "browser_click": return tools.browser_click(args.get("text", ""))
    if tool_type == "browser_fill": return tools.browser_fill(args.get("field", ""), args.get("value", ""))
    if tool_type == "browser_scroll": return tools.browser_scroll_page(args.get("direction", "down"), args.get("amount", 3))
    if tool_type == "browser_go_back": return tools.browser_go_back()
    if tool_type == "browser_get_url": return tools.browser_get_url()
    if tool_type == "browser_close": return tools.browser_close()
    # 🎵 Spotify
    if tool_type == "smart_play": return app_ctrl.smart_play(args.get("query", ""))
    if tool_type == "spotify_play_song": return app_ctrl.spotify_play_song(args.get("query", ""))
    if tool_type == "spotify_play_artist": return app_ctrl.spotify_play_artist(args.get("query", ""))
    if tool_type == "spotify_play_playlist": return app_ctrl.spotify_play_playlist(args.get("query", ""))
    if tool_type == "spotify_pause": return app_ctrl.spotify_pause()
    if tool_type == "spotify_resume": return app_ctrl.spotify_resume()
    if tool_type == "spotify_next": return app_ctrl.spotify_next()
    if tool_type == "spotify_prev": return app_ctrl.spotify_prev()
    if tool_type == "spotify_what_playing": return app_ctrl.spotify_what_playing()
    if tool_type == "spotify_set_volume": return app_ctrl.spotify_set_volume(args.get("level", 50))
    # 📺 VLC
    if tool_type == "vlc_play_file": return app_ctrl.vlc_play_file(args.get("filepath", ""))
    if tool_type == "vlc_pause": return app_ctrl.vlc_pause()
    if tool_type == "vlc_stop": return app_ctrl.vlc_stop()
    if tool_type == "vlc_next": return app_ctrl.vlc_next()
    if tool_type == "vlc_prev": return app_ctrl.vlc_prev()
    if tool_type == "vlc_set_volume": return app_ctrl.vlc_set_volume(args.get("level", 50))
    # 📁 File Explorer
    if tool_type == "explorer_open_folder": return app_ctrl.explorer_open_folder(args.get("path", ""))
    if tool_type == "explorer_open_path": return app_ctrl.explorer_open_path(args.get("path", ""))
    if tool_type == "find_file": return app_ctrl.find_file(args.get("name", ""), args.get("search_in", ""))
    # 💻 VS Code
    if tool_type == "vscode_open": return app_ctrl.vscode_open(args.get("path", ""))
    if tool_type == "vscode_new_file": return app_ctrl.vscode_new_file(args.get("filename", ""), args.get("content", ""))
    # 📝 Notepad
    if tool_type == "notepad_open": return app_ctrl.notepad_open(args.get("filepath"))
    if tool_type == "notepad_type_text": return app_ctrl.notepad_type_text(args.get("text", ""))
    if tool_type == "notepad_save": return app_ctrl.notepad_save(args.get("filepath"))
    # 🪟 Window Control
    if tool_type == "focus_window": return app_ctrl.focus_window(args.get("title", ""))
    if tool_type == "window_type_text": return app_ctrl.window_type_text(args.get("title", ""), args.get("text", ""))
    if tool_type == "app_search_in": return app_ctrl.app_search_in(args.get("app", ""), args.get("query", ""))



def speak(text: str):
    global _stop_event
    text = (text or "").strip()
    if not text:
        return
    if _stop_event.is_set():
        return  # already interrupted, skip this utterance
    cleaned = (
        text.replace("*", "")
        .replace("`", "")
        .replace("#", "")
        .replace("°C", " degrees Celsius")
        .replace("+", "")
    )
    try:
        model_path, config_path, speed = profile.get_voice_paths()
        r = subprocess.run(
            [
                str(PIPER_EXE),
                "-m", str(model_path),
                "-c", str(config_path),
                "-f", str(TTS_WAV),
                "--length_scale", str(speed)
            ],
            input=cleaned,
            text=True,
            encoding="utf-8",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if r.returncode != 0 or not TTS_WAV.exists():
            return
        if _stop_event.is_set():
            return  # interrupted before playback started

        # Start async (non-blocking) playback
        winsound.PlaySound(str(TTS_WAV), winsound.SND_FILENAME | winsound.SND_ASYNC)

        # Poll until done or interrupted — check every 50 ms
        # We use a short sleep loop; winsound gives no "done" callback so
        # we estimate duration and break early on _stop_event.
        import wave, contextlib
        duration = 0.0
        try:
            with contextlib.closing(wave.open(str(TTS_WAV))) as wf:
                duration = wf.getnframes() / wf.getframerate()
        except Exception:
            duration = 10.0  # fallback

        deadline = time.time() + duration + 0.5
        while time.time() < deadline:
            if _stop_event.is_set():
                winsound.PlaySound(None, winsound.SND_PURGE)  # stop immediately
                return
            time.sleep(0.05)

    except Exception as e:
        print("TTS error:", e)


def interrupt_response():
    """Stop any in-progress TTS and pending Ollama request."""
    global _ollama_session
    _stop_event.set()
    # Kill audio immediately
    try:
        winsound.PlaySound(None, winsound.SND_PURGE)
    except Exception:
        pass
    # Abort the Ollama HTTP request if one is in flight
    with _ollama_session_lock:
        s = _ollama_session
    if s is not None:
        try:
            s.close()
        except Exception:
            pass


def resample_linear(x, orig_sr, target_sr):
    if orig_sr == target_sr:
        return x.astype(np.float32, copy=False)
    duration = len(x) / orig_sr
    t_orig = np.linspace(0, duration, num=len(x), endpoint=False)
    t_new = np.linspace(0, duration, num=int(duration * target_sr), endpoint=False)
    return np.interp(t_new, t_orig, x).astype(np.float32)


def downsample_48k_to_16k(x48):
    x48 = x48[: (len(x48) // 3) * 3]
    return x48.reshape(-1, 3).mean(axis=1).astype(np.float32)


def record_command(device_index, max_wait, hud):
    q = queue.Queue()
    dev = sd.query_devices(device_index)
    sr = int(dev["default_samplerate"])

    def cb(indata, frames, time_info, status):
        q.put(indata[:, 0].astype(np.float32).copy())

    audio = []
    started = False
    last = None
    start = time.time()

    with sd.InputStream(device=device_index, channels=1, samplerate=sr, dtype="float32", callback=cb):
        while hud.running:
            now = time.time()
            if now - start > MAX_SECONDS:
                break
            if not started and (now - start) > max_wait:
                break
            if started and (now - last) > SILENCE_SECONDS_TO_STOP:
                break

            try:
                mono = q.get(timeout=0.08)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(mono * mono)) + 1e-12)
            if rms >= RMS_THRESHOLD:
                started = True
                last = time.time()
            if started:
                audio.append(mono)

    if not audio:
        return np.zeros((0,), dtype=np.float32), sr
    return np.concatenate(audio), sr


def listen_for_wakeword(wake, hud):
    mic_idx = tools.get_best_microphone_index()
    q = queue.Queue()
    dev = sd.query_devices(mic_idx)
    sr = int(dev["default_samplerate"])
    ratio = max(1, int(round(sr / TARGET_SR)))
    chunk_size = CHUNK_16K * ratio

    def cb(indata, frames, time_info, status):
        q.put(indata[:, 0].astype(np.float32).copy())

    with sd.InputStream(device=mic_idx, channels=1, samplerate=sr, blocksize=chunk_size, dtype="float32", callback=cb):
        while hud.running:
            if hud.pop_manual_trigger():
                wake.reset()
                interrupt_response()   # stop TTS if Jarvis was mid-speech
                return "manual"

            try:
                x_in = q.get(timeout=0.1)
            except queue.Empty:
                continue

            if sr == 48000:
                x16 = downsample_48k_to_16k(x_in)
            elif sr == 16000:
                x16 = x_in
            else:
                x16 = resample_linear(x_in, sr, TARGET_SR)

            x16_pcm = np.clip(x16 * 32767.0, -32768, 32767).astype(np.int16)
            scores = wake.predict(x16_pcm)
            score = float(scores.get(WAKE_MODEL_NAME, 0.0))
            if score >= WAKE_TRIGGER_THRESHOLD:
                wake.reset()
                interrupt_response()   # stop TTS if Jarvis was mid-speech
                return "wakeword"

    return None


def backend_loop(hud):
    user_name = profile.get_user_name()
    hud.set_state("IDLE", jarvis_msg=f"Say 'Hey Jarvis' or click MIC")

    # Start pre-warming primary models in background for zero cold-start delay
    router.prewarm_models()

    try:
        wake = WakeModel(wakeword_models=[WAKE_MODEL_NAME], inference_framework="onnx")
    except Exception:
        wake = WakeModel(inference_framework="onnx")

    try:
        whisper = WhisperModel("small.en", device="cuda", compute_type="float16")
    except Exception as e:
        print(f"Whisper CUDA fallback to CPU: {e}")
        whisper = WhisperModel("base.en", device="cpu", compute_type="int8")

    messages = [{"role": "system", "content": get_system_prompt()}]
    mic_idx = tools.get_best_microphone_index()

    while hud.running:
        # Reset interrupt flag at the start of every new listen cycle
        _stop_event.clear()
        hud.set_state("IDLE")
        trigger = listen_for_wakeword(wake, hud)
        if not hud.running or trigger is None:
            break

        # interrupt_response() was already called inside listen_for_wakeword; just clear the flag
        _stop_event.clear()

        user_name = profile.get_user_name()
        hud.set_state("LISTENING", jarvis_msg=f"Yes, {user_name}?")
        speak(f"Yes, {user_name}?")

        while hud.running:
            _stop_event.clear()
            hud.set_state("LISTENING")
            x, sr = record_command(mic_idx, max_wait=FOLLOWUP_WINDOW_SECONDS, hud=hud)
            if len(x) < 1000 or not hud.running:
                break

            x16 = resample_linear(x, sr, TARGET_SR)
            try:
                segs, _ = whisper.transcribe(
                    x16,
                    vad_filter=True,
                    vad_parameters={
                        "min_silence_duration_ms": 600,
                        "speech_pad_ms": 400,
                        "threshold": 0.3,
                    },
                    beam_size=5,
                    language="en",
                    condition_on_previous_text=False,
                    temperature=0.0,
                    no_speech_threshold=0.4,
                    log_prob_threshold=-0.8,
                    initial_prompt="Jarvis, open, close, play, stop, pause, volume up, volume down, screenshot, search, write, tell me, what time, weather",
                    word_timestamps=False,
                    without_timestamps=True,
                    compression_ratio_threshold=2.4,
                )
                text = " ".join(s.text.strip() for s in segs).strip()
            except Exception as e:
                print("Transcription error:", e)
                break

            if not text:
                break

            hud.set_state("THINKING", user_msg=text)

            # Check direct intent overrides first for instant response
            ov = direct_intent_override(text)
            if ov is not None:
                res = run_tool(ov.type, ov.args or {})
                if not _stop_event.is_set():
                    hud.set_state("RESPONDING", jarvis_msg=res)
                    speak(res)
                continue

            # ── Code-writing special path with specialized Coder model ─────
            if router.is_coding_intent(text):
                # 1. Tell user what's happening
                hud.set_state("RESPONDING", jarvis_msg=f"Opening Notepad to write that code, {user_name}.")
                speak(f"Certainly, {user_name}. Opening Notepad and writing the code now.")

                # 2. Open Notepad
                run_tool("open_installed_app", {"name": "Notepad"})
                time.sleep(1.5)   # give Notepad time to open

                # 3. Generate code with dedicated Coder model + code-focused prompt
                code_messages = [
                    {"role": "system", "content": get_code_system_prompt()},
                    {"role": "user",   "content": text},
                ]
                hud.set_state("THINKING", user_msg=text)
                coder_model = router.get_model_for_role("coder")
                print(f"[Jarvis] Coding task routed to: {coder_model}")
                try:
                    raw_code = ollama_chat(code_messages, model=coder_model, num_predict=400, temperature=0.1)
                except Exception:
                    if _stop_event.is_set():
                        break
                    speak(f"My apologies {user_name}, I could not generate the code.")
                    continue

                if _stop_event.is_set():
                    break

                # 4. Type the code into Notepad
                try:
                    code_call = Call(**extract_json(raw_code))
                    if code_call.type == "type_text":
                        run_tool("type_text", code_call.args or {})
                        hud.set_state("RESPONDING", jarvis_msg=f"Code written in Notepad, {user_name}.")
                        speak(f"All done, {user_name}. The code is ready in Notepad.")
                    else:
                        speak(f"The code is ready, {user_name}.")
                except Exception:
                    # Fallback: raw text response
                    speak(f"The code has been written to Notepad, {user_name}.")
                continue
            # ──────────────────────────────────────────────────────────────

            # Pick the optimal model automatically (fast, reasoning, etc.)
            chosen_model, role = router.route_request(text)
            print(f"[Jarvis] Query routed to '{chosen_model}' ({role})")

            token_budget = 200 if role == "reasoning" else 120
            temp = 0.5 if role == "reasoning" else 0.2

            # Query Ollama LLM
            system_prompt = get_system_prompt()
            turn = trim_history([{"role": "system", "content": system_prompt}] + messages[1:] + [{"role": "user", "content": text}])
            try:
                raw = ollama_chat(turn, model=chosen_model, num_predict=token_budget, temperature=temp)
            except Exception as e:
                if _stop_event.is_set():
                    # Interrupted — silently go back to listening
                    break
                err_msg = f"Sorry {user_name}, I could not reach my reasoning model."
                hud.set_state("RESPONDING", jarvis_msg=err_msg)
                speak(err_msg)
                break

            # If interrupted while Ollama was thinking, skip the response
            if _stop_event.is_set():
                break

            try:
                call = Call(**extract_json(raw))
            except Exception:
                hud.set_state("RESPONDING", jarvis_msg=raw)
                speak(raw)
                continue

            if call.type == "final":
                hud.set_state("RESPONDING", jarvis_msg=call.text or "")
                speak(call.text or "")
                continue

            res = run_tool(call.type, call.args or {})
            if not _stop_event.is_set():
                hud.set_state("RESPONDING", jarvis_msg=res)
                speak(res)


def _interrupt_watcher(hud):
    """Dedicated thread: polls hud for interrupt signals every 50 ms.
    Works even while speak() or ollama_chat() is blocking the backend thread."""
    while hud.running:
        if hud.pop_interrupt_request():
            interrupt_response()
        time.sleep(0.05)


def main():
    hud = JarvisHUD(1366, 768)
    backend_thread = threading.Thread(target=backend_loop, args=(hud,), daemon=True)
    backend_thread.start()
    # Separate thread so interrupts fire immediately regardless of backend state
    interrupt_thread = threading.Thread(target=_interrupt_watcher, args=(hud,), daemon=True)
    interrupt_thread.start()
    while hud.running:
        hud.render()


if __name__ == "__main__":
    main()