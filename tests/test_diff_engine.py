import io
import pytest
from PIL import Image
from app.services.diff_engine import generate_text_diff, generate_diff_summary, generate_visual_diff


def test_generate_text_diff():
    old = "Apple\nBanana\nCherry"
    new = "Apple\nBlueberry\nCherry\nDate"

    diff = generate_text_diff(old, new)
    assert len(diff) > 0

    types = [item["type"] for item in diff]
    assert "del" in types  # Banana deleted
    assert "add" in types  # Blueberry & Date added
    assert "context" in types  # Apple & Cherry preserved

    summary = generate_diff_summary(diff)
    assert "2 additions" in summary
    assert "1 deletion" in summary


def test_generate_visual_diff():
    # Create two 100x100 test images
    img1 = Image.new("RGB", (100, 100), (255, 255, 255))
    img2 = Image.new("RGB", (100, 100), (255, 255, 255))

    # Add a black box in img2
    for x in range(20, 40):
        for y in range(20, 40):
            img2.putpixel((x, y), (0, 0, 0))

    b1 = io.BytesIO()
    img1.save(b1, format="PNG")
    b2 = io.BytesIO()
    img2.save(b2, format="PNG")

    diff_bytes, change_pct = generate_visual_diff(b1.getvalue(), b2.getvalue())
    assert len(diff_bytes) > 0
    assert change_pct > 0.0
