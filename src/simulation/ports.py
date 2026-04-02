from abc import ABC, abstractmethod
from typing import List
from .models import VirtualAudioFrame

class IMicrophone(ABC):
    @abstractmethod
    def read_frame(self) -> VirtualAudioFrame:
        pass

class ISpeaker(ABC):
    @abstractmethod
    def play_frame(self, frame: VirtualAudioFrame):
        pass

    @abstractmethod
    def speak(self, text: str):
        pass

    @abstractmethod
    def flush(self) -> str:
        """Stops playback instantly and returns the text actually played."""
        pass
    
    @abstractmethod
    def is_speaking(self) -> bool:
        pass
    
    @abstractmethod
    def tick(self, ms: int):
        pass

class IVAD(ABC):
    @abstractmethod
    def analyze(self, frame: VirtualAudioFrame) -> float:
        pass

class ISTT(ABC):
    @abstractmethod
    def transcribe(self, frames: List[VirtualAudioFrame]) -> str:
        pass

class ILLMBridge(ABC):
    @abstractmethod
    def call_mcp_tool(self, context: dict) -> dict:
        pass
        
    @abstractmethod
    def start_request(self, context: dict):
        pass
        
    @abstractmethod
    def tick(self, ms: int):
        pass
        
    @abstractmethod
    def get_response(self) -> dict | None:
        pass
