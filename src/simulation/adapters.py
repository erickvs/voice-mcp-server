from typing import List, Dict, Any, Tuple, Optional
from .ports import IMicrophone, ISpeaker, IVAD, ISTT, ILLMBridge
from .models import VirtualAudioFrame

class ScriptedMicrophone(IMicrophone):
    def __init__(self, script: List[Tuple[int, bool, bool, str]]):
        self.frames = []
        for duration, has_speech, has_noise, text in script:
            num_frames = duration // 10
            for _ in range(num_frames):
                self.frames.append(VirtualAudioFrame(10, has_speech, has_noise, text))
        self.index = 0

    def read_frame(self) -> VirtualAudioFrame:
        if self.index < len(self.frames):
            frame = self.frames[self.index]
            self.index += 1
            return frame
        return VirtualAudioFrame(10, False, False, "")

class MockVAD(IVAD):
    def analyze(self, frame: VirtualAudioFrame) -> float:
        if frame.has_speech:
            return 1.0
        if frame.has_noise:
            return 0.5
        return 0.0

class VirtualSpeaker(ISpeaker):
    def __init__(self, wpm: int = 150, ttfa_ms: int = 0):
        self.wpm = wpm
        self.ttfa_ms = ttfa_ms
        self.words_per_ms = (wpm / 60) / 1000
        self.current_text = ""
        self.words = []
        self.total_time_needed_ms = 0
        self.elapsed_ms = 0

    def speak(self, text: str):
        self.current_text = text
        self.words = text.split()
        num_words = len(self.words)
        self.total_time_needed_ms = (num_words / self.words_per_ms if self.words_per_ms > 0 else 0) + self.ttfa_ms
        self.elapsed_ms = 0

    def play_frame(self, frame: VirtualAudioFrame):
        pass

    def tick(self, ms: int):
        if self.is_speaking():
            self.elapsed_ms += ms

    def is_speaking(self) -> bool:
        return self.elapsed_ms < self.total_time_needed_ms and len(self.current_text) > 0

    def has_started_audio(self) -> bool:
        return self.elapsed_ms >= self.ttfa_ms

    def flush(self) -> str:
        if not self.current_text:
            return ""
        if self.total_time_needed_ms == 0 or not self.has_started_audio():
            self.current_text = ""
            self.words = []
            self.elapsed_ms = 0
            self.total_time_needed_ms = 0
            return ""

        audio_elapsed = self.elapsed_ms - self.ttfa_ms
        audio_total = self.total_time_needed_ms - self.ttfa_ms
        fraction = min(1.0, audio_elapsed / audio_total) if audio_total > 0 else 1.0
        words_spoken = int(len(self.words) * fraction)
        spoken = " ".join(self.words[:words_spoken])
        
        self.current_text = ""
        self.words = []
        self.elapsed_ms = 0
        self.total_time_needed_ms = 0
        return spoken

class MockSTT(ISTT):
    def __init__(self, force_return: Optional[str] = None):
        self.force_return = force_return

    def transcribe(self, frames: List[VirtualAudioFrame]) -> str:
        if self.force_return is not None:
            return self.force_return
            
        texts = []
        last_text = None
        for f in frames:
            if f.has_speech and f.mock_text and f.mock_text != last_text:
                texts.append(f.mock_text)
                last_text = f.mock_text
        return " ".join(texts)

class MockLLMBridge(ILLMBridge):
    def __init__(self, responses: List[dict], latency_ms: int = 0, hang_forever: bool = False):
        self.responses = responses
        self.index = 0
        self.last_call = None
        self.latency_ms = latency_ms
        self.hang_forever = hang_forever
        self.current_wait = 0
        self.is_requesting = False

    def call_mcp_tool(self, context: dict) -> dict:
        self.start_request(context)
        self.current_wait = self.latency_ms
        return self.get_response()

    def start_request(self, context: dict):
        self.last_call = context
        self.is_requesting = True
        self.current_wait = 0

    def tick(self, ms: int):
        if self.is_requesting:
            self.current_wait += ms

    def get_response(self) -> dict | None:
        if self.hang_forever:
            return None
        if self.is_requesting and self.current_wait >= self.latency_ms:
            self.is_requesting = False
            if self.index < len(self.responses):
                resp = self.responses[self.index]
                self.index += 1
                return resp
            return {"action": "stop", "text": "", "expect_reply": False}
        return None
