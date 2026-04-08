import os
import time
import subprocess
import httpx
import threading
from simulation.ports import ISpeaker
from simulation.models import VirtualAudioFrame
from dotenv import load_dotenv
from logger import logger

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
        
        self._lock = threading.RLock()
        self._is_preparing = False
        self._stop_event = threading.Event()
        self._thread = None
        
        logger.info(f"ElevenLabs Speaker initialized. Voice ID: {self.voice_id}, API Key Present: {bool(self.api_key)}")

    def speak(self, text: str):
        if not text.strip():
            return

        # Cancel any current playback or preparation
        self.flush()

        with self._lock:
            self.current_text = text
            self.words = text.split()
            self._is_preparing = True
            self._stop_event.clear()
            self.start_time = 0 # Won't start until afplay starts

        self._thread = threading.Thread(target=self._generate_and_play, args=(text,), daemon=True)
        self._thread.start()

    def _generate_and_play(self, text: str):
        try:
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
                    logger.debug(f"Calling ElevenLabs API for Voice ID: {self.voice_id}")
                    response = client.post(url, json=data, headers=headers, timeout=10.0)
                    response.raise_for_status()
                    
                    if self._stop_event.is_set():
                        return

                    with open(self.temp_file, "wb") as f:
                        f.write(response.content)
                        
                    if self._stop_event.is_set():
                        return

                    with self._lock:
                        # Play the downloaded audio
                        self.start_time = time.time()
                        self.process = subprocess.Popen(
                            ["afplay", self.temp_file],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )
            else:
                logger.warning("No ELEVENLABS_API_KEY found, falling back to 'say'")
                if self._stop_event.is_set(): return
                with self._lock:
                    self.start_time = time.time()
                    self.process = subprocess.Popen(
                        ["say", text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
        except Exception as e:
            logger.error(f"ElevenLabs Error: {e}")
            if self._stop_event.is_set(): return
            # Fallback to macOS say
            with self._lock:
                self.start_time = time.time()
                self.process = subprocess.Popen(
                    ["say", text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        finally:
            with self._lock:
                self._is_preparing = False

    def play_frame(self, frame: VirtualAudioFrame):
        pass

    def tick(self, ms: int):
        pass

    def is_speaking(self) -> bool:
        with self._lock:
            if self._is_preparing:
                return True
            if self.process is None:
                return False
            is_running = self.process.poll() is None
            if not is_running:
                self.current_text = ""
                self.words = []
                self.process = None
            return is_running

    def has_started_audio(self) -> bool:
        with self._lock:
            if self.process is None:
                return False
            return self.process.poll() is None

    def flush(self) -> str:
        # Signal the thread to stop if it's still downloading
        self._stop_event.set()
        
        with self._lock:
            if not self.is_speaking():
                self._is_preparing = False
                return ""

            # Immediately kill the playback process if it exists
            if self.process:
                self.process.kill()
                self.process.wait()
            
            # If we were preparing but hadn't started afplay yet, we spoken 0 words
            if self.start_time == 0:
                words_spoken = 0
            else:
                elapsed_ms = (time.time() - self.start_time) * 1000
                words_spoken = int(elapsed_ms * self.words_per_ms)
            
            spoken = " ".join(self.words[:words_spoken])
            
            self.current_text = ""
            self.words = []
            self.process = None
            self._is_preparing = False
            
            return spoken
