from pathlib import Path

from PIL import Image

from hypogum.utils.image_dedup import dhash, hamming_distance

ASSETS = Path(__file__).parent / "assets"
PROD_HASH_SIZE = 16
PROD_THRESHOLD = 10


def _gradient(width=64, height=64, reverse=False):
    img = Image.new("L", (width, height))
    data = []
    for _ in range(height):
        for x in range(width):
            v = int(255 * x / (width - 1))
            data.append(255 - v if reverse else v)
    img.putdata(data)
    return img


def test_identical_image_distance_zero():
    img = _gradient()
    assert hamming_distance(dhash(img), dhash(img.copy())) == 0


def test_hamming_self_is_zero():
    h = dhash(_gradient())
    assert hamming_distance(h, h) == 0


def test_different_patterns_large_distance():
    lr = dhash(_gradient(reverse=False))
    rl = dhash(_gradient(reverse=True))
    assert hamming_distance(lr, rl) > 5


def test_minor_change_small_distance():
    base = _gradient()
    tweaked = base.copy()
    tweaked.putpixel((0, 0), 0)
    assert hamming_distance(dhash(base), dhash(tweaked)) <= 5


def test_hash_is_int_and_bounded():
    h = dhash(_gradient(), hash_size=8)
    assert isinstance(h, int)
    assert 0 <= h < (1 << 64)


def _load_pair(subdir):
    files = sorted((ASSETS / subdir).glob("*.png"))
    return files, [Image.open(f).convert("RGB") for f in files]


def _pair_distance(subdir):
    _, imgs = _load_pair(subdir)
    a, b = (dhash(im, PROD_HASH_SIZE) for im in imgs)
    return hamming_distance(a, b)


def test_assets_present():
    diff_files, _ = _load_pair("different")
    same_files, _ = _load_pair("same")
    assert len(diff_files) == 2, f"expected 2 'different' screenshots, found {diff_files}"
    assert len(same_files) == 2, f"expected 2 'same' screenshots, found {same_files}"


def test_different_screenshots_not_duplicate():
    distance = _pair_distance("different")
    assert distance > PROD_THRESHOLD, (
        f"different screenshots flagged as duplicate: distance={distance} "
        f"<= threshold={PROD_THRESHOLD}"
    )


def test_same_screenshots_are_duplicate():
    distance = _pair_distance("same")
    assert distance <= PROD_THRESHOLD, (
        f"same screenshots not flagged as duplicate: distance={distance} "
        f"> threshold={PROD_THRESHOLD}"
    )


def test_same_screenshot_is_duplicate():
    _, imgs = _load_pair("different")
    h = dhash(imgs[0], PROD_HASH_SIZE)
    assert hamming_distance(h, h) == 0
