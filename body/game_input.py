"""Game input via Win32 SendInput with hardware scan codes.

SDL-based games like Factorio ignore virtual key codes from pyautogui.
This module sends scan codes directly via SendInput, which SDL picks up.
"""

import ctypes
import ctypes.wintypes
import logging
import time

import win32gui
import win32api
import win32con

logger = logging.getLogger(__name__)

# --- SendInput structures ---

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]


def _send_input(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    ctypes.windll.user32.SendInput(n, arr, ctypes.sizeof(INPUT))


# --- Key name → virtual key code mapping ---

VK_MAP = {
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "space": 0x20, "enter": 0x0D, "return": 0x0D,
    "escape": 0x1B, "esc": 0x1B, "tab": 0x09,
    "shift": 0xA0, "lshift": 0xA0, "rshift": 0xA1,
    "ctrl": 0xA2, "lctrl": 0xA2, "rctrl": 0xA3,
    "alt": 0xA4, "lalt": 0xA4, "ralt": 0xA5,
    "backspace": 0x08, "delete": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73,
    "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def _vk_to_scan(vk: int) -> int:
    """Convert virtual key code to hardware scan code."""
    return ctypes.windll.user32.MapVirtualKeyW(vk, 0)


def _make_key_down(scan: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wScan = scan
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE
    return inp


def _make_key_up(scan: int) -> INPUT:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wScan = scan
    inp.union.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
    return inp


class GameInput:
    """Sends hardware scan codes via SendInput for SDL game compatibility.

    Mouse coordinates from the LLM are relative to the captured image.
    Set ``window_offset`` to the top-left corner of the game window so
    that clicks land in the right place on screen.
    Set ``hwnd`` to the game window handle to auto-focus before input.
    """

    def __init__(self, window_offset: tuple[int, int] = (0, 0), hwnd: int = 0):
        self.window_offset = window_offset
        self.hwnd = hwnd

    def _screen_xy(self, x: int, y: int) -> tuple[int, int]:
        ox, oy = self.window_offset
        return (x + ox, y + oy)

    def _focus_game(self) -> None:
        if self.hwnd and win32gui.IsWindow(self.hwnd):
            try:
                win32gui.SetForegroundWindow(self.hwnd)
                time.sleep(0.05)
            except Exception:
                pass

    def _get_scan(self, key: str) -> int:
        vk = VK_MAP.get(key.lower())
        if vk is None:
            logger.warning("Unknown key: '%s'", key)
            return 0
        return _vk_to_scan(vk)

    def key_press(self, key: str) -> None:
        scan = self._get_scan(key)
        if not scan:
            return
        logger.debug("key_press: %s (scan=0x%02X)", key, scan)
        _send_input(_make_key_down(scan), _make_key_up(scan))

    def key_hold(self, key: str, duration: float) -> None:
        scan = self._get_scan(key)
        if not scan:
            return
        logger.debug("key_hold: %s for %.1fs (scan=0x%02X)", key, duration, scan)
        _send_input(_make_key_down(scan))
        time.sleep(duration)
        _send_input(_make_key_up(scan))

    def mouse_click(self, x: int, y: int, button: str = "left") -> None:
        sx, sy = self._screen_xy(x, y)
        logger.debug("mouse_click: image(%d,%d) -> screen(%d,%d) %s", x, y, sx, sy, button)
        # Move cursor
        ctypes.windll.user32.SetCursorPos(sx, sy)
        time.sleep(0.02)
        # Click
        if button == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        else:
            down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        inp_down = INPUT()
        inp_down.type = INPUT_MOUSE
        inp_down.union.mi.dwFlags = down_flag
        inp_up = INPUT()
        inp_up.type = INPUT_MOUSE
        inp_up.union.mi.dwFlags = up_flag
        _send_input(inp_down, inp_up)

    def mouse_hold(self, x: int, y: int, duration: float, button: str = "right") -> None:
        sx, sy = self._screen_xy(x, y)
        logger.debug("mouse_hold: image(%d,%d) -> screen(%d,%d) %s %.1fs", x, y, sx, sy, button, duration)
        ctypes.windll.user32.SetCursorPos(sx, sy)
        time.sleep(0.02)
        if button == "right":
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
        else:
            down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        inp_down = INPUT()
        inp_down.type = INPUT_MOUSE
        inp_down.union.mi.dwFlags = down_flag
        _send_input(inp_down)
        time.sleep(duration)
        inp_up = INPUT()
        inp_up.type = INPUT_MOUSE
        inp_up.union.mi.dwFlags = up_flag
        _send_input(inp_up)

    def mouse_scroll(self, clicks: int) -> None:
        """Scroll mouse wheel. Positive = up (zoom in), negative = down (zoom out)."""
        logger.debug("mouse_scroll: %d clicks", clicks)
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.mouseData = ctypes.c_ulong(clicks * WHEEL_DELTA).value
        inp.union.mi.dwFlags = MOUSEEVENTF_WHEEL
        _send_input(inp)

    def mouse_move(self, x: int, y: int) -> None:
        sx, sy = self._screen_xy(x, y)
        logger.debug("mouse_move: image(%d,%d) -> screen(%d,%d)", x, y, sx, sy)
        ctypes.windll.user32.SetCursorPos(sx, sy)

    def wait(self, duration: float) -> None:
        logger.debug("wait: %.1fs", duration)
        time.sleep(duration)

    def execute(self, action_type: str, args: list[str]) -> bool:
        """Execute a GameAction. Returns True on success."""
        try:
            if action_type not in ("none", "wait"):
                self._focus_game()
            if action_type == "key_press":
                self.key_press(args[0])
            elif action_type == "key_hold":
                self.key_hold(args[0], float(args[1]))
            elif action_type == "mouse_click":
                x, y = int(args[0]), int(args[1])
                button = args[2] if len(args) > 2 else "left"
                self.mouse_click(x, y, button)
            elif action_type == "mouse_hold":
                x, y = int(args[0]), int(args[1])
                duration = float(args[2]) if len(args) > 2 else 2.0
                button = args[3] if len(args) > 3 else "right"
                self.mouse_hold(x, y, duration, button)
            elif action_type == "mouse_move":
                self.mouse_move(int(args[0]), int(args[1]))
            elif action_type == "zoom_in":
                clicks = int(args[0]) if args else 3
                self.mouse_scroll(clicks)
            elif action_type == "zoom_out":
                clicks = int(args[0]) if args else 3
                self.mouse_scroll(-clicks)
            elif action_type == "wait":
                self.wait(float(args[0]) if args else 1.0)
            elif action_type == "none":
                pass
            else:
                logger.warning("Unknown action type: %s", action_type)
                return False
            return True
        except Exception as e:
            logger.error("Action execution failed: %s", e)
            return False
