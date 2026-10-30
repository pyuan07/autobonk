"""Reads the corner minimap canvas (400x400 PNG, player at the centre, W = minimap-up).

Icons stay upright while the map turns with the camera, so a fixed template finds them.
Red dots are enemies, yellow dots elites.
"""

import io
import math
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image

# The rune altar's crystal (inside the ring, so purple- and cyan-ringed altars both match).
ALTAR_TEMPLATE = Path(__file__).parent / "altar_crystal.png"
# Normalised cross-correlation: clear altars score >= 0.84, ones under the player arrow ~0.56,
# every other icon <= 0.40.
ALTAR_MATCH = 0.5
# The 北 badge on the rim (red glyph; 南/东/西 are white and score ~0.45).
NORTH_TEMPLATE = Path(__file__).parent / "north_marker.png"
NORTH_MATCH = 0.7
RIM = (160, 200)  # the rim markers' distance from the centre, in minimap pixels
CENTRE = 200

Point = tuple[int, int]  # offset from the player, x right and y down, in minimap pixels


def find_altars(png: bytes) -> list[Point]:
    if not png:
        return []
    return [(x - CENTRE, y - CENTRE) for x, y in find_icons(load_rgb(png), ALTAR_TEMPLATE, ALTAR_MATCH)]


def north_bearing(png: bytes) -> float | None:
    """Where 北 sits on the rim, in degrees clockwise from minimap-up (W). A north-up compass
    bearing b then shows on the minimap at bearing `north + b`."""
    if not png:
        return None
    template = _template(NORTH_TEMPLATE)
    scores = _match(load_rgb(png), template)
    half = template.shape[0] // 2
    ys, xs = np.mgrid[: scores.shape[0], : scores.shape[1]]
    distance = np.hypot(xs + half - CENTRE, ys + half - CENTRE)
    scores[(distance < RIM[0]) | (distance > RIM[1])] = -1
    y, x = np.unravel_index(scores.argmax(), scores.shape)
    if scores[y, x] < NORTH_MATCH:
        return None
    return math.degrees(math.atan2(x + half - CENTRE, CENTRE - (y + half)))


def load_rgb(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float32)


def find_icons(image: np.ndarray, template_path: Path, threshold: float, step: int = 1) -> list[tuple[int, int]]:
    """Centres of every match of the template scoring at least `threshold`, best first.
    `step` > 1 matches on every step-th pixel of both: faster, lower scores."""
    template = _template(template_path)[::step, ::step]
    scores = _match(image[::step, ::step], template)
    size = template.shape[0]
    found: list[tuple[int, int]] = []
    while True:
        y, x = np.unravel_index(scores.argmax(), scores.shape)
        if scores[y, x] < threshold:
            return found
        found.append(((int(x) + size // 2) * step, (int(y) + size // 2) * step))
        scores[max(0, y - size):y + size, max(0, x - size):x + size] = -1


@cache
def _template(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)


def _match(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of `template` at every top-left position, via FFT."""
    return match_many(image, [template])[0]


def match_many(image: np.ndarray, templates: list[np.ndarray]) -> list[np.ndarray]:
    """`_match` for several same-sized templates, sharing the image's spectra and window sums."""
    height, width = image.shape[:2]
    h, w = templates[0].shape[:2]
    n = h * w * 3
    shape = (_fast_length(height), _fast_length(width))

    def window_sums(values: np.ndarray) -> np.ndarray:
        # float64: running sums of squares reach ~1e11, beyond float32's precision.
        s = np.pad(values.cumsum(0, dtype=np.float64).cumsum(1), ((1, 0), (1, 0)))
        return s[h:, w:] - s[:-h, w:] - s[h:, :-w] + s[:-h, :-w]

    image_spectra = np.fft.rfft2(image, shape, axes=(0, 1))
    mean = window_sums(image.sum(axis=2)) / n
    mean_square = window_sums((image**2).sum(axis=2)) / n
    std = np.sqrt(np.maximum(mean_square - mean**2, 1e-6))

    results = []
    for template in templates:
        product = (image_spectra * _template_spectrum(template, shape)).sum(axis=2)
        correlation = np.fft.irfft2(product, shape)[: height - h + 1, : width - w + 1]
        results.append(correlation / n / std)
    return results


_spectra: dict[tuple[bytes, tuple[int, ...], tuple[int, int]], np.ndarray] = {}


def _template_spectrum(template: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """Conjugate spectrum of the zero-mean, unit-variance template, cached by content (a slice of a
    cached template is a new array each time, and ids get reused)."""
    key = (template.tobytes(), template.shape, shape)
    if key not in _spectra:
        normalised = (template - template.mean()) / template.std()
        _spectra[key] = np.conj(np.fft.rfft2(normalised, shape, axes=(0, 1)))
    return _spectra[key]


def _fast_length(size: int) -> int:
    """The smallest length >= size with no prime factor above 5 (FFTs of those are fast)."""
    while True:
        rest = size
        for prime in (2, 3, 5):
            while rest % prime == 0:
                rest //= prime
        if rest == 1:
            return size
        size += 1
