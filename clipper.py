#!/usr/bin/env python3
"""Potong video YouTube jadi satu atau beberapa bagian, rasio 9:16, dengan subtitel otomatis.

Contoh:
    # Satu klip 9:16 + subtitel
    python clipper.py "https://youtu.be/XXXX" -s 1:30 -e 2:15 --subtitle

    # Rentang dipecah otomatis jadi bagian @ 60 detik
    python clipper.py "https://youtu.be/XXXX" -s 1:00 -e 5:00 --part-length 60 --subtitle

    # Beberapa bagian dengan waktu bebas, tanpa crop 9:16
    python clipper.py "https://youtu.be/XXXX" --segments "0:10-0:40,2:00-2:45" --no-vertical

Kebutuhan: yt-dlp dan ffmpeg (dengan libass untuk subtitel) di PATH. Tidak butuh API key.
Subtitel diambil dari caption YouTube (manual atau otomatis), jadi video harus punya caption.
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

MIN_LAST_PART = 3     # detik; sisa bagian terakhir yang lebih pendek digabung ke sebelumnya
SUB_MAX_WORDS = 5     # kata maksimal per baris subtitel
SUB_MAX_CHARS = 30    # karakter maksimal per baris subtitel
SUB_MAX_GAP = 1.0     # jeda (detik) yang memutus baris subtitel
WORD_MAX_DUR = 1.2    # durasi maksimal satu kata (detik)


# ---------------------------------------------------------------- waktu & segmen

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


# ---------------------------------------------------------------- subtitel

def load_words(path: str) -> list[tuple[float, float, str]]:
    """Baca caption YouTube (json3) menjadi daftar kata (mulai, selesai, teks)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    words = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        t0 = ev.get("tStartMs", 0) / 1000
        t_end = t0 + ev.get("dDurationMs", 0) / 1000
        items = []
        for seg in segs:
            text = seg.get("utf8", "").replace("\n", " ").strip()
            if text:
                items.append((t0 + seg.get("tOffsetMs", 0) / 1000, text))
        for i, (st, text) in enumerate(items):
            en = items[i + 1][0] if i + 1 < len(items) else t_end
            if en <= st:
                en = st + 0.3
            tokens = text.split()
            step = (en - st) / len(tokens)
            for j, tok in enumerate(tokens):
                words.append((st + j * step, st + (j + 1) * step, tok))

    words.sort(key=lambda w: w[0])

    # buang duplikat persis dan rapikan durasi kata
    cleaned = []
    for w in words:
        if cleaned and cleaned[-1][2] == w[2] and abs(cleaned[-1][0] - w[0]) < 0.05:
            continue
        cleaned.append(w)
    result = []
    for i, (st, en, tok) in enumerate(cleaned):
        if i + 1 < len(cleaned):
            en = min(en, cleaned[i + 1][0])
        en = min(en, st + WORD_MAX_DUR)
        en = max(en, st + 0.15)
        result.append((st, en, tok))
    return result


def make_cues(words: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Kelompokkan kata menjadi baris subtitel pendek (cocok untuk layar vertikal)."""
    cues = []
    chunk: list[tuple[float, float, str]] = []

    def flush():
        if chunk:
            cues.append((chunk[0][0], chunk[-1][1], " ".join(w[2] for w in chunk)))
            chunk.clear()

    for w in words:
        if chunk:
            chars = sum(len(x[2]) + 1 for x in chunk) + len(w[2])
            if (len(chunk) >= SUB_MAX_WORDS or chars > SUB_MAX_CHARS
                    or w[0] - chunk[-1][1] > SUB_MAX_GAP):
                flush()
        chunk.append(w)
        if w[2][-1] in ".?!":
            flush()
    flush()

    # gabungkan baris berisi satu kata ke baris sebelumnya bila masih muat
    merged: list[tuple[float, float, str]] = []
    for s, e, text in cues:
        if (merged and " " not in text and s - merged[-1][1] < 0.3
                and len(merged[-1][2].split()) + 1 <= SUB_MAX_WORDS + 2
                and len(merged[-1][2]) + 1 + len(text) <= SUB_MAX_CHARS + 8
                and merged[-1][2][-1] not in ".?!"):
            ps, _, ptext = merged.pop()
            merged.append((ps, e, ptext + " " + text))
        else:
            merged.append((s, e, text))
    cues = merged

    # baris tidak boleh menimpa baris berikutnya
    fixed = []
    for i, (s, e, t) in enumerate(cues):
        if i + 1 < len(cues):
            e = min(e, cues[i + 1][0])
        fixed.append((s, max(e, s + 0.15), t))
    return fixed


def cues_for_segment(cues, start: float, end: float):
    """Ambil baris yang jatuh di [start, end] dan geser waktunya ke awal klip."""
    out = []
    for cs, ce, text in cues:
        if ce <= start or cs >= end:
            continue
        s, e = max(cs, start) - start, min(ce, end) - start
        if e - s >= 0.3:   # lewati baris yang hanya muncul sekejap di tepi klip
            out.append((s, e, text))
    return out


def ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def write_ass(cues, path: str, vertical: bool):
    """Tulis subtitel ke file .ass (putih tebal dengan garis hitam, tengah-bawah)."""
    if vertical:
        res_x, res_y, size, margin_v = 1080, 1920, 72, 320   # margin besar agar tidak tertutup UI
    else:
        res_x, res_y, size, margin_v = 1920, 1080, 54, 70
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {res_x}",
        f"PlayResY: {res_y}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,Arial,{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
        f"-1,0,0,0,100,100,0,0,1,5,0,2,60,60,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for s, e, text in cues:
        text = text.replace("{", "").replace("}", "").replace("\n", " ")
        lines.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Default,,0,0,0,,{text}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def fetch_subtitles(url: str, lang: str, workdir: str) -> str | None:
    """Unduh caption YouTube (manual atau otomatis). Mengembalikan path file json3 atau None."""
    print(f"Mengambil caption YouTube (bahasa: {lang})...")
    cmd = [
        "yt-dlp", "--skip-download",
        "--write-subs", "--write-auto-subs",
        "--sub-langs", lang,
        "--sub-format", "json3",
        "--no-playlist",
        "-o", os.path.join(workdir, "subs.%(ext)s"),
        url,
    ]
    result = subprocess.run(cmd)
    files = sorted(glob.glob(os.path.join(workdir, "subs.*.json3")))
    if result.returncode != 0 or not files:
        print("PERINGATAN: caption tidak ditemukan/gagal diunduh. Klip dibuat tanpa subtitel.\n"
              "Coba bahasa lain dengan --sub-lang (contoh: en), atau coba lagi nanti.")
        return None
    return files[0]


# ---------------------------------------------------------------- video

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


def ass_filter(path: str) -> str:
    safe = path.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    return f"ass=filename='{safe}'"


def output_names(output: str, count: int) -> list[str]:
    """clip.mp4 -> clip.mp4 (satu bagian) atau clip_part1.mp4, clip_part2.mp4, ..."""
    if count == 1:
        return [output]
    stem, ext = os.path.splitext(output)
    ext = ext or ".mp4"
    return [f"{stem}_part{i}{ext}" for i in range(1, count + 1)]


def render(src: str, dst: str, offset: float, duration: float, filters: list[str]):
    """Potong `duration` detik mulai dari `offset` di file sumber."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y",
           "-ss", f"{offset:.3f}", "-i", src, "-t", f"{duration:.3f}"]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dst]
    subprocess.run(cmd, check=True)


def render_segments(src: str, base: float, segments: list[tuple[float, float]],
                    names: list[str], filters: list[str],
                    cues=None, vertical: bool = True, workdir: str | None = None):
    for i, ((s, e), name) in enumerate(zip(segments, names), start=1):
        print(f"\nMemproses bagian {i}/{len(segments)} ({s:.0f}s-{e:.0f}s) -> {name}")
        seg_filters = list(filters)
        if cues:
            seg_cues = cues_for_segment(cues, s, e)
            if seg_cues:
                ass_path = os.path.join(workdir or ".", f"sub{i}.ass")
                write_ass(seg_cues, ass_path, vertical)
                seg_filters.append(ass_filter(ass_path))
            else:
                print("  (tidak ada ucapan di bagian ini, tanpa subtitel)")
        render(src, name, s - base, e - s, seg_filters)


def main():
    p = argparse.ArgumentParser(description="Potong video YouTube: multi-bagian, 9:16, subtitel.")
    p.add_argument("url", help="Link video YouTube")
    p.add_argument("-s", "--start", type=to_seconds, help="Waktu mulai (SS, MM:SS, HH:MM:SS)")
    p.add_argument("-e", "--end", type=to_seconds, help="Waktu selesai (SS, MM:SS, HH:MM:SS)")
    p.add_argument("--part-length", type=float, metavar="DETIK",
                   help="Pecah rentang start-end menjadi bagian berdurasi sekian detik")
    p.add_argument("--segments", type=parse_segments, metavar="MULAI-SELESAI,...",
                   help='Beberapa rentang bebas, contoh: "0:10-0:40,2:00-2:45"')
    p.add_argument("-o", "--output", default="clip.mp4",
                   help="Nama file hasil (default clip.mp4; bagian jamak jadi clip_part1.mp4, ...)")
    p.add_argument("--vertical", action=argparse.BooleanOptionalAction, default=True,
                   help="Rasio 9:16 (bawaan aktif; matikan dengan --no-vertical)")
    p.add_argument("--subtitle", action="store_true",
                   help="Tempel subtitel otomatis dari caption YouTube")
    p.add_argument("--sub-lang", default="id",
                   help="Bahasa caption (default id; contoh: en). Bisa hasil terjemahan otomatis YouTube")
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

        cues = None
        if args.subtitle:
            sub_file = fetch_subtitles(args.url, args.sub_lang, tmp)
            if sub_file:
                cues = make_cues(load_words(sub_file))

        render_segments(raw, base, segments, names,
                        build_filters(args.vertical, args.watermark),
                        cues=cues, vertical=args.vertical, workdir=tmp)
    print("\nSelesai:\n  " + "\n  ".join(names))


if __name__ == "__main__":
    main()
