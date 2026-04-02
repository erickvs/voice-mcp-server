import numpy as np
import mlx_whisper
from typing import List

from simulation.ports import ISTT
from simulation.models import VirtualAudioFrame

class RealWhisperSTT(ISTT):
    def __init__(self, model_size="mlx-community/whisper-large-v3-mlx"):
        self.model_size = model_size
        print(f"[DEBUG STT] Preparing MLX Whisper model ({model_size}) for Apple Silicon...")
        # MLX will lazily load and compile the model on the first inference, but we print here to indicate we are using the MLX backend.

    def transcribe(self, frames: List[VirtualAudioFrame]) -> str:
        raw_bytes = b"".join(f.raw_bytes for f in frames if f.raw_bytes)
        if not raw_bytes:
            return ""
        
        # Convert 16-bit PCM (expected from microphone) to float32 [-1.0, 1.0] expected by Whisper
        audio_data = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        print(f"[DEBUG STT] Transcribing {len(audio_data)} samples with Apple MLX Whisper ({self.model_size})...")
        
        try:
            # We explicitly set English since you are speaking English, and fp16 for Metal acceleration
            result = mlx_whisper.transcribe(audio_data, path_or_hf_repo=self.model_size, language="en")
            text = result.get("text", "").strip()
            print(f"[DEBUG STT] MLX Transcription result: {text}")
            return text
        except Exception as e:
            print(f"[DEBUG STT] MLX Whisper transcription error: {e}")
            return ""
