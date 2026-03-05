"""Screen capture targeting the Factorio game window via its window handle."""

import base64
import hashlib
import io
import logging

import threading

import mss
import win32gui
from PIL import Image

logger = logging.getLogger(__name__)


class ScreenCapture:
    """Finds the Factorio window by handle and captures its client area."""

    WINDOW_TITLE_KEYWORD = "Factorio"

    def __init__(self):
        self._local = threading.local()
        self._hwnd: int = 0
        self._rect: tuple[int, int, int, int] | None = None  # left, top, right, bottom

    def _get_sct(self) -> mss.mss:
        """Get or create an mss instance for the current thread."""
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = mss.mss()
            self._local.sct = sct
        return sct

    # --- window discovery ---

    def find_window(self) -> bool:
        """Find the Factorio window. Returns True if found."""
        result = []

        # Exclude titles that are clearly not the game (e.g. terminals showing the project path)
        _EXCLUDE = {"Factorio Agent", "Factorio-Game-Bot"}

        def _enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title.startswith(self.WINDOW_TITLE_KEYWORD) and not any(ex in title for ex in _EXCLUDE):
                    result.append(hwnd)
            return True

        win32gui.EnumWindows(_enum_cb, None)
        if result:
            self._hwnd = result[0]
            self._refresh_rect()
            logger.info("Found Factorio window: hwnd=%s  rect=%s", self._hwnd, self._rect)
            return True
        logger.warning("Factorio window not found")
        return False

    def _refresh_rect(self) -> None:
        """Update cached client-area rect in screen coordinates."""
        if not self._hwnd:
            return
        cr = win32gui.GetClientRect(self._hwnd)           # (0, 0, w, h)
        tl = win32gui.ClientToScreen(self._hwnd, (cr[0], cr[1]))
        br = win32gui.ClientToScreen(self._hwnd, (cr[2], cr[3]))
        self._rect = (tl[0], tl[1], br[0], br[1])

    # --- public properties ---

    @property
    def window_rect(self) -> tuple[int, int, int, int] | None:
        """(left, top, right, bottom) in screen coords, or None."""
        return self._rect

    @property
    def window_size(self) -> tuple[int, int] | None:
        """(width, height) of the game client area, or None."""
        if self._rect is None:
            return None
        l, t, r, b = self._rect
        return (r - l, b - t)

    @property
    def window_offset(self) -> tuple[int, int]:
        """(x, y) offset to convert image coords → screen coords."""
        if self._rect is None:
            return (0, 0)
        return (self._rect[0], self._rect[1])

    # --- capture ---

    def capture(self) -> Image.Image:
        """Capture the Factorio client area and return as PIL Image."""
        self._refresh_rect()
        if self._rect is None:
            raise RuntimeError("No Factorio window found. Call find_window() first.")
        l, t, r, b = self._rect
        region = {"left": l, "top": t, "width": r - l, "height": b - t}
        shot = self._get_sct().grab(region)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def capture_base64(self) -> tuple[str, str, "Image.Image"]:
        """Capture and return (base64_jpeg, sha256_hash_16, pil_image)."""
        img = self.capture()
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        raw = buf.getvalue()
        b64 = base64.b64encode(raw).decode("ascii")
        img_hash = hashlib.sha256(raw).hexdigest()[:16]
        return b64, img_hash, img

    def close(self):
        sct = getattr(self._local, "sct", None)
        if sct is not None:
            sct.close()
            self._local.sct = None


if __name__ == "__main__":
    cap = ScreenCapture()
    if cap.find_window():
        print(f"Window size: {cap.window_size}")
        b64, h, _ = cap.capture_base64()
        print(f"Captured: {len(b64)} chars, hash={h}")
    else:
        print("Factorio window not found.")
    cap.close()
