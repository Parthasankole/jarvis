import json
import os
import subprocess
from pathlib import Path

from rapidfuzz import process as rf_process
import win32com.client

INDEX_PATH = Path.home() / "JarvisWorkspace" / "app_index.json"


def _start_menu_dirs():
    dirs = []
    if "ProgramData" in os.environ:
        dirs.append(Path(os.environ["ProgramData"]) / r"Microsoft\Windows\Start Menu\Programs")
    if "AppData" in os.environ:
        dirs.append(Path(os.environ["AppData"]) / r"Microsoft\Windows\Start Menu\Programs")
    return [d for d in dirs if d.exists()]


def _scan_start_menu_shortcuts():
    apps = []
    try:
        win32com.client.Dispatch("WScript.Shell")
    except Exception:
        pass

    for root in _start_menu_dirs():
        for lnk in root.rglob("*.lnk"):
            name = lnk.stem.strip()
            if not name:
                continue
            apps.append({
                "name": name,
                "type": "shortcut",
                "shortcut": str(lnk),
            })
    return apps


def _scan_uwp_apps():
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-StartApps | Select Name, AppID | ConvertTo-Json -Depth 2"
        ]
        out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="ignore").strip()
        if not out:
            return []

        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]

        apps = []
        for row in data:
            name = (row.get("Name") or "").strip()
            appid = (row.get("AppID") or "").strip()
            if name and appid:
                apps.append({
                    "name": name,
                    "type": "uwp",
                    "appid": appid
                })
        return apps
    except Exception:
        return []


def refresh_index() -> dict:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    apps = _scan_start_menu_shortcuts() + _scan_uwp_apps()

    index = {}
    for a in apps:
        key = a["name"]
        key_ci = key.lower()
        if key_ci not in index:
            index[key_ci] = a

    INDEX_PATH.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index


def load_index() -> dict:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return refresh_index()


def search_apps(query: str, limit: int = 6):
    index = load_index()
    names = [v["name"] for v in index.values()]
    matches = rf_process.extract(query, names, limit=limit)
    return [{"name": n, "score": float(s)} for (n, s, _) in matches]


def open_app(query: str) -> str:
    query = (query or "").strip()
    if not query:
        return "No application name provided."

    index = load_index()
    name_to_rec = {v["name"]: v for v in index.values()}
    names = list(name_to_rec.keys())

    match = rf_process.extractOne(query, names)
    if not match:
        return f"Could not find an application named {query}."

    name, score, _ = match
    if score < 60:
        return f"Could not find an application matching {query}."

    app = name_to_rec[name]

    if app["type"] == "shortcut":
        shortcut = app["shortcut"]
        if not Path(shortcut).exists():
            return f"Application {name} is not installed or shortcut is missing."
        os.startfile(shortcut)
        return f"Opened {name}."

    if app["type"] == "uwp":
        appid = app["appid"]
        subprocess.Popen(["explorer.exe", fr"shell:AppsFolder\{appid}"])
        return f"Opened {name}."

    return "Unsupported application type."