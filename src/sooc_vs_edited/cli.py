"""Command line entry point: build / serve / open / export."""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from . import __version__
from .pairing import DEFAULT_KEY_RE, pair_directories


def _progress(phase: str, done: int, total: int) -> None:
    bar = "#" * round(28 * done / total)
    end = "\n" if done == total else "\r"
    print(f"  {phase:<8} [{bar:<28}] {done}/{total}", end=end, flush=True)


def _load_project(out_dir: Path) -> dict:
    f = out_dir / "project.json"
    if not f.exists():
        sys.exit(f"没找到 {f}，先跑一次 build")
    return json.loads(f.read_text(encoding="utf-8"))


def cmd_build(a: argparse.Namespace) -> int:
    from .build import build

    sooc_dir, edited_dir = Path(a.sooc).expanduser(), Path(a.edited).expanduser()
    for d in (sooc_dir, edited_dir):
        if not d.is_dir():
            sys.exit(f"目录不存在：{d}")

    out_dir = Path(a.out).expanduser() if a.out else edited_dir.parent / f"{edited_dir.name} 对比"
    export_dir = Path(a.export_to).expanduser() if a.export_to else out_dir.parent / f"{out_dir.name} 精选"
    title = a.title or edited_dir.name

    p = pair_directories(sooc_dir, edited_dir, a.key_regex, a.recursive)
    # 候选只取修过的那些；整卷里没修的直出不参与对比
    print(f"候选 {len(p.pairs)} 组（修过的）· 未修的直出 {len(p.sooc_only)} 张不参与"
          + (f" · 找不到直出的修图 {len(p.edited_only)} 张" if p.edited_only else ""))
    if p.duplicates:
        print(f"  注意：{len(p.duplicates)} 个帧号有重名文件，只取第一个 "
              f"({', '.join(list(p.duplicates)[:5])})")
    if not p.pairs:
        sys.exit("没有可配对的图片，检查目录或 --key-regex")

    out_dir.mkdir(parents=True, exist_ok=True)
    build(
        p, sooc_dir, edited_dir, out_dir, export_dir, title,
        width=a.width, do_align=not a.no_align, jobs=a.jobs, on_progress=_progress,
    )
    print(f"完成 → {out_dir}")
    if not a.no_serve:
        return _serve(out_dir, a.port, open_browser=not a.no_open)
    print(f"下一步：svse serve '{out_dir}'")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    return _serve(Path(a.out).expanduser(), a.port, open_browser=not a.no_open)


def _serve(out_dir: Path, port: int, open_browser: bool) -> int:
    from .server import serve

    project = _load_project(out_dir)
    httpd = serve(out_dir, project, port)
    url = f"http://127.0.0.1:{port}/"
    print(f"服务已启动 {url}  (Ctrl-C 停止)")
    print(f"导出目标：{project['export_dir']}")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


def cmd_export(a: argparse.Namespace) -> int:
    from .server import do_export

    out_dir = Path(a.out).expanduser()
    project = _load_project(out_dir)
    if a.export_to:
        project["export_dir"] = str(Path(a.export_to).expanduser())
    payload = json.loads(Path(a.choices).expanduser().read_text(encoding="utf-8"))
    result = do_export(
        project, payload.get("choices", payload),
        mirror=not a.no_mirror, with_raw=a.raw, match_geometry=not a.keep_sooc_crop,
    )
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


def cmd_pair(a: argparse.Namespace) -> int:
    p = pair_directories(
        Path(a.sooc).expanduser(), Path(a.edited).expanduser(), a.key_regex, a.recursive
    )
    print(f"配对 {len(p.pairs)}：{' '.join(p.pairs)}")
    print(f"仅直出 {len(p.sooc_only)}：{' '.join(p.sooc_only)}")
    print(f"仅修图 {len(p.edited_only)}：{' '.join(p.edited_only)}")
    if p.duplicates:
        print(f"重名 {len(p.duplicates)}：{json.dumps(p.duplicates, ensure_ascii=False)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="svse",
        description="对比相机直出 JPEG 与 RAW 修图导出，挑选后导出原图。",
    )
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_pair_args(sp):
        sp.add_argument("--key-regex", default=DEFAULT_KEY_RE, help="从文件名提取帧号的正则")
        sp.add_argument("--recursive", action="store_true", help="递归扫描子目录")

    b = sub.add_parser("build", help="生成对比页（默认生成后直接起服务）")
    b.add_argument("--sooc", required=True, help="相机直出 JPEG 目录")
    b.add_argument("--edited", required=True, help="修图导出目录")
    b.add_argument("--out", help="输出目录，默认 <修图目录> 对比")
    b.add_argument("--export-to", help="挑选后导出目录，默认 <输出目录> 精选")
    b.add_argument("--title", help="页面标题，默认取修图目录名")
    b.add_argument("--width", type=int, default=1600, help="预览图宽度 (默认 1600)")
    b.add_argument("--no-align", action="store_true", help="跳过几何对齐（快，但裁切过的图无法叠加对比）")
    b.add_argument("--jobs", type=int, default=8, help="并行度 (默认 8)")
    b.add_argument("--port", type=int, default=8787)
    b.add_argument("--no-serve", action="store_true", help="只生成，不起服务")
    b.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    add_pair_args(b)
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("serve", help="为已生成的目录起本地服务")
    s.add_argument("out", help="build 的输出目录")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--no-open", action="store_true")
    s.set_defaults(func=cmd_serve)

    e = sub.add_parser("export", help="用 choices.json 离线导出（页面没连上服务时的兜底）")
    e.add_argument("out", help="build 的输出目录")
    e.add_argument("choices", help="choices.json")
    e.add_argument("--export-to", help="覆盖导出目录")
    e.add_argument("--raw", action="store_true", help="选直出的同时带上 RAW")
    e.add_argument("--keep-sooc-crop", action="store_true",
                   help="导出直出时保留相机原始构图，不套用修图的裁切/旋转/透视")
    e.add_argument("--no-mirror", action="store_true", help="保留导出目录里已有的其他文件")
    e.set_defaults(func=cmd_export)

    p = sub.add_parser("pair", help="只看配对结果，不生成任何东西")
    p.add_argument("--sooc", required=True)
    p.add_argument("--edited", required=True)
    add_pair_args(p)
    p.set_defaults(func=cmd_pair)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
