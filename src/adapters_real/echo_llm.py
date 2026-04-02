from simulation.ports import ILLMBridge

class EchoLLMBridge(ILLMBridge):
    def __init__(self, latency_ms: int = 0):
        self.last_call = None
        self.is_requesting = False
        self.latency_ms = latency_ms
        self.current_wait = 0

    def call_mcp_tool(self, context: dict) -> dict:
        self.start_request(context)
        return self.get_response()

    def start_request(self, context: dict):
        self.last_call = context
        self.is_requesting = True
        self.current_wait = 0

    def tick(self, ms: int):
        if self.is_requesting:
            self.current_wait += ms

    def get_response(self) -> dict | None:
        if self.is_requesting and self.current_wait >= self.latency_ms:
            self.is_requesting = False
            user_speech = self.last_call.get("user_speech", "")
            return {"text": f"I heard you say: {user_speech}", "expect_reply": True}
        return None
