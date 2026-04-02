import asyncio
import sys
import os
import time
import threading
import queue
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from hydra import compose, initialize
from hydra.utils import instantiate

# Enforce strict model download locations BEFORE loading any ML libraries
app_support_dir = os.path.expanduser("~/Library/Application Support/VoiceMCP/models")
os.makedirs(app_support_dir, exist_ok=True)
os.environ["HF_HOME"] = os.path.join(app_support_dir, "huggingface")
os.environ["TORCH_HOME"] = os.path.join(app_support_dir, "torch")

# Add src to python path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from simulation.models import Config
from simulation.engine import CoreEngine, State
from adapters_real.queue_llm import QueueLLMBridge

# --- Global State ---
mcp_command_queue = queue.Queue()
mcp_result_queue = queue.Queue()
active_session_id = None
mutex_lock = threading.Lock()
last_active_timestamp = time.time()
IDLE_TIMEOUT_SECONDS = 900 # 15 minutes

# Daemon Lifecycle State
daemon_status = "DOWNLOADING" # Starts in downloading state to prevent Claude timeouts
daemon_status_message = "Initializing models..."
daemon_progress = 0

# Engine reference
engine = None
mic = None
speaker = None

def pre_download_models():
    """Forces huggingface_hub to fetch the massive models into our explicit directory before instantiation."""
    global daemon_status_message, daemon_progress
    try:
        from huggingface_hub import snapshot_download, try_to_load_from_cache
        from huggingface_hub.utils import LocalEntryNotFoundError

        # 1. Kokoro TTS (82M)
        try:
            try_to_load_from_cache(repo_id="hexgrad/Kokoro-82M", filename="kokoro-v1_0.pth")
            daemon_status_message = "Loading Kokoro TTS (82M)..."
            daemon_progress = 10
            # Ensure everything is correct
            snapshot_download(repo_id="hexgrad/Kokoro-82M", allow_patterns=["*.pth", "*.json", "voices/*"], local_files_only=True)
        except (LocalEntryNotFoundError, Exception):
            daemon_status_message = "Downloading Kokoro TTS (82M)..."
            daemon_progress = 5
            snapshot_download(repo_id="hexgrad/Kokoro-82M", allow_patterns=["*.pth", "*.json", "voices/*"])

        # 2. MLX Whisper Large v3 (3GB)
        try:
            try_to_load_from_cache(repo_id="mlx-community/whisper-large-v3-mlx", filename="weights.npz")
            daemon_status_message = "Loading MLX Whisper Large v3 (3GB)..."
            daemon_progress = 50
            snapshot_download(repo_id="mlx-community/whisper-large-v3-mlx", local_files_only=True)
        except (LocalEntryNotFoundError, Exception):
            daemon_status_message = "Downloading MLX Whisper Large v3 (3GB)..."
            daemon_progress = 30
            snapshot_download(repo_id="mlx-community/whisper-large-v3-mlx")

        daemon_status_message = "Finalizing AI setup..."
        daemon_progress = 90
    except Exception as e:
        print(f"Model download error: {e}", file=sys.stderr)
        daemon_status_message = f"Error downloading models: {e}"

def run_audio_daemon():
    """Runs the CoreEngine in a persistent background thread."""
    global engine, mic, speaker, last_active_timestamp, daemon_status, daemon_status_message, daemon_progress
    
    # Pre-download models so the daemon status reflects exactly what is happening
    pre_download_models()
    daemon_status_message = "Instantiating hardware..."
    daemon_progress = 95
    
    # Load configuration using Hydra
    config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'config'))
    
    with initialize(version_base=None, config_path="../../config"):
        cfg = compose(config_name="config")
        print("Loaded Hydra configuration successfully.")

    mic = instantiate(cfg.microphone)
    speaker = instantiate(cfg.speaker)
    vad = instantiate(cfg.vad)
    stt = instantiate(cfg.stt)
    llm = QueueLLMBridge(mcp_command_queue, mcp_result_queue)
    
    config = Config(
        vad_probability_threshold=cfg.vad.get("vad_probability_threshold", 0.80),
        vad_bargein_threshold_ms=cfg.vad.get("vad_bargein_threshold_ms", 500),
        endpointing_patience_normal_ms=cfg.vad.get("endpointing_patience_normal_ms", 1500),
        endpointing_patience_interrupted_ms=cfg.vad.get("endpointing_patience_interrupted_ms", 700),
        vad_silence_grace_ms=cfg.config.get("vad_silence_grace_ms", 100)
    )
    
    engine = CoreEngine(config, mic, speaker, vad, stt, llm)
    engine.state = State.EXECUTING  # Start dormant
    
    daemon_status = "READY"
    daemon_status_message = "Audio Engine is online."
    daemon_progress = 100
    print("Audio Daemon Started. Waiting for commands.", file=sys.stderr)
    
    try:
        while True:
            # If dormant, check for commands from FastAPI
            if engine.state == State.EXECUTING:
                try:
                    cmd = mcp_command_queue.get(timeout=0.1) # Blocks briefly
                    
                    # We got a command, wake up the hardware!
                    mic.start_stream()
                    engine.start_conversation(cmd.get("text", ""))
                    engine.expect_reply = cmd.get("expect_reply", True)
                    
                except queue.Empty:
                    pass
            else:
                engine.tick()
                # Once we drop back to EXECUTING, we finished the conversation loop
                if engine.state == State.EXECUTING:
                    mic.stop_stream()
                    last_active_timestamp = time.time()
                    
    except Exception as e:
        print(f"Daemon exception: {e}", file=sys.stderr)
    finally:
        if mic:
            mic.close()

async def watchdog():
    """Monitors idle time and self-destructs if inactive."""
    global last_active_timestamp
    while True:
        await asyncio.sleep(60)
        idle_time = time.time() - last_active_timestamp
        if idle_time > IDLE_TIMEOUT_SECONDS:
            print(f"Idle timeout reached ({idle_time:.0f}s). Self-destructing to free RAM.", file=sys.stderr)
            if mic:
                mic.close()
            os._exit(0)

def parent_pid_polling():
    """Polls the parent PID. If the parent dies, the daemon instantly self-destructs."""
    while True:
        time.sleep(3.0)
        if os.getppid() == 1:
            print("Parent process died. Stopping daemon to prevent Zombie microphone lock.", file=sys.stderr)
            os._exit(0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Boot the daemon thread on startup
    daemon_thread = threading.Thread(target=run_audio_daemon, daemon=True)
    daemon_thread.start()
    
    # Start the watchdog
    asyncio.create_task(watchdog())
    
    # Start the Parent PID Poller
    polling_thread = threading.Thread(target=parent_pid_polling, daemon=True)
    polling_thread.start()
    
    yield
    # Shutdown logic
    if mic:
        mic.close()

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health_check():
    # If the app is up, we are technically "healthy" enough for the MCP client to connect,
    # even if we are downloading. The actual block happens in /converse.
    return {
        "status": "ok", 
        "daemon_status": daemon_status,
        "message": daemon_status_message,
        "progress": daemon_progress
    }

@app.get("/status")
async def status_sse(request: Request):
    """Server-Sent Events endpoint to broadcast download/status progress to the UI."""
    async def event_generator():
        last_msg = ""
        while True:
            if await request.is_disconnected():
                break
            
            # Only yield if the message changed to save bandwidth, unless we just connected
            if daemon_status_message != last_msg:
                last_msg = daemon_status_message
                yield {
                    "event": "status_update",
                    "data": f'{{"status": "{daemon_status}", "message": "{daemon_status_message}"}}'
                }
            await asyncio.sleep(0.5)
            
    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(event_generator())

@app.post("/reload")
async def reload_config():
    global engine, mic, speaker, vad, stt, daemon_status, daemon_status_message
    
    if daemon_status == "DOWNLOADING":
        return {"status": "error", "message": "Cannot reload while downloading models."}
        
    daemon_status = "RELOADING"
    daemon_status_message = "Hot-swapping audio models..."
    
    with mutex_lock:
        # 1. Stop the current engine
        if engine:
            engine.state = State.EXECUTING
        if mic: 
            mic.close()
            
        # 1b. CRITICAL: Explicitly obliterate old models from VRAM to prevent Out-Of-Memory (OOM) crashes on hot-swaps
        import gc
        try:
            del speaker
            del vad
            del stt
            del engine
        except NameError:
            pass
            
        gc.collect()
        
        try:
            import mlx.core as mx
            mx.metal.clear_cache()
        except ImportError:
            pass
            
        try:
            import torch
            if torch.backends.mps.is_available():
                torch.mps.empty_cache()
        except ImportError:
            pass
        
        try:
            # 2. Re-read the YAML file using Hydra
            with initialize(version_base=None, config_path="../../config"):
                cfg = compose(config_name="config")
                
            # 3. Instantiate the new models on the fly
            mic = instantiate(cfg.microphone)
            speaker = instantiate(cfg.speaker)
            vad = instantiate(cfg.vad)
            stt = instantiate(cfg.stt)
            llm = QueueLLMBridge(mcp_command_queue, mcp_result_queue)
            
            config = Config(
                vad_probability_threshold=cfg.vad.get("vad_probability_threshold", 0.80),
                vad_bargein_threshold_ms=cfg.vad.get("vad_bargein_threshold_ms", 500),
                endpointing_patience_normal_ms=cfg.vad.get("endpointing_patience_normal_ms", 1500),
                endpointing_patience_interrupted_ms=cfg.vad.get("endpointing_patience_interrupted_ms", 700),
                vad_silence_grace_ms=cfg.config.get("vad_silence_grace_ms", 100)
            )
            
            engine = CoreEngine(config, mic, speaker, vad, stt, llm)
            engine.state = State.EXECUTING
            
            daemon_status = "READY"
            daemon_status_message = "Audio Engine reloaded successfully."
            return {"status": "ok", "message": "Audio engine hot-swapped successfully."}
            
        except Exception as e:
            daemon_status = "ERROR"
            daemon_status_message = f"Failed to reload: {str(e)}"
            return {"status": "error", "message": daemon_status_message}

@app.post("/converse")
async def converse(request: Request):
    global active_session_id, last_active_timestamp
    
    # Fast-Fail Graceful State to prevent Claude Timeout during the 3GB initial download
    if daemon_status == "DOWNLOADING":
        return {
            "status": "system_busy", 
            "message": f"SYSTEM NOTIFICATION: Speak MCP is currently initializing. {daemon_status_message} Please instruct the user to wait a moment and try again."
        }
        
    body = await request.json()
    session_id = body.get("session_id")
    text_to_speak = body.get("text_to_speak", "")
    expect_reply = body.get("expect_reply", True)
    
    with mutex_lock:
        if active_session_id is not None and active_session_id != session_id:
            return {
                "status": "system_busy", 
                "message": "Microphone is in use by another session. Fallback to text."
            }
        # Lock the logical session
        active_session_id = session_id
        last_active_timestamp = time.time()

    try:
        # Feed command to daemon
        mcp_command_queue.put({"text": text_to_speak, "expect_reply": expect_reply})
        
        # Wait for human to interact or natural termination, checking for client disconnects
        while True:
            if await request.is_disconnected():
                print(f"[{session_id}] Client disconnected! Aborting audio loop.", file=sys.stderr)
                # Client hung up (e.g. reload or ctrl+c). We must reset the engine immediately.
                if speaker:
                    speaker.flush()
                if engine:
                    engine.state = State.EXECUTING # This will trigger mic.stop_stream() in the loop
                raise HTTPException(status_code=499, detail="Client Disconnected")
            
            try:
                # Use a short timeout so we can loop and check for is_disconnected()
                result = await asyncio.to_thread(mcp_result_queue.get, timeout=0.1)
                last_active_timestamp = time.time()
                return result
            except queue.Empty:
                await asyncio.sleep(0.01)

    finally:
        # Always release the logical lock when the request ends
        with mutex_lock:
            active_session_id = None

if __name__ == "__main__":
    import uvicorn
    import os
    
    # Isolate socket to user directory to prevent /tmp hijacking and permission issues
    app_support_dir = os.path.expanduser("~/Library/Application Support/VoiceMCP")
    os.makedirs(app_support_dir, exist_ok=True)
    socket_path = os.path.join(app_support_dir, "daemon.sock")
    
    # Cleanup orphaned socket to prevent "Address already in use" deadlock
    if os.path.exists(socket_path):
        try:
            os.unlink(socket_path)
        except OSError:
            pass

    # Important: run with workers=1 to ensure singleton
    uvicorn.run(app, uds=socket_path, workers=1)
