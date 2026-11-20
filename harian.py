"""Alur harian otomatis: riset video sumber, AI memilih momen, klip dibuat, lalu dijadwalkan ke Buffer.

Contoh (cocok dijalankan terjadwal tiap malam): clip harian --yes
"""
import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto as A  # noqa: E402
import buffer_queue as BQ  # noqa: E402
import riset as R  # noqa: E402


def base_dir() -> str:
    dl = os.path.expanduser("~/storage/downloads")
    return os.path.join(dl if os.path.isdir(dl) else ".", "ABIDIN_AI", "harian")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="clip harian", description="Riset -> klip -> jadwal Buffer, sekali jalan.")
    p.add_argument("--sumber", type=int, default=1, help="Jumlah video sumber per hari (default 1)")
    p.add_argument("-n", "--clips", type=int, default=3, help="Klip per video sumber (default 3 = 3 posting per hari)")
    p.add_argument("--ai", dest="provider", choices=["lokal"] + list(A.PROVIDERS), default=A.DEFAULT_PROVIDER)
    p.add_argument("--model")
    p.add_argument("--min-len", type=float, default=30, help="Durasi klip minimal, detik")
    p.add_argument("--max-len", type=float, default=60, help="Durasi klip maksimal, detik")
    p.add_argument("--niche", help="Tema (default: tema hari ini)")
    p.add_argument("-q", "--query", action="append", help="Kata kunci sendiri; melewati riset AI")
    p.add_argument("--min-views", type=int, default=20000)
    p.add_argument("--no-post", action="store_true", help="Buat klip saja, jangan kirim ke Buffer")
    p.add_argument("--no-reframe", action="store_true")
    p.add_argument("--watermark")
    p.add_argument("--drive", default="gdrive:Clipper/Buffer")
    p.add_argument("--channels", default="instagram,facebook,youtube")
    p.add_argument("--slots", default="08:00,12:00,19:00")
    p.add_argument("--yes", action="store_true", help="Tanpa konfirmasi (untuk dijalankan terjadwal)")
    args = p.parse_args(argv)

    niche, how, _, ranked = R.find_sources(args.provider, args.niche, args.model, min_views=args.min_views,
                                           queries_override=args.query)
    print(f"Tema hari ini: {niche} ({how}). Kandidat sumber: {len(ranked)}")
    if not ranked:
        print("Tidak ada video sumber yang cocok. Coba --min-views lebih kecil atau -q kata kunci.")
        return 1

    done = 0
    for cand in ranked[:8]:
        if done >= args.sumber:
            break
        print(f"\n##### Sumber: {cand['title'][:70]}  ({cand['views']:,} tayang)\n      {cand['url']}")
        out = os.path.join(base_dir(), f"{dt.date.today():%Y%m%d}_{cand['id']}")
        ai_args = [cand["url"], "-n", str(args.clips), "--yes", "--ai", args.provider, "--out", out,
                   "--min-len", str(args.min_len), "--max-len", str(args.max_len)]
        if args.model:
            ai_args += ["--model", args.model]
        if args.no_reframe:
            ai_args.append("--no-reframe")
        if args.watermark:
            ai_args += ["--watermark", args.watermark]
        try:
            A.main(ai_args)
        except SystemExit as exc:   # misalnya video tanpa caption: coba kandidat berikutnya
            print(f"Dilewati: {exc.code if isinstance(exc.code, str) else 'gagal membuat klip'}")
            continue
        if not os.path.exists(os.path.join(out, "plan.json")):
            continue
        R.mark_used(cand["id"])
        done += 1
        if args.no_post:
            print(f"Klip siap di {out} (tanpa kirim ke Buffer).")
            continue
        post_args = [out, "--drive", args.drive, "--channels", args.channels, "--slots", args.slots]
        if args.yes:
            post_args.append("--yes")
        BQ.main(post_args)
    if not done:
        print("\nTidak ada video sumber yang berhasil diproses.")
        return 1
    print(f"\nSelesai: {done} video sumber diproses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
