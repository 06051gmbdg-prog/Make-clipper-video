#!/usr/bin/env python3
"""ABIDIN AI CLIPPER: dari satu link YouTube, AI memilih momen terbaik lalu membuat beberapa klip 9:16.

Alur (mode semi otomatis):
  1. Ambil caption YouTube sebagai transkrip (tanpa Whisper, ringan untuk HP).
  2. AI (Gemini atau Claude) memilih momen terbaik dan memberi skor berbobot (hook, edukasi, viral, emosi,
     kejelasan, relevansi), plus judul, caption, dan hashtag.
  3. Kamu cek daftar momen dan pilih mana yang dibuat.
  4. Klip dibuat (9:16, subtitel, watermark), disimpan bersama jadwal.txt dan plan.json,
     lalu opsional diunggah ke Google Drive.

Pemakaian:
    clip ai "https://youtu.be/XXXX"
    clip ai "https://youtu.be/XXXX" -n 5 --topic "AI untuk bisnis kecil" --upload gdrive:Clipper

Bawaan memakai Gemini (ada kuota gratis; key dari https://aistudio.google.com/apikey).
Simpan di GEMINI_API_KEY atau biarkan program menyimpannya di ~/.config/clipper/gemini_key.
Pakai --ai claude untuk Claude (ANTHROPIC_API_KEY, berbayar). Jangan bagikan key ke siapa pun.
"""
import argparse
import getpass
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clipper as C  # noqa: E402

# penyedia AI: gemini (ada kuota gratis) atau claude (berbayar per pemakaian)
PROVIDERS = {
    "gemini": {
        "name": "Gemini", "model": "gemini-3.8-flash",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        "env": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        "key_file": os.path.expanduser("~/.config/clipper/gemini_key"),
        "where": "https://aistudio.google.com/apikey",
    },
    "claude": {
        "name": "Claude", "model": "claude-sonnet-5-5",
        "url": "https://api.anthropic.com/v1/messages",
        "env": ("ANTHROPIC_API_KEY",),
        "key_file": os.path.expanduser("~/.config/clipper/anthropic_key"),
        "where": "https://console.anthropic.com (menu API keys)",
    },
}
DEFAULT_PROVIDER = os.environ.get("CLIPPER_PROVIDER", "lokal")  # lokal = tanpa API key
API_URL = os.environ.get("CLIPPER_API_URL")  # untuk pengujian: timpa alamat API
KEY_FILE = PROVIDERS["claude"]["key_file"]
MAX_TRANSCRIPT_CHARS = 250_000

# bobot penilaian (sama dengan rencana ABIDIN AI CLIPPER)
WEIGHTS = {"hook": 0.25, "edukasi": 0.20, "viral": 0.20, "emosi": 0.15, "kejelasan": 0.10, "relevansi": 0.10}
DEFAULT_TOPIC = "audiens Indonesia: AI dan teknologi, bisnis online, affiliate marketing, edukasi digital, motivasi"


# ---------------------------------------------------------------- util

def fmt_time(sec: float) -> str:
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([\w-]{11})", url)
    return m.group(1) if m else None


def slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", text.lower().encode("ascii", "ignore").decode()).strip("_")
    return text[:40].strip("_") or "klip"


# ---------------------------------------------------------------- API key

def clean_key(raw: str) -> str:
    """Buang sisa karakter tempel (kode ESC, spasi, baris baru) yang bikin header ditolak."""
    raw = re.sub(r"\x1b\[[0-9;?]*[A-Za-z~]", "", raw)
    raw = re.sub(r"\[20[01]~", "", raw)
    return re.sub(r"[^A-Za-z0-9_-]", "", raw)


def load_api_key(provider: str = "claude") -> str:
    prov = PROVIDERS[provider]
    key_file = prov["key_file"]
    for var in prov["env"]:
        key = clean_key(os.environ.get(var, ""))
        if key:
            return key
    try:
        with open(key_file, encoding="utf-8") as f:
            key = clean_key(f.read())
    except OSError:
        key = ""
    if key:
        return key
    if not sys.stdin.isatty():
        sys.exit(f"API key {prov['name']} belum diatur. Isi variabel {prov['env'][0]} atau jalankan sekali secara interaktif.")
    print(f"API key {prov['name']} belum tersimpan. Buat di {prov['where']}.")
    key = clean_key(getpass.getpass("Tempel API key (tidak ditampilkan di layar): "))
    if not key:
        sys.exit("API key kosong.")
    if C.ask_yn(f"Simpan key di HP ini ({key_file}, hanya bisa dibaca akunmu)?", True):
        os.makedirs(os.path.dirname(key_file), exist_ok=True)
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key + "\n")
        print("Tersimpan. Hapus kapan saja dengan: rm " + key_file)
    return key


# ---------------------------------------------------------------- analisis AI

def transcript_text(words, per_line: int = 8) -> str:
    lines = []
    for i in range(0, len(words), per_line):
        chunk = words[i:i + per_line]
        lines.append(f"[{fmt_time(chunk[0][0])}] " + " ".join(w[2] for w in chunk))
    return "\n".join(lines)


def build_prompt(transcript: str, n: int, minlen: float, maxlen: float, topic: str, duration: float) -> str:
    return f"""Kamu editor konten Shorts/Reels/TikTok berbahasa Indonesia. Dari transkrip video berikut, pilih {n} momen terbaik untuk dijadikan klip pendek.

Aturan:
- Tiap klip berdurasi {int(minlen)} sampai {int(maxlen)} detik, tidak saling tumpang tindih.
- Mulai tepat di awal kalimat dengan hook kuat di 3 detik pertama; akhiri di akhir kalimat/gagasan yang tuntas.
- Waktu start dan end harus memakai stempel waktu yang ada di transkrip (format m:ss atau h:mm:ss) dan berada dalam rentang 0:00 sampai {fmt_time(duration)}.
- Audiens target: {topic}.
- Beri skor 0-10 untuk tiap kriteria: hook (3 detik pertama), edukasi, viral, emosi (emosi/storytelling), kejelasan (kejelasan bicara), relevansi (relevansi audiens).
- Jangan mengarang isi: judul, hook, dan caption harus sesuai ucapan di momen itu. Tulis dalam Bahasa Indonesia.
- caption: 1-3 kalimat, diakhiri ajakan (CTA) singkat. hashtags: 4-6 hashtag.

Balas HANYA dengan JSON valid tanpa teks lain, dengan bentuk:
{{"clips":[{{"start":"m:ss","end":"m:ss","title":"...","hook":"kalimat pembuka klip","caption":"...","hashtags":["#a","#b"],"scores":{{"hook":0,"edukasi":0,"viral":0,"emosi":0,"kejelasan":0,"relevansi":0}},"reason":"alasan singkat"}}]}}

TRANSKRIP:
{transcript}"""


def call_ai(prompt: str, key: str, model: str, provider: str = "claude", max_tokens: int = 8192) -> str:
    prov = PROVIDERS[provider]
    url = API_URL or prov["url"].format(model=model)
    if provider == "gemini":
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json",
                                                "temperature": 0.4, "maxOutputTokens": max_tokens}}).encode("utf-8")
        headers = {"x-goog-api-key": key, "content-type": "application/json"}
    else:
        body = json.dumps({"model": model, "max_tokens": min(max_tokens, 4096),
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    headers["user-agent"] = "abidin-ai-clipper/1.0"
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    name = prov["name"]
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600].strip()
        try:
            detail = json.loads(detail)["error"]["message"]
        except Exception:
            pass
        if not detail:
            detail = (f"(tanpa pesan dari server) {exc.reason}; ukuran permintaan {len(body)//1024} KB; "
                      f"server={exc.headers.get('server', '?')}")
        low = detail.lower()
        if exc.code in (400, 401, 403) and ("api key" in low or "api_key" in low or "x-api-key" in low):
            hint = "API key salah atau sudah dicabut."
        elif exc.code == 400 and ("credit" in low or "balance" in low):
            hint = "Saldo kredit API habis. Isi di console.anthropic.com, menu Plans & Billing."
        elif exc.code == 400:
            hint = "Permintaan ditolak; baca pesan di bawah."
        else:
            hint = {401: "API key salah atau sudah dicabut.", 403: "Key tidak punya izin untuk model/akses ini.",
                    404: "Nama model tidak ditemukan. Coba --model lain.",
                    429: "Kuota habis atau terlalu banyak permintaan. Tunggu beberapa menit lalu coba lagi."}.get(exc.code, "")
        raise RuntimeError(f"API {name} menolak (HTTP {exc.code}). {hint}\n{detail}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Tidak bisa menghubungi API {name}: {exc}") from None
    if provider == "gemini":
        parts = [pt.get("text", "") for c in data.get("candidates", [])[:1]
                 for pt in c.get("content", {}).get("parts", [])]
        if not "".join(parts).strip():
            why = (data.get("promptFeedback") or {}).get("blockReason") or \
                  (data.get("candidates") or [{}])[0].get("finishReason", "")
            raise RuntimeError(f"Balasan Gemini kosong ({why or 'tanpa alasan'}).")
    else:
        parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        if not parts:
            raise RuntimeError("Balasan API kosong.")
    return "".join(parts)


# ---------------------------------------------------------------- mode lokal (tanpa API key)

_KW = {
    "hook": ("rahasia", "ternyata", "jangan", "kesalahan", "gratis", "cuan", "viral", "gila", "bahaya", "wajib",
             "stop", "kenapa", "mengapa", "bagaimana", "caranya", "penting", "fakta", "bohong", "salah", "pertama",
             "banyak orang", "tahukah", "pernah", "bayangkan"),
    "edukasi": ("cara", "tips", "langkah", "belajar", "strategi", "kunci", "rumus", "contoh", "tutorial", "fungsi",
                "ilmu", "pelajaran", "prinsip", "metode", "alasan", "artinya", "misalnya", "karena", "sehingga"),
    "emosi": ("sedih", "bangkit", "gagal", "sukses", "takut", "bangga", "perjuangan", "mimpi", "hancur", "bahagia",
              "menangis", "kecewa", "semangat", "percaya", "berani", "hidup", "keluarga", "bersyukur"),
    "relevansi": ("ai", "bisnis", "online", "affiliate", "digital", "penghasilan", "jualan", "konten", "marketing",
                  "uang", "otomatis", "teknologi", "usaha", "produk", "pelanggan", "income", "kerja"),
}


def _hits(words_text: list[str], kws) -> int:
    joined = " " + " ".join(words_text).lower() + " "
    return sum(joined.count(f" {k} ") for k in kws)


def local_clips(words, n: int, minlen: float, maxlen: float) -> dict:
    """Pemilih momen sederhana tanpa AI: cari awal kalimat lalu nilai tiap jendela dari kata kunci dan kepadatan bicara."""
    def pause_before(i):  # ada jeda bicara sebelum kata ke-i (caption otomatis sering tanpa jeda)
        return i == 0 or words[i][0] - words[i - 1][1] >= 0.4

    # awal jendela: setiap jeda bicara, ditambah tiap 6 kata supaya tetap ada pilihan bila caption tanpa jeda
    starts = [i for i in range(len(words)) if pause_before(i) or i % 6 == 0]
    if len(starts) > 3000:
        starts = starts[::len(starts) // 3000 + 1]
    target = (minlen + maxlen) / 2
    cands = []
    for si in starts:
        t0 = words[si][0]
        # akhir jendela: utamakan jeda bicara, cadangan tiap 6 kata; durasi dekat target dan tidak melebihi maxlen
        best, ei, bestp = None, None, False
        for j in range(si + 1, len(words) + 1):
            dur = words[j - 1][1] - t0
            if dur > maxlen:
                break
            at_pause = j == len(words) or pause_before(j)
            if dur >= minlen and (at_pause or j % 6 == 0):
                better = (best is None or (at_pause and not bestp)
                          or (at_pause == bestp and abs(dur - target) < abs(best - target)))
                if better:
                    best, ei, bestp = dur, j, at_pause
        if ei is None:
            continue
        seg = words[si:ei]
        texts = [w[2] for w in seg]
        dur = seg[-1][1] - t0
        per100 = 100 / max(len(texts), 1)
        first = texts[:10]
        hook = min(10, (1.5 if pause_before(si) else 0) + 2 + 2.5 * _hits(first, _KW["hook"]) + (3 if any(t.endswith("?") for t in first) else 0)
                   + (2 if any(re.search(r"\d", t) for t in first) else 0))
        edu = min(10, 2 + _hits(texts, _KW["edukasi"]) * per100 * 0.8)
        viral = min(10, 2 + _hits(texts, _KW["hook"]) * per100 * 0.9)
        emo = min(10, 2 + _hits(texts, _KW["emosi"]) * per100 * 1.2)
        rel = min(10, 2 + _hits(texts, _KW["relevansi"]) * per100 * 1.0)
        wps = len(texts) / dur
        clarity = max(0, 10 - abs(wps - 2.8) * 3.5)
        cands.append({
            "start": str(int(t0)), "end": str(int(seg[-1][1] + 0.5)),
            "title": " ".join(texts[:8]).capitalize(), "hook": " ".join(texts[:14]),
            "caption": " ".join(texts[:16]) + "... Simak sampai habis, follow untuk tips lainnya!",
            "hashtags": ["#shorts", "#reels", "#abidinai", "#edukasi", "#tips"],
            "scores": {"hook": hook, "edukasi": edu, "viral": viral, "emosi": emo, "kejelasan": clarity, "relevansi": rel},
            "reason": "Dipilih oleh aturan lokal (kata kunci dan kepadatan bicara), bukan AI. Cek isinya sebelum diposting.",
        })
    return {"clips": cands}



def parse_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text)
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("Balasan AI bukan JSON.")
    return json.loads(text[a:b + 1])


def _num(v, lo=0.0, hi=10.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.0


def normalize_clips(raw: dict, n: int, lo: float, hi: float, minlen: float, maxlen: float) -> list[dict]:
    """Validasi hasil AI: waktu masuk akal, durasi sesuai, tidak tumpang tindih, urut skor tertinggi."""
    clips = []
    for c in raw.get("clips", []) if isinstance(raw, dict) else []:
        if not isinstance(c, dict):
            continue
        try:
            s, e = C.to_seconds(str(c["start"])), C.to_seconds(str(c["end"]))
        except (KeyError, argparse.ArgumentTypeError):
            continue
        s, e = max(s, lo), min(e, hi)
        if e - s > maxlen:
            e = s + maxlen
        if e <= s or e - s < minlen * 0.8:
            continue
        sc = c.get("scores") if isinstance(c.get("scores"), dict) else {}
        scores = {k: _num(sc.get(k)) for k in WEIGHTS}
        tags = []
        for t in c.get("hashtags") or []:
            t = "#" + re.sub(r"[^\w]", "", str(t))
            if len(t) > 1 and t not in tags:
                tags.append(t)
        clips.append({
            "start": s, "end": e,
            "title": str(c.get("title") or "Klip").strip()[:100],
            "hook": str(c.get("hook") or "").strip()[:200],
            "caption": str(c.get("caption") or "").strip()[:600],
            "hashtags": tags[:8],
            "scores": scores,
            "total": round(sum(WEIGHTS[k] * scores[k] for k in WEIGHTS) * 10, 1),
            "reason": str(c.get("reason") or "").strip()[:300],
        })
    clips.sort(key=lambda x: -x["total"])
    chosen = []
    for c in clips:
        if all(c["end"] <= o["start"] or c["start"] >= o["end"] for o in chosen):
            chosen.append(c)
        if len(chosen) >= n:
            break
    return chosen


# ---------------------------------------------------------------- keluaran

def source_link(url: str, vid: str | None, start: float) -> str:
    return f"https://youtu.be/{vid}?t={int(start)}" if vid else url


def write_jadwal(path: str, url: str, vid: str | None, clips: list[dict], watermark: str | None):
    lines = [f"Sumber: {url}", f"Dibuat: {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for i, c in enumerate(clips, 1):
        lines += [
            f"=== Klip {i}: {c['title']} ===",
            f"File     : {os.path.basename(c.get('file', ''))}",
            f"Skor     : {c['total']}/100",
            f"Sumber   : {source_link(url, vid, c['start'])}  ({fmt_time(c['start'])}-{fmt_time(c['end'])})",
            "",
            "Caption:",
            c["caption"],
            "",
            " ".join(c["hashtags"]),
        ]
        if watermark:
            lines.append(f"Watermark: {watermark}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def print_plan(clips: list[dict]):
    print("\nMomen terbaik menurut AI:\n")
    for i, c in enumerate(clips, 1):
        print(f" {i}. [{c['total']:>5}/100] {fmt_time(c['start'])}-{fmt_time(c['end'])}  {c['title']}")
        if c["hook"]:
            print(f"      Hook: {c['hook']}")
        if c["reason"]:
            print(f"      Alasan: {c['reason']}")
    print()


def pick(clips: list[dict], answer: str) -> list[dict]:
    answer = answer.strip().lower()
    if answer in ("", "semua", "all", "y", "ya"):
        return clips
    if answer in ("n", "no", "batal"):
        return []
    idx = {int(x) for x in re.findall(r"\d+", answer)}
    return [c for i, c in enumerate(clips, 1) if i in idx]


# ---------------------------------------------------------------- program utama

def main(argv=None):
    p = argparse.ArgumentParser(prog="clip ai", description="AI memilih momen terbaik lalu membuat klip 9:16.")
    p.add_argument("url", nargs="?", help="Link video YouTube sumber")
    p.add_argument("-n", "--clips", type=int, default=5, help="Jumlah klip yang diminta dari AI (default 5)")
    p.add_argument("--min-len", type=float, default=30, help="Durasi klip minimal, detik (default 30)")
    p.add_argument("--max-len", type=float, default=60, help="Durasi klip maksimal, detik (default 60)")
    p.add_argument("--topic", default=DEFAULT_TOPIC, help="Gambaran audiens/tema agar AI menilai relevansi")
    p.add_argument("--ai", dest="provider", choices=["lokal"] + list(PROVIDERS), default=DEFAULT_PROVIDER,
                   help="lokal = tanpa API key (bawaan), gemini (kuota gratis), atau claude (berbayar)")
    p.add_argument("--model", default=os.environ.get("CLIPPER_MODEL"), help="Nama model (bawaan sesuai --ai)")
    p.add_argument("--sub-lang", default="id", help="Bahasa caption YouTube (default id; jika tidak ada dicoba en)")
    p.add_argument("--sub-style", choices=C.SUB_STYLES, default="pop", help="Gaya teks (default pop)")
    p.add_argument("--no-subtitle", action="store_true", help="Buat klip tanpa subtitel")
    p.add_argument("--no-reframe", action="store_true", help="Matikan fitur crop yang mengikuti pembicara (pakai crop tengah)")
    p.add_argument("--watermark", help="Teks watermark, contoh \"ABIDIN AI\"")
    p.add_argument("--upload", metavar="TUJUAN", help="Unggah hasil ke Drive, contoh gdrive:Clipper atau link folder")
    p.add_argument("--out", help="Folder hasil (default Download/ABIDIN_AI/<id video>)")
    p.add_argument("--yes", action="store_true", help="Lewati pengecekan, buat semua klip pilihan AI")
    p.add_argument("--plan-only", action="store_true", help="Hanya buat rencana (plan.json), jangan buat klip")
    p.add_argument("--from-plan", metavar="PLAN.JSON", help="Pakai plan.json yang sudah ada, lewati analisis AI")
    args = p.parse_args(argv)
    args.model = args.model or (PROVIDERS[args.provider]["model"] if args.provider != "lokal" else "lokal")

    plan_in = None
    if args.from_plan:
        with open(args.from_plan, encoding="utf-8") as f:
            plan_in = json.load(f)
        args.url = args.url or plan_in.get("url")
    if not args.url:
        p.error("Isi link YouTube, atau pakai --from-plan.")
    if not re.match(r"^https?://", args.url, re.I):
        p.error("Link harus diawali https://")
    if args.clips < 1 or args.min_len <= 0 or args.max_len < args.min_len:
        p.error("Nilai --clips/--min-len/--max-len tidak valid.")
    if args.upload and not C.resolve_upload_target(args.upload)[0] and not re.search(r"drive\.google\.com", args.upload):
        p.error("--upload harus berbentuk namaremote:folder, contoh gdrive:Clipper, atau link folder Drive.")

    C.check_tools()
    print("Pastikan kamu punya izin memakai video sumber ini. Sertakan kredit ke pembuat aslinya saat memublikasikan.\n")
    vid = video_id(args.url)
    with tempfile.TemporaryDirectory() as tmp:
        sub_file = C.fetch_subtitles(args.url, args.sub_lang, tmp)
        if not sub_file and args.sub_lang != "en":
            print("Mencoba caption bahasa Inggris...")
            sub_file = C.fetch_subtitles(args.url, "en", tmp)
        if not sub_file:
            sys.exit("Video ini tidak punya caption, jadi AI tidak bisa membaca isinya (Whisper belum ada di V1).\n"
                     "Coba video lain, atau potong manual dengan: clip")
        words = C.load_words(sub_file)
        if not words:
            sys.exit("Caption kosong.")
        lo, hi = words[0][0], words[-1][1]

        if plan_in:
            clips = normalize_clips({"clips": [
                {**c, "start": c["start"], "end": c["end"]} for c in plan_in.get("clips", [])]},
                len(plan_in.get("clips", [])) or 1, 0, hi + 1, 1, 10 ** 6)
            if not clips:
                sys.exit("plan.json tidak berisi klip yang valid.")
        else:
            text = transcript_text(words)
            if len(text) > MAX_TRANSCRIPT_CHARS:
                print("PERINGATAN: transkrip sangat panjang, hanya bagian awal yang dianalisis.")
                text = text[:MAX_TRANSCRIPT_CHARS]
            if args.provider == "lokal":
                print(f"Memilih momen dari {fmt_time(hi)} transkrip dengan aturan lokal (tanpa API key)...")
                raw = local_clips(words, args.clips, args.min_len, args.max_len)
            else:
                key = load_api_key(args.provider)
                print(f"Menganalisis {fmt_time(hi)} transkrip dengan {args.model}...")
                try:
                    raw = parse_json(call_ai(build_prompt(text, args.clips, args.min_len, args.max_len, args.topic, hi),
                                             key, args.model, args.provider))
                except (RuntimeError, ValueError) as exc:
                    sys.exit(f"Analisis AI gagal: {exc}")
            clips = normalize_clips(raw, args.clips, lo, hi, args.min_len, args.max_len)
            if not clips:
                sys.exit("AI tidak menemukan momen yang memenuhi syarat. Coba lagi, atau longgarkan --min-len/--max-len.")

        base = os.path.expanduser("~/storage/downloads")
        outdir = args.out or os.path.join(base if os.path.isdir(base) else ".", "ABIDIN_AI", vid or time.strftime("%Y%m%d_%H%M%S"))
        os.makedirs(outdir, exist_ok=True)
        plan_path = os.path.join(outdir, "plan.json")
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump({"url": args.url, "video_id": vid, "model": args.model, "clips": clips}, f, ensure_ascii=False, indent=2)

        print_plan(clips)
        print(f"Rencana disimpan: {plan_path}")
        if args.plan_only:
            return 0
        if not args.yes:
            clips = pick(clips, C.ask("Klip mana yang dibuat? (Enter = semua, contoh 1,3, n = batal)", "semua"))
            if not clips:
                print("Dibatalkan. Rencana tetap tersimpan; lanjutkan nanti dengan --from-plan.")
                return 0

        cues = None if args.no_subtitle else C.make_cues(words)
        filters = C.build_filters(True, args.watermark)
        made = []
        for i, c in enumerate(clips, 1):
            name = os.path.join(outdir, f"{i:02d}_{slug(c['title'])}.mp4")
            print(f"\n=== Klip {i}/{len(clips)}: {c['title']} ({fmt_time(c['start'])}-{fmt_time(c['end'])}) ===")
            work = os.path.join(tmp, f"clip{i}")
            os.makedirs(work, exist_ok=True)
            try:
                raw_file = C.download_section(args.url, c["start"], c["end"], work)
                C.render_segments(raw_file, c["start"], [(c["start"], c["end"])], [name], filters,
                                  cues=cues, vertical=True, workdir=work, sub_style=args.sub_style,
                                  reframe=not args.no_reframe)
            except (SystemExit, Exception) as exc:  # satu klip gagal tidak menghentikan yang lain
                print(f"GAGAL membuat klip {i}: {exc}")
                continue
            c["file"] = name
            made.append(c)

    if not made:
        sys.exit("Tidak ada klip yang berhasil dibuat.")
    jadwal = os.path.join(outdir, "jadwal.txt")
    write_jadwal(jadwal, args.url, vid, made, args.watermark)
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump({"url": args.url, "video_id": vid, "model": args.model, "clips": made}, f, ensure_ascii=False, indent=2)

    print(f"\nSelesai: {len(made)} klip di {outdir}")
    for c in made:
        print("  " + os.path.basename(c["file"]))
    print(f"Caption dan hashtag: {jadwal}")
    if args.upload:
        print()
        C.upload_files([c["file"] for c in made] + [jadwal, plan_path], args.upload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
