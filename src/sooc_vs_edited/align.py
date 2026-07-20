"""Register a SOOC frame onto its edited counterpart.

Editing usually changes framing (crop, straighten, occasionally a perspective
correction). Overlaying the two frames is only meaningful once that geometry is
undone, so we estimate a homography from SIFT correspondences and warp the SOOC
frame into the edited frame's coordinate system. What is left over is colour.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_sift = None
_matcher = None

MIN_INLIERS = 15
RATIO = 0.75
RANSAC_PX = 4.0


def _engines():
    global _sift, _matcher
    if _sift is None:
        import cv2

        _sift = cv2.SIFT_create(nfeatures=6000)
        _matcher = cv2.BFMatcher(cv2.NORM_L2)
    return _sift, _matcher


@dataclass
class Alignment:
    ok: bool
    persp_px: float = 0.0  # residual after fitting the best affine — the non-affine part
    scale: float = 1.0  # >1 means the edit is cropped in
    rot_deg: float = 0.0
    inliers: int = 0
    reason: str = ""

    def as_meta(self) -> dict:
        return {"p": round(self.persp_px, 1), "s": round(self.scale, 3), "r": round(self.rot_deg, 2)}


def _affine_residual(src: np.ndarray, dst: np.ndarray) -> tuple[float, float, float]:
    """Least-squares fit an affine to 4 corner correspondences.

    The residual is how much of the transform an affine *cannot* express, i.e. the
    projective (keystone) component, in destination pixels.
    """
    A = np.zeros((8, 6))
    b = np.zeros(8)
    for i, (p, q) in enumerate(zip(src, dst)):
        A[2 * i] = [p[0], p[1], 1, 0, 0, 0]
        b[2 * i] = q[0]
        A[2 * i + 1] = [0, 0, 0, p[0], p[1], 1]
        b[2 * i + 1] = q[1]
    m, *_ = np.linalg.lstsq(A, b, rcond=None)
    M = m.reshape(2, 3)
    pred = (M @ np.vstack([src.T, np.ones(len(src))])).T
    resid = float(np.linalg.norm(pred - dst, axis=1).max())
    scale = float(np.sqrt(abs(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])))
    rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    return resid, scale, rot


def align(sooc_bgr: np.ndarray, edited_bgr: np.ndarray) -> tuple[np.ndarray | None, Alignment]:
    """Warp `sooc_bgr` into `edited_bgr`'s frame. Returns (warped, report)."""
    import cv2

    sift, matcher = _engines()
    gs = cv2.cvtColor(sooc_bgr, cv2.COLOR_BGR2GRAY)
    ge = cv2.cvtColor(edited_bgr, cv2.COLOR_BGR2GRAY)

    kp_s, des_s = sift.detectAndCompute(gs, None)
    kp_e, des_e = sift.detectAndCompute(ge, None)
    if des_s is None or des_e is None or len(kp_s) < 10 or len(kp_e) < 10:
        return None, Alignment(False, reason="too few features")

    good = [m for m, n in matcher.knnMatch(des_s, des_e, k=2) if m.distance < RATIO * n.distance]
    if len(good) < MIN_INLIERS:
        return None, Alignment(False, reason=f"only {len(good)} good matches")

    src = np.float32([kp_s[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp_e[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    H, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_PX)
    if H is None:
        return None, Alignment(False, reason="no homography")
    inliers = int(mask.sum())
    if inliers < MIN_INLIERS:
        return None, Alignment(False, inliers=inliers, reason=f"only {inliers} inliers")

    h, w = sooc_bgr.shape[:2]
    he, we = edited_bgr.shape[:2]
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    mapped = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
    persp, scale, rot = _affine_residual(corners.reshape(-1, 2), mapped)

    warped = cv2.warpPerspective(
        sooc_bgr, H, (we, he), flags=cv2.INTER_LANCZOS4, borderValue=(0, 0, 0)
    )
    return warped, Alignment(True, persp, scale, rot, inliers)
