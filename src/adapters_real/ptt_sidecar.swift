import Foundation
import IOKit.hid
import AudioToolbox
import AppKit

var isPTTActive = false
var isCtrlPressed = false
var pingID: SystemSoundID = 0
var popID: SystemSoundID = 0

var idleTimer: Timer?
let IDLE_TIMEOUT: TimeInterval = 900 // 15 minutes

func resetIdleTimer() {
    idleTimer?.invalidate()
    idleTimer = Timer.scheduledTimer(withTimeInterval: IDLE_TIMEOUT, repeats: false) { _ in
        print("💤 [SWIFT] Sidecar idle for \(Int(IDLE_TIMEOUT / 60)) minutes. Exiting to save resources.")
        exit(0)
    }
}

// Load uncompressed audio for 0ms latency
let pingURL = URL(fileURLWithPath: "/System/Library/Sounds/Morse.aiff") as CFURL
let popURL = URL(fileURLWithPath: "/System/Library/Sounds/Pop.aiff") as CFURL
AudioServicesCreateSystemSoundID(pingURL, &pingID)
AudioServicesCreateSystemSoundID(popURL, &popID)

func sendSocketMessage(code: UInt8) -> Bool {
    let fd = socket(AF_UNIX, SOCK_STREAM, 0)
    guard fd >= 0 else { return false }
    defer { close(fd) }

    var addr = sockaddr_un()
    addr.sun_family = sa_family_t(AF_UNIX)
    
    let path = "/tmp/voice_mcp_ptt.sock"
    let pathSize = Int(MemoryLayout.size(ofValue: addr.sun_path))
    _ = withUnsafeMutablePointer(to: &addr.sun_path.0) { ptr in
        path.withCString { cstr in
            strncpy(ptr, cstr, pathSize)
        }
    }

    let len = socklen_t(MemoryLayout<sockaddr_un>.size)
    let connectResult = withUnsafePointer(to: &addr) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, len) }
    }
    
    if connectResult == 0 {
        var byte: UInt8 = code
        write(fd, &byte, 1)
        return true
    }
    return false
}

func isTerminalFrontmost() -> Bool {
    guard let frontApp = NSWorkspace.shared.frontmostApplication else { return false }
    let bundleID = frontApp.bundleIdentifier ?? ""
    // Add common terminal emulators and editors
    let allowedTerminals = [
        "com.apple.Terminal",
        "com.googlecode.iterm2",
        "dev.warp.Warp-Stable",
        "co.zeit.hyper",
        "com.mitchellh.ghostty",
        "net.kovidgoyal.kitty",
        "org.alacritty",
        "com.anthropic.claudedesktop",
        "com.microsoft.VSCode",
        "com.todesktop.Cursor"
    ]
    return allowedTerminals.contains(bundleID)
}

var lastPressTime: TimeInterval = 0
var lastReleaseTime: TimeInterval = 0
let DOUBLE_TAP_THRESHOLD: TimeInterval = 0.4 // 400 milliseconds

let hidCallback: IOHIDValueCallback = { context, result, sender, value in
    let element = IOHIDValueGetElement(value)
    let usagePage = IOHIDElementGetUsagePage(element)
    let usage = IOHIDElementGetUsage(element)
    let intValue = IOHIDValueGetIntegerValue(value)

    // 0x07 = Generic Desktop Keyboard
    if usagePage == 0x07 {
        let isPressed = (intValue == 1)
        
        // 0xE6 = Right Option
        if usage == 0xE6 {
            // Only process events if our terminal is the active window!
            if isTerminalFrontmost() {
                let now = Date().timeIntervalSince1970
                
                if isPressed && !isPTTActive {
                    resetIdleTimer()
                    
                    // Check for Double-Tap!
                    // If the time since the LAST release is very short, and the time
                    // since the LAST press is also very short, this is the second press of a double-tap.
                    if (now - lastReleaseTime) < DOUBLE_TAP_THRESHOLD && (now - lastPressTime) < DOUBLE_TAP_THRESHOLD {
                        // Abort signal!
                        if sendSocketMessage(code: 2) {
                            print("🚨 [SWIFT] -> DOUBLE TAP DETECTED! Transmitted 0x02 (Abort)")
                            AudioServicesPlaySystemSound(popID) // Play pop to confirm abort
                        }
                        // Reset timestamps so we don't accidentally triple-tap
                        lastPressTime = 0
                        lastReleaseTime = 0
                        return
                    }
                    
                    // Normal Single Press
                    lastPressTime = now
                    if sendSocketMessage(code: 1) {
                        isPTTActive = true
                        AudioServicesPlaySystemSound(pingID)
                        print("[SWIFT] -> Transmitted 0x01 (Press)")
                    }
                    
                } else if !isPressed && isPTTActive {
                    lastReleaseTime = now
                    isPTTActive = false
                    
                    // Normal Release
                    _ = sendSocketMessage(code: 0)
                    AudioServicesPlaySystemSound(popID)
                    print("[SWIFT] -> Transmitted 0x00 (Release)")
                }
            }
        }
    }
}

let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
let deviceMatch: [String: Any] = ["DeviceUsagePage": 1, "DeviceUsage": 6]
IOHIDManagerSetDeviceMatching(manager, deviceMatch as CFDictionary)
IOHIDManagerRegisterInputValueCallback(manager, hidCallback, nil)
IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.defaultMode.rawValue)

let openResult = IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
if openResult != kIOReturnSuccess {
    print("❌ FATAL: macOS blocked hardware access.")
    print("👉 ACTION REQUIRED: Open System Settings -> Privacy & Security -> Input Monitoring.")
    print("👉 Add your Terminal application, toggle it ON, completely restart the terminal, and try again.")
    exit(1)
}

print("✅ [SWIFT] Sidecar Online with Context-Aware Focus Filter.")
print("🎧 [SWIFT] Listening natively for Right Option (Hardware Matrix 0xE6)...")
print("🔒 [SWIFT] Mic will ONLY open if a Terminal window is currently active.")

resetIdleTimer() // Start the idle timer initially

CFRunLoopRun()
