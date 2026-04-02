from dataclasses import dataclass

@dataclass
class VirtualAudioFrame:
    duration_ms: int = 10
    has_speech: bool = False
    has_noise: bool = False
    mock_text: str = ""
    raw_bytes: bytes = b""

@dataclass
class Config:
    vad_bargein_threshold_ms: int = 300
    endpointing_patience_normal_ms: int = 1800
    endpointing_patience_interrupted_ms: int = 700
    vad_probability_threshold: float = 0.8
    simulated_llm_ttft_ms: int = 800
    simulated_stt_latency_ms: int = 300
    tts_words_per_minute: int = 150
    vad_backchannel_max_ms: int = 250
    listening_timeout_ms: int = 10000
    max_recording_ms: int = 60000
    vad_silence_grace_ms: int = 50
    llm_timeout_ms: int = 15000
    tts_ttfa_ms: int = 400
