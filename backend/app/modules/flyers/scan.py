"""The flyer scanner: phone photos of paper flyer pages in,
clean squared pages out (owner side note #3, feasibility
checked 2026-11-02 — a proven open-source library folded into
the site's code; that library is OpenCV).

Two pure-bytes steps, so the whole route is testable without
storage or a request:

  detect_corners(data) -> the paper's four corners as
  normalized [x, y] points (top-left, top-right, bottom-right,
  bottom-left), found by the classic document-scanner recipe
  (blur, Canny edges, the largest four-sided contour). When no
  clean quad reads, it answers an inset rectangle with
  detected=False — the user's corner-nudge editor starts from
  either answer, so a bad guess is a starting point, never a
  dead end.

  warp_page(data, corners) -> the page squared by a
  perspective transform into a rectangle sized from the
  quad's own edges, then cleaned: a gray-world white balance
  and a gentle contrast lift on the lightness channel that
  keep the flyer's colors (a sales flyer is color — nothing
  here grayscales it).
"""

import io

import numpy as np

# The guess when detection finds no quad: the paper fills most
# phone frames, so a small inset is the honest starting point
# for the nudge editor.
_FALLBACK_INSET = 0.06

_MIN_SIDE = 600
_MAX_SIDE = 2400


class ScanError(ValueError):
    """The bytes aren't a readable page photo."""


def _decode(data: bytes):
    import cv2

    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    if image is None:
        raise ScanError("That photo couldn't be read as an image.")
    return image


def _order_corners(points: np.ndarray) -> np.ndarray:
    """Order four points TL, TR, BR, BL (the sum/difference
    trick every scanner uses)."""
    pts = points.reshape(4, 2).astype(np.float64)
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(4)
    ordered = np.zeros((4, 2), dtype=np.float64)
    ordered[0] = pts[np.argmin(sums)]  # top-left
    ordered[2] = pts[np.argmax(sums)]  # bottom-right
    ordered[1] = pts[np.argmin(diffs)]  # top-right
    ordered[3] = pts[np.argmax(diffs)]  # bottom-left
    return ordered


def _default_corners() -> list[list[float]]:
    i = _FALLBACK_INSET
    return [[i, i], [1 - i, i], [1 - i, 1 - i], [i, 1 - i]]


def detect_corners(data: bytes) -> tuple[list[list[float]], bool, int, int]:
    """(corners normalized TL/TR/BR/BL, detected?, width, height).

    Detection runs on a downscaled copy (800px tall) for speed;
    normalized coordinates make the scale irrelevant to the
    answer.
    """
    import cv2

    image = _decode(data)
    height, width = image.shape[:2]
    ratio = height / 800.0 if height > 800 else 1.0
    if ratio > 1.0:
        small = cv2.resize(
            image, (int(width / ratio), 800), interpolation=cv2.INTER_AREA
        )
    else:
        small = image
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 50, 200)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
    small_h, small_w = small.shape[:2]
    frame_area = float(small_h * small_w)
    for contour in contours:
        area = cv2.contourArea(contour)
        # The paper is a page-sized thing: anything under 8% of
        # the frame is content ON the page (a product photo, a
        # price box), never the page itself — no matter how
        # clean its four corners are.
        if area < 0.08 * frame_area:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = None
        for epsilon in (0.02, 0.03, 0.04, 0.05):
            candidate = cv2.approxPolyDP(contour, epsilon * perimeter, True)
            if len(candidate) == 4:
                approx = candidate
                break
        if approx is None and area >= 0.25 * frame_area:
            # Soft or slightly rounded corners split into extra
            # points at every epsilon; the minimum-area rectangle
            # of a frame-filling contour is still the paper.
            approx = cv2.boxPoints(cv2.minAreaRect(contour))
        if approx is not None:
            ordered = _order_corners(np.asarray(approx, dtype=np.float64))
            normalized = [
                [float(x / small_w), float(y / small_h)] for x, y in ordered
            ]
            return normalized, True, width, height
    return _default_corners(), False, width, height


def _clean(image):
    """Gray-world white balance + CLAHE on lightness. Color
    stays color; paper whites come back toward white and the
    print gains contrast."""
    import cv2

    balanced = image.astype(np.float32)
    means = balanced.reshape(-1, 3).mean(axis=0)
    gray_mean = means.mean()
    for channel in range(3):
        if means[channel] > 0:
            balanced[:, :, channel] *= gray_mean / means[channel]
    balanced = np.clip(balanced, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(balanced, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    lightness = clahe.apply(lightness)
    merged = cv2.merge((lightness, a, b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)


def warp_page(data: bytes, corners: list[list[float]]) -> bytes:
    """Square one page photo by its four corners (normalized,
    TL/TR/BR/BL) and clean it. Returns JPEG bytes."""
    import cv2

    if len(corners) != 4:
        raise ScanError("A page needs exactly four corners.")
    image = _decode(data)
    height, width = image.shape[:2]
    source = np.array(
        [[float(x) * width, float(y) * height] for x, y in corners],
        dtype=np.float32,
    )

    def _dist(a: int, b: int) -> float:
        return float(np.linalg.norm(source[a] - source[b]))

    target_w = int(max(_dist(0, 1), _dist(3, 2)))
    target_h = int(max(_dist(0, 3), _dist(1, 2)))
    target_w = max(_MIN_SIDE, min(_MAX_SIDE, target_w))
    target_h = max(_MIN_SIDE, min(_MAX_SIDE, target_h))
    dest = np.array(
        [
            [0, 0],
            [target_w - 1, 0],
            [target_w - 1, target_h - 1],
            [0, target_h - 1],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(source, dest)
    warped = cv2.warpPerspective(image, matrix, (target_w, target_h))
    cleaned = _clean(warped)
    ok, encoded = cv2.imencode(".jpg", cleaned, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ScanError("The cleaned page couldn't be encoded.")
    return encoded.tobytes()


