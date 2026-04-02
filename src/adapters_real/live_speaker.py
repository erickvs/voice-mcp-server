import subprocess
import time
from simulation.ports import ISpeaker
from simulation.models import VirtualAudioFrame

class LiveSpeaker(ISpeaker):
    def __init__(self, wpm=150):
        self.wpm = wpm
        self.words_per_ms = (wpm / 60) / 1000
        self.current_text = ""
        self.words = []
        self.process = None
        self.start_time = 0

    def speak(self, text: str):
        self.current_text = text
        self.words = text.split()
        self.start_time = time.time()
        
        # Start say command non-blocking
        self.process = subprocess.Popen(
            ["say", text],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    def play_frame(self, frame: VirtualAudioFrame):
        pass

    def tick(self, ms: int):
        pass # Clock is driven by the mic in a real environment

    def is_speaking(self) -> bool:
        if self.process is None:
            return False
        # Poll returns None if process is still running
        is_running = self.process.poll() is None
        if not is_running:
            self.current_text = ""
            self.words = []
            self.process = None
        return is_running

    def has_started_audio(self) -> bool:
        return self.is_speaking() # Approximation for macOS say

    def flush(self) -> str:
        if not self.is_speaking():
            return ""

        # Immediately kill the say process
        self.process.kill()
        
        # Explicitly wait for the process to terminate and reap it
        self.process.wait()
        
        elapsed_ms = (time.time() - self.start_time) * 1000
        words_spoken = int(elapsed_ms * self.words_per_ms)
        
        spoken = " ".join(self.words[:words_spoken])
        
        self.current_text = ""
        self.words = []
        self.process = None
        
        return spoken
