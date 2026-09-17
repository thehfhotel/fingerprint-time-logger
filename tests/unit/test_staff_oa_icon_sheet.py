"""The approved 3x2 icon sheet is cropped, never regenerated."""
from pathlib import Path

from PIL import Image

from scripts.split_staff_oa_icon_sheet import split_icon_sheet


def test_splitter_preserves_each_cell_pixels_exactly(tmp_path: Path):
    source = tmp_path / "sheet.png"
    out = tmp_path / "icons"
    width, height = 300, 200
    cell_w, cell_h = width // 3, height // 2
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = image.load()

    # Six deliberately unique RGBA cells. Exact pixel comparison catches any
    # resize, filtering, recolouring, interpolation or accidental reordering.
    colours = [
        (11, 21, 31, 255), (41, 51, 61, 240), (71, 81, 91, 220),
        (101, 111, 121, 200), (131, 141, 151, 180), (161, 171, 181, 160),
    ]
    for index, colour in enumerate(colours):
        row, column = divmod(index, 3)
        for y in range(row * cell_h, (row + 1) * cell_h):
            for x in range(column * cell_w, (column + 1) * cell_w):
                pixels[x, y] = colour
    image.save(source)

    paths = split_icon_sheet(source, out)
    assert [path.name for path in paths] == [f"icon-{i:02d}.png" for i in range(1, 7)]
    for path, colour in zip(paths, colours):
        with Image.open(path) as crop:
            assert crop.size == (cell_w, cell_h)
            assert crop.mode == "RGBA"
            assert set(crop.getdata()) == {colour}


def test_splitter_rejects_non_divisible_sheet(tmp_path: Path):
    source = tmp_path / "bad.png"
    Image.new("RGBA", (301, 200)).save(source)
    try:
        split_icon_sheet(source, tmp_path / "out")
    except ValueError as exc:
        assert "3x2" in str(exc)
    else:
        raise AssertionError("non-divisible sheet must fail instead of trimming pixels")
