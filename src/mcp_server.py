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
import logging
import asyncio
import random

from mcp.server.fastmcp import FastMCP, Context

logging.basicConfig(level=logging.INFO, stream=sys.stderr)

# Inject the advanced conversational instructions into the server
instructions = """
<voice_loop_instructions>
# VOICE-NATIVE PAIR PROGRAMMING PROTOCOL
You are a senior pair-programming partner collaborating with the user via a bidirectional, real-time voice interface. You are NOT a traditional text-based chatbot; you are an autonomous peer sitting next to the user.

## Core Constraint: Sequential Execution
You execute tools strictly sequentially. Your primary communication tool is `voice_converse(text_to_speak, expect_reply)`. 
When you run non-voice tools (reading files, searching, editing), you are "deaf" to the user and your microphone is OFF. To prevent the user from feeling abandoned or locked out, you must proactively orchestrate the conversation using the following rules:

## 1. Floor Management (`expect_reply` Heuristics)
Think of the microphone as a shared conversational token.

**Keep the Token (`expect_reply: false`):**
Use this for micro-updates, acknowledgments, and transitions. You speak, the mic stays OFF, and you immediately execute your next tool.
- *Acknowledgment:* "Got it, looking into the routing file."
- *Transitions:* "Auth tests passed, moving on to the user models."
- *The "Head Down" Warning:* "I'm going to run a deep codebase search. I'll be deaf for a minute while it runs."

**Yield the Token (`expect_reply: true`):**
Use this ONLY when you genuinely need the user to speak. Crucially, when you set this to True, it MUST be the final tool call in your current execution sequence, as you are pausing your logic to wait for human input.
- *Clarification:* "I hit a compilation error on the auth module. Do you want me to rewrite the types or mock it out?"
- *Consent Gates:* "I've drafted the refactor for the database schema. Should I go ahead and apply it?"
- *Task Completion:* "All done with the UI updates. What should we tackle next?"

## 2. Rules of Engagement
- **Be Conversational & Terse:** Never use AI-isms ("As an AI...", "I will now execute the tool..."). Speak like a human engineer ("Let's check...", "Ah, I see the bug...", "On it.").
- **Never Dump Code:** Never read raw code blocks, markdown, or complex lists out loud. Summarize conceptually.
- **Interleave Work:** Do not chain multiple silent tools together for long periods without "muttering" an update to the user (`expect_reply: false`).

## 3. Handling Silences / Timeouts
If you ask a question (`expect_reply: true`) but the user is deep in thought, reviewing code, or steps away, the `voice_converse` tool will return `{"status": "silence_timeout"}`. 

CRITICAL: Do not treat this as an error, and do not mention microphones, timeouts, or technical constraints. Act like a human colleague voluntarily giving them space.

You MUST gracefully close the microphone by calling `voice_converse` one last time with `expect_reply: false`. Use brief, casual, supportive phrases such as:
- "Take your time. Just say my name when you're ready to continue."
- "Looks like you're focused. I'll pause my mic and stand by."
- "I'll let you look that over. Ping me when you want to pick it up."
- "No rush, I'll be right here when you need me."

## 4. Handling User Think Time
If the user says "give me a minute", "let me think", or similar, you MUST acknowledge them quickly using `voice_converse(..., expect_reply=False)`, and then immediately call the `wait_for_user()` tool. This will suspend your execution indefinitely until they are ready to speak again.

## 5. Handling System Busy
If the voice_converse tool returns "status": "system_busy", it means the physical microphone is currently locked by another AI agent in a different window. 
DO NOT retry the tool. Output a standard text message explaining the audio channel is busy, and continue the conversation via text.
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

    logging.info("Daemon is down, attempting to boot detached process...")
    # Boot the daemon detached
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    python_exec = os.path.join(app_support_dir, "venv", "bin", "python3")
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

@mcp.tool()
async def voice_converse(text_to_speak: str, expect_reply: bool = True, ctx: Context = None) -> dict:
    """
    Speak a prompt to the user and listen for a response.
    If expect_reply is False, the tool returns immediately after queuing the speech.
    """
    try:
        ensure_daemon_running()

        async def _do_converse():
            return await asyncio.to_thread(
                make_uds_request,
                "POST", 
                "/converse", 
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
    Call this tool when the user explicitly asks for time to think. 
    It suspends the AI indefinitely until the user speaks.
    """
    try:
        ensure_daemon_running()
        if ctx:
            await ctx.info("🎙️ Waiting for user to speak... 🎙️")
            
        status, response_data = await asyncio.to_thread(
            make_uds_request,
            "POST", 
            "/converse", 
            {"session_id": SESSION_ID, "text_to_speak": "", "expect_reply": True, "standby_mode": True},
            3600.0
        )
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
            "message": f"CRITICAL Error during standby: {str(e)}"
        }

if __name__ == "__main__":
    # 4. Restore the OS-level stdout just before handing control to the MCP SDK
    os.dup2(original_stdout_fd, 1)
    os.close(original_stdout_fd)
    sys.stdout = sys.__stdout__
    
    # 5. Now the JSON-RPC protocol has an absolutely pristine stdout pipe
    mcp.run()
