"""Screenshots for the model, and a cheap 'did the screen change?' check used
while waiting for the user to do a step themselves."""

import base64
import os

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
THUMB = (160, 90)


class Shot:
    """A screenshot as sent to the model, plus how to map its pixels back to the screen."""

    def __init__(self, jpeg, width, height, stage_width, stage_height):
        self.jpeg = jpeg
        self.width = width
        self.height = height
        self.stage_width = stage_width
        self.stage_height = stage_height

    def data_url(self):
        return "data:image/jpeg;base64," + base64.b64encode(self.jpeg).decode("ascii")

    def to_stage(self, x, y):
        x = min(max(x, 0), self.width - 1)
        y = min(max(y, 0), self.height - 1)
        return x * self.stage_width / self.width, y * self.stage_height / self.height

    def from_stage(self, x, y):
        return round(x * self.width / self.stage_width), round(y * self.height / self.stage_height)


def capture(driver, max_width=1920, quality=82):
    path = os.path.join(RUNTIME_DIR, "clicky-shot.png")
    meta = driver.screenshot(path, True)
    pix = GdkPixbuf.Pixbuf.new_from_file(path)
    width, height = pix.get_width(), pix.get_height()
    if width > max_width:
        height = round(height * max_width / width)
        width = max_width
        pix = pix.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    ok, jpeg = pix.save_to_bufferv("jpeg", ["quality"], [str(quality)])
    stage_w, stage_h = meta["stage"]
    return Shot(bytes(jpeg), width, height, stage_w, stage_h)


class Fingerprint:
    """A 160x90 grayscale thumbnail with the overlay's own drawings masked out."""

    def __init__(self, gray, mask):
        self.gray = gray
        self.mask = mask

    def changed_fraction(self, other, tolerance=24):
        changed = counted = 0
        for i, (a, b) in enumerate(zip(self.gray, other.gray)):
            if self.mask[i] or other.mask[i]:
                continue
            counted += 1
            if abs(a - b) > tolerance:
                changed += 1
        return changed / counted if counted else 0.0


def fingerprint(driver):
    path = os.path.join(RUNTIME_DIR, "clicky-watch.png")
    meta = driver.screenshot(path, False)
    stage_w, stage_h = meta["stage"]
    tw, th = THUMB
    pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, tw, th, False)
    data = pix.get_pixels()
    stride, channels = pix.get_rowstride(), pix.get_n_channels()
    gray = bytearray(tw * th)
    for y in range(th):
        row = y * stride
        for x in range(tw):
            p = row + x * channels
            gray[y * tw + x] = (data[p] * 3 + data[p + 1] * 6 + data[p + 2]) // 10
    mask = bytearray(tw * th)
    sx, sy = tw / stage_w, th / stage_h
    for bx, by, bw, bh in meta.get("overlay_boxes", []):
        x0, y0 = max(0, int(bx * sx)), max(0, int(by * sy))
        x1, y1 = min(tw, int((bx + bw) * sx) + 1), min(th, int((by + bh) * sy) + 1)
        for y in range(y0, y1):
            mask[y * tw + x0:y * tw + x1] = b"\x01" * (x1 - x0)
    return Fingerprint(gray, mask)
