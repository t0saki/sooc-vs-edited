"""Match SOOC files to edited files by frame key."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Files an editor may spit out. RAW is listed so `--sooc` can point at a mixed dump.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"}
RAW_EXTS = {".rw2", ".arw", ".cr2", ".cr3", ".nef", ".dng", ".orf", ".raf", ".pef"}

# "P1035532" out of "P1035532.JPG", "P1035699.RW22.jpg", "DSC_0123-Edit.jpg",
# "IMG_4821_1.jpg". Anything that does not match falls back to the bare stem.
DEFAULT_KEY_RE = r"^([A-Za-z]*[_-]?\d+)"


def frame_key(path: Path, pattern: str = DEFAULT_KEY_RE) -> str:
    """Reduce a filename to the camera frame number it belongs to."""
    head = path.name.split(".")[0]
    m = re.match(pattern, head)
    return m.group(1) if m else head


def list_images(directory: Path, recursive: bool = False) -> list[Path]:
    it = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(
        p for p in it if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not p.name.startswith(".")
    )


def find_raw(directory: Path, key: str, pattern: str = DEFAULT_KEY_RE) -> Path | None:
    """Locate the RAW file for a frame, searching `directory` and a sibling raw/ dir."""
    roots = [directory, directory / "raw", directory / "RAW", directory.parent / "raw"]
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.iterdir()):
            if p.is_file() and p.suffix.lower() in RAW_EXTS and frame_key(p, pattern) == key:
                return p
    return None


@dataclass
class Pairing:
    """Result of matching two directories against each other."""

    pairs: list[str] = field(default_factory=list)
    sooc: dict[str, Path] = field(default_factory=dict)
    edited: dict[str, Path] = field(default_factory=dict)
    sooc_only: list[str] = field(default_factory=list)
    edited_only: list[str] = field(default_factory=list)
    duplicates: dict[str, list[str]] = field(default_factory=dict)


def _index(files: list[Path], pattern: str, dupes: dict[str, list[str]]) -> dict[str, Path]:
    idx: dict[str, Path] = {}
    for p in files:
        k = frame_key(p, pattern)
        if k in idx:
            dupes.setdefault(k, [idx[k].name]).append(p.name)
            continue  # first one wins, deterministically (sorted input)
        idx[k] = p
    return idx


def pair_directories(
    sooc_dir: Path,
    edited_dir: Path,
    pattern: str = DEFAULT_KEY_RE,
    recursive: bool = False,
) -> Pairing:
    dupes: dict[str, list[str]] = {}
    sooc = _index(list_images(sooc_dir, recursive), pattern, dupes)
    edited = _index(list_images(edited_dir, recursive), pattern, dupes)
    keys = sorted(set(sooc) & set(edited))
    return Pairing(
        pairs=keys,
        sooc={k: sooc[k] for k in keys},
        edited={k: edited[k] for k in keys},
        sooc_only=sorted(set(sooc) - set(edited)),
        edited_only=sorted(set(edited) - set(sooc)),
        duplicates=dupes,
    )
