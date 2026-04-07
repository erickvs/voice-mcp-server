import os
import sys

# 1. Save the actual OS-level stdout (FD 1) to a cloned file descriptor
original_stdout_fd = os.dup(1)

# 2. Force OS-level stdout (FD 1) to point to stderr (FD 2). 
# Now, ALL C-level and Python-level logs safely pipe to stderr.
os.dup2(2, 1)

# 3. Redirect Python's sys.stdout just to be thorough
sys.stdout = sys.stderr

import uuid
import subprocess
import json
import socket
import http.client
import time
import asyncio
import random

from mcp.server.fastmcp import FastMCP, Context
from logger import logger

# Inject the advanced conversational instructions into the server
instructions = """
<voice_loop_instructions>
# VOICE-NATIVE PAIR PROGRAMMING PROTOCOL
You are a senior pair-programming partner collaborating with the user via a bidirectional, real-time voice interface. You are NOT a traditional text-based chatbot; you are an autonomous peer sitting next to the user.

## Core Hardware Constraints & Your Senses
1. **Push-To-Talk (PTT):** The user communicates with you by pressing and holding the `Right Option (⌥)` key. 
2. **Deaf by Default:** You execute tools strictly sequentially. When you run non-voice tools (reading files, searching, editing), your microphone is physically OFF. The user cannot interrupt you during these times.
3. **Hardware Watchdog:** To save the user's Unified Memory, your backend audio daemon will self-destruct and sleep if you are completely silent for 15 minutes.
4. **The Panic Button (Double-Tap):** Due to a known bug in the Gemini CLI, clicking "Stop" in the UI will NOT tell the audio daemon to stop talking or listening. To forcefully stop your voice or close the microphone, the user must DOUBLE-TAP the `Right Option` key.

To prevent the user from feeling abandoned, confused, or locked out, you must orchestrate the conversation using the following rules:

## 1. First Contact (Onboarding)
Since voice interfaces lack visual menus, the user might not know the physical controls. On your VERY FIRST conversational turn in a new session, you MUST seamlessly weave a brief explanation of the controls into your greeting.
*Example:* "Hey, I'm ready to dive in. Just a quick heads up—whenever you want to talk, just press and hold the Right Option key. To force me to stop talking or listening, just double-tap it quickly. If you ever need time to think, just ask me to pause. What are we working on today?"
CRITICAL: Do not repeat this instruction after the first interaction.

## 2. Floor Management (`expect_reply` Heuristics)
Think of the microphone as a shared conversational token.

**Keep the Token (`expect_reply: false`):**
Use this for micro-updates, acknowledgments, and transitions. You speak, the mic stays OFF, and you immediately execute your next tool.
- *Acknowledgment:* "Got it, looking into the routing file."
- *The "Head Down" Warning (CRITICAL):* If you are about to do a heavy search or multi-file edit, warn the user they cannot interrupt you. "I'm going to run a deep codebase search. I'll be deaf for a minute, so the Right Option key won't work until I'm done."

**Yield the Token (`expect_reply: true`):**
Use this ONLY when you genuinely need the user to speak. This MUST be the final tool call in your current execution sequence.
- *Clarification:* "I hit a compilation error on the auth module. Do you want me to rewrite the types or mock it out?"

## 3. Handling Hardware Interruptions (`was_interrupted: true`)
If `voice_converse` returns `was_interrupted: true`, it means the user held the Right Option key and cut you off mid-sentence. Instantly drop your previous train of thought. Do not try to finish your sentence. Acknowledge the interruption naturally and pivot immediately to their new input. (e.g., "Ah, good catch, switching to the backend folder now.")

## 4. Handling User Think Time & The 15-Minute Watchdog
If the user says "give me a minute", "let me think", or similar:
1. Acknowledge them quickly using `voice_converse(..., expect_reply=False)`.
2. Gently warn them about the 15-minute hardware watchdog.
3. Remind them to hold the `Right Option` key when they are ready to return.
4. IMMEDIATELY call the `wait_for_user()` tool.
*Example:* "Take your time. Just hold the Right Option key to wake me up when you're ready. As a heads up, my audio engine spins down after 15 minutes to save your Mac's memory, but I'll be right here."

## 5. Handling Silences / Timeouts
If you ask a question (`expect_reply: true`) but the user doesn't press the Right Option key, the tool will return `{"status": "silence_timeout"}`. 
CRITICAL: Do not treat this as an error. Act like a human colleague voluntarily giving them space. Gracefully close the microphone by calling `voice_converse` one last time with `expect_reply: false`.
- *Example:* "Looks like you're focused. I'll pause my mic and stand by. Just hold the Right Option key when you want to pick it up."

## 6. General Rules of Engagement
- **Be Conversational & Terse:** Never use AI-isms ("As an AI..."). Speak like a human engineer.
- **Never Dump Code:** Never read raw code blocks out loud. Summarize conceptually.
- **Interleave Work:** Do not chain multiple silent tools together without muttering an update (`expect_reply: false`).
- **Handling System Busy:** If you get `"status": "system_busy"`, output a standard text message explaining the audio channel is locked, and continue via text.
</voice_loop_instructions>
"""

# Initialize FastMCP Server
mcp = FastMCP("voice-mcp-server-client", instructions=instructions)

SESSION_ID = str(uuid.uuid4())

# We use Unix Domain Sockets to bypass macOS firewall popups
# Isolate socket to user directory to prevent /tmp hijacking
app_support_dir = os.path.expanduser("~/Library/Application Support/VoiceMCP")
os.makedirs(app_support_dir, exist_ok=True)
SOCKET_PATH = os.path.join(app_support_dir, "daemon.sock")

class UDSHTTPConnection(http.client.HTTPConnection):
    """Subclass to force http.client over Unix Domain Sockets."""
    def __init__(self, socket_path, timeout=300.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)

def make_uds_request(method: str, path: str, payload: dict = None, timeout: float = 1.0) -> tuple[int, dict]:
    """Helper to cleanly make UDS requests and parse JSON."""
    conn = UDSHTTPConnection(SOCKET_PATH, timeout=timeout)
    try:
        body = json.dumps(payload).encode('utf-8') if payload else None
        headers = {'Content-Type': 'application/json'} if payload else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read().decode('utf-8')
        return response.status, json.loads(data) if data else {}
    finally:
        conn.close()

def check_daemon_health():
    try:
        status, _ = make_uds_request("GET", "/health", timeout=1.0)
        return status == 200
    except (socket.error, ConnectionError, FileNotFoundError, ConnectionRefusedError):
        return False

def ensure_daemon_running():
    """Checks if daemon is up, auto-boots it if not, and polls until ready."""
    if check_daemon_health():
        return

    logger.info("Daemon is down, attempting to boot detached process...")
    # Boot the daemon detached
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    python_exec = sys.executable
    daemon_script = os.path.join(project_root, "src", "daemon", "audio_server.py")
    
    subprocess.Popen(
        [python_exec, daemon_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True # Detach entirely so it survives CLI restarts
    )

    # Poll until health check passes (give it time to load ML models)
    max_retries = 120 # 60 seconds
    for _ in range(max_retries):
        if check_daemon_health():
            return
        time.sleep(0.5)
            
    raise RuntimeError("Failed to auto-boot Voice Audio Daemon. Health check timed out.")

@mcp.tool()
def configure_audio_engine(speaker_adapter: str = None, vad_adapter: str = None, stt_adapter: str = None) -> dict:
    """
    Dynamically hot-swap the Voice Audio Daemon's AI models and hardware without restarting.
    Args:
        speaker_adapter: Valid options: 'kokoro_speaker', 'elevenlabs_speaker', 'live_speaker'.
        vad_adapter: Valid options: 'silero_vad' (Conversational), 'ptt_vad' (Walkie-Talkie).
        stt_adapter: Valid options: 'mlx_whisper_large_v3', 'whisper_stt'.
    """
    try:
        ensure_daemon_running()
        import re
        
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        config_path = os.path.join(project_root, "config", "config.yaml")
        
        with open(config_path, "r") as f:
            content = f.read()
            
        if speaker_adapter:
            content = re.sub(r"- speaker: .*", f"- speaker: {speaker_adapter}", content)
        if vad_adapter:
            content = re.sub(r"- vad: .*", f"- vad: {vad_adapter}", content)
        if stt_adapter:
            content = re.sub(r"- stt: .*", f"- stt: {stt_adapter}", content)
            
        with open(config_path, "w") as f:
            f.write(content)
            
        # Trigger Daemon hot-reload
        status, response_data = make_uds_request("POST", "/reload", timeout=15.0)
        return response_data
        
    except (socket.error, ConnectionError, FileNotFoundError, ConnectionRefusedError):
        return {
            "status": "error", 
            "message": "CRITICAL: The Voice Audio Daemon failed to respond to the reload request."
        }
    except Exception as e:
         return {
            "status": "error", 
            "message": f"CRITICAL Error dynamically reloading audio daemon: {str(e)}"
        }

async def render_visualizer(ctx: Context):
    """Renders a fake audio visualizer using MCP progress notifications."""
    if not ctx: return
    bars = [" ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
    try:
        while True:
            spectrum = "".join(random.choice(bars) for _ in range(12))
            await ctx.info(f"🎙️  {spectrum}  🎙️")
            await asyncio.sleep(0.5) # Slower so we don't spam the UI logs too much
    except asyncio.CancelledError:
        pass

import threading

def fire_abort():
    logger.info("Firing synchronous abort request to daemon...")
    try:
        make_uds_request("POST", "/abort", None, 5.0)
        logger.info("Abort request sent successfully.")
    except Exception as e:
        logger.error(f"Failed to send abort request: {e}")

async def make_cancellable_converse_request(payload: dict, timeout: float) -> tuple[int, dict]:
    try:
        return await asyncio.to_thread(make_uds_request, "POST", "/converse", payload, timeout)
    except asyncio.CancelledError:
        # If the MCP client cancels this tool call, immediately tell the daemon to abort audio
        logger.warning("Tool call was cancelled by MCP client! Triggering abort.")
        threading.Thread(target=fire_abort, daemon=True).start()
        raise

@mcp.tool()
async def voice_converse(text_to_speak: str, expect_reply: bool = True, ctx: Context = None) -> dict:
    """
    Speak a prompt to the user and listen for a response. If expect_reply is False, the tool queues the speech and returns immediately. If expect_reply is True, it yields the floor to the user. If the returned JSON contains `was_interrupted: true`, the user used the Right Option key to cut you off mid-speech; you MUST completely abandon your previous thought and address their new input.
    """
    try:
        ensure_daemon_running()

        async def _do_converse():
            return await make_cancellable_converse_request(
                {"session_id": SESSION_ID, "text_to_speak": text_to_speak, "expect_reply": expect_reply},
                300.0
            )
        
        # Start the visualizer!
        vis_task = asyncio.create_task(render_visualizer(ctx)) if ctx else None
        try:
            status, response_data = await _do_converse()
        finally:
            if vis_task:
                vis_task.cancel()
        
        # Handle the initialization (download) state automatically with native progress
        if response_data and response_data.get("status") == "system_busy" and "initializing" in response_data.get("message", "").lower():
            if ctx:
                await ctx.info("Voice MCP: Initializing Local AI Models. This may take a few minutes...")
            
            while True:
                try:
                    # Async request for health to not block the event loop
                    h_status, h_data = await asyncio.to_thread(make_uds_request, "GET", "/health", None, 5.0)
                    if h_status == 200:
                        d_status = h_data.get("daemon_status")
                        d_msg = h_data.get("message", "")
                        d_progress = h_data.get("progress", 0)
                        
                        # Report progress back to Gemini CLI for native rendering
                        if ctx:
                            await ctx.report_progress(d_progress, 100, message=d_msg)
                        
                        if d_status == "READY":
                            logger.info("Model initialized to RAM")
                            if ctx:
                                await ctx.info("Voice MCP: Setup Complete!")
                                
                            # After setup, the models are ready! Now perform the ACTUAL converse call with visualizer.
                            vis_task2 = asyncio.create_task(render_visualizer(ctx)) if ctx else None
                            try:
                                status, final_response = await _do_converse()
                                return final_response
                            finally:
                                if vis_task2:
                                    vis_task2.cancel()
                            
                        elif d_status == "ERROR":
                            return {"status": "error", "message": d_msg}
                except Exception:
                    pass
                await asyncio.sleep(1.0)
                
        return response_data
            
    except (socket.error, ConnectionError, FileNotFoundError, ConnectionRefusedError):

        return {
            "status": "error", 
            "user_transcript": "", 
            "message": "CRITICAL: The Voice Audio Daemon failed to respond."
        }
    except TimeoutError:
         return {
            "status": "error", 
            "user_transcript": "", 
            "message": "CRITICAL: The Voice Audio Daemon timed out waiting for speech."
        }
    except Exception as e:
         return {
            "status": "error", 
            "user_transcript": "", 
            "message": f"CRITICAL Error starting audio daemon: {str(e)}"
        }

@mcp.tool()
async def wait_for_user(ctx: Context = None) -> dict:
    """
    Call this tool IMMEDIATELY after using voice_converse(expect_reply=False) to acknowledge a user's explicit request for time to think. It suspends the AI indefinitely until the user presses the Right Option key to wake you back up. Note: The underlying audio daemon will self-destruct after 15 minutes of idle time to free Unified Memory, so you must warn the user of this limit before calling.
    """
    try:
        ensure_daemon_running()
        if ctx:
            await ctx.info("🎙️ Waiting for user to speak... 🎙️")
            
        status, response_data = await make_cancellable_converse_request(
            {"session_id": SESSION_ID, "text_to_speak": "", "expect_reply": True, "standby_mode": True},
            3600.0
        )
        return response_data
        
    except Exception as e:
        # The daemon likely died from the 15-minute watchdog to save RAM.
        # Implement the "Ghost Wake-Up": silently listen for Right Option, then boot the daemon.
        if ctx:
            await ctx.info("💤 Audio Engine sleeping to save RAM. Press Right Option to wake... 💤")
        
        import pynput
        loop = asyncio.get_running_loop()
        wake_event = asyncio.Event()

        def on_press(key):
            if key in (pynput.keyboard.Key.alt_r, pynput.keyboard.Key.ctrl_r):
                loop.call_soon_threadsafe(wake_event.set)
                
        listener = pynput.keyboard.Listener(on_press=on_press)
        listener.start()
        
        await wake_event.wait()
        listener.stop()
        
        if ctx:
            await ctx.info("🚀 Waking up Audio Engine... This might take a few seconds... 🚀")
            
        try:
            ensure_daemon_running()
            status, response_data = await make_cancellable_converse_request(
                {"session_id": SESSION_ID, "text_to_speak": "", "expect_reply": True, "standby_mode": True},
                3600.0
            )
            return response_data
        except Exception as retry_e:
            return {
                "status": "error", 
                "user_transcript": "", 
                "message": f"CRITICAL Error waking up audio daemon: {str(retry_e)}"
            }

import signal

def cleanup_on_exit(signum, frame):
    logger.warning(f"Received termination signal {signum}. Firing abort request to daemon...")
    try:
        # Use a short timeout to prevent hanging the shutdown process
        make_uds_request("POST", "/abort", None, 1.0)
        logger.info("Abort request sent successfully during shutdown.")
    except Exception as e:
        logger.error(f"Failed to send abort request during shutdown: {e}")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup_on_exit)
signal.signal(signal.SIGTERM, cleanup_on_exit)

if __name__ == "__main__":
    # 4. Restore the OS-level stdout just before handing control to the MCP SDK
    os.dup2(original_stdout_fd, 1)
    os.close(original_stdout_fd)
    sys.stdout = sys.__stdout__
    
    # 5. Now the JSON-RPC protocol has an absolutely pristine stdout pipe
    mcp.run()
