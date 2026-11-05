"""Template matching via 2D FFT normalized cross-correlation."""

import io
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image

Point = tuple[int, int]


def load_rgb(png: bytes) -> np.ndarray:
    """Load PNG bytes as an RGB float32 array."""
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float32)


@cache
def load_template(path: Path) -> np.ndarray:
    """Load and cache an image template as float32 RGB."""
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)


def find_icons(
    image: np.ndarray,
    template_path: Path,
    threshold: float,
    step: int = 1,
) -> list[tuple[int, int]]:
    """Centres of every match of the template scoring at least `threshold`, best first.
    `step` > 1 matches on every step-th pixel of both: faster, lower scores."""
    template = load_template(template_path)[::step, ::step]
    scores = match_many(image[::step, ::step], [template])[0]
    size = template.shape[0]
    found: list[tuple[int, int]] = []
    while True:
        y, x = np.unravel_index(scores.argmax(), scores.shape)
        if scores[y, x] < threshold:
            return found
        found.append(((int(x) + size // 2) * step, (int(y) + size // 2) * step))
        scores[max(0, y - size):y + size, max(0, x - size):x + size] = -1


def match_many(image: np.ndarray, templates: list[np.ndarray]) -> list[np.ndarray]:
    """Normalized cross-correlation of several same-sized templates, sharing image spectra."""
    if not templates:
        return []
    height, width = image.shape[:2]
    h, w = templates[0].shape[:2]
    if any(t.shape[:2] != (h, w) for t in templates):
        # The shared window statistics assume one size; mixed sizes give garbage scores.
        raise ValueError(f"match_many needs same-sized templates, got {sorted({t.shape[:2] for t in templates})}")
    n = h * w * 3
    shape = (_fast_length(height), _fast_length(width))

    def window_sums(values: np.ndarray) -> np.ndarray:
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
    key = (template.tobytes(), template.shape, shape)
    if key not in _spectra:
        normalised = (template - template.mean()) / max(float(template.std()), 1e-6)
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
