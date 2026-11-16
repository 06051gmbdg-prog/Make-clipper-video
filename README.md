# Make-clipper-video

Potong video YouTube jadi klip **9:16** (Shorts/Reels/TikTok): satu klip atau beberapa bagian, dengan **subtitel otomatis**, gaya teks beranimasi (**motion text**), watermark, dan unggah otomatis ke Google Drive. Tanpa API key.

## Pasang

Disarankan di HP Android lewat [Termux](https://f-droid.org/packages/com.termux/) (pasang dari F-Droid, bukan Play Store).

```bash
# Unduh repo (pilih salah satu)
git clone https://github.com/06051gmbdg-prog/Make-clipper-video
gh repo clone 06051gmbdg-prog/Make-clipper-video      # kalau GitHub CLI sudah terpasang (pkg install gh)

# Pasang semua kebutuhan dan buat perintah `clip`
cd Make-clipper-video
sh install.sh
```

`install.sh` memasang python, ffmpeg, git, rclone, dan yt-dlp, meminta izin penyimpanan, lalu membuat perintah **`clip`**. Di komputer biasa, pasang manual: Python 3.10+, [yt-dlp](https://github.com/yt-dlp/yt-dlp), dan [ffmpeg](https://ffmpeg.org/download.html) (dengan libass untuk subtitel).

Perbarui kapan saja dengan `clip update`.

## Cara tercepat: ketik `clip`

```bash
clip
```

Program menanyakan satu per satu: link, mode potong, waktu, rasio 9:16, subtitel dan gaya teks, watermark, unggah ke Drive, dan nama file. Hasil disimpan di folder Download HP.

## Pakai dengan perintah

```bash
# Potong menit 1:30 sampai 2:15
clip "https://youtu.be/XXXX" -s 1:30 -e 2:15

# 9:16 (bawaan) + subtitel + watermark
clip "https://youtu.be/XXXX" -s 90 -e 135 --subtitle --watermark "@namakamu" -o short.mp4

# Tetap rasio asli (tanpa crop 9:16)
clip "https://youtu.be/XXXX" -s 90 -e 135 --no-vertical
```

`clip` sama dengan `python clipper.py`. Format waktu: `SS`, `MM:SS`, atau `HH:MM:SS`.

### Beberapa bagian

```bash
# Rentang 1:00-5:00 dipecah otomatis jadi bagian @ 60 detik
clip "https://youtu.be/XXXX" -s 1:00 -e 5:00 --part-length 60 -o seri.mp4

# Beberapa rentang bebas (dipisah koma)
clip "https://youtu.be/XXXX" --segments "0:10-0:40,2:00-2:45,5:10-5:50" -o highlight.mp4
```

Hasilnya `seri_part1.mp4`, `seri_part2.mp4`, dan seterusnya. Video hanya diunduh sekali untuk semua bagian.

| Opsi | Fungsi |
|---|---|
| `-s`, `--start` | Waktu mulai |
| `-e`, `--end` | Waktu selesai |
| `--part-length` | Pecah rentang start-end jadi bagian berdurasi sekian detik |
| `--segments` | Beberapa rentang bebas, `MULAI-SELESAI,MULAI-SELESAI` |
| `-o`, `--output` | Nama file hasil (default `clip.mp4`) |
| `--vertical` / `--no-vertical` | Crop tengah ke 9:16 (1080x1920). Aktif secara bawaan |
| `--subtitle` | Tempel subtitel otomatis dari caption YouTube |
| `--sub-style` | Gaya teks: `klasik`, `pop`, atau `kata` (lihat di bawah) |
| `--sub-lang` | Bahasa caption (default `id`, contoh `en`) |
| `--watermark` | Teks watermark di bagian bawah |
| `--upload` | Unggah hasil ke Google Drive lewat rclone, contoh `gdrive:Clipper` |

## Gaya teks (motion text)

Dipakai bersama `--subtitle`. Pilih dengan `--sub-style`:

| Gaya | Tampilan |
|---|---|
| `klasik` (bawaan) | Satu baris statis, putih dengan garis hitam. |
| `pop` | Satu baris huruf besar; **kata yang sedang diucapkan menyala kuning** dan berpindah mengikuti suara. |
| `kata` | **Satu kata besar** di tengah layar, muncul dengan efek zoom-in, ganti kata demi kata. |

```bash
clip "https://youtu.be/XXXX" -s 1:30 -e 2:15 --subtitle --sub-style pop
clip "https://youtu.be/XXXX" -s 1:30 -e 2:15 --subtitle --sub-style kata
```

Di `clip` mode tanya-jawab dan di `app.html`, gaya ini tinggal dipilih. Waktu animasi mengikuti waktu kata dari caption YouTube, jadi ketepatannya sama dengan caption aslinya.

## Subtitel otomatis

`--subtitle` memakai caption yang sudah ada di YouTube (buatan pemilik video atau otomatis).

- Video harus punya caption. Kalau tidak ada, klip tetap dibuat tanpa subtitel dan muncul peringatan.
- `--sub-lang id` bisa menampilkan terjemahan otomatis YouTube untuk video berbahasa lain.
- Teks dipecah jadi baris pendek (maks. 5 kata) dan diletakkan agak ke atas supaya tidak tertutup tombol aplikasi.
- Kalau teks tidak muncul di Termux, kemungkinan ffmpeg-nya tanpa libass atau font belum tersedia.

## Simpan otomatis ke Google Drive

Tambahkan `--upload` dan hasil klip diunggah ke Drive setelah selesai (file di HP tetap ada). Memakai [rclone](https://rclone.org), gratis.

**Sambungkan sekali di Termux** (satu perintah, tanpa pertanyaan):

```bash
rclone config create gdrive drive scope=drive.file
```

Buka link yang muncul di Chrome HP, masuk ke akun Google, lalu izinkan. Scope `drive.file` hanya memberi akses ke file buatan rclone, jadi isi Drive lainnya tidak tersentuh. Tes dengan `rclone lsd gdrive:`.

> Kalau mau mengunggah ke **folder yang kamu buat sendiri** di Drive (lihat bagian link folder di bawah), pakai akses penuh: `rclone config create gdrive drive scope=drive`.

**Pemakaian:**

```bash
clip "https://youtu.be/XXXX" -s 1:30 -e 2:15 --subtitle --upload gdrive:Clipper
```

`gdrive:Clipper` artinya remote `gdrive`, folder `Clipper` (dibuat otomatis kalau belum ada). Kalau unggah gagal (sinyal putus, belum login), klip tetap ada di HP dan bisa diunggah ulang:

```bash
rclone copy ~/storage/downloads/clip.mp4 gdrive:Clipper
```

**Unggah ke folder Drive yang sudah ada:** tempel link foldernya langsung.

```bash
clip "https://youtu.be/XXXX" -s 1:30 -e 2:15 --upload "https://drive.google.com/drive/folders/ID_FOLDER"
```

Ini hanya bisa kalau rclone login dengan `scope=drive` (akses penuh). Dengan `drive.file`, rclone tidak bisa melihat folder buatan sendiri dan unggahan gagal; script akan menampilkan petunjuknya.

Saat memakai `clip` mode tanya-jawab, pertanyaan unggah ke Drive muncul otomatis kalau rclone sudah tersambung.

## ABIDIN AI CLIPPER: AI memilih momen terbaik (`clip ai`)

Tempel satu link video panjang, lalu momen terbaik dipilih otomatis (bawaan: **tanpa API key**, atau pakai AI Gemini/Claude), lalu klip 9:16 + subtitel + watermark dibuat otomatis. Cocok untuk alur semi-otomatis: hasil kamu tinjau dulu sebelum diposting.

```bash
clip ai "https://youtu.be/XXXX" -n 5 --watermark "ABIDIN AI" --upload gdrive:Clipper
```

Yang dilakukan:

1. Mengambil caption video (butuh caption, `--sub-lang id`, cadangan `en`).
2. AI memberi skor tiap kandidat: hook 25%, edukasi 20%, viral 20%, emosi 15%, kejelasan 10%, relevansi audiens 10%.
3. Menampilkan rencana klip (judul, waktu, skor) dan meminta konfirmasi.
4. Memotong 30-60 detik per klip, 9:16 1080x1920, subtitel gaya `pop`, watermark.
5. Menyimpan `NN_judul.mp4`, `plan.json`, dan `jadwal.txt` (judul, caption, hashtag, link sumber + timestamp, skor). Unggah ke Drive kalau `--upload` diisi.

**Tanpa API key (bawaan):** program memilih momen dengan aturan sederhana, yaitu kata kunci hook/edukasi/emosi dan kepadatan bicara. Hasilnya kurang pintar daripada AI, jadi cek `plan.json` atau daftar yang muncul sebelum membuat klip. Mau AI? Pakai `--ai gemini` atau `--ai claude`.

**API key AI (opsional).** `--ai gemini` memakai **Gemini**, yang punya kuota gratis. Buat key di [aistudio.google.com/apikey](https://aistudio.google.com/apikey), lalu jalankan `clip ai ...`, tempel saat diminta, dan jawab `y` untuk menyimpan di `~/.config/clipper/gemini_key` (hanya bisa dibaca kamu). Atau isi `export GEMINI_API_KEY=...`. Mau pakai Claude (berbayar per pemakaian)? Tambahkan `--ai claude` dan siapkan `ANTHROPIC_API_KEY`. Jangan kirim key ke chat atau commit ke repo.

| Opsi | Fungsi |
|---|---|
| `-n`, `--clips` | Jumlah klip (default 5) |
| `--min-len`, `--max-len` | Durasi klip dalam detik (default 30 dan 60) |
| `--topic` | Fokus topik untuk penilaian relevansi |
| `--ai` | `lokal` (bawaan, tanpa key), `gemini` (model `gemini-3.8-flash`), atau `claude` |
| `--model` | Nama model lain untuk penyedia yang dipilih |
| `--sub-style`, `--no-subtitle` | Gaya subtitel atau matikan |
| `--watermark`, `--upload` | Seperti perintah biasa |
| `--out` | Folder hasil (default `~/storage/downloads/ABIDIN_AI/ID_VIDEO`) |
| `--yes` | Lewati konfirmasi |
| `--plan-only` | Hanya buat `plan.json`, belum memotong |
| `--from-plan` | Potong dari `plan.json` yang sudah kamu edit |

Alur tinjau dulu: `--plan-only`, ubah `plan.json` kalau perlu, lalu `--from-plan plan.json`.

Belum termasuk: pencarian video otomatis (YouTube Data API), Whisper, auto reframing wajah, musik, posting ke Buffer, Notion, dan analitik. Jadwalkan `jadwal.txt` ke Buffer secara manual.

Pakai hanya video milikmu atau yang boleh dipakai ulang, dan cantumkan kredit sumber (link ada di `jadwal.txt`).

## Aplikasi (app.html)

`app.html` adalah aplikasi web untuk HP: isi form, salin perintahnya, lalu tempel di Termux. Ada juga pencatat jadwal posting dan panduan pemasangan.

- **Buat**: link YouTube, mode (satu klip, pecah otomatis, pilih sendiri), 9:16, subtitel dan gaya teks, watermark, Drive, pratinjau, lalu perintah siap salin.
- **Jadwal**: catatan caption, hashtag, platform, dan waktu posting. Tersimpan di HP.
- **Panduan**: langkah pemasangan Termux dengan tombol salin dan daftar centang.

Cara memasang di layar utama HP: buka `app.html` lewat alamat https (misalnya GitHub Pages: Settings, Pages, branch `main`), lalu di Chrome pilih **Pasang aplikasi** atau menu titik tiga, **Tambahkan ke layar utama**. Setelah itu bisa dibuka tanpa internet.

Aplikasi ini hanya menyusun perintah. Pemotongan videonya dijalankan `clipper.py` di Termux.

## Catatan

Gunakan hanya untuk video milikmu sendiri atau yang kamu punya izin untuk memotongnya.
