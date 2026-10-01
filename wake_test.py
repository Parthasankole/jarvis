import time
import queue
from xml.parsers.expat import model
import numpy as np
import sounddevice as sd

from openwakeword.model import Model
from openwakeword.utils import download_models
import jarvis_tools as tools

MIC_DEVICE_INDEX = tools.get_best_microphone_index()
MODEL_SR = 16000            # openWakeWord expects 16 kHz
CHUNK_16K = 1280            # 80 ms at 16k
CHUNK_48K = CHUNK_16K * 3   # 3840 samples at 48k -> 1280 at 16k
TRIGGER_THRESHOLD = 0.6

def downsample_48k_to_16k(x48: np.ndarray) -> np.ndarray:
    """
    Cheap 3:1 downsample for 48k -> 16k:
    average groups of 3 samples (acts like a tiny low-pass).
    Input: 1D float32 length 3840
    Output: 1D float32 length 1280
    """
    x48 = x48[: (len(x48) // 3) * 3]
    return x48.reshape(-1, 3).mean(axis=1).astype(np.float32)

def main():
    print("Downloading wake-word models (first run may take a bit)...")
    download_models()

    # Try to load the Jarvis model explicitly; if not present, Model() still loads whatever is available.
    try:
        model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
    except Exception:
        model = Model(inference_framework="onnx")

    # Print what models are actually loaded
    loaded = None
    for attr in ("models", "wakeword_models", "model_names"):
        if hasattr(model, attr):
            try:
                val = getattr(model, attr)
                if isinstance(val, dict):
                    loaded = list(val.keys())
                else:
                    loaded = val
            except Exception:
                pass
    print(f"Loaded wake models: {loaded}")

    q = queue.Queue()

    dev = sd.query_devices(MIC_DEVICE_INDEX)
    sr = int(dev["default_samplerate"])  # likely 48000
    print(f"Mic default sample rate: {sr}")

    if sr != 48000:
        print("Note: this script assumes 48kHz mic rate for simple downsample.")
        print("If your device isn't 48k, tell me the number printed above and I’ll adjust it.")

    def callback(indata, frames, time_info, status):
        mono = indata[:, 0].astype(np.float32).copy()
        q.put(mono)

    print("Listening for wake word... (Ctrl+C to stop)")
    print("Say: 'Jarvis' or 'Hey Jarvis' (depending on the available model).")

    with sd.InputStream(
        device=MIC_DEVICE_INDEX,
        channels=1,
        samplerate=sr,
        blocksize=CHUNK_48K,
        dtype="float32",
        callback=callback,
    ):
        last_print = time.time()
        while True:
            x48 = q.get()

            # downsample to 16k chunk
            x16 = downsample_48k_to_16k(x48)

            x16_pcm = np.clip(x16 * 32767.0, -32768, 32767).astype(np.int16)
            scores = model.predict(x16_pcm)  # dict: model_name -> score

            if time.time() - last_print > 2.0 and scores:
                best = max(scores.items(), key=lambda x: x[1])
                print(f"Best: {best[0]} = {best[1]:.3f}")
                last_print = time.time()

            for name, score in scores.items():
                if score >= TRIGGER_THRESHOLD:
                    print(f"\nWAKE WORD DETECTED: {name} (score={score:.3f})")
                    model.reset()
                    time.sleep(1.0)
                    break

if __name__ == "__main__":
    main()