"""Build the static comparison site: previews, alignment, project.json, index.html."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps

from .pairing import Pairing

TEMPLATE = Path(__file__).parent / "templates" / "viewer.html"

PREVIEW_QUALITY = 88
THUMB_WIDTH = 260
THUMB_QUALITY = 78


def _load(path: Path) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    return im.convert("RGB")


def _save_resized(im: Image.Image, dest: Path, width: int, quality: int) -> None:
    if im.width > width:
        h = round(im.height * width / im.width)
        im = im.resize((width, h), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    im.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)


def _align_pair(key: str, img_dir: Path) -> dict:
    """Align the already-downscaled previews — full-res adds cost, not accuracy."""
    import cv2

    from .align import align

    src = cv2.imread(str(img_dir / "sooc" / f"{key}.jpg"))
    ref = cv2.imread(str(img_dir / "edited" / f"{key}.jpg"))
    out = img_dir / "sooc_aligned" / f"{key}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    if src is None or ref is None:
        shutil.copy2(img_dir / "sooc" / f"{key}.jpg", out)
        return {"p": 0.0, "s": 1.0, "r": 0.0, "ok": False}

    warped, report = align(src, ref)
    if warped is None:
        # Fall back to the unaligned preview so the viewer never hits a 404.
        shutil.copy2(img_dir / "sooc" / f"{key}.jpg", out)
        return {"p": 0.0, "s": 1.0, "r": 0.0, "ok": False, "why": report.reason}
    cv2.imwrite(str(out), warped, [cv2.IMWRITE_JPEG_QUALITY, PREVIEW_QUALITY])
    return {**report.as_meta(), "ok": True}


def build(
    pairing: Pairing,
    sooc_dir: Path,
    edited_dir: Path,
    out_dir: Path,
    export_dir: Path,
    title: str,
    width: int = 1600,
    do_align: bool = True,
    jobs: int = 8,
    on_progress=None,
) -> dict:
    img_dir = out_dir / "img"
    for sub in ("sooc", "edited", "thumb", "sooc_aligned"):
        (img_dir / sub).mkdir(parents=True, exist_ok=True)

    def previews(key: str) -> None:
        s = _load(pairing.sooc[key])
        e = _load(pairing.edited[key])
        _save_resized(s, img_dir / "sooc" / f"{key}.jpg", width, PREVIEW_QUALITY)
        _save_resized(e, img_dir / "edited" / f"{key}.jpg", width, PREVIEW_QUALITY)
        _save_resized(e, img_dir / "thumb" / f"{key}.jpg", THUMB_WIDTH, THUMB_QUALITY)

    _run(previews, pairing.pairs, jobs, on_progress, "preview")

    meta: dict[str, dict] = {}
    if do_align:
        def worker(key: str) -> None:
            meta[key] = _align_pair(key, img_dir)

        _run(worker, pairing.pairs, jobs, on_progress, "align")
    else:
        for key in pairing.pairs:
            shutil.copy2(img_dir / "sooc" / f"{key}.jpg", img_dir / "sooc_aligned" / f"{key}.jpg")
            meta[key] = {"p": 0.0, "s": 1.0, "r": 0.0, "ok": False}

    project = {
        "title": title,
        "sooc_dir": str(sooc_dir),
        "edited_dir": str(edited_dir),
        "export_dir": str(export_dir),
        "aligned": do_align,
        "preview_width": width,
        "pairs": pairing.pairs,
        "files": {
            k: {"sooc": pairing.sooc[k].name, "edited": pairing.edited[k].name}
            for k in pairing.pairs
        },
        "meta": meta,
        "sooc_only": pairing.sooc_only,
        "edited_only": pairing.edited_only,
        "duplicates": pairing.duplicates,
    }
    (out_dir / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=1))

    html = TEMPLATE.read_text()
    replacements = {  # __TITLE_JSON__ must come first, it contains __TITLE__
        "__TITLE_JSON__": json.dumps(title, ensure_ascii=False),
        "__TITLE__": _escape(title),
        "__PAIRS__": json.dumps(pairing.pairs),
        "__META__": json.dumps(meta, ensure_ascii=False),
        "__NOTE__": json.dumps(_note(pairing), ensure_ascii=False),
    }
    for token, value in replacements.items():
        html = html.replace(token, value)
    (out_dir / "index.html").write_text(html)
    return project


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _note(p: Pairing) -> str:
    # 候选集 = 修过的那些。没修的直出是整卷的剩余部分，属于正常情况，不提示。
    bits = []
    if p.edited_only:
        bits.append(f"{len(p.edited_only)} 张只有修图版")
    if p.duplicates:
        bits.append(f"{len(p.duplicates)} 个帧号有重名文件，取首个")
    return " · ".join(bits)


def _run(fn, items, jobs, on_progress, phase) -> None:
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for _ in ex.map(fn, items):
            done += 1
            if on_progress:
                on_progress(phase, done, len(items))
