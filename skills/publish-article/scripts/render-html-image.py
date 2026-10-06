#!/usr/bin/env python
"""Render a standalone HTML file to a trimmed PNG via headless Chrome/Edge.

Used to produce card / social images from an article's summary table, and to
screenshot a built page for visual checks. Style the HTML with the site's own
CSS and fonts so the image matches the rest of the site. Build a small
standalone HTML file (table markup + inlined colours + @font-face pointing at
the site's font files), then run this.

Usage:
    python render-html-image.py <input.html> <output.png> [--scale 2] [--width 1030] [--height 1600]

Notes:
- @font-face src must be absolute file:/// URLs to the site's font files, or the
  fonts won't load in headless Chrome (it fetches nothing over the network here).
- The screenshot is taken at --width x --height, then auto-trimmed to the content
  bounding box (background = top-left pixel) and re-padded evenly.
"""
import os
import sys
import shutil
import argparse
import tempfile
import subprocess

try:
    from PIL import Image, ImageChops
except ImportError:
    sys.exit("Pillow not installed. Run: python -m pip install Pillow")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "google-chrome", "chromium", "chromium-browser",
]


def find_browser():
    for c in CHROME_CANDIDATES:
        if os.path.sep in c or ":" in c:
            if os.path.exists(c):
                return c
        elif shutil.which(c):
            return shutil.which(c)
    sys.exit("No Chrome/Edge binary found. Install Chrome or edit CHROME_CANDIDATES.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_html")
    ap.add_argument("output_png")
    ap.add_argument("--scale", type=float, default=2)
    ap.add_argument("--width", type=int, default=1030)
    ap.add_argument("--height", type=int, default=1600)
    ap.add_argument("--pad", type=int, default=48, help="padding in output pixels")
    ap.add_argument("--bg", default="255,255,255", help="pad colour r,g,b (default white)")
    args = ap.parse_args()

    browser = find_browser()
    raw = os.path.join(tempfile.gettempdir(), "publish-article-raw.png")
    file_url = "file:///" + os.path.abspath(args.input_html).replace("\\", "/")
    subprocess.run([
        browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--force-device-scale-factor={args.scale}",
        f"--window-size={args.width},{args.height}",
        f"--screenshot={raw}", file_url,
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    im = Image.open(raw).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((0, 0)))
    bbox = ImageChops.difference(im, bg).getbbox()
    if bbox:
        im = im.crop(bbox)
    pad = args.pad
    pad_rgb = tuple(int(x) for x in args.bg.split(","))
    canvas = Image.new("RGB", (im.width + pad * 2, im.height + pad * 2), pad_rgb)
    canvas.paste(im, (pad, pad))
    canvas.save(args.output_png, optimize=True)
    print(f"wrote {args.output_png} {canvas.size} ({os.path.getsize(args.output_png)} bytes)")


if __name__ == "__main__":
    main()
