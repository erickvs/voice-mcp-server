import wave
from simulation.ports import IMicrophone
from simulation.models import VirtualAudioFrame

class WavFileMicrophone(IMicrophone):
    def __init__(self, filepath: str):
        self.wf = wave.open(filepath, 'rb')
        if self.wf.getnchannels() != 1 or self.wf.getsampwidth() != 2 or self.wf.getframerate() != 16000:
            raise ValueError("Wav file must be 16kHz, 16-bit, mono")
            
    def read_frame(self) -> VirtualAudioFrame:
        # 16kHz * 2 bytes/sample * 1 channel * 0.010s = 320 bytes
        # 160 frames at 2 bytes = 320 bytes
        raw_bytes = self.wf.readframes(160)
        if len(raw_bytes) < 320:
            return VirtualAudioFrame(10, False, False, "", b"")
        return VirtualAudioFrame(10, False, False, "", raw_bytes)
