# CCTV People Flow

Sistem realtime untuk mendeteksi orang dari RTSP, menjaga tracking ByteTrack,
menentukan ENTER/EXIT melalui virtual line, menyimpan snapshot dan event ke
PostgreSQL, serta menampilkan data melalui FastAPI dan dashboard React.

## Menjalankan dengan Docker

1. Salin konfigurasi contoh: `cp .env.example .env`.
2. Ubah minimal `POSTGRES_PASSWORD`, `JWT_SECRET`, dan `API_ADMIN_PASSWORD`.
3. Jalankan: `docker compose up --build`.

Image lokal memakai wheel PyTorch CPU agar Mac M1 tidak mengunduh library CUDA
yang tidak dapat dipakai. Untuk server NVIDIA, atur `TORCH_INDEX_URL` ke index
CUDA resmi yang sesuai dengan driver sebelum build.

Compose menunggu PostgreSQL sehat, menjalankan `alembic upgrade head`, lalu
menyalakan API dan dashboard. URL yang tersedia:

- API dan Swagger: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/v1/health`
- Dashboard: `http://localhost:5173`

Saat database masih kosong, API membuat akun awal dari `API_ADMIN_USERNAME` dan
`API_ADMIN_PASSWORD`. Akun ini memiliki role `SUPER_ADMIN`. Nilai password hanya
digunakan untuk bootstrap pertama; perubahan berikutnya disimpan sebagai hash
scrypt di PostgreSQL, bukan kembali ke `.env`.

## User Management dan RBAC

Menu **Administrasi** tersedia setelah login. Pembagian akses saat ini:

| Role | Monitoring & histori | Kelola kamera | Kelola pengguna | Backup & arsip |
| --- | --- | --- | --- | --- |
| `SUPER_ADMIN` | Ya | Ya | Ya | Ya |
| `ADMIN` | Ya | Ya | Tidak | Tidak |
| `SUPERVISOR` | Ya | Tidak | Tidak | Tidak |
| `OPERATOR` | Ya | Tidak | Tidak | Tidak |
| `AUDITOR` | Ya | Tidak | Tidak | Tidak |

Super admin dapat membuat pengguna, mengubah role/status, dan mereset password
pengguna lain. Password sementara minimal 12 karakter dan wajib diganti oleh
pengguna. Perubahan role, status, dan password menaikkan `token_version` sehingga
JWT lama langsung ditolak. Login gagal berulang dikunci sesuai
`LOGIN_MAX_FAILED_ATTEMPTS` dan `LOGIN_LOCK_MINUTES`.

Setiap perubahan pengguna atau kamera dicatat di tabel `audit_logs`. Tindakan
DELETE kamera bersifat aman: kamera dinonaktifkan dari runtime, sedangkan
tracking, event, dan snapshot historis tetap disimpan. Kamera dapat diaktifkan
kembali dari form **Ubah konfigurasi kamera**.

## Backup harian dan import arsip

Scheduler membuat backup observasional setiap hari pada `BACKUP_SCHEDULE_TIME`
menurut `BACKUP_TIMEZONE`. Default `00:15 Asia/Jakarta` berarti backup untuk
tanggal kemarin dibuat 15 menit setelah pergantian hari. File tersimpan pada
volume persisten:

```text
storage/backups/YYYY/MM/YYYYMMDD_<uuid>.zip
```

ZIP memuat `manifest.json`, dataset JSON Lines, snapshot JPEG, dan metadata
snapshot. Setiap member memiliki checksum SHA-256. File dibuat secara atomik;
job yang terputus akibat restart ditandai `FAILED` saat startup dan dapat dibuat
ulang secara manual. Backup otomatis yang lebih tua dari
`BACKUP_RETENTION_DAYS` dibersihkan, sedangkan arsip yang di-import tidak ikut
dihapus oleh retention.

Menu **Administrasi → Backup & arsip** hanya tersedia bagi `SUPER_ADMIN` dan
menyediakan:

- pembuatan backup manual untuk tanggal tertentu;
- unduh ZIP;
- import ZIP dengan pemeriksaan ukuran, path traversal, symbolic link,
  compression bomb, struktur manifest, dan checksum;
- penelusuran event, tracking, person, kamera, pengguna, audit log, serta
  preview snapshot langsung dari ZIP.

Import bersifat **baca-saja**: arsip masuk ke katalog terisolasi dan tidak
menimpa database operasional. URL RTSP, embedding ReID, hash password, dan data
pengamanan sesi sengaja tidak dimasukkan. Karena itu fitur ini tepat untuk
melihat kembali histori, tetapi belum menggantikan disaster-recovery database
penuh. Salin folder `storage/backups` ke media/server lain bila diperlukan;
backup yang hanya berada pada server yang sama tidak melindungi dari kegagalan
disk.

Konfigurasi terkait:

```dotenv
ENABLE_BACKUP_SCHEDULER=true
BACKUP_SCHEDULE_TIME=00:15
BACKUP_TIMEZONE=Asia/Jakarta
BACKUP_RETENTION_DAYS=30
BACKUP_INCLUDE_SNAPSHOTS=true
BACKUP_MAX_UPLOAD_MB=2048
BACKUP_MAX_MEMBERS=100000
BACKUP_MAX_EXPANSION_RATIO=100
```

JPEG umumnya sudah terkompresi, sehingga ZIP lebih banyak menghemat ruang pada
dataset JSON daripada pada snapshot. Kendali kapasitas utama tetap retention
dan kebijakan pemindahan arsip ke storage eksternal.

## Disaster Recovery penuh

Backup observasional di atas tetap dipertahankan untuk pencarian histori. Untuk
pemulihan server tersedia paket DR terpisah yang berisi:

- dump PostgreSQL format custom dari `pg_dump` (termasuk user, kamera, URL RTSP,
  embedding ReID, tracking, event, dan audit log);
- isi folder `storage` termasuk snapshot dan metadata;
- manifest dan checksum SHA-256 untuk setiap file;
- enkripsi streaming AES-256-GCM dengan key yang diturunkan menggunakan scrypt.

Aktifkan scheduler hanya setelah passphrase disimpan di secret manager:

```dotenv
ENABLE_DR_SCHEDULER=true
DR_SCHEDULE_TIME=02:00
DR_RETENTION_DAYS=14
DR_ENCRYPTION_PASSPHRASE=ganti-dengan-secret-acak-minimal-16-karakter
DR_INCLUDE_STORAGE=true
DR_OFFSITE_PATH=/offsite/cctv
DR_OFFSITE_REQUIRED=true
DR_RESTORE_DATABASE_SUFFIX=_restore
DR_ALLOW_IN_PLACE_RESTORE=false
DR_COMMAND_TIMEOUT_SECONDS=3600
```

Mount NAS pada service `api` di `docker-compose.yml`, misalnya
`/mnt/cctv-backup:/offsite/cctv`. Penyalinan offsite menggunakan file sementara,
rename atomik, lalu verifikasi checksum. Jika `DR_OFFSITE_REQUIRED=true`, job
dianggap gagal ketika salinan offsite gagal; kebijakan ini mencegah status sukses
palsu saat backup hanya berada pada disk server yang sama.

Endpoint `SUPER_ADMIN` berada di `/api/v1/disaster-recovery`:

- `POST /` membuat DR manual;
- `POST /import` mendaftarkan file `.dr.enc` dari offsite;
- `POST /{id}/validate` mendekripsi dan memeriksa seluruh checksum;
- `POST /{id}/restore` melakukan restore aman ke database `cctv_restore`;
- `GET /{id}/download` mengunduh arsip terenkripsi.

Restore melalui API memerlukan teks konfirmasi persis `RESTORE cctv_restore`.
Database live tidak disentuh dan storage hasil restore ditempatkan di
`storage/restores/<archive-id>` untuk diperiksa. Lakukan uji restore berkala;
backup yang belum pernah berhasil direstore belum dapat dianggap tervalidasi.

### Cutover pemulihan server

Cutover live bersifat destruktif dan hanya boleh dilakukan saat API/dashboard
sudah dihentikan. Simpan file `.dr.enc` pada mount terpisah, set
`DR_ALLOW_IN_PLACE_RESTORE=true`, lalu jalankan container satu kali dengan
entrypoint langsung agar migration startup tidak berjalan sebelum database
dipulihkan:

```bash
docker compose stop api dashboard
docker compose run --rm --no-deps --entrypoint python \
  -v /lokasi/offsite:/recovery:ro api \
  -m app.utils.dr_restore_cli \
  --archive /recovery/cctv_dr_YYYYMMDD_HHMMSS_UUID.dr.enc \
  --confirm "RESTORE LIVE cctv"
docker compose up -d api dashboard
```

Perintah melakukan validasi dan dekripsi lebih dahulu, membuat ulang database,
menjalankan `pg_restore`, lalu memulihkan storage. File storage lama yang berbeda
dipindahkan ke `storage/pre-restore/<timestamp>` dan receipt pemulihan ditulis ke
`storage/restores/live-<timestamp>.json`. Passphrase tidak pernah dimasukkan ke
nama file, manifest, log, atau argumen perintah.

## Dashboard multi-kamera

Dashboard mengambil hingga 200 kamera dari API, mengelompokkannya berdasarkan
gedung/lokasi, dan menyediakan grid live 1, 4, 9, atau 16 kamera. WebSocket
menggunakan subscription sehingga browser hanya menerima frame kamera yang
sedang dipilih. Status kamera dianggap online saat frame diterima dalam 15 detik
terakhir.

Saat membuat kamera, metadata lokasi dapat ikut dikirim:

```json
{
  "name": "Pintu Utama 01",
  "rtsp_url": "rtsp://user:password@192.168.1.10/stream",
  "enabled": true,
  "location": "Pintu Utama",
  "building": "Gedung A",
  "floor": "Lantai 1",
  "zone": "Lobby",
  "display_order": 1
}
```

Container API otomatis menjalankan seluruh migration sampai revision terbaru
saat startup. Publisher realtime harus mengirim `camera_id` yang sama dengan ID pada
database ketika memanggil `dashboard_hub.publish_frame(...)`.

`CameraRuntimeManager` aktif secara default. Manager memuat kamera aktif dari
PostgreSQL, membuka sumber RTSP/HLS, memperbarui status kesehatan, dan hanya
melakukan encoding JPEG ketika dashboard berlangganan ke kamera tersebut. Atur
`DASHBOARD_STREAM_FPS` serta `DASHBOARD_JPEG_QUALITY` untuk menyeimbangkan
kelancaran live view dengan CPU dan bandwidth.

## Pipeline AI realtime end-to-end

Setiap kamera aktif memiliki state ByteTrack dan line-crossing sendiri. Model
YOLO dan OSNet dibagi antar-kamera agar weight tidak dimuat berulang, sedangkan
semaphore membatasi inference paralel agar CPU/GPU tidak kehabisan memori.

```text
CameraService latest frame
  → YOLOv11 (hanya class person)
  → ByteTrack per kamera
  → OSNet ReID saat track baru
  → Person + Tracking PostgreSQL
  → Line Crossing ENTER/EXIT
  → Snapshot JPEG + JSON
  → Event + Snapshot dalam transaksi database
  → WebSocket frame/tracks/event/occupancy
  → Dashboard React
```

AI tetap memproses kamera walaupun tidak ada dashboard yang berlangganan. JPEG
live hanya diencode untuk kamera yang sedang dilihat. Tracking yang tidak muncul
lagi ditutup otomatis, dan event yang gagal disimpan karena gangguan database
masuk ke antrean retry bounded tanpa membuang snapshot.

Konfigurasi pipeline:

```dotenv
ENABLE_AI_PIPELINE=true
AI_PIPELINE_FPS=5
AI_MAX_CONCURRENT_INFERENCES=1
AI_PERSON_CLASS_ID=0
AI_TRACKING_PERSIST_INTERVAL_SECONDS=1.0
AI_TRACK_INACTIVE_FRAMES=60
AI_EVENT_RETRY_QUEUE_SIZE=1000
REID_MIN_CROP_WIDTH=32
REID_MIN_CROP_HEIGHT=64
REID_SIMILARITY_THRESHOLD=0.78
REID_MATCH_MARGIN=0.05
REID_MIN_QUALITY_SCORE=0.45
REID_EMBEDDING_RETENTION_DAYS=90
REID_MIN_EMBEDDINGS_PER_PERSON=3
REID_MAX_EMBEDDINGS_PER_PERSON=20
ENABLE_REID_RETENTION=true
```

Untuk Mac M1/CPU mulai dari `AI_PIPELINE_FPS=2` dan concurrency `1`. Untuk GPU,
naikkan FPS dan concurrency secara bertahap sambil memantau VRAM serta latency.

### Menguji dengan webcam MacBook

Docker Desktop tidak mengekspos webcam macOS sebagai `/dev/video0`. Untuk mode
uji, webcam disiarkan oleh FFmpeg di host menuju MediaMTX, kemudian API membaca
relay tersebut sebagai RTSP biasa.

```bash
brew install ffmpeg
docker compose --profile webcam up -d mediamtx
./scripts/list_mac_cameras.sh
./scripts/start_mac_webcam.sh
```

Saat macOS meminta izin, izinkan Camera untuk Terminal. Tambahkan kamera dari
dashboard dengan URL berikut (hostname `mediamtx` dipakai karena API berada di
jaringan Docker):

```text
rtsp://mediamtx:8554/macbook-webcam
```

Jika kamera bukan indeks `0`, jalankan misalnya
`WEBCAM_DEVICE_INDEX=1 ./scripts/start_mac_webcam.sh`. Tekan `Ctrl+C` pada
terminal FFmpeg untuk menghentikan stream. MediaMTX hanya aktif ketika profile
`webcam` dipilih dan tidak ikut berjalan pada deployment produksi biasa.

### ReID production dan koreksi identitas

Embedding OSNet 512 dimensi disimpan sebagai template terpisah pada PostgreSQL
`pgvector` dan dicari menggunakan cosine distance melalui indeks HNSW. Sebuah
hasil hanya diterima jika melewati threshold dan unggul dari kandidat orang
kedua sebesar `REID_MATCH_MARGIN`. Hasil yang melewati threshold tetapi terlalu
dekat dengan kandidat kedua dibuat sebagai identitas baru berstatus **perlu
ditinjau**, sehingga dua orang tidak otomatis digabung karena pakaian/APD yang
mirip. Crop kecil, buram, atau confidence rendah tidak masuk galeri embedding.

Admin dan super admin dapat membuka **Administrasi → Identitas ReID** untuk:

- menggabungkan beberapa identitas ke satu identitas utama;
- memisahkan tracking historis ke identitas baru;
- melihat threshold, margin ambigu, jumlah template, dan status tinjauan.

Merge/split ditolak selama tracking terkait masih aktif, berjalan dalam satu
transaksi, mempertahankan event/snapshot, dan dicatat di audit log. Scheduler
retensi menghapus template embedding yang kedaluwarsa atau melebihi batas per
orang, tetapi selalu mempertahankan jumlah minimum dan tidak menghapus Person,
Tracking, Event, atau Snapshot.

### Garis crossing per kamera

Admin dan super admin dapat memilih kamera pada **Live workbench**, lalu menekan
ikon garis pada header feed. Editor mendukung:

- garis horizontal dengan arah masuk atas/bawah;
- garis vertical dengan arah masuk kiri/kanan;
- polygon dengan event `ENTER` saat centroid berpindah dari luar ke dalam dan
  `EXIT` saat berpindah dari dalam ke luar;
- aktivasi/nonaktivasi crossing tanpa menghapus geometri.

Koordinat disimpan dalam rentang relatif `0..1`, sehingga konfigurasi tetap
berlaku ketika resolusi stream berubah. Worker kamera mengambil perubahan dari
PostgreSQL dan mengganti state crossing tanpa memuat ulang YOLO, ByteTrack, atau
OSNet. Perubahan biasanya aktif dalam waktu maksimal
`CAMERA_SYNC_INTERVAL_SECONDS` dan dicatat pada audit log.

Endpoint terkait:

```text
GET /api/v1/camera/{camera_id}/crossing-config
PUT /api/v1/camera/{camera_id}/crossing-config  # ADMIN / SUPER_ADMIN
```

Kamera yang belum mempunyai konfigurasi masih memakai nilai crossing global
dari `.env` untuk kompatibilitas dengan instalasi sebelumnya. Setelah konfigurasi
disimpan dari dashboard, konfigurasi per kamera menjadi sumber utama.

Hentikan layanan dengan `docker compose down`. Tambahkan `-v` hanya bila data
PostgreSQL memang ingin dihapus.

## Konfigurasi performa

- `YOLO_DEVICE=auto` dan `REID_DEVICE=auto` memilih CUDA bila tersedia; selain
  itu berjalan di CPU.
- `YOLO_HALF_PRECISION=true` mengaktifkan FP16 hanya ketika YOLO berjalan pada
  CUDA.
- Batasi CPU pada host multi-kamera melalui `TORCH_NUM_THREADS` dan
  `OPENCV_NUM_THREADS`; nilai `0` memakai default library.
- `CAMERA_READ_FPS`, ukuran frame, confidence, serta pengaturan ByteTrack
  seluruhnya dikontrol lewat `.env`.

## Struktur

```text
app/
├── api/          HTTP routes, JWT, schema, DI, dan error handler
├── config/       Settings Pydantic dari .env
├── database/     Engine dan async SQLAlchemy session
├── models/       Entitas ORM termasuk Camera, Event, backup, dan katalog DR
├── repository/   Query per entitas dan transaksi persistence pipeline realtime
├── services/     Kamera, pipeline AI, crossing, backup/DR, dan scheduler
├── detector/     Adapter YOLOv11
├── tracker/      Adapter ByteTrack + riwayat centroid
├── reid/         OSNet/TorchReID dan pencocokan embedding
├── storage/      Snapshot JPEG dan metadata JSON
├── dashboard/    WebSocket hub realtime
└── utils/        Logging, runtime CPU/GPU, dan CLI cutover DR offline
alembic/          Migrasi PostgreSQL
dashboard/        React + Vite + Material UI
tests/            Unit test tanpa RTSP, GPU, maupun database nyata
docker/           Entrypoint container untuk migrasi otomatis
```
