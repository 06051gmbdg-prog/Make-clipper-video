"""Riset konten viral Indonesia: AI mengusulkan kata kunci, yt-dlp mencari video sumber (tanpa API key YouTube).

Catatan jujur: AI di sini bekerja dari pengetahuan modelnya, bukan data trending langsung. Karena itu hasil
pencarian diurutkan memakai jumlah penayangan nyata dari YouTube, dan tema harian mengikuti rencana mingguan.
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto as A  # noqa: E402

USED_FILE = os.path.expanduser("~/.config/clipper/riset_used.json")

# Tema harian (Senin=0) sesuai rencana mingguan ABIDIN AI CLIPPER, dengan kata kunci cadangan tanpa AI.
WEEK = {
    0: ("AI & teknologi", ["podcast AI teknologi Indonesia", "cara pakai AI untuk bisnis kecil", "tools AI terbaru untuk kerja"]),
    1: ("Affiliate marketing", ["podcast affiliate marketing Indonesia", "kesalahan pemula affiliate", "cara mulai affiliate dari nol"]),
    2: ("Penghasilan online", ["podcast penghasilan online Indonesia", "cara dapat uang dari internet", "bisnis digital pemula"]),
    3: ("Motivasi & bisnis", ["podcast kisah pengusaha sukses Indonesia", "wawancara pengusaha muda", "motivasi bisnis jatuh bangun"]),
    4: ("Edukasi digital", ["tutorial AI dan otomasi", "podcast edukasi digital Indonesia", "cara kerja otomatis pakai AI"]),
    5: ("Tren viral", ["podcast viral Indonesia minggu ini", "topik ramai dibicarakan Indonesia", "wawancara viral Indonesia"]),
    6: ("Tren viral", ["podcast viral Indonesia minggu ini", "topik ramai dibicarakan Indonesia", "wawancara viral Indonesia"]),
}


def load_used() -> list:
    try:
        with open(USED_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def mark_used(vid: str):
    used = load_used()
    if vid not in used:
        used.append(vid)
        os.makedirs(os.path.dirname(USED_FILE), exist_ok=True)
        with open(USED_FILE, "w", encoding="utf-8") as f:
            json.dump(used[-500:], f)


def ai_queries(provider: str, niche: str, count: int, model: str | None):
    prompt = (
        f"Kamu analis konten media sosial Indonesia. Hari ini {dt.date.today():%A %d %B %Y}. Tema hari ini: {niche}.\\n"
        f"Usulkan {count} kata kunci pencarian YouTube (bahasa Indonesia) untuk VIDEO PANJANG (podcast, wawancara, "
        "edukasi) yang kemungkinan besar punya momen 30-60 detik yang bisa viral sebagai Shorts/Reels di Indonesia. "
        "Utamakan topik yang sedang ramai atau selalu laku (AI, penghasilan online, bisnis, edukasi praktis). "
        'Balas HANYA JSON: {"topics":[{"query":"...","alasan":"satu kalimat"}]}'
    ).replace("\\n", "\n")
    key = A.load_api_key(provider)
    model = model or A.PROVIDERS[provider]["model"]
    data = A.parse_json(A.call_ai(prompt, key, model, provider, max_tokens=2000))
    out = [t for t in data.get("topics", []) if isinstance(t, dict) and str(t.get("query", "")).strip()]
    return [{"query": str(t["query"]).strip(), "alasan": str(t.get("alasan", "")).strip()} for t in out][:count]


def get_topics(provider: str, niche: str, count: int, model: str | None, weekday_queries: list[str]):
    """Kembalikan (daftar topik, keterangan sumber). Jatuh ke kata kunci bawaan bila AI tidak tersedia."""
    if provider != "lokal":
        try:
            topics = ai_queries(provider, niche, count, model)
            if topics:
                return topics, f"AI ({provider}), dari pengetahuan model"
        except (SystemExit, RuntimeError, ValueError) as exc:
            print(f"AI riset tidak tersedia ({exc}); pakai kata kunci bawaan.", file=sys.stderr)
    return [{"query": q, "alasan": f"tema harian: {niche}"} for q in weekday_queries[:count]], "kata kunci bawaan tema harian"


def search_youtube(query: str, n: int = 10) -> list[dict]:
    try:
        res = subprocess.run(["yt-dlp", "--flat-playlist", "-J", "--no-warnings", f"ytsearch{n}:{query}"],
                             capture_output=True, text=True, timeout=120)
        entries = json.loads(res.stdout).get("entries", []) if res.stdout.strip() else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return []
    out = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        out.append({"id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                    "views": e.get("view_count") or 0, "duration": e.get("duration") or 0,
                    "url": e.get("webpage_url") or f"https://www.youtube.com/watch?v={e['id']}"})
    return out


def rank(cands: list[dict], min_views: int, min_min: int, max_min: int, used: list) -> list[dict]:
    seen, out = set(), []
    for c in cands:
        if c["id"] in seen or c["id"] in used:
            continue
        seen.add(c["id"])
        minutes = c["duration"] / 60
        if not (min_min <= minutes <= max_min) or c["views"] < min_views:
            continue
        bonus = 0.3 if re.search(r"podcast|wawancara|ngobrol|interview", c["title"], re.I) else 0
        c["skor"] = round(math.log10(c["views"] + 1) + bonus, 2)
        out.append(c)
    return sorted(out, key=lambda c: -c["skor"])


def find_sources(provider="lokal", niche=None, model=None, topics=4, per_query=10, min_views=20000,
                 min_min=8, max_min=120, queries_override=None):
    theme, fallback = WEEK[dt.date.today().weekday()]
    niche = niche or theme
    if queries_override:
        tops, how = [{"query": q, "alasan": "kata kunci dari kamu"} for q in queries_override], "dari kamu"
    else:
        tops, how = get_topics(provider, niche, topics, model, fallback)
    cands = []
    for t in tops:
        found = search_youtube(t["query"], per_query)
        for c in found:
            c["query"] = t["query"]
        cands += found
    return niche, how, tops, rank(cands, min_views, min_min, max_min, load_used())


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="clip riset", description="Cari video sumber untuk dijadikan klip viral.")
    p.add_argument("--niche", help="Tema (default: tema hari ini dari rencana mingguan)")
    p.add_argument("-q", "--query", action="append", help="Kata kunci sendiri (boleh berkali-kali); melewati AI")
    p.add_argument("-k", "--top", type=int, default=8, help="Jumlah kandidat ditampilkan (default 8)")
    p.add_argument("--ai", dest="provider", choices=["lokal"] + list(A.PROVIDERS), default=A.DEFAULT_PROVIDER)
    p.add_argument("--model")
    p.add_argument("--min-views", type=int, default=20000, help="Penayangan minimal (default 20000)")
    p.add_argument("--min-menit", type=int, default=8)
    p.add_argument("--max-menit", type=int, default=120)
    p.add_argument("--out", help="Simpan hasil ke file JSON ini")
    args = p.parse_args(argv)

    niche, how, tops, ranked = find_sources(args.provider, args.niche, args.model, min_views=args.min_views,
                                            min_min=args.min_menit, max_min=args.max_menit, queries_override=args.query)
    print(f"Tema: {niche}  |  Kata kunci: {how}")
    for t in tops:
        print(f"  - {t['query']}" + (f"  ({t['alasan']})" if t["alasan"] else ""))
    if not ranked:
        print("\nTidak ada video yang memenuhi syarat. Turunkan --min-views atau coba kata kunci lain (-q).")
        return 1
    print(f"\nKandidat video sumber (urut penayangan):")
    for i, c in enumerate(ranked[:args.top], 1):
        print(f"{i}. {c['title'][:70]}\n   {c['channel']} | {c['views']:,} tayang | {c['duration'] // 60} menit\n   {c['url']}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"tema": niche, "kata_kunci": tops, "kandidat": ranked[:args.top]}, f, ensure_ascii=False, indent=2)
    print("\nBuat klip: clip ai \"LINK\" -n 3   |  otomatis: clip harian")
    print("Pastikan kamu boleh memakai ulang videonya dan cantumkan kredit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
