#!/usr/bin/env sh
# Pasang semua kebutuhan Clipper Video di Termux, lalu buat perintah `clip`.
# Pemakaian:  cd ~/Make-clipper-video && sh install.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

if command -v pkg >/dev/null 2>&1; then
  echo "==> Memasang python, ffmpeg, git, rclone..."
  pkg update -y
  pkg install -y python ffmpeg git rclone
  echo "==> Izin penyimpanan (ketuk Izinkan bila diminta)..."
  termux-setup-storage || true
else
  echo "(Bukan Termux: lewati pkg. Pastikan python, ffmpeg, dan rclone sudah terpasang.)"
fi

echo "==> Memasang yt-dlp..."
python -m pip install -U yt-dlp || echo "PERINGATAN: yt-dlp gagal dipasang. Coba lagi: pip install yt-dlp"

BIN="${PREFIX:-$HOME/.local}/bin"
mkdir -p "$BIN"
cat > "$BIN/clip" <<WRAP
#!/usr/bin/env sh
if [ "\$1" = "update" ]; then
  git -C "$DIR" pull && python -m pip install -U yt-dlp
  exit \$?
fi
exec python "$DIR/clipper.py" "\$@"
WRAP
chmod +x "$BIN/clip"

echo
echo "Selesai! Ketik:  clip        (mode tanya-jawab)"
echo "Perbarui nanti:  clip update"
echo "Google Drive:    rclone config create gdrive drive scope=drive.file"
