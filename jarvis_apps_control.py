"""
jarvis_apps_control.py — Deep app control for JARVIS
Handles: Spotify, VLC, File Explorer, VS Code, Notepad, and generic window automation
"""
import os
import re
import time
import subprocess
import webbrowser
import urllib.parse
from pathlib import Path

import pyautogui

# ──────────────────────────────────────────────
#  SPOTIFY — Web API (requires JARVIS_SPOTIFY_* env vars or jarvis_config.json)
# ──────────────────────────────────────────────

_spotify_client = None
_spotify_device_id = None


def _get_spotify():
    """Lazy-init Spotify client. Returns None if credentials not configured."""
    global _spotify_client
    if _spotify_client is not None:
        return _spotify_client
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        import json

        # Try loading from jarvis_config.json
        config_path = Path(__file__).parent / "jarvis_config.json"
        cid = os.environ.get("JARVIS_SPOTIFY_CLIENT_ID", "")
        secret = os.environ.get("JARVIS_SPOTIFY_CLIENT_SECRET", "")

        if not cid and config_path.exists():
            cfg = json.loads(config_path.read_text())
            spotify_cfg = cfg.get("spotify", {})
            cid = spotify_cfg.get("client_id", "")
            secret = spotify_cfg.get("client_secret", "")

        if not cid or not secret:
            return None

        scope = "user-read-playback-state user-modify-playback-state user-read-currently-playing"
        cache_path = Path(__file__).parent / ".spotify_cache"
        auth = SpotifyOAuth(
            client_id=cid,
            client_secret=secret,
            redirect_uri="http://localhost:8888/callback",
            scope=scope,
            cache_path=str(cache_path),
            open_browser=True,
        )
        _spotify_client = spotipy.Spotify(auth_manager=auth)
        return _spotify_client
    except Exception:
        return None


def _get_spotify_device():
    """Returns first active Spotify device id, launches Spotify if none found."""
    global _spotify_device_id
    sp = _get_spotify()
    if not sp:
        return None
    try:
        devices = sp.devices().get("devices", [])
        if not devices:
            # Launch Spotify and wait for it
            subprocess.Popen(["cmd", "/c", "start", "spotify:"], shell=False)
            time.sleep(4)
            devices = sp.devices().get("devices", [])
        if devices:
            # Prefer active device
            active = [d for d in devices if d.get("is_active")]
            _spotify_device_id = (active or devices)[0]["id"]
        return _spotify_device_id
    except Exception:
        return None


def spotify_play_song(query: str) -> str:
    """Search Spotify and play the best matching track."""
    sp = _get_spotify()
    if not sp:
        return _spotify_fallback_play(query)
    try:
        device_id = _get_spotify_device()
        results = sp.search(q=query, type="track", limit=1)
        tracks = results.get("tracks", {}).get("items", [])
        if not tracks:
            return f"Spotify: No results found for '{query}'."
        track = tracks[0]
        track_name = track["name"]
        artist = track["artists"][0]["name"]
        uri = track["uri"]
        sp.start_playback(device_id=device_id, uris=[uri])
        return f"Playing '{track_name}' by {artist} on Spotify."
    except Exception as e:
        return f"Spotify error: {e}"


def spotify_play_playlist(query: str) -> str:
    """Search and play a Spotify playlist."""
    sp = _get_spotify()
    if not sp:
        return _spotify_fallback_play(query)
    try:
        device_id = _get_spotify_device()
        results = sp.search(q=query, type="playlist", limit=1)
        playlists = results.get("playlists", {}).get("items", [])
        if not playlists:
            return f"Spotify: No playlist found for '{query}'."
        pl = playlists[0]
        sp.start_playback(device_id=device_id, context_uri=pl["uri"])
        return f"Playing playlist '{pl['name']}' on Spotify."
    except Exception as e:
        return f"Spotify error: {e}"


def spotify_play_artist(query: str) -> str:
    """Search and play a Spotify artist."""
    sp = _get_spotify()
    if not sp:
        return _spotify_fallback_play(query)
    try:
        device_id = _get_spotify_device()
        results = sp.search(q=query, type="artist", limit=1)
        artists = results.get("artists", {}).get("items", [])
        if not artists:
            return f"Spotify: No artist found for '{query}'."
        artist = artists[0]
        sp.start_playback(device_id=device_id, context_uri=artist["uri"])
        return f"Playing music by '{artist['name']}' on Spotify."
    except Exception as e:
        return f"Spotify error: {e}"


def spotify_pause() -> str:
    sp = _get_spotify()
    if not sp:
        # Fallback: media key
        import ctypes
        ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
        return "Paused."
    try:
        sp.pause_playback()
        return "Spotify paused."
    except Exception:
        return "Could not pause Spotify."


def spotify_resume() -> str:
    sp = _get_spotify()
    if not sp:
        import ctypes
        ctypes.windll.user32.keybd_event(0xB3, 0, 0, 0)
        return "Resumed."
    try:
        sp.start_playback()
        return "Spotify resumed."
    except Exception:
        return "Could not resume Spotify."


def spotify_next() -> str:
    sp = _get_spotify()
    if not sp:
        import ctypes
        ctypes.windll.user32.keybd_event(0xB0, 0, 0, 0)
        return "Skipped to next track."
    try:
        sp.next_track()
        return "Skipped to next track on Spotify."
    except Exception:
        return "Could not skip track."


def spotify_prev() -> str:
    sp = _get_spotify()
    if not sp:
        import ctypes
        ctypes.windll.user32.keybd_event(0xB1, 0, 0, 0)
        return "Previous track."
    try:
        sp.previous_track()
        return "Went back to previous track on Spotify."
    except Exception:
        return "Could not go back."


def spotify_what_playing() -> str:
    sp = _get_spotify()
    if not sp:
        return "Spotify API not configured."
    try:
        current = sp.current_playback()
        if not current or not current.get("item"):
            return "Nothing is currently playing on Spotify."
        item = current["item"]
        name = item["name"]
        artists = ", ".join(a["name"] for a in item["artists"])
        return f"Currently playing '{name}' by {artists}."
    except Exception as e:
        return f"Spotify error: {e}"


def spotify_set_volume(level: int) -> str:
    """Set Spotify volume 0-100."""
    sp = _get_spotify()
    if not sp:
        return "Spotify API not configured."
    try:
        level = max(0, min(100, int(level)))
        sp.volume(level)
        return f"Spotify volume set to {level}%."
    except Exception as e:
        return f"Spotify volume error: {e}"


def _spotify_fallback_play(query: str) -> str:
    """Open Spotify URI search as fallback."""
    uri = f"spotify:search:{urllib.parse.quote(query)}"
    try:
        subprocess.Popen(["cmd", "/c", "start", "", uri], shell=False)
    except Exception:
        webbrowser.open(f"https://open.spotify.com/search/{urllib.parse.quote(query)}")
    return f"Opening Spotify search for '{query}'. Spotify API not configured — set up your API key for full control."


# ──────────────────────────────────────────────
#  VLC — HTTP Interface
# ──────────────────────────────────────────────

VLC_HOST = "http://localhost:9090"
VLC_PASSWORD = "jarvis"


def _vlc_cmd(path: str, params: dict = None):
    """Send command to VLC HTTP interface."""
    try:
        import requests
        url = f"{VLC_HOST}/requests/{path}"
        r = requests.get(url, params=params, auth=("", VLC_PASSWORD), timeout=2)
        return r
    except Exception:
        return None


def _vlc_is_running() -> bool:
    r = _vlc_cmd("status.json")
    return r is not None and r.status_code == 200


def _launch_vlc_with_http():
    """Launch VLC with HTTP interface enabled."""
    vlc_paths = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
    ]
    for p in vlc_paths:
        if Path(p).exists():
            subprocess.Popen([
                p,
                "--extraintf=http",
                f"--http-host=localhost",
                f"--http-port=9090",
                f"--http-password={VLC_PASSWORD}",
            ])
            time.sleep(2)
            return True
    return False


def vlc_play_file(filepath: str) -> str:
    """Play a file in VLC."""
    if not _vlc_is_running():
        _launch_vlc_with_http()
    path = filepath.replace("\\", "/")
    r = _vlc_cmd("status.json", {"command": "in_play", "input": path})
    if r and r.status_code == 200:
        return f"Playing '{Path(filepath).name}' in VLC."
    return "Could not play file in VLC."


def vlc_pause() -> str:
    if not _vlc_is_running():
        return "VLC is not running."
    _vlc_cmd("status.json", {"command": "pl_pause"})
    return "VLC paused."


def vlc_stop() -> str:
    if not _vlc_is_running():
        return "VLC is not running."
    _vlc_cmd("status.json", {"command": "pl_stop"})
    return "VLC stopped."


def vlc_next() -> str:
    if not _vlc_is_running():
        return "VLC is not running."
    _vlc_cmd("status.json", {"command": "pl_next"})
    return "VLC: next track."


def vlc_prev() -> str:
    if not _vlc_is_running():
        return "VLC is not running."
    _vlc_cmd("status.json", {"command": "pl_previous"})
    return "VLC: previous track."


def vlc_set_volume(level: int) -> str:
    if not _vlc_is_running():
        return "VLC is not running."
    # VLC volume is 0-512 (256=100%)
    vlc_vol = int((level / 100) * 256)
    _vlc_cmd("status.json", {"command": "volume", "val": vlc_vol})
    return f"VLC volume set to {level}%."


# ──────────────────────────────────────────────
#  FILE EXPLORER — Control & Navigation
# ──────────────────────────────────────────────

def explorer_open_folder(path: str) -> str:
    """Open a folder in File Explorer."""
    p = Path(path).expanduser()
    if not p.exists():
        # Try common shortcuts
        shortcuts = {
            "desktop": Path.home() / "Desktop",
            "documents": Path.home() / "Documents",
            "downloads": Path.home() / "Downloads",
            "pictures": Path.home() / "Pictures",
            "music": Path.home() / "Music",
            "videos": Path.home() / "Videos",
            "this pc": "shell:MyComputerFolder",
            "my computer": "shell:MyComputerFolder",
        }
        low = path.lower().strip()
        for key, dest in shortcuts.items():
            if key in low:
                if isinstance(dest, str):
                    subprocess.Popen(["explorer.exe", dest])
                else:
                    subprocess.Popen(["explorer.exe", str(dest)])
                return f"Opened {key.title()} in File Explorer."
        return f"Folder not found: {path}"
    subprocess.Popen(["explorer.exe", str(p)])
    return f"Opened '{p.name}' in File Explorer."


def explorer_open_path(path: str) -> str:
    """Open a specific path — file or folder."""
    p = Path(path).expanduser()
    if p.is_file():
        os.startfile(str(p))
        return f"Opened file '{p.name}'."
    elif p.is_dir():
        subprocess.Popen(["explorer.exe", str(p)])
        return f"Opened folder '{p.name}'."
    return f"Path not found: {path}"


def find_file(name: str, search_in: str = None) -> str:
    """Search for a file by name and open its containing folder."""
    search_root = Path(search_in).expanduser() if search_in else Path.home()
    name_lower = name.lower()
    found = []
    try:
        for p in search_root.rglob("*"):
            if p.is_file() and name_lower in p.name.lower():
                found.append(p)
                if len(found) >= 5:
                    break
    except PermissionError:
        pass
    if not found:
        return f"No file matching '{name}' found in {search_root}."
    if len(found) == 1:
        subprocess.Popen(["explorer.exe", "/select,", str(found[0])])
        return f"Found and highlighted '{found[0].name}' in Explorer."
    result = "\n".join(str(f) for f in found[:5])
    return f"Found {len(found)} matches:\n{result}"


# ──────────────────────────────────────────────
#  VS CODE — Open files and folders
# ──────────────────────────────────────────────

def vscode_open(path: str) -> str:
    """Open a file or folder in VS Code."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"Path not found: {path}"
    try:
        subprocess.Popen(["code", str(p)], shell=True)
        return f"Opened '{p.name}' in VS Code."
    except Exception as e:
        return f"Could not open VS Code: {e}"


def vscode_new_file(filename: str, content: str = "") -> str:
    """Create a new file and open it in VS Code."""
    from pathlib import Path
    workspace = Path.home() / "JarvisWorkspace"
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / filename
    target.write_text(content, encoding="utf-8")
    try:
        subprocess.Popen(["code", str(target)], shell=True)
        return f"Created and opened '{filename}' in VS Code."
    except Exception:
        return f"Created '{filename}' but could not open VS Code."


# ──────────────────────────────────────────────
#  NOTEPAD — Direct control via pywinauto
# ──────────────────────────────────────────────

def notepad_open(filepath: str = None) -> str:
    """Open Notepad, optionally with a file."""
    if filepath:
        p = Path(filepath).expanduser()
        subprocess.Popen(["notepad.exe", str(p)])
        return f"Opened '{p.name}' in Notepad."
    subprocess.Popen(["notepad.exe"])
    return "Opened Notepad."


def notepad_type_text(text: str) -> str:
    """Find open Notepad window and type text into it."""
    try:
        from pywinauto import Application, findwindows
        import win32gui
        # Find Notepad
        handles = findwindows.find_windows(class_name="Notepad")
        if not handles:
            subprocess.Popen(["notepad.exe"])
            time.sleep(1)
            handles = findwindows.find_windows(class_name="Notepad")
        if not handles:
            return "Could not find Notepad window."
        hwnd = handles[0]
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        pyautogui.write(text, interval=0.03)
        return f"Typed text into Notepad."
    except Exception as e:
        return f"Notepad type error: {e}"


def notepad_save(filepath: str = None) -> str:
    """Save the current Notepad document."""
    try:
        from pywinauto import findwindows
        import win32gui
        handles = findwindows.find_windows(class_name="Notepad")
        if not handles:
            return "Notepad is not open."
        win32gui.SetForegroundWindow(handles[0])
        time.sleep(0.2)
        if filepath:
            pyautogui.hotkey("ctrl", "shift", "s")
            time.sleep(0.5)
            pyautogui.write(filepath, interval=0.03)
            pyautogui.press("enter")
        else:
            pyautogui.hotkey("ctrl", "s")
        return "Notepad saved."
    except Exception as e:
        return f"Could not save Notepad: {e}"


# ──────────────────────────────────────────────
#  GENERIC WINDOW CONTROL — bring any app to front, type, click
# ──────────────────────────────────────────────

def focus_window(title_fragment: str) -> str:
    """Bring a window with matching title to the foreground."""
    try:
        import win32gui, win32con
        matched = []
        def handler(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if title_fragment.lower() in t.lower():
                    matched.append((hwnd, t))
        win32gui.EnumWindows(handler, None)
        if not matched:
            return f"No window found matching '{title_fragment}'."
        hwnd, title = matched[0]
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return f"Focused window: '{title}'."
    except Exception as e:
        return f"Could not focus window: {e}"


def window_type_text(title_fragment: str, text: str) -> str:
    """Focus a window by title and type text into it."""
    result = focus_window(title_fragment)
    if "No window" in result or "error" in result.lower():
        return result
    time.sleep(0.3)
    pyautogui.write(text, interval=0.02)
    return f"Typed into '{title_fragment}'."


def app_search_in(app: str, query: str) -> str:
    """Press Ctrl+F or Ctrl+L to open search/address bar in the focused app, then type query."""
    focus_result = focus_window(app)
    if "No window" in focus_result:
        return focus_result
    time.sleep(0.3)
    app_lower = app.lower()
    if any(b in app_lower for b in ("chrome", "edge", "firefox", "browser")):
        pyautogui.hotkey("ctrl", "l")  # address bar
    elif any(e in app_lower for e in ("explorer", "file")):
        pyautogui.hotkey("ctrl", "l")  # path bar
    else:
        pyautogui.hotkey("ctrl", "f")  # generic find
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.write(query, interval=0.02)
    pyautogui.press("enter")
    return f"Searched for '{query}' in {app}."


# ──────────────────────────────────────────────
#  SMART PLAY ROUTER — figures out WHERE to play based on context
# ──────────────────────────────────────────────

def smart_play(query: str) -> str:
    """
    Intelligent play command:
    1. If Spotify is configured and running → play on Spotify
    2. Else if Spotify is installed → open Spotify search
    3. Else fall back to YouTube (browser)
    """
    # Try Spotify first
    sp = _get_spotify()
    if sp:
        return spotify_play_song(query)

    # Check if Spotify app is installed/running
    import psutil
    spotify_running = any("spotify" in p.name().lower() for p in psutil.process_iter(["name"]))
    if spotify_running:
        return _spotify_fallback_play(query)

    # Check if Spotify is installed
    spotify_paths = [
        Path.home() / "AppData" / "Roaming" / "Spotify" / "Spotify.exe",
        Path(r"C:\Program Files\WindowsApps"),
    ]
    for p in spotify_paths:
        if p.exists():
            return _spotify_fallback_play(query)

    # Final fallback: YouTube via browser
    try:
        from jarvis_browser import youtube_play as browser_youtube
        return browser_youtube(query)
    except Exception:
        url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        webbrowser.open(url)
        return f"Searching YouTube for '{query}'."


# ──────────────────────────────────────────────
#  SPOTIFY SETUP HELPER
# ──────────────────────────────────────────────

def spotify_setup(client_id: str, client_secret: str) -> str:
    """Save Spotify credentials to jarvis_config.json."""
    import json
    config_path = Path(__file__).parent / "jarvis_config.json"
    cfg = {}
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text())
        except Exception:
            pass
    cfg["spotify"] = {
        "client_id": client_id.strip(),
        "client_secret": client_secret.strip(),
    }
    config_path.write_text(json.dumps(cfg, indent=2))
    global _spotify_client
    _spotify_client = None  # force re-init
    return "Spotify credentials saved. Say 'play a song on Spotify' to test."
