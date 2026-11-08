#!/usr/bin/env python3
"""Potong video YouTube berdasarkan waktu mulai dan selesai.

Contoh:
    python clipper.py "https://youtu.be/XXXX" --start 1:30 --end 2:15
    python clipper.py "https://youtu.be/XXXX" -s 90 -e 135 --vertical --watermark "@namakamu"

Kebutuhan: yt-dlp dan ffmpeg terpasang di PATH.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile


def to_seconds(value: str) -> float:
    """Ubah 'SS', 'MM:SS' atau 'HH:MM:SS' menjadi detik."""
    parts = [float(p) for p in value.strip().split(":")]
    if not 1 <= len(parts) <= 3:
        raise argparse.ArgumentTypeError(f"Format waktu tidak valid: {value}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def check_tools():
    missing = [t for t in ("yt-dlp", "ffmpeg") if shutil.which(t) is None]
    if missing:
        sys.exit(
            f"Tool belum terpasang: {', '.join(missing)}\n"
            "Install: pip install yt-dlp  |  ffmpeg: https://ffmpeg.org/download.html"
        )


def download_section(url: str, start: float, end: float, workdir: str) -> str:
    """Unduh hanya bagian video yang diminta."""
    out_template = os.path.join(workdir, "raw.%(ext)s")
    cmd = [
        "yt-dlp",
        "--download-sections", f"*{start}-{end}",
        "--force-keyframes-at-cuts",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
        "--merge-output-format", "mp4",
        "--no-playlist",
        "-o", out_template,
        url,
    ]
    print("Mengunduh potongan video...")
    subprocess.run(cmd, check=True)
    files = glob.glob(os.path.join(workdir, "raw.*"))
    if not files:
        sys.exit("Gagal: file hasil unduhan tidak ditemukan.")
    return files[0]


def build_filters(vertical: bool, watermark: str | None) -> list[str]:
    filters = []
    if vertical:
        # Potong tengah menjadi 9:16 lalu skala ke 1080x1920
        filters.append("crop=ih*9/16:ih,scale=1080:1920")
    if watermark:
        safe = watermark.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
        filters.append(
            f"drawtext=text='{safe}':fontcolor=white:fontsize=36:"
            "borderw=2:bordercolor=black:x=(w-text_w)/2:y=h-text_h-60"
        )
    return filters


def render(src: str, dst: str, filters: list[str]):
    cmd = ["ffmpeg", "-y", "-i", src]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst]
    print("Memproses video...")
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser(description="Potong video YouTube.")
    p.add_argument("url", help="Link video YouTube")
    p.add_argument("-s", "--start", type=to_seconds, required=True,
                   help="Waktu mulai (SS, MM:SS atau HH:MM:SS)")
    p.add_argument("-e", "--end", type=to_seconds, required=True,
                   help="Waktu selesai (SS, MM:SS atau HH:MM:SS)")
    p.add_argument("-o", "--output", default="clip.mp4", help="Nama file hasil")
    p.add_argument("--vertical", action="store_true",
                   help="Ubah ke rasio 9:16 (Shorts/Reels/TikTok)")
    p.add_argument("--watermark", help="Teks watermark di bagian bawah")
    args = p.parse_args()

    if args.end <= args.start:
        sys.exit("Waktu selesai harus lebih besar dari waktu mulai.")

    check_tools()
    with tempfile.TemporaryDirectory() as tmp:
        raw = download_section(args.url, args.start, args.end, tmp)
        render(raw, args.output, build_filters(args.vertical, args.watermark))
    print(f"Selesai: {args.output}")


if __name__ == "__main__":
    main()
