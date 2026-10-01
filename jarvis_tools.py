import os
import time
import base64
import ctypes
import datetime
import subprocess
import webbrowser
import urllib.parse
from pathlib import Path

import psutil
import requests
from PIL import ImageGrab

import jarvis_memory as memory
import jarvis_apps

WORKSPACE = Path.home() / "JarvisWorkspace"
WORKSPACE.mkdir(parents=True, exist_ok=True)

ALLOWED_APPS = {
    "notepad": "notepad",
    "calc": "calc",
    "mspaint": "mspaint",
    "explorer": "explorer",
    "chrome": "chrome",
    "firefox": "firefox",
    "code": "code",
}

# Windows Virtual-Key Codes
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800


def get_best_microphone_index() -> int:
    """
    Auto-detect the best input microphone index.
    Prefers WASAPI Microphone Array / Microphone, falls back to default.
    """
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        for idx, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                name = d.get("name", "").lower()
                host = sd.query_hostapis(d.get("hostapi", 0)).get("name", "").lower()
                if "wasapi" in host and ("microphone array" in name or "microphone" in name):
                    return idx
        for idx, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0:
                host = sd.query_hostapis(d.get("hostapi", 0)).get("name", "").lower()
                if "wasapi" in host:
                    return idx
        default_in = sd.default.device[0]
        if default_in is not None and default_in >= 0:
            return default_in
    except Exception:
        pass
    return 0


# ==========================================
# 👁️ SCREEN VISION & INSPECTION
# ==========================================

def get_available_vision_model() -> str | None:
    """Checks if any vision-capable model is loaded in Ollama."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            names = [m.get("name", "").split(":")[0] for m in r.json().get("models", [])]
            for candidate in ("moondream", "llama3.2-vision", "llava", "minicpm-v", "bakllava"):
                if candidate in names:
                    return candidate
    except Exception:
        pass
    return None


def see_screen(prompt: str = "") -> str:
    """
    Captures the current screen and uses a local vision model to describe
    and answer questions about what is visible on the screen.
    """
    shots_dir = WORKSPACE / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    img_path = shots_dir / "screen_eye.jpg"
    captured = False

    try:
        img = ImageGrab.grab()
        img.thumbnail((1024, 768))
        img.save(img_path, format="JPEG", quality=85)
        captured = True
    except Exception:
        captured = False

    if captured and img_path.exists():
        v_model = get_available_vision_model()
        if v_model:
            try:
                with open(img_path, "rb") as f:
                    b64_img = base64.b64encode(f.read()).decode("utf-8")

                query = prompt.strip() if prompt else "Briefly describe what is currently open on this screen in 1 or 2 concise sentences."
                r = requests.post(
                    "http://localhost:11434/api/chat",
                    json={
                        "model": v_model,
                        "messages": [
                            {
                                "role": "user",
                                "content": query,
                                "images": [b64_img]
                            }
                        ],
                        "stream": False
                    },
                    timeout=30
                )
                if r.status_code == 200:
                    answer = r.json().get("message", {}).get("content", "").strip()
                    cleaned = answer.replace("*", "").replace("\n", " ").strip()
                    if cleaned:
                        return cleaned
            except Exception:
                pass

    active = get_active_window()
    windows = list_open_windows()
    return f"{active} {windows}"


# ==========================================
# 🖱️ CURSOR & MOUSE CONTROLS
# ==========================================

def get_cursor_position() -> str:
    """Returns the current mouse cursor coordinates and screen size."""
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        return f"Cursor is at coordinate {pt.x}, {pt.y} on your {sw} by {sh} display."
    except Exception:
        return "Cursor coordinates unavailable."


def move_cursor(x: int | str = "center", y: int | str = None) -> str:
    """Moves the mouse cursor to coordinates or named screen positions."""
    try:
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)

        if isinstance(x, str):
            low = x.lower().strip()
            if "center" in low or "middle" in low:
                tx, ty = sw // 2, sh // 2
            elif "top left" in low:
                tx, ty = 120, 100
            elif "top right" in low:
                tx, ty = sw - 120, 100
            elif "bottom left" in low:
                tx, ty = 120, sh - 100
            elif "bottom right" in low:
                tx, ty = sw - 120, sh - 100
            elif "," in low:
                parts = low.split(",")
                tx, ty = int(float(parts[0].strip())), int(float(parts[1].strip()))
            else:
                tx, ty = sw // 2, sh // 2
        else:
            tx = int(x)
            ty = int(y if y is not None else sh // 2)

        ctypes.windll.user32.SetCursorPos(tx, ty)
        return f"Moved cursor to {tx}, {ty}."
    except Exception:
        return "Failed to move cursor."


def move_cursor_relative(dx: int = 0, dy: int = 0) -> str:
    """Moves the cursor relative to its current position."""
    try:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        nx = pt.x + int(dx)
        ny = pt.y + int(dy)
        ctypes.windll.user32.SetCursorPos(nx, ny)
        return f"Moved cursor by {dx}, {dy}."
    except Exception:
        return "Failed to shift cursor."


def click_mouse(button: str = "left", clicks: int = 1, x: int = None, y: int = None) -> str:
    """Clicks the left or right mouse button, supports single and double click."""
    try:
        user32 = ctypes.windll.user32
        if x is not None and y is not None:
            user32.SetCursorPos(int(x), int(y))
            time.sleep(0.05)

        btn = (button or "left").lower().strip()
        num_clicks = int(clicks) if clicks else 1

        for i in range(num_clicks):
            if "right" in btn:
                user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            else:
                user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            if i < num_clicks - 1:
                time.sleep(0.08)

        if num_clicks == 2:
            return f"Double-clicked {btn} mouse button."
        return f"Clicked {btn} mouse button."
    except Exception:
        return "Failed to click mouse."


def scroll_mouse(direction: str = "down", amount: int = 3) -> str:
    """Scrolls mouse wheel up or down."""
    try:
        user32 = ctypes.windll.user32
        steps = int(amount) if amount else 3
        delta = 120 * steps if "up" in (direction or "").lower() else -120 * steps
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, delta, 0)
        dir_name = "up" if delta > 0 else "down"
        return f"Scrolled {dir_name}."
    except Exception:
        return "Failed to scroll."


# ==========================================
# ⌨️ KEYBOARD & ON-SCREEN CONTROLS
# ==========================================

def type_text(text: str) -> str:
    """Types text into the currently focused window using clipboard paste."""
    text = (text or "").strip()
    if not text:
        return "No text provided to type."
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()

        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press('v')
            kb.release('v')
        return f"Typed: {text}"
    except Exception:
        try:
            from pynput.keyboard import Controller
            kb = Controller()
            kb.type(text)
            return f"Typed: {text}"
        except Exception:
            return "Failed to type text."


def press_key(key_name: str) -> str:
    """Presses a single keyboard key (e.g., enter, tab, space, esc, backspace)."""
    k = (key_name or "").lower().strip()
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        key_map = {
            "enter": Key.enter,
            "return": Key.enter,
            "space": Key.space,
            "tab": Key.tab,
            "esc": Key.esc,
            "escape": Key.esc,
            "backspace": Key.backspace,
            "delete": Key.delete,
            "up": Key.up,
            "down": Key.down,
            "left": Key.left,
            "right": Key.right,
            "home": Key.home,
            "end": Key.end,
            "page_up": Key.page_up,
            "page_down": Key.page_down,
            "caps_lock": Key.caps_lock,
        }
        if k in key_map:
            kb.press(key_map[k])
            kb.release(key_map[k])
            return f"Pressed {k}."
        elif len(k) == 1:
            kb.press(k)
            kb.release(k)
            return f"Pressed {k}."
        return f"Unknown key {k}."
    except Exception:
        return "Failed to press key."


def press_hotkey(combo: str) -> str:
    """Presses keyboard shortcuts like 'ctrl+c', 'ctrl+v', 'alt+tab', 'win+d'."""
    combo = (combo or "").lower().strip().replace(" ", "")
    parts = combo.split("+")
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        mod_map = {
            "ctrl": Key.ctrl,
            "control": Key.ctrl,
            "alt": Key.alt,
            "shift": Key.shift,
            "win": Key.cmd,
            "cmd": Key.cmd,
            "windows": Key.cmd,
        }
        key_map = {
            "enter": Key.enter,
            "tab": Key.tab,
            "esc": Key.esc,
            "space": Key.space,
            "backspace": Key.backspace,
            "delete": Key.delete,
        }

        active_mods = []
        for p in parts[:-1]:
            if p in mod_map:
                active_mods.append(mod_map[p])

        final_part = parts[-1]
        final_key = mod_map.get(final_part, key_map.get(final_part, final_part))

        for m in active_mods:
            kb.press(m)
        kb.press(final_key)
        kb.release(final_key)
        for m in reversed(active_mods):
            kb.release(m)

        return f"Pressed shortcut {combo}."
    except Exception:
        return "Failed to trigger shortcut."


def open_onscreen_keyboard() -> str:
    """Opens the Windows On-Screen Keyboard (osk.exe)."""
    try:
        subprocess.Popen(["cmd", "/c", "start", "osk.exe"])
        return "Opened on-screen keyboard."
    except Exception:
        return "Failed to open on-screen keyboard."


def close_onscreen_keyboard() -> str:
    """Closes the Windows On-Screen Keyboard (osk.exe)."""
    try:
        closed = False
        for proc in psutil.process_iter(['name']):
            if (proc.info['name'] or '').lower() == 'osk.exe':
                proc.terminate()
                closed = True
        return "Closed on-screen keyboard." if closed else "On-screen keyboard was not open."
    except Exception:
        return "Failed to close on-screen keyboard."


# ==========================================
# 🚀 APPS & WINDOW CONTROLS
# ==========================================

def open_app(app_key: str) -> str:
    app_key = (app_key or "").lower().strip()
    if app_key not in ALLOWED_APPS:
        return f"App '{app_key}' is not in the allow-list."
    try:
        subprocess.Popen(["cmd", "/c", "start", "", ALLOWED_APPS[app_key]])
        return f"Opened {app_key}."
    except Exception:
        return f"Could not open {app_key}."


def refresh_app_index() -> str:
    idx = jarvis_apps.refresh_index()
    return f"Indexed {len(idx)} installed applications."


def search_installed_apps(query: str) -> str:
    matches = jarvis_apps.search_apps(query, limit=5)
    if not matches:
        return f"No matches found for '{query}'."
    names = [m["name"] for m in matches]
    return f"Found applications: {', '.join(names)}."


def open_installed_app(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "No application name provided."
    r = jarvis_apps.open_app(name)
    if r.startswith("Could not find") or r.startswith("Not sure"):
        jarvis_apps.refresh_index()
        r = jarvis_apps.open_app(name)
    return r


def create_file(relative_path: str, content: str = "") -> str:
    rel = (relative_path or "").strip().replace("\\", "/").lstrip("/")
    lowered = rel.lower()
    for prefix in ("workspace/", "jarvisworkspace/"):
        if lowered.startswith(prefix):
            rel = rel[len(prefix):]
            break
    if ":" in rel or rel.startswith("\\\\") or rel.startswith("//"):
        return "Absolute paths are not allowed."
    rel = rel.rstrip("/")
    if not rel:
        return "Invalid filename."
    p = Path(rel)
    if p.suffix == "":
        rel = rel + ".txt"
    target = (WORKSPACE / rel).resolve()
    if WORKSPACE not in target.parents and target != WORKSPACE:
        return "Path outside workspace is not allowed."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content or "", encoding="utf-8")
    filename = Path(rel).name
    return f"Created file {filename} in your workspace."


def system_status() -> str:
    cpu = psutil.cpu_percent(interval=0.3)
    mem = psutil.virtual_memory()
    return f"CPU usage is at {int(cpu)} percent, and RAM usage is at {int(mem.percent)} percent."


def get_time_date() -> str:
    now = datetime.datetime.now()
    return now.strftime("Today is %A, %B %d, %Y, and the current time is %I:%M %p.")


def get_weather(city: str = "") -> str:
    city = (city or "").strip()
    try:
        if city:
            url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%C,+%t+(feels+like+%f)"
        else:
            url = "https://wttr.in/?format=%C,+%t+(feels+like+%f)"
        resp = requests.get(url, timeout=4, headers={"User-Agent": "curl/7.68.0"})
        if resp.status_code == 200 and resp.text:
            text = resp.text.strip()
            if ":" in text:
                text = text.split(":", 1)[1].strip()
            cleaned = text.replace("°C", " degrees Celsius").replace("+", "")
            prefix = f"In {city}, it is " if city else "It is currently "
            return f"{prefix}{cleaned}."
        return "Could not retrieve weather right now."
    except Exception:
        return "Weather service is currently unavailable."


def media_control(action: str) -> str:
    action = (action or "").lower().strip()
    try:
        if any(w in action for w in ("play", "pause", "resume", "space")):
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)
            return "Toggled media playback."
        elif any(w in action for w in ("next", "skip", "forward")):
            ctypes.windll.user32.keybd_event(VK_MEDIA_NEXT_TRACK, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_NEXT_TRACK, 0, KEYEVENTF_KEYUP, 0)
            return "Skipped to next track."
        elif any(w in action for w in ("prev", "previous", "back", "replay")):
            ctypes.windll.user32.keybd_event(VK_MEDIA_PREV_TRACK, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_PREV_TRACK, 0, KEYEVENTF_KEYUP, 0)
            return "Went to previous track."
        elif "stop" in action:
            ctypes.windll.user32.keybd_event(VK_MEDIA_STOP, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_MEDIA_STOP, 0, KEYEVENTF_KEYUP, 0)
            return "Stopped media."
        return "Unknown media command."
    except Exception:
        return "Failed to control media."


def set_volume(action: str) -> str:
    action = (action or "").lower().strip()
    try:
        if "up" in action:
            for _ in range(5):
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_UP, 0, KEYEVENTF_KEYUP, 0)
            return "Volume increased."
        if "down" in action:
            for _ in range(5):
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, 0, 0)
                ctypes.windll.user32.keybd_event(VK_VOLUME_DOWN, 0, KEYEVENTF_KEYUP, 0)
            return "Volume decreased."
        if "mute" in action:
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, 0, 0)
            ctypes.windll.user32.keybd_event(VK_VOLUME_MUTE, 0, KEYEVENTF_KEYUP, 0)
            return "Volume muted."
        return "Unknown volume command."
    except Exception:
        return "Volume adjustment failed."


def take_screenshot() -> str:
    shots_dir = WORKSPACE / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    filename = shots_dir / f"screenshot_{int(time.time())}.png"
    img = ImageGrab.grab()
    img.save(filename)
    return "Screenshot captured and saved to your workspace."


def get_clipboard() -> str:
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                return f"Clipboard contains: {data}" if data else "Clipboard is empty."
            return "Clipboard contains non-text data."
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return "Failed to read clipboard."


def set_clipboard(text: str) -> str:
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text or "", win32clipboard.CF_UNICODETEXT)
            return "Copied to clipboard."
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return "Failed to copy to clipboard."


def get_active_window() -> str:
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd)
            return f"The active window is {title}." if title else "Active window has no title."
        return "No active window."
    except Exception:
        return "Could not determine active window."


def list_open_windows() -> str:
    try:
        import win32gui
        matched = []
        def enum_handler(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).strip()
                if title and title not in ("Program Manager", "Settings", "Windows Input Experience"):
                    matched.append(title)
        win32gui.EnumWindows(enum_handler, None)
        if not matched:
            return "No open application windows found."
        unique = list(dict.fromkeys(matched))[:6]
        return f"Open windows include: {', '.join(unique)}."
    except Exception:
        return "Failed to list windows."


def open_web(query: str) -> str:
    q = (query or "").strip()
    if not q:
        return "No query provided."
    if q.startswith("http://") or q.startswith("https://"):
        webbrowser.open(q)
        domain = urllib.parse.urlparse(q).netloc.replace("www.", "")
        return f"Opened {domain}." if domain else "Opened website."
    if "youtube" in q.lower():
        cleaned = q.lower().replace("youtube", "").strip()
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(cleaned)}"
        webbrowser.open(url)
        return f"Opened YouTube search for {cleaned}." if cleaned else "Opened YouTube."
    url = f"https://www.google.com/search?q={urllib.parse.quote(q)}"
    webbrowser.open(url)
    return f"Searching Google for {q}."


def save_memory(key: str, value: str) -> str:
    return memory.save_memory(key, value)


def recall_memory(query: str) -> str:
    return memory.recall_memory(query)


# ---- CLOSE LOGIC ----

def close_window_by_title(query: str) -> str:
    try:
        import win32gui, win32con
    except Exception:
        return "Window close is not available."
    query = (query or "").strip()
    if not query:
        return "No window title provided."
    matched = []
    def enum_handler(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title and query.lower() in title.lower():
                matched.append((hwnd, title))
    try:
        win32gui.EnumWindows(enum_handler, None)
    except Exception:
        return "Failed to find windows."
    if not matched:
        return f"No open window found containing '{query}'."
    closed = 0
    for hwnd, _ in matched:
        try:
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            closed += 1
        except Exception:
            pass
    return f"Closed {query}." if closed > 0 else f"Could not close {query}."


def close_app(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "No application name provided."
    low = name.lower()
    if "jarvis" in low:
        return "I will not close Jarvis itself."
    win_result = close_window_by_title(name)
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pname = (proc.info['name'] or "")
            if not pname:
                continue
            plow = pname.lower()
            if low in plow or plow.replace(".exe","") in low or low.replace(".exe","") in plow:
                try:
                    cmdline = " ".join(proc.cmdline()).lower() if proc.cmdline() else ""
                    if "jarvis_wake.py" in cmdline or "jarvis_voice_ptt.py" in cmdline:
                        continue
                except Exception:
                    pass
                if plow in ("textinputhost.exe", "searchhost.exe", "sihost.exe"):
                    continue
                try:
                    proc.terminate()
                except Exception:
                    continue
        except Exception:
            continue
    return f"Closed {name}."


def close_current_tab() -> str:
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press('w')
            kb.release('w')
        return "Closed current tab."
    except Exception:
        return "Failed to close tab."


def close_current_window() -> str:
    try:
        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.alt):
            kb.press(Key.f4)
            kb.release(Key.f4)
        return "Closed current window."
    except Exception:
        return "Failed to close window."


# ─────────────────────────────────────────────────────────────────────────────
# Browser automation (Playwright) — delegates to jarvis_browser.py
# ─────────────────────────────────────────────────────────────────────────────

def _browser():
    import jarvis_browser as _b
    return _b

def browser_open(url: str) -> str:
    return _browser().browser_open(url)

def youtube_play(query: str) -> str:
    return _browser().youtube_play(query)

def web_search(query: str) -> str:
    return _browser().web_search(query)

def browser_read_page() -> str:
    return _browser().browser_read_page()

def browser_click(text: str) -> str:
    return _browser().browser_click(text)

def browser_fill(field: str, value: str) -> str:
    return _browser().browser_fill(field, value)

def browser_scroll_page(direction: str = "down", amount: int = 3) -> str:
    return _browser().browser_scroll(direction, amount)

def browser_go_back() -> str:
    return _browser().browser_go_back()

def browser_press_enter() -> str:
    return _browser().browser_press_enter()

def browser_screenshot() -> str:
    return _browser().browser_screenshot()

def browser_get_url() -> str:
    return _browser().browser_get_url()

def browser_close() -> str:
    return _browser().browser_close()