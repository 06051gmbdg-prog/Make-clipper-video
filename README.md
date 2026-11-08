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

### Beberapa bagian

```bash
# Rentang 1:00-5:00 dipecah otomatis jadi bagian @ 60 detik
python clipper.py "https://youtu.be/XXXX" -s 1:00 -e 5:00 --part-length 60 -o seri.mp4

# Beberapa rentang bebas (dipisah koma)
python clipper.py "https://youtu.be/XXXX" --segments "0:10-0:40,2:00-2:45,5:10-5:50" -o highlight.mp4
```

Hasilnya `seri_part1.mp4`, `seri_part2.mp4`, dan seterusnya. Video hanya diunduh sekali untuk semua bagian. Tidak butuh API key.

| Opsi | Fungsi |
|---|---|
| `-s`, `--start` | Waktu mulai |
| `-e`, `--end` | Waktu selesai |
| `--part-length` | Pecah rentang start-end jadi bagian berdurasi sekian detik |
| `--segments` | Beberapa rentang bebas, `MULAI-SELESAI,MULAI-SELESAI` |
| `-o`, `--output` | Nama file hasil (default `clip.mp4`) |
| `--vertical` | Crop tengah ke 9:16 (1080x1920) |
| `--watermark` | Teks watermark di bagian bawah |

## Catatan

Gunakan hanya untuk video milikmu sendiri atau yang kamu punya izin untuk memotongnya.
