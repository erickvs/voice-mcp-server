import os
import time
import subprocess
import torch
import soundfile as sf
from kokoro import KPipeline
from simulation.ports import ISpeaker
from simulation.models import VirtualAudioFrame

class KokoroSpeaker(ISpeaker):
    def __init__(self, wpm=150, voice="af_heart"): # 'af_heart' is a highly expressive American Female voice
        self.wpm = wpm
        self.words_per_ms = (wpm / 60) / 1000
        self.current_text = ""
        self.words = []
        self.process = None
        self.start_time = 0
        self.temp_file = "/tmp/kokoro_output.wav"
        
        print(f"[DEBUG SPEAKER] Loading local Kokoro TTS model (Voice: {voice})...")
        # Load the pipeline. Since you are on M4 Max, we will try to use MPS if available
        if torch.backends.mps.is_available():
            self.device = "mps"
        elif torch.cuda.is_available():
            self.device = "cuda"
        else:
            self.device = "cpu"
            
        # Initialize the pipeline (downloads weights first time ~300MB)
        # We use lang_code 'a' for American English
        self.pipeline = KPipeline(lang_code='a', device=self.device)
        self.voice = voice
        print(f"[DEBUG SPEAKER] Kokoro TTS loaded successfully on {self.device}.")

    def speak(self, text: str):
        if not text.strip():
            return

        self.current_text = text
        self.words = text.split()
        
        try:
            print(f"[DEBUG SPEAKER] Generating Kokoro audio for: {text[:50]}...")
            # Generate the audio locally
            generator = self.pipeline(
                text, voice=self.voice, # <= change voice here
                speed=1.0, split_pattern=r'\n+'
            )
            
            # Since pipeline returns a generator of segments, we can just grab the first one (or concatenate them)
            # For simplicity in testing, we concatenate them all
            audio_segments = []
            for gs, ps, audio in generator:
                audio_segments.append(audio)
            
            if not audio_segments:
                print("[DEBUG SPEAKER] Kokoro generated empty audio.")
                return
                
            final_audio = torch.cat(audio_segments, dim=0).cpu().numpy()
            
            # Save to temporary file at 24kHz (Kokoro's default sample rate)
            sf.write(self.temp_file, final_audio, 24000)
            print("[DEBUG SPEAKER] Audio generated, starting playback.")
            
            # Play the generated audio using afplay (macOS native)
            self.start_time = time.time()
            self.process = subprocess.Popen(
                ["afplay", self.temp_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
        except Exception as e:
            print(f"[DEBUG SPEAKER] Kokoro Generation Error: {e}")
            # Fallback to macOS say
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