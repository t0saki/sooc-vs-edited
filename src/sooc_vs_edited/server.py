"""Local server for the viewer: static files plus a POST /export endpoint.

The page itself can only see 1600px previews. Export has to hand back the real
originals, so it happens here instead of in the browser.
"""

from __future__ import annotations

import csv
import json
import shutil
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pairing import DEFAULT_KEY_RE, find_raw


class Handler(SimpleHTTPRequestHandler):
    project: dict = {}
    root: Path = Path(".")

    def log_message(self, fmt, *args):  # quieter than the default access log
        if "export" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def do_POST(self):  # noqa: N802 - stdlib naming
        if self.path.rstrip("/") != "/export":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            result = do_export(
                self.project,
                body.get("choices") or {},
                mirror=bool(body.get("mirror", True)),
                with_raw=bool(body.get("raw", False)),
            )
        except Exception as exc:  # surface the reason in the toast
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": False, "error": str(exc)}).encode())
            return
        payload = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def source_for(project: dict, key: str, choice: str) -> Path | None:
    entry = project["files"].get(key)
    if not entry:
        return None
    if choice == "sooc":
        return Path(project["sooc_dir"]) / entry["sooc"]
    if choice == "edit":
        return Path(project["edited_dir"]) / entry["edited"]
    return None


def do_export(project: dict, choices: dict, mirror: bool = True, with_raw: bool = False) -> dict:
    out = Path(project["export_dir"])
    out.mkdir(parents=True, exist_ok=True)

    wanted: dict[str, Path] = {}
    missing: list[str] = []
    counts = {"sooc": 0, "edit": 0, "raw": 0}

    for key, choice in sorted(choices.items()):
        src = source_for(project, key, choice)
        if src is None or not src.exists():
            missing.append(key)
            continue
        wanted[f"{key}{src.suffix.lower()}"] = src
        counts[choice] += 1
        if with_raw and choice == "sooc":
            raw = find_raw(Path(project["sooc_dir"]), key, DEFAULT_KEY_RE)
            if raw:
                wanted[raw.name] = raw
                counts["raw"] += 1

    if mirror:
        # The folder should equal the current selection, not accumulate old picks.
        keep = set(wanted) | {"manifest.csv"}
        for p in out.iterdir():
            if p.is_file() and p.name not in keep:
                p.unlink()

    for name, src in wanted.items():
        dest = out / name
        if dest.exists() and dest.stat().st_size == src.stat().st_size:
            continue
        shutil.copy2(src, dest)

    with (out / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["frame", "choice", "source"])
        for key, choice in sorted(choices.items()):
            src = source_for(project, key, choice)
            w.writerow([key, choice, str(src) if src else ""])

    return {
        "ok": True,
        "out": str(out),
        "sooc": counts["sooc"],
        "edit": counts["edit"],
        "raw": counts["raw"],
        "missing": missing,
    }


def serve(out_dir: Path, project: dict, port: int = 8787, host: str = "127.0.0.1"):
    handler = partial(Handler, directory=str(out_dir))
    Handler.project = project
    Handler.root = out_dir
    return ThreadingHTTPServer((host, port), handler)
