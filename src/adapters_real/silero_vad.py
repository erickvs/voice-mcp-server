import numpy as np
import torch
from silero_vad import load_silero_vad
from simulation.ports import IVAD
from simulation.models import VirtualAudioFrame

class RealSileroVAD(IVAD):
    def __init__(self, **kwargs):
        # Determine if Apple Silicon (MPS) or CUDA is available for hardware acceleration
        if torch.backends.mps.is_available():
            self.device = torch.device("mps")
            print("[DEBUG VAD] Initializing Silero VAD on Apple Metal GPU (MPS)")
        elif torch.cuda.is_available():
            self.device = torch.device("cuda")
        else:
            self.device = torch.device("cpu")
            
        self.model = load_silero_vad().to(self.device)
        self.buffer = b""
        self.last_prob = 0.0

    def analyze(self, frame: VirtualAudioFrame) -> float:
        if not frame.raw_bytes:
            return 0.0
            
        self.buffer += frame.raw_bytes
        
        # 512 samples = 1024 bytes
        if len(self.buffer) >= 1024:
            chunk = self.buffer[:1024]
            self.buffer = self.buffer[1024:]
            
            audio_int16 = np.frombuffer(chunk, dtype=np.int16)
            audio_float32 = audio_int16.astype(np.float32) / 32768.0
            
            # Move the tensor to the active GPU/CPU device
            tensor = torch.from_numpy(audio_float32).to(self.device)
            # silero-vad model natively handles the state!
            prob = self.model(tensor, 16000).item()
            self.last_prob = float(prob)
            # print(f"[DEBUG VAD] Prob: {self.last_prob:.3f}")
            
        return self.last_prob
