# CCTV People Flow

Sistem realtime untuk mendeteksi orang dari RTSP, menjaga tracking ByteTrack,
menentukan ENTER/EXIT melalui virtual line, menyimpan snapshot dan event ke
PostgreSQL, serta menampilkan data melalui FastAPI dan dashboard React.

## Menjalankan dengan Docker

1. Salin konfigurasi contoh: `cp .env.example .env`.
2. Ubah minimal `POSTGRES_PASSWORD`, `JWT_SECRET`, dan `API_ADMIN_PASSWORD`.
3. Jalankan: `docker compose up --build`.

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
├── models/       Entitas ORM termasuk Camera, Event, User, dan BackupArchive
├── repository/   Query dan persistensi per entitas, termasuk katalog backup
├── services/     Kamera RTSP, RBAC, backup/import, scheduler, composition root
├── detector/     Adapter YOLOv11
├── tracker/      Adapter ByteTrack + riwayat centroid
├── reid/         OSNet/TorchReID dan pencocokan embedding
├── storage/      Snapshot JPEG dan metadata JSON
├── dashboard/    WebSocket hub realtime
└── utils/        Logging dan pengaturan runtime CPU/GPU
alembic/          Migrasi PostgreSQL
dashboard/        React + Vite + Material UI
tests/            Unit test tanpa RTSP, GPU, maupun database nyata
docker/           Entrypoint container untuk migrasi otomatis
```
