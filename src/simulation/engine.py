from enum import Enum
from typing import List
from .models import Config, VirtualAudioFrame
from .ports import IMicrophone, ISpeaker, IVAD, ISTT, ILLMBridge

class State(Enum):
    IDLE = 1
    AI_SPEAKING = 2
    LISTENING = 3
    PROCESSING = 4
    EXECUTING = 5
    STANDBY = 6

class CoreEngine:
    def __init__(self, config: Config, mic: IMicrophone, speaker: ISpeaker, vad: IVAD, stt: ISTT, llm: ILLMBridge):
        self.config = config
        self.mic = mic
        self.speaker = speaker
        self.vad = vad
        self.stt = stt
        self.llm = llm
        
        self.state = State.EXECUTING
        self.tick_ms = 10
        self.current_silence_duration_ms = 0
        self.current_speech_duration_ms = 0
        self.current_grace_ms = 0
        self.buffer: List[VirtualAudioFrame] = []
        self.was_interrupted = False
        
        self.latest_transcription = ""
        self.last_tool_call_result = None
        self.expect_reply = True
        self.standby_mode = False
        
        self.total_recording_ms = 0
        self.total_listening_ms = 0
        self.has_started_speaking = False
        self.processing_wait_ms = 0

    def start_conversation(self, initial_text: str, standby_mode: bool = False):
        self.expect_reply = True
        self.standby_mode = standby_mode
        if initial_text:
            self.state = State.AI_SPEAKING
            self.speaker.speak(initial_text)
        elif self.standby_mode:
            # We are entering standby mode to wait for the user indefinitely.
            # If the VAD is PTT, we can safely close the mic stream to turn off the orange dot.
            if hasattr(self.vad, "is_pressed"):
                if hasattr(self.mic, "stop_stream"):
                    self.mic.stop_stream()
            self.state = State.STANDBY
            self._reset_listening_state()
        else:
            self.state = State.LISTENING
            self._reset_listening_state()

    def _reset_listening_state(self):
        self.buffer = []
        self.current_silence_duration_ms = 0
        self.current_speech_duration_ms = 0
        self.current_grace_ms = 0
        self.total_recording_ms = 0
        self.total_listening_ms = 0
        self.has_started_speaking = False

    def _trigger_processing(self):
        self.state = State.PROCESSING
        self.processing_wait_ms = 0
        self.latest_transcription = self.stt.transcribe(self.buffer)
        self.buffer = [] 
        self.current_speech_duration_ms = 0
        self.current_grace_ms = 0
        self.current_silence_duration_ms = 0
        self.total_recording_ms = 0
        self.total_listening_ms = 0
        self.has_started_speaking = False
        
        if not self.latest_transcription.strip() or self.latest_transcription.strip() == "[BLANK_AUDIO]":
            self.state = State.LISTENING
            self.buffer = []
            self.current_silence_duration_ms = 0
            self.current_speech_duration_ms = 0
            self.current_grace_ms = 0
            self.total_recording_ms = 0
            self.has_started_speaking = False
            return
            
        context = {
            "user_speech": self.latest_transcription,
            "was_interrupted": self.was_interrupted
        }
        self.llm.start_request(context)

    def tick(self):
        frame = self.mic.read_frame()
        self.speaker.tick(self.tick_ms)
        self.llm.tick(self.tick_ms)
        
        vad_prob = self.vad.analyze(frame)
        is_speech = vad_prob > self.config.vad_probability_threshold
        frame.has_speech = is_speech

        if self.state == State.AI_SPEAKING:
            if is_speech:
                self.current_grace_ms = 0
                self.buffer.append(frame)
                self.current_speech_duration_ms += self.tick_ms
                
                if self.current_speech_duration_ms >= self.config.vad_bargein_threshold_ms:
                    # TTFA Interruption check
                    if hasattr(self.speaker, "has_started_audio") and not self.speaker.has_started_audio():
                        # Intercepted before the user even heard audio!
                        self.speaker.flush() # drop it
                        self.was_interrupted = False # from user's perspective, they just kept talking
                        self.state = State.LISTENING
                        self.current_silence_duration_ms = 0
                        self.total_recording_ms = self.current_speech_duration_ms
                        self.has_started_speaking = True
                        self.total_listening_ms = 0
                    else:
                        spoken_text = self.speaker.flush()
                        self.was_interrupted = True
                        self.state = State.LISTENING
                        self.current_silence_duration_ms = 0
                        self.total_recording_ms = self.current_speech_duration_ms
                        self.has_started_speaking = True
                        self.total_listening_ms = 0
                elif not self.speaker.is_speaking():
                    if self.standby_mode:
                        self.state = State.STANDBY
                        if hasattr(self.vad, "is_pressed") and hasattr(self.mic, "stop_stream"):
                            self.mic.stop_stream()
                        self._reset_listening_state()
                    else:
                        self.state = State.LISTENING if self.expect_reply else State.EXECUTING
                        if self.state == State.LISTENING:
                            self.was_interrupted = False
                            self.current_silence_duration_ms = 0
                            self.total_recording_ms = self.current_speech_duration_ms
                            self.has_started_speaking = True
                            self.total_listening_ms = 0
                        elif self.state == State.EXECUTING:
                            if hasattr(self.mic, 'stop_stream'):
                                self.mic.stop_stream()
                            self.llm.start_request({"status": "notification_delivered"})
            else:
                self.current_grace_ms += self.tick_ms
                if self.current_grace_ms > self.config.vad_silence_grace_ms:
                    if self.current_speech_duration_ms > 0 and self.current_speech_duration_ms < self.config.vad_backchannel_max_ms:
                        pass # Ignore backchannel
                    self.buffer = [] 
                    self.current_speech_duration_ms = 0
                    self.current_grace_ms = 0
                    
                if not self.speaker.is_speaking():
                    if self.standby_mode:
                        self.state = State.STANDBY
                        if hasattr(self.vad, "is_pressed") and hasattr(self.mic, "stop_stream"):
                            self.mic.stop_stream()
                        self._reset_listening_state()
                    else:
                        self.state = State.LISTENING if self.expect_reply else State.EXECUTING
                        if self.state == State.LISTENING:
                            self._reset_listening_state()
                            self.was_interrupted = False
                        elif self.state == State.EXECUTING:
                            if hasattr(self.mic, 'stop_stream'):
                                self.mic.stop_stream()
                            self.llm.start_request({"status": "notification_delivered"})

        elif self.state == State.LISTENING:
            self.buffer.append(frame)
            self.total_listening_ms += self.tick_ms
            
            if is_speech:
                self.current_grace_ms = 0
                self.current_silence_duration_ms = 0
                self.current_speech_duration_ms += self.tick_ms
                if not self.has_started_speaking:
                    self.has_started_speaking = True
                self.total_recording_ms += self.tick_ms
            else:
                self.current_grace_ms += self.tick_ms
                if self.current_grace_ms > self.config.vad_silence_grace_ms:
                    self.current_silence_duration_ms += self.tick_ms
                    self.current_speech_duration_ms = 0
                else:
                    # Still consider it speech for the duration counter!
                    self.current_speech_duration_ms += self.tick_ms
                    self.current_silence_duration_ms = 0

                if self.has_started_speaking:
                    self.total_recording_ms += self.tick_ms
                
            patience = self.config.endpointing_patience_interrupted_ms if self.was_interrupted else self.config.endpointing_patience_normal_ms
            
            if self.total_recording_ms >= self.config.max_recording_ms:
                self._trigger_processing()
                return

            if not self.has_started_speaking and self.total_listening_ms >= self.config.listening_timeout_ms:
                self.llm.start_request({"status": "silence_timeout", "user_transcript": ""})
                self.state = State.PROCESSING
                self.processing_wait_ms = 0
                return

            if self.has_started_speaking and self.current_silence_duration_ms >= patience:
                if any(f.has_speech for f in self.buffer):
                    self._trigger_processing()
                else:
                    self._reset_listening_state()

        elif self.state == State.STANDBY:
            if is_speech:
                self.standby_mode = False
                self.state = State.LISTENING
                if hasattr(self.vad, "is_pressed") and hasattr(self.mic, "start_stream"):
                    # We closed it earlier for PTT, so we need to reopen it.
                    self.mic.start_stream()
                self._reset_listening_state()
                self.buffer.append(frame)
                self.total_listening_ms += self.tick_ms
                self.current_speech_duration_ms += self.tick_ms
                self.has_started_speaking = True
                self.total_recording_ms += self.tick_ms

        elif self.state == State.PROCESSING:
            self.buffer.append(frame)
            self.processing_wait_ms += self.tick_ms
            
            if self.processing_wait_ms >= self.config.llm_timeout_ms:
                import sys
                print("LLM Timeout reached. Assuming agent abandoned the voice loop. Tearing down hardware.", file=sys.stderr)
                self.state = State.EXECUTING
                if hasattr(self.mic, 'stop_stream'):
                    self.mic.stop_stream()
                self.processing_wait_ms = 0
                self.buffer = []
                return

            response = self.llm.get_response()
            if response is not None:
                self.last_tool_call_result = response
                
                orphan_speech = any(f.has_speech for f in self.buffer)
                if orphan_speech:
                    self.was_interrupted = True
                    self.state = State.LISTENING
                    self.has_started_speaking = True
                    self.current_silence_duration_ms = 0
                    self.total_recording_ms = len(self.buffer) * self.tick_ms
                    self.current_speech_duration_ms = sum(10 for f in self.buffer if f.has_speech)
                    self.current_grace_ms = 0
                    return

                self.buffer = []
                self.expect_reply = response.get("expect_reply", True)
                text = response.get("text", "")
                
                if text:
                    self.speaker.speak(text)
                    self.state = State.AI_SPEAKING
                else:
                    self.state = State.LISTENING if self.expect_reply else State.EXECUTING
                    if self.state == State.LISTENING:
                        self._reset_listening_state()

        elif self.state == State.EXECUTING:
            if is_speech:
                self.buffer.append(frame)
                if "Agent, stop" in self.stt.transcribe(self.buffer):
                    self.state = State.LISTENING
                    self.was_interrupted = True
                    self._reset_listening_state()
            else:
                if not self.speaker.is_speaking():
                    self.buffer = []
