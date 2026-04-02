import queue
from simulation.ports import ILLMBridge

class QueueLLMBridge(ILLMBridge):
    def __init__(self, command_queue: queue.Queue, result_queue: queue.Queue):
        self.cmd_q = command_queue
        self.res_q = result_queue
        self.is_requesting = False
        
    def call_mcp_tool(self, context: dict) -> dict:
        self.start_request(context)
        while True:
            resp = self.get_response()
            if resp is not None:
                return resp
            import time
            time.sleep(0.01)

    def start_request(self, context: dict):
        self.is_requesting = True
        # Send the transcript to the MCP server
        self.res_q.put(context)

    def tick(self, ms: int):
        pass

    def get_response(self) -> dict | None:
        if self.is_requesting:
            try:
                # Non-blocking check for next command from MCP server
                cmd = self.cmd_q.get_nowait()
                self.is_requesting = False
                return cmd
            except queue.Empty:
                return None
        return None
