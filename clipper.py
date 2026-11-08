#!/usr/bin/env python3
"""Potong video YouTube menjadi satu atau beberapa bagian.

Contoh:
    # Satu klip
    python clipper.py "https://youtu.be/XXXX" -s 1:30 -e 2:15

    # Rentang 1:00-5:00 dipecah otomatis jadi bagian @ 60 detik
    python clipper.py "https://youtu.be/XXXX" -s 1:00 -e 5:00 --part-length 60

    # Beberapa bagian dengan waktu bebas
    python clipper.py "https://youtu.be/XXXX" --segments "0:10-0:40,2:00-2:45,5:10-5:50"

Kebutuhan: yt-dlp dan ffmpeg terpasang di PATH. Tidak butuh API key.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

MIN_LAST_PART = 3  # detik; sisa bagian terakhir yang lebih pendek digabung ke sebelumnya


def to_seconds(value: str) -> float:
    """Ubah 'SS', 'MM:SS' atau 'HH:MM:SS' menjadi detik."""
    try:
        parts = [float(p) for p in value.strip().split(":")]
    except ValueError:
        raise argparse.ArgumentTypeError(f"Format waktu tidak valid: {value}")
    if not 1 <= len(parts) <= 3:
        raise argparse.ArgumentTypeError(f"Format waktu tidak valid: {value}")
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def parse_segments(text: str) -> list[tuple[float, float]]:
    """Ubah '0:10-0:40,2:00-2:45' menjadi [(10, 40), (120, 165)]."""
    segments = []
    for item in text.split(","):
        item = item.strip()
        if not item:
            continue
        if "-" not in item:
            raise argparse.ArgumentTypeError(f"Segmen harus berbentuk MULAI-SELESAI: {item}")
        a, b = item.split("-", 1)
        start, end = to_seconds(a), to_seconds(b)
        if end <= start:
            raise argparse.ArgumentTypeError(f"Waktu selesai harus setelah mulai: {item}")
        segments.append((start, end))
    if not segments:
        raise argparse.ArgumentTypeError("Daftar segmen kosong.")
    return segments


def split_range(start: float, end: float, length: float) -> list[tuple[float, float]]:
    """Pecah rentang menjadi bagian-bagian berdurasi `length` detik."""
    segments = []
    t = start
    while t < end:
        segments.append((t, min(t + length, end)))
        t += length
    if len(segments) > 1 and segments[-1][1] - segments[-1][0] < MIN_LAST_PART:
        last = segments.pop()
        segments[-1] = (segments[-1][0], last[1])
    return segments


def check_tools():
    missing = [t for t in ("yt-dlp", "ffmpeg") if shutil.which(t) is None]
    if missing:
        sys.exit(
            f"Tool belum terpasang: {', '.join(missing)}\n"
            "Install: pip install yt-dlp  |  ffmpeg: https://ffmpeg.org/download.html"
        )


def download_section(url: str, start: float, end: float, workdir: str) -> str:
    """Unduh hanya rentang video yang dibutuhkan (satu kali untuk semua bagian)."""
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


def output_names(output: str, count: int) -> list[str]:
    """clip.mp4 -> clip.mp4 (satu bagian) atau clip_part1.mp4, clip_part2.mp4, ..."""
    if count == 1:
        return [output]
    stem, ext = os.path.splitext(output)
    ext = ext or ".mp4"
    return [f"{stem}_part{i}{ext}" for i in range(1, count + 1)]


def render(src: str, dst: str, offset: float, duration: float, filters: list[str]):
    """Potong `duration` detik mulai dari `offset` di file sumber."""
    cmd = ["ffmpeg", "-y", "-ss", f"{offset:.3f}", "-i", src, "-t", f"{duration:.3f}"]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)


def render_segments(src: str, base: float, segments: list[tuple[float, float]],
                    names: list[str], filters: list[str]):
    for i, ((s, e), name) in enumerate(zip(segments, names), start=1):
        print(f"Memproses bagian {i}/{len(segments)} ({s:.0f}s-{e:.0f}s) -> {name}")
        render(src, name, s - base, e - s, filters)


def main():
    p = argparse.ArgumentParser(description="Potong video YouTube jadi beberapa bagian.")
    p.add_argument("url", help="Link video YouTube")
    p.add_argument("-s", "--start", type=to_seconds, help="Waktu mulai (SS, MM:SS, HH:MM:SS)")
    p.add_argument("-e", "--end", type=to_seconds, help="Waktu selesai (SS, MM:SS, HH:MM:SS)")
    p.add_argument("--part-length", type=float, metavar="DETIK",
                   help="Pecah rentang start-end menjadi bagian berdurasi sekian detik")
    p.add_argument("--segments", type=parse_segments, metavar="MULAI-SELESAI,...",
                   help='Beberapa rentang bebas, contoh: "0:10-0:40,2:00-2:45"')
    p.add_argument("-o", "--output", default="clip.mp4",
                   help="Nama file hasil (default clip.mp4; bagian jamak jadi clip_part1.mp4, ...)")
    p.add_argument("--vertical", action="store_true", help="Ubah ke rasio 9:16")
    p.add_argument("--watermark", help="Teks watermark di bagian bawah")
    args = p.parse_args()

    if args.segments:
        if args.part_length or args.start is not None or args.end is not None:
            p.error("--segments tidak bisa digabung dengan --start/--end/--part-length.")
        segments = args.segments
    else:
        if args.start is None or args.end is None:
            p.error("Isi --start dan --end, atau pakai --segments.")
        if args.end <= args.start:
            p.error("Waktu selesai harus lebih besar dari waktu mulai.")
        if args.part_length:
            if args.part_length <= 0:
                p.error("--part-length harus lebih dari 0.")
            segments = split_range(args.start, args.end, args.part_length)
        else:
            segments = [(args.start, args.end)]

    names = output_names(args.output, len(segments))
    base = min(s for s, _ in segments)
    last = max(e for _, e in segments)

    check_tools()
    with tempfile.TemporaryDirectory() as tmp:
        raw = download_section(args.url, base, last, tmp)
        render_segments(raw, base, segments, names, build_filters(args.vertical, args.watermark))
    print("Selesai:\n  " + "\n  ".join(names))


if __name__ == "__main__":
    main()
