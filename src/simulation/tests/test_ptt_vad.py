import pytest
import threading
import time
import socket
import os
from unittest.mock import patch, MagicMock

from adapters_real.ptt_vad import PushToTalkVAD

@pytest.fixture
def mock_ptt_vad():
    # Patch the subprocess calls so we don't actually try to compile/run the Swift binary
    with patch("subprocess.check_output"), \
         patch("subprocess.run"), \
         patch("subprocess.Popen") as mock_popen:
        
        # We need to test the socket logic, so we let the socket be created,
        # but we don't want a real sidecar connecting to it.
        vad = PushToTalkVAD()
        
        # Start the internal server thread (it will block on accept)
        vad._start_server()
        
        yield vad
        
        # Cleanup
        vad._cleanup()

class TestPushToTalkVAD:
    
    def _send_byte(self, byte_val: bytes):
        """Helper to simulate the Swift Sidecar sending a byte."""
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect("/tmp/voice_mcp_ptt.sock")
        client.sendall(byte_val)
        client.close()
        # Give the listener thread a tiny moment to process the byte
        time.sleep(0.05)

    def test_normal_press_and_release(self, mock_ptt_vad):
        """Test that 0x01 activates PTT and 0x00 deactivates it."""
        assert mock_ptt_vad.is_ptt_active is False
        
        # Simulate Press
        self._send_byte(b'\x01')
        assert mock_ptt_vad.is_ptt_active is True
        
        # Simulate Release
        self._send_byte(b'\x00')
        assert mock_ptt_vad.is_ptt_active is False

    @patch("adapters_real.ptt_vad.UDSHTTPConnection")
    def test_double_tap_abort(self, mock_uds_conn_class, mock_ptt_vad):
        """Test that sending 0x02 triggers the HTTP /abort request."""
        mock_conn_instance = MagicMock()
        mock_uds_conn_class.return_value = mock_conn_instance
        mock_response = MagicMock()
        mock_conn_instance.getresponse.return_value = mock_response
        
        assert mock_ptt_vad.is_ptt_active is False
        
        # Simulate Double-Tap (Abort)
        self._send_byte(b'\x02')
        
        # The VAD should NOT become active during an abort
        assert mock_ptt_vad.is_ptt_active is False
        
        # It should have triggered a POST /abort to the daemon
        mock_conn_instance.request.assert_called_once_with(
            "POST", "/abort", body=None, headers={}
        )
        mock_response.read.assert_called_once()

    def test_rapid_state_changes(self, mock_ptt_vad):
        """Test that the lock prevents race conditions during rapid state changes."""
        # Blast the socket with alternating bytes very quickly
        for _ in range(10):
            self._send_byte(b'\x01')
            self._send_byte(b'\x00')
            
        assert mock_ptt_vad.is_ptt_active is False
