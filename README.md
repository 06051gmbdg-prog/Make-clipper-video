# Make-clipper-video

Potong video YouTube berdasarkan waktu mulai dan selesai. Hasil default **rasio 9:16** (Shorts/Reels/TikTok), bisa dipecah jadi beberapa bagian, dan bisa diberi **subtitel otomatis**.

## Kebutuhan

- Python 3.10+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp): `pip install yt-dlp`
- [ffmpeg](https://ffmpeg.org/download.html) (harus ada di PATH; untuk subtitel perlu dukungan libass)

## Cara pakai

```bash
# Potong menit 1:30 sampai 2:15
python clipper.py "https://youtu.be/XXXX" --start 1:30 --end 2:15

# 9:16 (bawaan) + subtitel + watermark, simpan sebagai short.mp4
python clipper.py "https://youtu.be/XXXX" -s 90 -e 135 --subtitle --watermark "@namakamu" -o short.mp4

# Tetap rasio asli (tanpa crop 9:16)
python clipper.py "https://youtu.be/XXXX" -s 90 -e 135 --no-vertical
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
| `--vertical` / `--no-vertical` | Crop tengah ke 9:16 (1080x1920). Aktif secara bawaan |
| `--subtitle` | Tempel subtitel otomatis dari caption YouTube |
| `--sub-lang` | Bahasa caption (default `id`, contoh `en`) |
| `--watermark` | Teks watermark di bagian bawah |
| `--upload` | Unggah hasil ke Google Drive lewat rclone, contoh `gdrive:Clipper` |

## Aplikasi (app.html)

`app.html` adalah aplikasi web untuk HP: isi form, salin perintahnya, lalu tempel di Termux. Ada juga pencatat jadwal posting dan panduan pemasangan.

- **Buat**: link YouTube, mode (satu klip, pecah otomatis, pilih sendiri), 9:16, subtitel, watermark, pratinjau, lalu perintah siap salin.
- **Jadwal**: catatan caption, hashtag, platform, dan waktu posting. Tersimpan di HP.
- **Panduan**: langkah pemasangan Termux dengan tombol salin dan daftar centang.

Cara memasang di layar utama HP: buka `app.html` lewat alamat https (misalnya GitHub Pages: Settings, Pages, branch `main`), lalu di Chrome pilih **Pasang aplikasi** atau menu titik tiga, **Tambahkan ke layar utama**. Setelah itu bisa dibuka tanpa internet.

Aplikasi ini hanya menyusun perintah. Pemotongan videonya tetap dijalankan `clipper.py` di Termux.

## Simpan otomatis ke Google Drive

Tambahkan `--upload` dan hasil klip diunggah ke Drive setelah selesai (file di HP tetap ada). Memakai [rclone](https://rclone.org), gratis dan tanpa API key.

**Setup sekali di Termux:**

```bash
pkg install -y rclone
rclone config
```

1. Ketik `n` (new remote), beri nama `gdrive`.
2. Pilih **Google Drive** dari daftar. Kosongkan client id dan secret.
3. Scope: pilih `1` (akses penuh) atau `3` (hanya file yang dibuat rclone, lebih aman).
4. Enter sampai ditanya *Use web browser to automatically authenticate?*, jawab `y`.
5. Buka link yang muncul di Chrome HP, masuk ke akun Google, dan izinkan. Kembali ke Termux.

**Pemakaian:**

```bash
python clipper.py "https://youtu.be/XXXX" -s 1:30 -e 2:15 --subtitle --upload gdrive:Clipper
```

`gdrive:Clipper` artinya remote `gdrive`, folder `Clipper` (dibuat otomatis kalau belum ada). Kalau unggah gagal (sinyal putus, belum login), klip tetap ada di HP dan bisa diunggah ulang:

```bash
rclone copy ~/storage/downloads/clip.mp4 gdrive:Clipper
```

Di `app.html`, aktifkan saklar **Simpan ke Google Drive** dan perintahnya otomatis memuat `--upload`.

## Subtitel otomatis

`--subtitle` memakai caption yang sudah ada di YouTube (buatan pemilik video atau otomatis), jadi **tidak butuh API key**.
Teks dipecah jadi baris pendek (maks. 5 kata) di bagian bawah layar, putih dengan garis hitam.

- Video harus punya caption. Kalau tidak ada, klip tetap dibuat tanpa subtitel dan muncul peringatan.
- `--sub-lang id` bisa menampilkan terjemahan otomatis YouTube untuk video berbahasa lain.
- Kalau teks tidak muncul di Termux, kemungkinan ffmpeg-nya tanpa libass atau font belum tersedia.

## Catatan

Gunakan hanya untuk video milikmu sendiri atau yang kamu punya izin untuk memotongnya.
