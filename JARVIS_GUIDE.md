# J.A.R.V.I.S. (100% Local & Offline Voice Assistant)

Welcome to your personal AI assistant running locally on Windows with zero cloud dependencies.

---

## 🚀 How to Run Jarvis

You have 3 easy ways to run Jarvis. Simply **double-click** any of these files in `C:\jarvis-local`:

### 1. **Sci-Fi HUD (Wakeword + UI)**: Double-click `run_jarvis_wake.cmd`
- Displays the Iron Man style holographic HUD.
- **Wake Word**: Say **"Hey Jarvis"** to activate.
- **Manual Click**: Click the **MIC button** on the left side of the HUD anytime to activate manually without speaking the wake word.
- **Exit**: Click the standard window **X** to cleanly close Jarvis.

### 2. **Push-To-Talk Mode**: Double-click `run_jarvis_ptt.cmd`
- Runs in a clean, lightweight terminal window.
- **How to talk**: Press and **HOLD the F8 key** anywhere on your computer while you speak.
- Release **F8** when done speaking — Jarvis will transcribe your voice, perform the task, and reply with his voice!

### 3. **Interactive Terminal (Text Mode)**: Double-click `run_jarvis_terminal.cmd`
- Type directly to Jarvis without needing to use your microphone.
- Has access to all tools and capabilities.

---

## 🎙️ What You Can Say to Jarvis

### 👁️ See The Screen (Vision)
- *"Look at my screen"* / *"See my screen"*
- *"What is currently on my screen?"*
- *"Describe what you see on the screen"*
*(Uses your local Moondream vision model to capture and understand your desktop!)*

### 🖱️ Cursor & Mouse Controls
- *"Where is my cursor?"* (reports current coordinates and screen size)
- *"Move cursor to center"*
- *"Click"* / *"Left click"*
- *"Right click"* / *"Context menu"*
- *"Double click"*
- *"Scroll down"* / *"Scroll up"*

### ⌨️ Keyboard & On-Screen Keyboard
- *"Show on-screen keyboard"* / *"Open keyboard"* (launches Windows On-Screen Keyboard)
- *"Close on-screen keyboard"* / *"Hide keyboard"*
- *"Type [anything]"* (e.g. *"Type Hello world"*)
- *"Press enter"* / *"Press space"* / *"Press tab"* / *"Press escape"*

### 💻 Windows Apps & Browsing
- *"Open Chrome"* / *"Open Notepad"* / *"Open Calculator"* / *"Open Brave"*
- *"Search for photo apps"*
- *"Close Notepad"* / *"Close Brave"*
- *"Close this tab"* (sends Ctrl+W)
- *"Close this window"* (sends Alt+F4)
- *"Open YouTube metallica"*

### 🎵 Media & Audio Controls
- *"Play music"* / *"Pause music"*
- *"Next track"* / *"Skip song"*
- *"Previous song"*
- *"Volume up"* / *"Volume down"* / *"Mute sound"*

### 🕒 Time, Date & Weather
- *"What time is it?"* / *"What is today's date?"*
- *"What is the weather?"*
- *"What is the weather in Paris?"*

### 🖥️ Screen & System Status
- *"Take a screenshot"* (saved automatically to `~/JarvisWorkspace/screenshots`)
- *"What is my active window?"*
- *"What windows are open?"*
- *"System status"* (checks CPU and RAM usage)
- *"What is in my clipboard?"*

### 🧠 Persistent Long-Term Memory
- *"Remember my pin code is 4492"*
- *"What is my pin code?"*
- *"Remember my friend's birthday is October 15"*

---

## ⚙️ Architecture & Local Models

- **Vision AI**: Local `moondream` vision model running in Ollama.
- **Wake Word**: `openWakeWord` running on ONNX (`hey_jarvis`).
- **Speech-to-Text**: `faster-whisper` (`small.en`) running on your NVIDIA GPU with CUDA acceleration.
- **Local Brain (LLM)**: `Ollama` running `qwen2.5:7b` (with fallback to `llama3.2:3b`).
- **Voice Synthesis (TTS)**: `Piper TTS` (`en_US-lessac-low.onnx`).
- **App & Windows Automation**: Win32 API, `pynput` mouse/keyboard, and `osk.exe` on-screen keyboard.
