import subprocess
import json
import time
import signal
import os
import sys

# Ensure daemon is running first
print("Ensuring Audio Daemon is running...")
subprocess.run(["python3", "-c", "import sys; sys.path.append('src'); import mcp_server; mcp_server.ensure_daemon_running()"])
time.sleep(2) # Give it a moment to settle

print("\n--- Starting Mock MCP Client Test ---")

# 1. Launch the MCP Server as a subprocess, piping stdin/stdout
mcp_process = subprocess.Popen(
    ["python3", "src/mcp_server.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)

# 2. Construct a valid JSON-RPC request to call the voice_converse tool
request_id = "test_cancel_123"
tool_call = {
    "jsonrpc": "2.0",
    "id": request_id,
    "method": "tools/call",
    "params": {
        "name": "voice_converse",
        "arguments": {
            "text_to_speak": "I am a test script. Please cancel me.",
            "expect_reply": True
        }
    }
}

# 3. Send the request down the stdin pipe
print("Sending voice_converse tool call to MCP Server...")
mcp_process.stdin.write(json.dumps(tool_call) + "\n")
mcp_process.stdin.flush()

# 4. Wait 3 seconds. The Audio Daemon should now have the microphone open.
print("Waiting 3 seconds for Audio Daemon to open microphone...")
time.sleep(3)

# 5. Send a SIGTERM to the MCP Server, exactly like a CLI timeout would.
print("Sending SIGTERM to MCP Server (Simulating forced cancellation)...")
mcp_process.send_signal(signal.SIGTERM)

# Wait for the process to die
mcp_process.wait(timeout=5)
print(f"MCP Server exited with code: {mcp_process.returncode}")

# 6. Verify the Audio Daemon received the abort!
print("\n--- Verifying Audio Daemon Telemetry ---")
time.sleep(1) # Give daemon a moment to write logs
log_path = os.path.expanduser("~/Library/Application Support/VoiceMCP/logs/telemetry.log")

try:
    with open(log_path, "r") as f:
        # Read the last 20 lines
        lines = f.readlines()[-20:]
        
        abort_received = False
        mic_stopped = False
        
        for line in lines:
            if "Received /abort command" in line:
                abort_received = True
            if "LiveMicrophone stream stopped" in line:
                mic_stopped = True
                
        if abort_received and mic_stopped:
            print("✅ AUTOMATED TEST PASSED: The dying MCP Server successfully fired the /abort flare, and the Audio Daemon dropped the microphone!")
        else:
            print("❌ AUTOMATED TEST FAILED: The Audio Daemon did not log a successful abort sequence.")
            print("Last 5 log lines for debugging:")
            for line in lines[-5:]:
                print(line.strip())
except Exception as e:
    print(f"Failed to read telemetry log: {e}")
