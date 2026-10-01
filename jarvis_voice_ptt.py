import os
import sys
import json
import time
import queue
import threading
import subprocess
import winsound
from pathlib import Path

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

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

import requests
import numpy as np
import sounddevice as sd
from pydantic import BaseModel
from faster_whisper import WhisperModel
from pynput import keyboard
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

import jarvis_tools as tools
import jarvis_profile as profile
import jarvis_router as router

console = Console()

TARGET_SR = 16000
PIPER_EXE = Path(r"C:\jarvis-local\piper\piper_windows_amd64\piper\piper.exe")
TTS_WAV = Path(r"C:\jarvis-local\piper\jarvis_reply.wav")


def get_system_prompt() -> str:
    user_name = profile.get_user_name()
    return f"""You are JARVIS, a sophisticated, loyal, and intelligent AI companion running locally on Windows.
Your creator and user is {user_name}. Always address him warmly and respectfully as {user_name}.
Output ONLY valid JSON in ONE of these formats:
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
{{"type":"final","text":"your normal response"}}
Rules: Output ONLY JSON. Keep spoken responses concise and natural.
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


def ollama_chat(messages, model: str = None, format: str = "json", num_predict: int = 150):
    return router.chat_routed(
        messages=messages,
        model=model,
        format=format,
        num_predict=num_predict,
        timeout=120
    )


def direct_intent_override(text: str):
    t = text.strip()
    low = t.lower()
    user_name = profile.get_user_name()

    # 👤 Personal Identity & Greetings
    if any(p in low for p in ("who are you", "what is your name", "what's your name")):
        return Call(type="final", text=f"I am JARVIS, your personal artificial intelligence, {user_name}. Standing by.")
    if any(p in low for p in ("who am i", "what is my name", "what's my name", "do you know me")):
        return Call(type="final", text=f"You are {user_name}, my creator and boss.")
    if any(low == p for p in ("hello", "hi jarvis", "hey jarvis", "hello jarvis", "greetings")):
        return Call(type="final", text=f"Hello, {user_name}. How may I be of service?")
    if any(p in low for p in ("how are you", "how are you doing", "how do you feel")):
        return Call(type="final", text=f"All systems are operating at peak efficiency, {user_name}. Ready for your command.")
    if any(low == p or low.startswith(p + " ") for p in ("thank you", "thanks", "thanks jarvis")):
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

    if any(p in low for p in ("what time", "what's the time", "current time", "what day is", "today's date", "what is the date")):
        return Call(type="get_time_date", args={})

    if "weather" in low:
        city = ""
        if " in " in low:
            city = low.split(" in ", 1)[1].strip("?., ")
        return Call(type="get_weather", args={"city": city})

    if any(low == p or low.startswith(p + " ") for p in ("pause", "resume", "play music", "pause music", "stop music", "toggle media")):
        return Call(type="media_control", args={"action": "play"})
    if any(p in low for p in ("next song", "next track", "skip track", "skip song")):
        return Call(type="media_control", args={"action": "next"})
    if any(p in low for p in ("previous song", "previous track", "last song")):
        return Call(type="media_control", args={"action": "prev"})

    if any(p in low for p in ("volume up", "increase volume", "louder")):
        return Call(type="set_volume", args={"action": "up"})
    if any(p in low for p in ("volume down", "decrease volume", "lower volume", "quieter")):
        return Call(type="set_volume", args={"action": "down"})
    if any(p in low for p in ("mute volume", "unmute volume", "mute sound", "mute", "unmute")):
        return Call(type="set_volume", args={"action": "mute"})

    if "screenshot" in low:
        return Call(type="take_screenshot", args={})

    if any(p in low for p in ("active window", "what window is this", "current window", "foreground window")):
        return Call(type="get_active_window", args={})
    if any(p in low for p in ("list open windows", "what windows are open", "open windows", "list windows")):
        return Call(type="list_open_windows", args={})

    if any(p in low for p in ("what's in my clipboard", "what did i copy", "read clipboard", "clipboard content")):
        return Call(type="get_clipboard", args={})

    if any(p in low for p in ("system status", "cpu status", "ram status", "computer status")):
        return Call(type="system_status", args={})

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

    for verb in ("open ", "launch ", "start ", "run "):
        if low.startswith(verb):
            return Call(type="open_installed_app", args={"name": t[len(verb):].strip()})

    if "refresh app" in low:
        return Call(type="refresh_app_index", args={})

    return None


def run_tool(tool_type: str, args: dict):
    args = args or {}
    if tool_type == "see_screen": return tools.see_screen(args.get("prompt", ""))
    if tool_type == "get_cursor_position": return tools.get_cursor_position()
    if tool_type == "move_cursor": return tools.move_cursor(args.get("x", "center"), args.get("y"))
    if tool_type == "move_cursor_relative": return tools.move_cursor_relative(args.get("dx", 0), args.get("dy", 0))
    if tool_type == "click_mouse": return tools.click_mouse(args.get("button", "left"), args.get("clicks", 1), args.get("x"), args.get("y"))
    if tool_type == "scroll_mouse": return tools.scroll_mouse(args.get("direction", "down"), args.get("amount", 3))
    if tool_type == "type_text": return tools.type_text(args.get("text", ""))
    if tool_type == "press_key": return tools.press_key(args.get("key_name", ""))
    if tool_type == "press_hotkey": return tools.press_hotkey(args.get("combo", ""))
    if tool_type == "open_onscreen_keyboard": return tools.open_onscreen_keyboard()
    if tool_type == "close_onscreen_keyboard": return tools.close_onscreen_keyboard()
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
    return "Unknown tool."


def speak(text: str):
    text = (text or "").strip()
    if not text:
        return
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
        if r.returncode == 0 and TTS_WAV.exists():
            winsound.PlaySound(str(TTS_WAV), winsound.SND_FILENAME)
    except Exception as e:
        console.print(f"[red]TTS error: {e}[/red]")


def resample_linear(x, orig_sr, target_sr):
    if orig_sr == target_sr:
        return x.astype(np.float32, copy=False)
    duration = len(x) / orig_sr
    t_orig = np.linspace(0, duration, num=len(x), endpoint=False)
    t_new = np.linspace(0, duration, num=int(duration * target_sr), endpoint=False)
    return np.interp(t_new, t_orig, x).astype(np.float32)


class PushToTalkEngine:
    def __init__(self):
        self.is_recording = False
        self.audio_chunks = []
        self.mic_idx = tools.get_best_microphone_index()
        dev = sd.query_devices(self.mic_idx)
        self.sr = int(dev["default_samplerate"])
        self.stream = None
        self.lock = threading.Lock()

        console.print("[cyan]Loading Faster-Whisper model...[/cyan]")
        try:
            self.whisper = WhisperModel("small.en", device="cuda", compute_type="float16")
            console.print("[green]Whisper loaded on GPU (CUDA)![/green]")
        except Exception as e:
            console.print(f"[yellow]CUDA failed ({e}), loading on CPU...[/yellow]")
            self.whisper = WhisperModel("base.en", device="cpu", compute_type="int8")

        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    def start_recording(self):
        with self.lock:
            if self.is_recording:
                return
            self.is_recording = True
            self.audio_chunks = []

        console.print("\n[bold red]● RECORDING... (Release F8 to process)[/bold red]")

        def audio_cb(indata, frames, time_info, status):
            if self.is_recording:
                self.audio_chunks.append(indata[:, 0].astype(np.float32).copy())

        self.stream = sd.InputStream(
            device=self.mic_idx,
            channels=1,
            samplerate=self.sr,
            dtype="float32",
            callback=audio_cb
        )
        self.stream.start()

    def stop_recording_and_process(self):
        with self.lock:
            if not self.is_recording:
                return
            self.is_recording = False

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        console.print("[bold yellow]Transcribing...[/bold yellow]")
        if not self.audio_chunks:
            console.print("[dim]No audio captured.[/dim]")
            return

        x = np.concatenate(self.audio_chunks)
        if len(x) < 1000:
            console.print("[dim]Audio too short.[/dim]")
            return

        x16 = resample_linear(x, self.sr, TARGET_SR)
        try:
            segs, _ = self.whisper.transcribe(
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
            console.print(f"[red]Whisper error: {e}[/red]")
            return

        if not text:
            console.print("[dim]Nothing understood.[/dim]")
            return

        user_name = profile.get_user_name()
        console.print(f"[bold cyan]{user_name}:[/bold cyan] {text}")

        # Check direct intent overrides
        ov = direct_intent_override(text)
        if ov is not None:
            res = run_tool(ov.type, ov.args or {})
            console.print(f"[bold green]Jarvis:[/bold green] {res}")
            speak(res)
            return

        # Intelligent dynamic model routing
        chosen_model, role = router.route_request(text)
        console.print(f"[dim]Routing to '{chosen_model}' ({role})...[/dim]")

        token_budget = 200 if role == "reasoning" else 120
        turn = [{"role": "system", "content": get_system_prompt()}] + self.messages[1:] + [{"role": "user", "content": text}]
        try:
            raw = ollama_chat(turn, model=chosen_model, num_predict=token_budget)
        except Exception as e:
            console.print(f"[red]Ollama error: {e}[/red]")
            return

        try:
            call = Call(**extract_json(raw))
        except Exception:
            console.print(f"[bold green]Jarvis:[/bold green] {raw}")
            speak(raw)
            return

        if call.type == "final":
            reply = call.text or ""
            console.print(f"[bold green]Jarvis:[/bold green] {reply}")
            speak(reply)
            return

        res = run_tool(call.type, call.args or {})
        console.print(f"[bold magenta]Action Result:[/bold magenta] {res}")
        speak(res)


def main():
    console.print(Panel.fit(
        "[bold cyan]J.A.R.V.I.S. Push-To-Talk Voice Assistant[/bold cyan]\n"
        "[white]• Press and [bold yellow]HOLD F8[/bold yellow] to speak, release to send.[/white]\n"
        "[white]• Press [bold red]Ctrl+C[/bold red] in this terminal to exit.[/white]",
        border_style="cyan"
    ))

    ptt = PushToTalkEngine()
    key_is_down = False

    def on_press(key):
        nonlocal key_is_down
        if key == keyboard.Key.f8 and not key_is_down:
            key_is_down = True
            threading.Thread(target=ptt.start_recording, daemon=True).start()

    def on_release(key):
        nonlocal key_is_down
        if key == keyboard.Key.f8 and key_is_down:
            key_is_down = False
            threading.Thread(target=ptt.stop_recording_and_process, daemon=True).start()

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            console.print("\n[yellow]Shutting down Jarvis PTT...[/yellow]")


if __name__ == "__main__":
    main()