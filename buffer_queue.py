"""Jadwalkan klip hasil `clip ai` ke Buffer, 3 kali sehari.

Alur: klip diunggah ke Google Drive (rclone) lalu dibuat link publik, setelah itu dibuat posting
terjadwal di Buffer untuk tiap channel (Instagram Reels, Facebook Reels, YouTube Shorts).
Buffer perlu API key: Buffer > Settings > API. Simpan di BUFFER_API_KEY atau ~/.config/clipper/buffer_key.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

API_URL = os.environ.get("BUFFER_API_URL", "https://api.buffer.com")
CONFIG_DIR = os.path.expanduser("~/.config/clipper")
KEY_FILE = os.path.join(CONFIG_DIR, "buffer_key")
STATE_FILE = os.path.join(CONFIG_DIR, "buffer_state.json")
TZ = dt.timezone(dt.timedelta(hours=7))  # WIB (Asia/Jakarta, tanpa DST)

# ID channel Buffer milik akun ini (lihat Buffer > channel). Ganti lewat --channel-id nama=ID.
CHANNELS = {
    "instagram": "6afccbd5ece6dfde5ffef86d",
    "facebook": "6b001158ece6dfde5f2f48ff",
    "youtube": "6ae4d8412f1f5ed6482370f4",
}


def gql(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def clean_key(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "", re.sub(r"\x1b\[[0-9;?]*[A-Za-z~]", "", raw))


def load_key() -> str:
    key = clean_key(os.environ.get("BUFFER_API_KEY", ""))
    if not key and os.path.exists(KEY_FILE):
        key = clean_key(open(KEY_FILE, encoding="utf-8").read())
    return key


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def parse_slots(text: str) -> list[dt.time]:
    out = []
    for part in text.split(","):
        h, m = part.strip().split(":")
        out.append(dt.time(int(h), int(m)))
    return sorted(out)


def next_slots(count: int, slots: list[dt.time], after: dt.datetime) -> list[dt.datetime]:
    """`count` waktu posting berurutan (WIB) setelah `after`, mengikuti jam harian `slots`."""
    result, day = [], after.date()
    while len(result) < count:
        for t in slots:
            due = dt.datetime.combine(day, t, tzinfo=TZ)
            if due > after:
                result.append(due)
                if len(result) == count:
                    break
        day += dt.timedelta(days=1)
    return result


def source_link(url: str, vid: str | None, start) -> str:
    return f"https://youtu.be/{vid}?t={int(float(start))}" if vid else url


def caption_for(clip: dict, service: str, link: str, credit: bool) -> str:
    parts = [clip["caption"].strip()]
    if credit:
        parts.append(f"Sumber: {link}")
    tags = " ".join(clip.get("hashtags", []))
    if service == "youtube" and "#shorts" not in tags.lower():
        tags = (tags + " #Shorts").strip()
    parts.append(tags)
    text = "\n\n".join(p for p in parts if p)
    return text[:2100] if service == "instagram" else text[:4900]


def metadata_for(service: str, clip: dict) -> str:
    if service == "instagram":
        return "{ instagram: { type: reel, shouldShareToFeed: true } }"
    if service == "facebook":
        return "{ facebook: { type: reel } }"
    return f'{{ youtube: {{ title: {gql(clip["title"][:95])}, categoryId: "27" }} }}'


def build_mutation(text: str, channel_id: str, due: str, video_url: str, meta: str) -> str:
    return (
        "mutation { createPost(input: { "
        f"text: {gql(text)}, channelId: {gql(channel_id)}, schedulingType: automatic, "
        f"mode: customScheduled, dueAt: {gql(due)}, "
        f"assets: [{{ video: {{ url: {gql(video_url)} }} }}], metadata: {meta} "
        "}) { ... on PostActionSuccess { post { id } } ... on MutationError { message } } }"
    )


def call_buffer(query: str, key: str):
    """Kembalikan (id_posting, None) bila sukses, atau (None, pesan_error)."""
    req = urllib.request.Request(
        API_URL, data=json.dumps({"query": query}).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}", "content-type": "application/json",
                 "user-agent": "abidin-ai-clipper/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        hint = " (API key salah?)" if exc.code in (401, 403) else ""
        return None, f"HTTP {exc.code}{hint} {body}".strip()
    except (urllib.error.URLError, TimeoutError) as exc:
        return None, f"tidak bisa menghubungi Buffer: {exc}"
    if data.get("errors"):
        return None, "; ".join(e.get("message", str(e)) for e in data["errors"])[:300]
    res = (data.get("data") or {}).get("createPost") or {}
    if res.get("post"):
        return res["post"].get("id", "?"), None
    return None, res.get("message", "balasan tidak dikenal")


def drive_public_url(path: str, target: str):
    """Unggah ke Drive dan kembalikan link unduh langsung yang bisa dibaca Buffer."""
    name = os.path.basename(path)
    dest = target.rstrip("/") + "/" + name
    subprocess.run(["rclone", "copyto", path, dest], check=True)
    link = subprocess.run(["rclone", "link", dest], check=True, capture_output=True, text=True).stdout.strip()
    m = re.search(r"(?:[?&]id=|/d/)([\w-]{20,})", link)
    if not m:
        raise RuntimeError(f"link Drive tidak dikenali: {link}")
    return f"https://drive.google.com/uc?export=download&id={m.group(1)}"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="clip post", description="Jadwalkan klip ke Buffer (3x sehari).")
    p.add_argument("folder", help="Folder hasil `clip ai` (berisi plan.json dan file mp4)")
    p.add_argument("--drive", default="gdrive:Clipper/Buffer", help="Folder Drive tempat video diunggah (default gdrive:Clipper/Buffer)")
    p.add_argument("--channels", default="instagram,facebook,youtube", help="Channel tujuan, dipisah koma")
    p.add_argument("--channel-id", action="append", default=[], metavar="NAMA=ID", help="Timpa ID channel Buffer")
    p.add_argument("--slots", default="08:00,12:00,19:00", help="Jam posting harian WIB (default 08:00,12:00,19:00)")
    p.add_argument("--start-date", help="Mulai dari tanggal ini (YYYY-MM-DD), default: slot kosong berikutnya")
    p.add_argument("--no-credit", action="store_true", help="Jangan tulis link sumber di caption")
    p.add_argument("--yes", action="store_true", help="Lewati konfirmasi")
    p.add_argument("--dry-run", action="store_true", help="Tampilkan jadwal saja, tidak mengunggah/membuat posting")
    args = p.parse_args(argv)

    channels = dict(CHANNELS)
    for item in args.channel_id:
        name, _, cid = item.partition("=")
        channels[name.strip()] = cid.strip()
    wanted = [c.strip() for c in args.channels.split(",") if c.strip()]
    unknown = [c for c in wanted if c not in channels]
    if unknown:
        sys.exit(f"Channel tidak dikenal: {', '.join(unknown)}. Pilihan: {', '.join(channels)}")

    plan_path = os.path.join(args.folder, "plan.json")
    try:
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
    except (OSError, ValueError) as exc:
        sys.exit(f"Tidak bisa membaca {plan_path}: {exc}")
    qpath = os.path.join(args.folder, "queue_state.json")
    try:
        with open(qpath, encoding="utf-8") as f:
            queued = json.load(f)
    except (OSError, ValueError):
        queued = {}

    clips = [c for c in plan.get("clips", []) if c.get("file") and os.path.exists(c["file"])]
    todo = [c for c in clips if len(queued.get(os.path.basename(c["file"]), {}).get("done", [])) < len(wanted)]
    if not todo:
        print("Tidak ada klip baru untuk dijadwalkan.")
        return 0

    key = load_key()
    if not key and not args.dry_run:
        sys.exit("API key Buffer belum diatur. Buat di Buffer > Settings > API, lalu:\n"
                 '  export BUFFER_API_KEY="..."\n(atau simpan di ~/.config/clipper/buffer_key)')

    state = load_state()
    now = dt.datetime.now(TZ) + dt.timedelta(minutes=20)
    after = now
    if state.get("last_due"):
        after = max(after, dt.datetime.fromisoformat(state["last_due"]))
    if args.start_date:
        after = max(after, dt.datetime.combine(dt.date.fromisoformat(args.start_date), dt.time(0, 0), tzinfo=TZ))
    slots = parse_slots(args.slots)
    fresh = [c for c in todo if os.path.basename(c["file"]) not in queued]
    due_times = next_slots(len(fresh), slots, after)
    due_by_file = {os.path.basename(c["file"]): d for c, d in zip(fresh, due_times)}
    for c in todo:  # klip yang sebagian channel-nya sudah jadi tetap memakai jadwal lamanya
        b = os.path.basename(c["file"])
        if b in queued:
            due_by_file[b] = dt.datetime.fromisoformat(queued[b]["due"])

    print("Jadwal posting (WIB):")
    for c in todo:
        d = due_by_file[os.path.basename(c["file"])]
        print(f"  {d:%a %d %b %H:%M}  {c['title'][:60]}  -> {', '.join(wanted)}")
    print("\nCatatan: paket Buffer gratis membatasi 10 posting terjadwal per channel.")
    if args.dry_run:
        print("(dry-run: tidak ada yang dikirim)")
        return 0
    if not args.yes:
        if input("\nJadwalkan ke Buffer? (Y/n): ").strip().lower() in ("n", "no", "t", "tidak"):
            print("Dibatalkan.")
            return 0

    vid, url = plan.get("video_id"), plan.get("url", "")
    ok_count = fail_count = 0
    for c in todo:
        base = os.path.basename(c["file"])
        due = due_by_file[base]
        rec = queued.setdefault(base, {"due": due.isoformat(), "done": []})
        print(f"\n=== {c['title'][:60]} ({due:%d %b %H:%M}) ===")
        try:
            video_url = drive_public_url(c["file"], args.drive)
        except (subprocess.CalledProcessError, RuntimeError, OSError) as exc:
            print(f"  Gagal mengunggah ke Drive: {exc}")
            fail_count += len(wanted) - len(rec["done"])
            continue
        due_utc = due.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        link = source_link(url, vid, c.get("start", 0))
        for name in wanted:
            if name in rec["done"]:
                continue
            q = build_mutation(caption_for(c, name, link, not args.no_credit), channels[name], due_utc,
                               video_url, metadata_for(name, c))
            post_id, err = call_buffer(q, key)
            if err:
                print(f"  {name}: GAGAL - {err}")
                fail_count += 1
            else:
                print(f"  {name}: terjadwal (id {post_id})")
                rec["done"].append(name)
                ok_count += 1
        with open(qpath, "w", encoding="utf-8") as f:
            json.dump(queued, f, indent=2)
        if rec["done"]:
            last = max(dt.datetime.fromisoformat(state["last_due"]) if state.get("last_due") else due, due)
            state["last_due"] = last.isoformat()
            save_state(state)
    print(f"\nSelesai: {ok_count} posting terjadwal, {fail_count} gagal.")
    return 0 if ok_count or not fail_count else 1


if __name__ == "__main__":
    sys.exit(main())
