import pytest
from simulation.models import Config
from simulation.ports import VirtualAudioFrame
from simulation.adapters import ScriptedMicrophone, MockVAD, VirtualSpeaker, MockSTT, MockLLMBridge
from simulation.engine import CoreEngine, State

def test_scenario_1_thoughtful_pause():
    script = [
        (2000, False, False, ""),
        (1000, True, False, "I want a python script..."),
        (1200, False, False, ""),
        (1000, True, False, "...that uses pandas."),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Got it.", "expect_reply": True}])
    
    config = Config(endpointing_patience_normal_ms=1800)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.start_conversation("How can I help?")
    
    while engine.state == State.AI_SPEAKING:
        engine.tick()
        
    assert engine.state == State.LISTENING
    
    for _ in range(720): # 7200 ms total
        engine.tick()
    
    assert engine.latest_transcription == "I want a python script... ...that uses pandas."
    assert engine.last_tool_call_result is not None


def test_scenario_2_brutal_barge_in():
    script = [
        (2000, False, False, ""),
        (1000, True, False, "No wait, use a database."),
        (1000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=150)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Okay database.", "expect_reply": True}])
    
    config = Config(vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    sentence = "One two three four five six seven eight nine ten eleven twelve."
    engine.start_conversation(sentence)
    
    for _ in range(200): # 2000ms silence
        engine.tick()
    
    assert engine.state == State.AI_SPEAKING
    assert engine.speaker.is_speaking() == True
    
    for _ in range(30): # 300ms of speech
        engine.tick()
        
    assert engine.state == State.LISTENING
    assert engine.was_interrupted == True
    
    for _ in range(170): # finish the rest
        engine.tick()
        
    assert engine.latest_transcription == "No wait, use a database."
    assert "user_speech" in engine.llm.last_call
    assert engine.llm.last_call["was_interrupted"] == True


def test_scenario_3_dog_bark():
    script = [
        (1000, False, False, ""),
        (150, False, True, "bark"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([])
    
    config = Config(vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    engine.start_conversation("This is a short sentence.")
    
    while engine.speaker.is_speaking():
        engine.tick()
        
    assert engine.was_interrupted == False
    assert engine.state == State.LISTENING


def test_scenario_4_phase_transition():
    script = [
        (1000, True, False, "Do the task."),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Working on it.", "expect_reply": False}])
    
    config = Config(endpointing_patience_normal_ms=1800)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING 
    
    for _ in range(500):
        engine.tick()
        if engine.state == State.EXECUTING:
            break
            
    assert engine.state == State.EXECUTING

def test_scenario_5_backchannel():
    script = [
        (2000, False, False, ""),
        (200, True, False, "mhmm"),
        (3000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=150)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([])
    
    config = Config(vad_backchannel_max_ms=250, vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    # 5000ms sentence at 150wpm -> 12.5 words.
    engine.start_conversation("One two three four five six seven eight nine ten eleven twelve thirteen.")
    
    for _ in range(550):
        engine.tick()
        
    assert engine.was_interrupted == False
    assert engine.state == State.LISTENING

def test_scenario_6_hesitant_interruption():
    script = [
        (2000, False, False, ""),
        (400, True, False, "Wait, actually-"),
        (1000, False, False, "") # Total 3400ms
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=150)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Yes?", "expect_reply": True}])
    
    config = Config(vad_bargein_threshold_ms=300, endpointing_patience_interrupted_ms=700)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    engine.start_conversation("One two three four five six seven eight nine ten eleven twelve thirteen.")
    
    for _ in range(350):
        engine.tick()
        
    assert engine.state == State.PROCESSING or engine.state == State.AI_SPEAKING
    assert engine.latest_transcription == "Wait, actually-"
    assert engine.was_interrupted == True

def test_scenario_7_collision():
    script = [
        (1000, True, False, "I speak first"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Okay", "expect_reply": True}])
    
    config = Config(vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    engine.start_conversation("I will say something.")
    
    for _ in range(30):
        engine.tick()
    
    assert engine.state == State.LISTENING
    assert engine.was_interrupted == True

def test_scenario_8_wait_dont_execute():
    script = [
        (500, False, False, ""),
        (1000, True, False, "Stop!"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=150)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([])
    
    config = Config(vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    engine.expect_reply = False
    engine.start_conversation("I am going to run the drop table script.")
    
    for _ in range(80): # 800ms
        engine.tick()
        
    assert engine.state == State.LISTENING
    assert engine.was_interrupted == True

def test_scenario_9_thinker():
    script = [
        (500, True, False, "First part"),
        (1200, False, False, ""),
        (1000, True, False, "Second part"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Got it", "expect_reply": True}])
    
    config = Config(endpointing_patience_normal_ms=1800)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING
    engine._reset_listening_state()
    
    for _ in range(480):
        engine.tick()
        
    assert engine.latest_transcription == "First part Second part"

def test_scenario_10_noise_during_patience():
    script = [
        (1000, True, False, "Hello"),
        (500, False, False, ""),
        (400, False, True, "noise"),
        (1000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Got it", "expect_reply": True}])
    
    config = Config(endpointing_patience_normal_ms=1800)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING
    engine._reset_listening_state()
    
    for _ in range(290):
        engine.tick()
        
    assert engine.state == State.PROCESSING or engine.state == State.AI_SPEAKING
    assert engine.latest_transcription == "Hello"

def test_scenario_11_ghost():
    script = [
        (11000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Hello?", "expect_reply": True}])
    
    config = Config(listening_timeout_ms=10000)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING
    engine._reset_listening_state()
    
    for _ in range(1000):
        engine.tick()
        
    assert engine.llm.last_call is not None
    assert engine.llm.last_call.get("status") == "silence_timeout"

def test_scenario_12_endless_rambler():
    script = [
        (65000, True, False, "Rambling...")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Okay enough", "expect_reply": True}])
    
    config = Config(max_recording_ms=60000)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING
    engine._reset_listening_state()
    
    for _ in range(6000):
        engine.tick()
        
    assert engine.latest_transcription == "Rambling..."
    assert engine.state == State.PROCESSING or engine.state == State.AI_SPEAKING

def test_scenario_13_orphan_speech():
    script = [
        (1000, False, False, ""),
        (1000, True, False, "Oh, and also..."),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "This is delayed", "expect_reply": True}], latency_ms=3000)
    
    config = Config()
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    engine.state = State.PROCESSING
    engine.llm.start_request({"user_speech": "Original text", "was_interrupted": False})
    
    for _ in range(350):
        engine.tick()
        
    assert engine.state == State.LISTENING
    assert engine.was_interrupted == True

def test_scenario_14_empty_stt_return():
    script = [
        (500, True, False, ""),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT(force_return="")
    llm = MockLLMBridge([])
    
    config = Config(endpointing_patience_normal_ms=1800)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING
    engine._reset_listening_state()
    
    for _ in range(260):
        engine.tick()
        
    assert engine.state == State.LISTENING
    assert engine.llm.last_call is None

def test_scenario_15_rapid_turn_taking():
    script = [
        (500, True, False, "User 1"),
        (1000, False, False, ""),
        (500, True, False, "User 2"),
        (1000, False, False, ""),
        (500, True, False, "User 3"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=600)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([
        {"text": "AI 1", "expect_reply": True},
        {"text": "AI 2", "expect_reply": True},
        {"text": "AI 3", "expect_reply": True}
    ], latency_ms=0)
    
    config = Config(endpointing_patience_normal_ms=700)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING
    engine._reset_listening_state()
    
    for _ in range(560):
        engine.tick()
        
    assert engine.latest_transcription == "User 3"

def test_scenario_16_late_barge_in():
    script = [
        (2900, False, False, ""),
        (500, True, False, "Late interrupt"),
        (1000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=150)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Got it", "expect_reply": True}])
    
    config = Config(vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    
    engine.start_conversation("One two three four five six seven eight")
    
    for _ in range(450):
        engine.tick()
        
    assert engine.was_interrupted == True
    assert engine.state == State.PROCESSING or engine.state == State.AI_SPEAKING
    assert engine.latest_transcription == "Late interrupt"

def test_scenario_17_wake_word():
    script = [
        (800, True, False, "Agent, stop"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([])
    
    config = Config()
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.EXECUTING
    
    for _ in range(100):
        engine.tick()
        
    assert engine.state == State.LISTENING
    assert engine.was_interrupted == True

def test_scenario_18_vad_flicker():
    script = [
        (150, True, False, "First"),
        (40, False, False, ""),
        (150, True, False, "Second"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([])
    
    config = Config(vad_silence_grace_ms=50, vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.start_conversation("A longer sentence to test flicker.")
    
    for _ in range(50): # 500ms
        engine.tick()
        
    assert engine.state == State.LISTENING
    assert engine.was_interrupted == True

def test_scenario_19_whisper_hallucination():
    script = [
        (400, True, False, ""),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker()
    vad = MockVAD()
    stt = MockSTT(force_return=" [BLANK_AUDIO] ")
    llm = MockLLMBridge([])
    
    config = Config(endpointing_patience_normal_ms=1800)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.LISTENING
    engine._reset_listening_state()
    
    for _ in range(250):
        engine.tick()
        
    assert engine.state == State.LISTENING
    assert engine.llm.last_call is None

def test_scenario_20_ttfa_interruption():
    script = [
        (100, False, False, ""),
        (500, True, False, "User spoke early"),
        (2000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=150, ttfa_ms=600)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([{"text": "Ok", "expect_reply": True}])
    
    config = Config(tts_ttfa_ms=600, vad_bargein_threshold_ms=300)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.start_conversation("I am an AI about to speak.")
    
    for _ in range(280): # 2800ms
        engine.tick()
        
    assert engine.state in [State.PROCESSING, State.AI_SPEAKING, State.LISTENING]
    assert engine.was_interrupted == False
    assert engine.latest_transcription == "User spoke early"

def test_scenario_21_network_black_hole():
    script = [
        (15000, False, False, "")
    ]
    mic = ScriptedMicrophone(script)
    speaker = VirtualSpeaker(wpm=1000)
    vad = MockVAD()
    stt = MockSTT()
    llm = MockLLMBridge([], hang_forever=True)
    
    config = Config(llm_timeout_ms=15000)
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.PROCESSING
    engine.llm.start_request({"user_speech": "Hello", "was_interrupted": False})
    
    for _ in range(1500):
        engine.tick()
        
    assert engine.state == State.EXECUTING