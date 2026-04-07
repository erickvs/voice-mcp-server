from logger import logger
import threading
import subprocess
import socket
import os
import sys
import atexit
import http.client
from simulation.ports import IVAD
from simulation.models import VirtualAudioFrame

SOCKET_PATH = "/tmp/voice_mcp_ptt.sock"

class UDSHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout=300.0):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path
        
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)

class PushToTalkVAD(IVAD):
    def __init__(self, key_name="right_option", **kwargs):
        self.lock = threading.Lock()
        self.is_ptt_active = False
        
        logger.info("Initializing Push-To-Talk VAD via Swift Sidecar.")
        
        self.sidecar_process = None
        self.server_socket = None
        self.listener_thread = None
        self._stop_event = threading.Event()
        
        self._start_sidecar()
        atexit.register(self._cleanup)

    def set_active(self, active: bool):
        if active and self.server_socket is None:
            self._start_server()
        elif not active and self.server_socket is not None:
            self._stop_server()

    def _start_server(self):
        self._stop_event.clear()
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except OSError:
                pass
                
        self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_socket.bind(SOCKET_PATH)
        self.server_socket.listen(1)
        logger.debug(f"PTT socket created at {SOCKET_PATH}")
        
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        
    def _stop_server(self):
        self._stop_event.set()
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None
            
        if self.listener_thread:
            self.listener_thread.join(timeout=1.0)
            self.listener_thread = None
            
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except OSError:
                pass
                
        with self.lock:
            self.is_ptt_active = False

    def _start_sidecar(self):
        try:
            output = subprocess.check_output(["pgrep", "-x", "ptt_sidecar"])
            if len(output.strip()) > 0:
                logger.debug("Swift Sidecar is already running.")
                return
        except subprocess.CalledProcessError:
            pass
            
        sidecar_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ptt_sidecar")
        if not os.path.exists(sidecar_path):
            logger.info(f"Compiling Swift Sidecar at {sidecar_path}...")
            swift_src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ptt_sidecar.swift")
            subprocess.run(["swiftc", swift_src, "-o", sidecar_path])
            
        if os.path.exists(sidecar_path):
            self.sidecar_process = subprocess.Popen(
                [sidecar_path], 
                stdout=sys.stdout, 
                stderr=sys.stderr,
                start_new_session=True
            )
            logger.info("Swift Sidecar started.")
        else:
            logger.error("Failed to start Swift Sidecar, executable not found.")

    def _listen_loop(self):
        while not self._stop_event.is_set():
            try:
                if not self.server_socket:
                    break
                conn, _ = self.server_socket.accept()
                with conn:
                    while not self._stop_event.is_set():
                        data = conn.recv(1)
                        if not data:
                            break
                        
                        with self.lock:
                            if data == b'\x01':
                                logger.info("Mic Alive (Right Option Pressed) - Received 0x01")
                                self.is_ptt_active = True
                            elif data == b'\x00':
                                logger.info("Mic Dead (Right Option Released) - Received 0x00")
                                self.is_ptt_active = False
                            elif data == b'\x02':
                                logger.info("Abort (Esc/Ctrl+C Pressed) - Received 0x02. Triggering /abort")
                                try:
                                    daemon_sock = os.path.expanduser("~/Library/Application Support/VoiceMCP/daemon.sock")
                                    conn_uds = UDSHTTPConnection(daemon_sock, timeout=1.0)
                                    conn_uds.request("POST", "/abort", body=None, headers={})
                                    conn_uds.getresponse().read()
                                    conn_uds.close()
                                except Exception as e:
                                    logger.error(f"Failed to trigger /abort natively: {e}")
            except Exception as e:
                pass

    def analyze(self, frame: VirtualAudioFrame) -> float:
        with self.lock:
            return 1.0 if self.is_ptt_active else 0.0

    def _cleanup(self):
        self._stop_server()
        if self.sidecar_process:
            try:
                self.sidecar_process.terminate()
            except Exception:
                pass

    def __del__(self):
        self._cleanup()