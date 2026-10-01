import os
import sys
import time
import queue
from pathlib import Path

# --- Quiet the HuggingFace symlink warning ---
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

# --- Make the pip-installed CUDA DLLs (cublas/cudnn) visible to Whisper ---
nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
for sub in ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc"):
    dll_dir = nvidia_root / sub / "bin"
    if dll_dir.exists():
        os.add_dll_directory(str(dll_dir))
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ["PATH"]

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
import jarvis_tools as tools

MIC_DEVICE_INDEX = tools.get_best_microphone_index()
MAX_SECONDS = 20              # hard stop
WAIT_FOR_SPEECH_SECONDS = 8   # how long to wait for you to start talking
SILENCE_SECONDS_TO_STOP = 1.2 # stop after this much silence once you've spoken
RMS_THRESHOLD = 0.008         # lower (0.004) if it never detects you; raise if it triggers on noise
TARGET_SR = 16000


def resample_linear(x, orig_sr, target_sr):
    if orig_sr == target_sr:
        return x.astype(np.float32, copy=False)
    duration = len(x) / orig_sr
    t_orig = np.linspace(0, duration, num=len(x), endpoint=False)
    t_new = np.linspace(0, duration, num=int(duration * target_sr), endpoint=False)
    return np.interp(t_new, t_orig, x).astype(np.float32)


def record_until_silence(device_index):
    q = queue.Queue()
    dev = sd.query_devices(device_index)
    sr = int(dev["default_samplerate"])

    def callback(indata, frames, time_info, status):
        mono = indata[:, 0].astype(np.float32).copy()
        q.put(mono)

    audio = []
    speech_started = False
    last_voice = None
    peak_rms = 0.0
    start = time.time()

    print(f"Listening on device {device_index} at {sr} Hz. Speak now...")

    with sd.InputStream(device=device_index, channels=1, samplerate=sr,
                        dtype="float32", callback=callback):
        while True:
            now = time.time()
            if now - start > MAX_SECONDS:
                break
            if not speech_started and (now - start) > WAIT_FOR_SPEECH_SECONDS:
                print("No speech detected (timeout).")
                break
            if speech_started and (now - last_voice) > SILENCE_SECONDS_TO_STOP:
                break
            try:
                mono = q.get(timeout=0.1)
            except queue.Empty:
                continue

            rms = float(np.sqrt(np.mean(mono * mono)) + 1e-12)
            peak_rms = max(peak_rms, rms)
            if rms >= RMS_THRESHOLD:
                if not speech_started:
                    print("Speech detected, recording...")
                speech_started = True
                last_voice = time.time()
            if speech_started:
                audio.append(mono)

    print(f"(debug) peak mic level = {peak_rms:.4f}, threshold = {RMS_THRESHOLD}")
    if not audio:
        return np.zeros((0,), dtype=np.float32), sr
    return np.concatenate(audio), sr


def load_model():
    try:
        m = WhisperModel("base.en", device="cuda", compute_type="float16")
        print("Whisper loaded on CUDA (GPU).")
        return m
    except Exception as e:
        print(f"GPU load failed ({e}). Falling back to CPU.")
        m = WhisperModel("base.en", device="cpu", compute_type="int8")
        print("Whisper loaded on CPU.")
        return m


def main():
    model = load_model()
    x, sr = record_until_silence(MIC_DEVICE_INDEX)
    if len(x) < 1000:
        print("No audio captured. If peak level was ~0.0000, check Windows mic privacy settings.")
        return

    x16 = resample_linear(x, sr, TARGET_SR)
    print("Transcribing...")
    try:
        segments, _ = model.transcribe(x16, vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segments).strip()
    except Exception as e:
        print(f"GPU transcription failed ({e}). Retrying on CPU...")
        cpu_model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, _ = cpu_model.transcribe(x16, vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segments).strip()

    print("\n--- TRANSCRIPT ---")
    print(text)
    print("------------------")


if __name__ == "__main__":
    main()