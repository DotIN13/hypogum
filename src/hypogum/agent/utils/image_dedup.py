"""Perceptual image fingerprinting for near-duplicate detection (PIL-only)."""

from PIL import Image


def dhash(img: "Image.Image", hash_size: int = 8) -> int:
    """Difference hash: returns a (hash_size*hash_size)-bit integer fingerprint.

    Converts to grayscale, resizes to (hash_size+1, hash_size), and sets one bit
    per adjacent horizontal pixel pair (left brighter than right). Robust to JPEG
    noise, small cursor movement, and minor changes.
    """
    small = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(small.getdata())
    width = hash_size + 1

    bits = 0
    for row in range(hash_size):
        base = row * width
        for col in range(hash_size):
            left = pixels[base + col]
            right = pixels[base + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming_distance(a: int, b: int) -> int:
    """Number of differing bits between two hashes (0 = identical)."""
    return bin(a ^ b).count("1")
