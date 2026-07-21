"""Re-apply an edit's framing to the full-resolution SOOC file.

Picking "直出" means picking the camera's colour, not the camera's framing — the
crop, straighten and perspective fix made in the editor should survive. The
homography estimated during build lives in preview coordinates, so scale it up
to full resolution and warp the original into the edit's frame.
"""

from __future__ import annotations

from pathlib import Path

EXPORT_QUALITY = 95
IDENTITY_TOL_PX = 1.5  # below this the warp is a no-op; copy instead of re-encoding


def _scaled_homography(H, scale_src: float, scale_dst: float):
    """preview→preview homography, restated as full-res→full-res.

    `scale_src` maps full-res SOOC to its preview; `scale_dst` maps full-res
    edited to its preview.
    """
    import numpy as np

    def diag(k):
        return np.array([[k, 0, 0], [0, k, 0], [0, 0, 1]], dtype=np.float64)

    return diag(1.0 / scale_dst) @ np.asarray(H, dtype=np.float64) @ diag(scale_src)


def reframe(
    sooc_path: Path,
    edited_path: Path,
    geometry: dict,
    dest: Path,
    quality: int = EXPORT_QUALITY,
) -> bool:
    """Write `sooc_path` into `edited_path`'s frame. False if there was nothing to do."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    H = geometry.get("H")
    if not H:
        return False

    src = ImageOps.exif_transpose(Image.open(sooc_path)).convert("RGB")
    with Image.open(edited_path) as raw:
        we, he = ImageOps.exif_transpose(raw).size

    Hf = _scaled_homography(H, geometry["prev_sooc"][0] / src.width, geometry["prev_edited"][0] / we)

    corners = np.float32([[0, 0], [src.width, 0], [src.width, src.height], [0, src.height]])
    mapped = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), Hf).reshape(-1, 2)
    if (src.width, src.height) == (we, he) and np.abs(mapped - corners).max() < IDENTITY_TOL_PX:
        return False  # the edit did not change framing — keep the untouched original

    bgr = np.asarray(src)[:, :, ::-1]
    warped = cv2.warpPerspective(bgr, Hf, (we, he), flags=cv2.INTER_LANCZOS4, borderValue=(0, 0, 0))
    out = Image.fromarray(warped[:, :, ::-1])

    exif = src.getexif()
    blob = exif.tobytes() if len(exif) else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(
        dest, "JPEG", quality=quality, subsampling=0, optimize=True, progressive=True,
        **({"exif": blob} if blob else {}),
    )
    return True
