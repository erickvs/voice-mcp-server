from logger import logger
import pyaudio
import queue
from simulation.ports import IMicrophone
from simulation.models import VirtualAudioFrame

class LiveMicrophone(IMicrophone):
    def __init__(self, rate=16000, chunk=160):
        self.rate = rate
        self.chunk = chunk
        self.q = queue.Queue(maxsize=100)
        self.p = pyaudio.PyAudio()
        self.stream = None
        logger.info(f"Initialized LiveMicrophone with rate={rate}, chunk={chunk}")

    def start_stream(self):
        if self.stream is not None:
            return
            
        # Clear any stale data from previous sessions
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break
                
        self.stream = self.p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
            stream_callback=self._callback
        )
        self.stream.start_stream()
        logger.info("LiveMicrophone stream started")

    def stop_stream(self):
        stream = self.stream
        self.stream = None
        if stream is not None:
            try:
                stream.stop_stream()
            except OSError as e:
                logger.debug(f"Ignored PyAudio OSError during stop_stream: {e}")
            try:
                stream.close()
            except Exception:
                pass
            logger.info("LiveMicrophone stream stopped")

    def _callback(self, in_data, frame_count, time_info, status):
        try:
            self.q.put_nowait(in_data)
        except queue.Full:
            pass # drop frames if queue is full rather than blocking audio thread
        return (None, pyaudio.paContinue)

    def read_frame(self) -> VirtualAudioFrame:
        if self.stream is None:
             return VirtualAudioFrame(10, False, False, "", b"")
             
        try:
            raw_bytes = self.q.get(timeout=0.1) # Block briefly to act as clock
            # If we didn't get 320 bytes, that's weird but we handle it
            if len(raw_bytes) < self.chunk * 2:
                logger.warning(f"LiveMicrophone read_frame got only {len(raw_bytes)} bytes instead of {self.chunk * 2}")
                return VirtualAudioFrame(10, False, False, "", b"")
            return VirtualAudioFrame(10, False, False, "", raw_bytes)
        except queue.Empty:
            logger.error("LiveMicrophone queue is EMPTY on read! (PyAudio might have crashed or stopped feeding data)")
            # If queue is empty, yield silence frame
            return VirtualAudioFrame(10, False, False, "", b"")

    def close(self):
        self.stop_stream()
        self.p.terminate()

