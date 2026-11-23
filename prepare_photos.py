#!/usr/bin/env python3
"""
prepare_photos.py: make small, fast web copies of the photos.

HOW TO USE
  1. Put the original photos in the  photos/  folder.
  2. Run:   python3 prepare_photos.py --hero NAME-OF-MAIN-PHOTO.jpg
  3. Fill in the alt text (a short description of each photo) in data/photos.json.
     Alt text you already wrote is kept when you run this again.

What it does
  * Fixes sideways phone photos, removes hidden location (GPS) data.
  * Saves web copies in images/ (large view + small thumbnail).
  * Makes images/share.jpg, the preview picture when the link is shared.
  * Writes data/photos.json, which the page reads.

Needs the Pillow library (pip install Pillow).
"""
import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageOps

try:  # lets the script read iPhone .HEIC photos if pillow-heif is installed
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "photos"
OUT = ROOT / "images"
DATA = ROOT / "data" / "photos.json"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", Path(name).stem.lower()).strip("-")
    return s or "photo"


def save_jpeg(img, path, max_side, quality=80):
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    im.save(path, "JPEG", quality=quality, optimize=True, progressive=True)
    return im.size


def cover(img, w, h):
    """Crop to fill exactly w x h, keeping the upper-middle (where faces usually are)."""
    return ImageOps.fit(img, (w, h), Image.LANCZOS, centering=(0.5, 0.35))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hero", help="file name of the main photo of Jen (in photos/)")
    args = ap.parse_args()

    files = sorted(p for p in SRC.iterdir() if p.suffix.lower() in EXTS) if SRC.exists() else []
    if not files:
        print("No photos found in photos/. Add some and run again.")
        return

    old = json.loads(DATA.read_text()) if DATA.exists() else {}
    old_alt = {g.get("file"): g.get("alt", "") for g in old.get("gallery", [])}
    if old.get("hero"):
        old_alt.setdefault(old["hero"].get("file"), old["hero"].get("alt", ""))

    hero_name = args.hero or (old.get("hero") or {}).get("file") or files[0].name
    OUT.mkdir(exist_ok=True)
    gallery, hero, used = [], None, set()

    for f in files:
        s = slug(f.name)
        while s in used:
            s += "-2"
        used.add(s)
        with Image.open(f) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")  # upright, no hidden data

        w, h = save_jpeg(img, OUT / f"{s}.jpg", 1600, 80)
        cover(img, 600, 600).save(OUT / f"{s}-thumb.jpg", "JPEG", quality=76, optimize=True, progressive=True)
        entry = {"file": f.name, "src": f"images/{s}.jpg", "thumb": f"images/{s}-thumb.jpg",
                 "width": w, "height": h, "alt": old_alt.get(f.name, "")}
        gallery.append(entry)

        if f.name == hero_name:
            cover(img, 900, 1125).save(OUT / "hero.jpg", "JPEG", quality=82, optimize=True, progressive=True)
            cover(img, 1200, 630).save(OUT / "share.jpg", "JPEG", quality=82, optimize=True, progressive=True)
            hero = {"file": f.name, "src": "images/hero.jpg", "width": 900, "height": 1125,
                    "alt": (old.get("hero") or {}).get("alt") or old_alt.get(f.name, "")}

    DATA.write_text(json.dumps({"hero": hero, "gallery": gallery}, indent=2, ensure_ascii=False) + "\n")

    total_in = sum(f.stat().st_size for f in files) / 1e6
    total_out = sum(p.stat().st_size for p in OUT.glob("*.jpg")) / 1e6
    print(f"Done: {len(files)} photos. Originals {total_in:.1f} MB -> web copies {total_out:.1f} MB.")
    print(f"Main photo: {hero_name}")
    missing = [g["file"] for g in gallery if not g["alt"]]
    if missing:
        print("Still need alt text in data/photos.json for:", ", ".join(missing))


if __name__ == "__main__":
    main()
