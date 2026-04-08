import os
import time
import subprocess
import httpx
from simulation.ports import ISpeaker
from simulation.models import VirtualAudioFrame
from dotenv import load_dotenv

load_dotenv()

class ElevenLabsSpeaker(ISpeaker):
    def __init__(self, wpm=150, voice_id="aEO01A4wXwd1O8GPgGlF"):
        self.wpm = wpm
        self.words_per_ms = (wpm / 60) / 1000
        self.current_text = ""
        self.words = []
        self.process = None
        self.start_time = 0
        self.voice_id = os.getenv("ELEVENLABS_VOICE_ID", voice_id)
        self.api_key = os.getenv("ELEVENLABS_API_KEY")
        self.temp_file = "/tmp/elevenlabs_output.mp3"

    def speak(self, text: str):
        if not text.strip():
            return

        self.current_text = text
        self.words = text.split()

        if self.api_key:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self.api_key
            }
            data = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.5
                }
            }
            
            with httpx.Client() as client:
                try:
                    response = client.post(url, json=data, headers=headers, timeout=10.0)
                    response.raise_for_status()
                    
                    with open(self.temp_file, "wb") as f:
                        f.write(response.content)
                        
                    # Play the downloaded audio
                    self.start_time = time.time()
                    self.process = subprocess.Popen(
                        ["afplay", self.temp_file],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                except Exception as e:
                    print(f"ElevenLabs API Error: {e}")
                    # Fallback to macOS say
                    self.start_time = time.time()
                    self.process = subprocess.Popen(
                        ["say", text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
        else:
            print("Warning: No ELEVENLABS_API_KEY found, falling back to 'say'")
            self.start_time = time.time()
            self.process = subprocess.Popen(
                ["say", text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

    def play_frame(self, frame: VirtualAudioFrame):
        pass

    def tick(self, ms: int):
        pass

    def is_speaking(self) -> bool:
        if self.process is None:
            return False
        is_running = self.process.poll() is None
        if not is_running:
            self.current_text = ""
            self.words = []
            self.process = None
        return is_running

    def has_started_audio(self) -> bool:
        return self.is_speaking()

    def flush(self) -> str:
        if not self.is_speaking():
            return ""

        # Immediately kill the playback process
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
