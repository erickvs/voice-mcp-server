import asyncio
import socket
import http.client
import json
import os
import sys

SOCKET_PATH = os.path.expanduser("~/Library/Application Support/VoiceMCP/daemon.sock")

class UDSHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout=300.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)

def make_uds_request(method: str, path: str, payload: dict = None, timeout: float = 1.0) -> tuple[int, dict]:
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

async def test_abort_during_synthesis():
    print("\n--- Test 1: Abort during TTS Synthesis ---")
    
    # Task 1: Start a long conversation
    async def run_converse():
        print("[Converse Task] Sending /converse request (Expect a 5-second TTS delay)...")
        payload = {"session_id": "test_1", "text_to_speak": "This is a very long sentence that will take a moment to synthesize.", "expect_reply": True}
        try:
            status, response = await asyncio.to_thread(make_uds_request, "POST", "/converse", payload, 30.0)
            print(f"[Converse Task] Finished with status: {status}, response: {response}")
            return response
        except Exception as e:
            print(f"[Converse Task] Failed: {e}")
            return None

    # Task 2: Fire the abort after 1 second
    async def run_abort():
        await asyncio.sleep(1.0)
        print("[Abort Task] Firing /abort request NOW!")
        status, response = await asyncio.to_thread(make_uds_request, "POST", "/abort", None, 5.0)
        print(f"[Abort Task] /abort returned status: {status}, response: {response}")

    converse_task = asyncio.create_task(run_converse())
    abort_task = asyncio.create_task(run_abort())
    
    response = await converse_task
    await abort_task
    
    if response and "User manually aborted" in response.get("message", ""):
        print("✅ TEST 1 PASSED: Converse loop was successfully interrupted by /abort!")
    else:
        print("❌ TEST 1 FAILED: Converse loop did not return the expected cancellation message.")

async def test_abort_during_standby():
    print("\n--- Test 2: Abort during Standby Mode ---")
    
    async def run_standby():
        print("[Standby Task] Entering infinite standby mode...")
        payload = {"session_id": "test_2", "text_to_speak": "", "expect_reply": True, "standby_mode": True}
        try:
            status, response = await asyncio.to_thread(make_uds_request, "POST", "/converse", payload, 30.0)
            print(f"[Standby Task] Finished with status: {status}, response: {response}")
            return response
        except Exception as e:
            print(f"[Standby Task] Failed: {e}")
            return None

    async def run_abort():
        await asyncio.sleep(1.5)
        print("[Abort Task] Firing /abort request NOW!")
        status, response = await asyncio.to_thread(make_uds_request, "POST", "/abort", None, 5.0)
        print(f"[Abort Task] /abort returned status: {status}, response: {response}")

    standby_task = asyncio.create_task(run_standby())
    abort_task = asyncio.create_task(run_abort())
    
    response = await standby_task
    await abort_task
    
    if response and "User manually aborted" in response.get("message", ""):
        print("✅ TEST 2 PASSED: Standby loop was successfully interrupted by /abort!")
    else:
        print("❌ TEST 2 FAILED: Standby loop did not return the expected cancellation message.")

async def main():
    # Ensure daemon is up before testing
    try:
        make_uds_request("GET", "/health")
    except Exception:
        print("CRITICAL: Audio Daemon is not running or socket is missing.")
        sys.exit(1)
        
    await test_abort_during_synthesis()
    await test_abort_during_standby()
    print("\nAll tests completed.")

if __name__ == "__main__":
    asyncio.run(main())