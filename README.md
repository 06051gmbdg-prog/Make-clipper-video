# Make-clipper-video

Potong video YouTube berdasarkan waktu mulai dan selesai, dengan opsi rasio 9:16 dan watermark teks.

## Kebutuhan

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp): `pip install yt-dlp`
- [ffmpeg](https://ffmpeg.org/download.html) (harus ada di PATH)

## Cara pakai

```bash
# Potong menit 1:30 sampai 2:15
python clipper.py "https://youtu.be/XXXX" --start 1:30 --end 2:15

# Jadi video vertikal 9:16 + watermark, simpan sebagai short.mp4
python clipper.py "https://youtu.be/XXXX" -s 90 -e 135 --vertical --watermark "@namakamu" -o short.mp4
```

Format waktu: `SS`, `MM:SS`, atau `HH:MM:SS`.

| Opsi | Fungsi |
|---|---|
| `-s`, `--start` | Waktu mulai |
| `-e`, `--end` | Waktu selesai |
| `-o`, `--output` | Nama file hasil (default `clip.mp4`) |
| `--vertical` | Crop tengah ke 9:16 (1080x1920) |
| `--watermark` | Teks watermark di bagian bawah |

## Catatan

Gunakan hanya untuk video milikmu sendiri atau yang kamu punya izin untuk memotongnya.
