from pynput import keyboard
from simulation.ports import IVAD
from simulation.models import VirtualAudioFrame

class PushToTalkVAD(IVAD):
    def __init__(self, key_name="shift", **kwargs):
        self.is_pressed = False
        print(f"[DEBUG VAD] Initializing Push-To-Talk VAD. Walkie-Talkie Hotkey: '{key_name}'")
        
        # Map string names to pynput Key objects
        key_map = {
            "shift": keyboard.Key.shift,
            "shift_r": keyboard.Key.shift_r,
            "ctrl": keyboard.Key.ctrl,
            "alt": keyboard.Key.alt,
            "cmd": keyboard.Key.cmd,
            "space": keyboard.Key.space
        }
        
        self.hotkey = key_map.get(key_name.lower(), keyboard.Key.shift)

        def on_press(key):
            if key == self.hotkey:
                self.is_pressed = True

        def on_release(key):
            if key == self.hotkey:
                self.is_pressed = False

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()

    def analyze(self, frame: VirtualAudioFrame) -> float:
        # If the key is held down, we return 1.0 (100% certainty of speech).
        # If the key is released, we return 0.0 (0% certainty of speech).
        return 1.0 if self.is_pressed else 0.0