"""Reads the corner minimap canvas (400x400 PNG, player at the centre, W = minimap-up).

Icons stay upright while the map turns with the camera, so a fixed template finds them.
Red dots are enemies, yellow dots elites.
"""

import io
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image

# The rune altar's crystal (inside the ring, so purple- and cyan-ringed altars both match).
ALTAR_TEMPLATE = Path(__file__).parent / "altar_crystal.png"
# Normalised cross-correlation: clear altars score >= 0.84, ones under the player arrow ~0.56,
# every other icon <= 0.40.
ALTAR_MATCH = 0.5
CENTRE = 200

Point = tuple[int, int]  # offset from the player, x right and y down, in minimap pixels


def find_altars(png: bytes) -> list[Point]:
    if not png:
        return []
    image = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float64)
    template = _altar_template()
    scores = _match(image, template)
    size = template.shape[0]
    altars: list[Point] = []
    while True:
        y, x = np.unravel_index(scores.argmax(), scores.shape)
        if scores[y, x] < ALTAR_MATCH:
            return altars
        altars.append((int(x) + size // 2 - CENTRE, int(y) + size // 2 - CENTRE))
        scores[max(0, y - size):y + size, max(0, x - size):x + size] = -1


@cache
def _altar_template() -> np.ndarray:
    return np.asarray(Image.open(ALTAR_TEMPLATE).convert("RGB"), dtype=np.float64)


def _match(image: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of `template` at every top-left position, via FFT."""
    height, width = image.shape[:2]
    h, w = template.shape[:2]
    n = h * w * 3
    normalised = (template - template.mean()) / template.std()

    def spectrum(channel: np.ndarray) -> np.ndarray:
        return np.fft.rfft2(channel, (height, width))

    correlation = sum(
        np.fft.irfft2(spectrum(image[..., c]) * np.conj(spectrum(normalised[..., c])), (height, width))
        for c in range(3)
    )[: height - h + 1, : width - w + 1]

    def window_sums(values: np.ndarray) -> np.ndarray:
        s = np.pad(values.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
        return s[h:, w:] - s[:-h, w:] - s[h:, :-w] + s[:-h, :-w]

    mean = sum(window_sums(image[..., c]) for c in range(3)) / n
    mean_square = sum(window_sums(image[..., c] ** 2) for c in range(3)) / n
    std = np.sqrt(np.maximum(mean_square - mean**2, 1e-6))
    return correlation / n / std
