import difflib
import io
from typing import List, Dict, Any, Tuple, Optional
from PIL import Image, ImageChops, ImageEnhance


def generate_text_diff(old_text: str, new_text: str) -> List[Dict[str, Any]]:
    """
    Produces structured line-by-line diff items for accessible UI rendering.
    Each item: {"type": "add"|"del"|"context"|"header", "text": str, "old_lineno": int, "new_lineno": int}
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    diff_items = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for idx, line in enumerate(old_lines[i1:i2]):
                diff_items.append({
                    "type": "context",
                    "text": line,
                    "old_lineno": i1 + idx + 1,
                    "new_lineno": j1 + idx + 1,
                })
        elif tag == "replace":
            for idx, line in enumerate(old_lines[i1:i2]):
                diff_items.append({
                    "type": "del",
                    "text": line,
                    "old_lineno": i1 + idx + 1,
                    "new_lineno": None,
                })
            for idx, line in enumerate(new_lines[j1:j2]):
                diff_items.append({
                    "type": "add",
                    "text": line,
                    "old_lineno": None,
                    "new_lineno": j1 + idx + 1,
                })
        elif tag == "delete":
            for idx, line in enumerate(old_lines[i1:i2]):
                diff_items.append({
                    "type": "del",
                    "text": line,
                    "old_lineno": i1 + idx + 1,
                    "new_lineno": None,
                })
        elif tag == "insert":
            for idx, line in enumerate(new_lines[j1:j2]):
                diff_items.append({
                    "type": "add",
                    "text": line,
                    "old_lineno": None,
                    "new_lineno": j1 + idx + 1,
                })

    return diff_items


def generate_diff_summary(diff_items: List[Dict[str, Any]]) -> str:
    """Generate a concise summary of changes (e.g. '+3 lines, -1 lines')."""
    adds = sum(1 for item in diff_items if item["type"] == "add")
    dels = sum(1 for item in diff_items if item["type"] == "del")

    if adds == 0 and dels == 0:
        return "No text changes detected."
    return f"{adds} addition{'s' if adds != 1 else ''}, {dels} deletion{'s' if dels != 1 else ''}"


def generate_visual_diff(img1_bytes: bytes, img2_bytes: bytes) -> Tuple[bytes, float]:
    """
    Compares two PNG screenshot byte arrays using Pillow.
    Returns: (diff_image_png_bytes, percentage_different)
    """
    img1 = Image.open(io.BytesIO(img1_bytes)).convert("RGB")
    img2 = Image.open(io.BytesIO(img2_bytes)).convert("RGB")

    # Align canvas sizes
    max_w = max(img1.width, img2.width)
    max_h = max(img1.height, img2.height)

    canvas1 = Image.new("RGB", (max_w, max_h), (255, 255, 255))
    canvas2 = Image.new("RGB", (max_w, max_h), (255, 255, 255))

    canvas1.paste(img1, (0, 0))
    canvas2.paste(img2, (0, 0))

    # Compute absolute difference
    diff = ImageChops.difference(canvas1, canvas2)
    gray_diff = diff.convert("L")

    # Threshold difference to find changed pixels
    threshold = 25
    mask = gray_diff.point(lambda p: 255 if p > threshold else 0)

    # Calculate change percentage
    bbox = mask.getbbox()
    total_pixels = max_w * max_h
    if bbox:
        # Count non-zero pixels
        getter = getattr(mask, "get_flattened_data", mask.getdata)
        diff_count = sum(1 for pixel in getter() if pixel > 0)
        change_pct = round((diff_count / total_pixels) * 100, 2)
    else:
        change_pct = 0.0

    # Create highlighted visual overlay (new screenshot dimmed + bright red overlay on changed regions)
    enhancer = ImageEnhance.Brightness(canvas2)
    dimmed_canvas = enhancer.enhance(0.7)

    # Magenta/Red overlay highlight for changed regions
    highlight_layer = Image.new("RGB", (max_w, max_h), (239, 68, 68))  # Tailwind red-500

    # Composite: where mask is white, blend red overlay; else keep dimmed_canvas
    result = Image.composite(highlight_layer, dimmed_canvas, mask)

    out = io.BytesIO()
    result.save(out, format="PNG")
    return out.getvalue(), change_pct
