"""Ikuti pembicara: crop 9:16 bergeser ke arah orang yang sedang bicara (podcast, wawancara).

Cara kerja:
  1. Ambil frame kecil (3 gambar per detik) dari potongan video lewat ffmpeg.
  2. Cari posisi pembicara: kalau OpenCV terpasang, pakai deteksi wajah lalu pilih wajah yang
     paling bergerak (mulut/kepala). Kalau tidak, pakai gerakan terbesar di layar. Tanpa paket tambahan.
  3. Haluskan posisi, lalu hanya pindah saat pembicara benar-benar berganti (bukan goyang terus).
  4. Hasilnya ekspresi `crop` ffmpeg dengan perpindahan halus 0,5 detik.
"""
import os
import statistics
import subprocess

FPS = 3
MOVE_MIN = 0.15      # selisih posisi (bagian lebar layar) yang dianggap pembicara berganti
HOLD_SAMPLES = 3     # harus bertahan sekian sampel (1 detik) sebelum kamera pindah
MIN_DWELL = 2.0      # jeda minimal antar perpindahan, detik
EASE = 0.5           # lama perpindahan halus, detik


def _probe_size(src: str):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height", "-of", "csv=p=0", src],
                         capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")[:2]
    return int(w), int(h)


def _frames(src: str, offset: float, duration: float, w: int, h: int) -> list[bytes]:
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{offset:.3f}", "-i", src, "-t", f"{duration:.3f}",
           "-an", "-vf", f"fps={FPS},scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    data = subprocess.run(cmd, capture_output=True).stdout
    size = w * h
    return [data[i * size:(i + 1) * size] for i in range(len(data) // size)]


def _motion_positions(frames: list[bytes], w: int, h: int) -> list:
    """Tanpa OpenCV: posisi horizontal dengan gerakan terbanyak (bagian 0-1), None kalau diam."""
    pos = [None]
    win = max(3, w // 6)
    for a, b in zip(frames, frames[1:]):
        cols = [0] * w
        for r in range(h):
            ra, rb = a[r * w:(r + 1) * w], b[r * w:(r + 1) * w]
            for x, (p, q) in enumerate(zip(ra, rb)):
                if abs(p - q) > 14:
                    cols[x] += 1
        sums = [sum(cols[max(0, x - win // 2):x + win // 2 + 1]) for x in range(w)]
        top = max(sums)
        if top < 4:
            pos.append(None)
            continue
        peak = sums.index(top)
        lo, hi = max(0, peak - w // 5), min(w, peak + w // 5 + 1)   # pusat massa di sekitar puncak
        weight = sum(cols[lo:hi])
        pos.append((sum((x + 0.5) * cols[x] for x in range(lo, hi)) / weight) / w if weight else None)
    return pos


def _face_positions(frames: list[bytes], w: int, h: int):
    """Dengan OpenCV: wajah mana yang paling bergerak. None kalau OpenCV tidak ada atau wajah jarang terlihat."""
    if os.environ.get("CLIPPER_NO_CV"):
        return None
    try:
        import cv2
        import numpy as np
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        if cascade.empty():
            return None
    except Exception:
        return None
    gray = [np.frombuffer(f, np.uint8).reshape(h, w) for f in frames]
    pos, found = [], 0
    for k, g in enumerate(gray):
        faces = cascade.detectMultiScale(g, 1.1, 5, minSize=(max(12, w // 20),) * 2)
        if len(faces) == 0:
            pos.append(None)
            continue
        found += 1
        if len(faces) == 1 or k == 0:
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        else:
            d = cv2.absdiff(g, gray[k - 1])
            x, y, fw, fh = max(faces, key=lambda f: int(d[f[1]:f[1] + int(f[3] * 1.4), f[0]:f[0] + f[2]].sum()))
        pos.append((x + fw / 2) / w)
    return pos if found >= 0.3 * len(gray) else None


def _keyframes(pos: list) -> list[tuple[float, float]]:
    known = [p for p in pos if p is not None]
    if not known:
        return []
    last = known[0]
    filled = []
    for p in pos:
        last = last if p is None else p
        filled.append(last)
    med = [statistics.median(filled[max(0, i - 3):i + 4]) for i in range(len(filled))]
    cur = med[0]
    keys, count, last_switch = [(0.0, cur)], 0, -99.0
    for i, p in enumerate(med):
        t = i / FPS
        count = count + 1 if abs(p - cur) > MOVE_MIN and t - last_switch >= MIN_DWELL else 0
        if count >= HOLD_SAMPLES:
            cur = statistics.median(med[i - HOLD_SAMPLES + 1:i + 1])
            keys.append(((i - HOLD_SAMPLES + 1) / FPS, cur))
            count, last_switch = 0, t
    return keys


def crop_expression(keys: list[tuple[float, float]]) -> str:
    def x_of(c: float) -> str:
        return f"min(max({c:.4f}*iw-ih*9/32,0),iw-ih*9/16)"
    expr = x_of(keys[0][1])
    for (t, c), (_, prev) in zip(keys[1:], keys):
        expr += f"+({x_of(c)}-{x_of(prev)})*clip((t-{t:.2f})/{EASE},0,1)"
    return f"crop=w='ih*9/16':h=ih:x='{expr}':y=0"


def crop_filter_for(src: str, offset: float, duration: float):
    """Filter crop yang mengikuti pembicara, atau None (pakai crop tengah) bila gagal/tak perlu."""
    try:
        iw, ih = _probe_size(src)
        if iw * 16 <= ih * 9 * 1.05:      # sumber sudah vertikal
            return None
        w = 320
        h = max(2, round(w * ih / iw))
        frames = _frames(src, offset, duration, w, h)
        if len(frames) < 4:
            return None
        pos = _face_positions(frames, w, h)
        how = "wajah"
        if pos is None:
            how = "gerakan"
            sw, sh = 96, max(2, round(96 * ih / iw))
            pos = _motion_positions(_frames(src, offset, duration, sw, sh), sw, sh)
        keys = _keyframes(pos)
        if not keys:
            print("  Ikuti pembicara: tidak ada gerakan/wajah terdeteksi, pakai crop tengah.")
            return None
        print(f"  Ikuti pembicara ({how}): {len(keys) - 1} perpindahan kamera.")
        return crop_expression(keys)
    except Exception as exc:  # gagal apa pun: tetap buat klip dengan crop tengah
        print(f"  Ikuti pembicara gagal ({exc}), pakai crop tengah.")
        return None
