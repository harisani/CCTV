# CCTV People Flow

Sistem realtime untuk mendeteksi orang dari RTSP, menjaga tracking ByteTrack,
menentukan ENTER/EXIT melalui virtual line, menyimpan snapshot dan event ke
PostgreSQL, serta menampilkan data melalui FastAPI dan dashboard React.

## Menjalankan dengan Docker

1. Salin konfigurasi contoh: `cp .env.example .env`.
2. Ubah minimal `POSTGRES_PASSWORD`, `JWT_SECRET`, dan `API_ADMIN_PASSWORD`.
3. Pada host Linux, siapkan direktori evidence bind-mounted agar dapat ditulis
   oleh user API non-root (UID/GID `10001`):

   ```bash
   sudo install -d -o 10001 -g 10001 storage
   ```

4. Jalankan: `docker compose up --build`.

Perintah `install` di atas menyiapkan direktori evidence `storage` pada host
Linux. Perintah ini tidak diperlukan pada Docker Desktop untuk macOS jika file
sharing sudah memberikan akses tulis ke direktori proyek.

Image lokal memakai wheel PyTorch CPU agar Mac M1 tidak mengunduh library CUDA
yang tidak dapat dipakai. Untuk server NVIDIA, atur `TORCH_INDEX_URL` ke index
CUDA resmi yang sesuai dengan driver sebelum build.

Compose menunggu PostgreSQL sehat, menjalankan `alembic upgrade head`, lalu
menyalakan API dan dashboard. URL yang tersedia:

- API dan Swagger: `http://localhost:8000/docs`
- Liveness: `http://localhost:8000/api/v1/health/live`
- Readiness (termasuk koneksi database): `http://localhost:8000/api/v1/health/ready`
- Health check lengkap (kompatibilitas): `http://localhost:8000/api/v1/health`
- Dashboard: `http://localhost:5173`

Pada production, `LOG_FORMAT=auto` menghasilkan log JSON terstruktur; pada
terminal development log tetap mudah dibaca. Setiap request memiliki correlation
ID untuk penelusuran. Pembatas login menggunakan state in-memory dan hanya akurat
untuk satu instance API; deployment multi-instance memerlukan limiter bersama
seperti Redis.

Saat database masih kosong, API membuat akun awal dari `API_ADMIN_USERNAME` dan
`API_ADMIN_PASSWORD`. Akun ini memiliki role `SUPER_ADMIN`. Nilai password hanya
digunakan untuk bootstrap pertama; perubahan berikutnya disimpan sebagai hash
scrypt di PostgreSQL, bukan kembali ke `.env`.

## Security baseline

- Never expose the API or dashboard directly to the internet without TLS and an approved reverse proxy.
- Production startup accepts only `development`, `test`, or `production` as
  the application environment. Production rejects placeholder database, JWT,
  administrator, and evidence-signing secrets, and requires separate JWT and
  evidence-signing keys.
- Keep `.env` outside Git with file permission `0600`; production secrets belong in the deployment secret manager.
- Snapshot evidence is not public static content. After an authenticated grant,
  the dashboard sends the short-lived evidence token only in the HTTP
  `Authorization` header, fetches the image as a Blob, and renders a temporary
  in-memory object URL. Evidence tokens never appear in URLs, inherit user
  session revocation through `token_version`, and every grant/view is audited
  with a shared grant ID.
- Phase 3 evidence assets use immutable relative storage keys and SHA-256
  checksums. Database triggers prevent changing an asset's capture identity,
  storage key, or enrolled checksum after creation.
- Phase 4 AI jobs use a durable PostgreSQL queue. Claims use row locks,
  ownership leases, heartbeat renewal, bounded retry, and unique idempotency
  keys so a restart does not duplicate processing.
- Phase 6 uses pinned OpenCV Zoo YuNet/SFace artifacts. Face candidates and
  periocular evidence are quality-scored; identity is confirmed only when both
  the similarity threshold and the separation from the next distinct subject
  are sufficient. Ambiguous/probable results require review and raw embeddings
  are never returned by the API.
- Snapshot list responses expose stable snapshot/event IDs, bounding boxes, and
  timestamps only. Server filesystem paths for images and metadata remain
  internal persistence details and are never part of the public API contract.
- Do not delete `storage/`, PostgreSQL volumes, or historical Alembic migrations during source cleanup.

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

ZIP memuat `manifest.json`, dataset JSON Lines, snapshot lama, capture event,
evidence asset, kandidat wajah/periocular, dan hasil identity matching. Embedding
referensi tidak dimasukkan ke backup observasional; embedding tetap tersedia
dalam backup DR terenkripsi. Setiap member memiliki checksum SHA-256. File dibuat secara atomik;
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

## Phase 6: Face/periocular candidate dan identity matching

Saat capture crossing masuk ke durable queue, worker menjalankan tiga job secara
berurutan: `CAPTURE_INGESTION`, `PERSON_DETECTION`, lalu
`IDENTITY_CORRELATION`. YuNet mencari kandidat wajah pada crop tubuh atau
snapshot, menilai confidence, ukuran, ketajaman, dan pencahayaan, kemudian
menyimpan `FACE_CROP` serta `PERIOCULAR_CROP` sebagai evidence immutable.
Periocular saat ini hanya menjadi bukti fallback dan tidak dipaksakan menjadi
hasil pengenalan.

SFace menghasilkan embedding native 128 dimensi. Vektor dinormalisasi lalu
di-zero-pad ke kolom `Vector(512)` sehingga cosine similarity tetap sama dan
skema siap untuk recognizer 512 dimensi di masa depan. Keputusan:

- `CONFIRMED`: skor melewati threshold dan berbeda cukup jauh dari subjek kedua;
- `PROBABLE` atau `CONFLICT`: kandidat tersedia tetapi wajib review;
- `UNKNOWN`: kualitas cukup, namun tidak ada referensi atau skor tidak cocok;
- `UNRESOLVED`: tidak ada kandidat wajah yang layak/alignable.

Endpoint terautentikasi tersedia di `/api/v1/biometrics`. Enrollment dan revoke
template hanya untuk `SUPER_ADMIN`/`ADMIN` dan tercatat di audit log. Enrollment
menggunakan `FACE_CROP` yang sudah tersimpan:

```json
{
  "source_asset_id": "UUID_FACE_CROP",
  "person_id": "UUID_PERSON",
  "external_subject_key": null
}
```

`external_subject_key` disediakan agar branch integrasi RFID kelak dapat
mengaitkan employee tanpa mengubah format template. Threshold pada `.env`
merupakan baseline konservatif dan wajib dikalibrasi menggunakan data CCTV,
masker, APD, sudut, serta pencahayaan lokasi sebenarnya sebelum produksi.

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
  → Evidence bundle atomik + checksum SHA-256
  → Event/Snapshot kompatibilitas + CaptureEvent/EvidenceAsset
  → WebSocket frame/tracks/event/occupancy
  → Dashboard React
```

AI tetap memproses kamera walaupun tidak ada dashboard yang berlangganan. JPEG
live hanya diencode untuk kamera yang sedang dilihat. Tracking yang tidak muncul
lagi ditutup otomatis, dan event yang gagal disimpan karena gangguan database
masuk ke antrean retry bounded tanpa membuang snapshot.

Setiap crossing yang diterima menyimpan original snapshot, gambar beranotasi,
full-body crop, thumbnail, dan metadata JSON. Semua metadata database dibuat
dalam transaksi yang sama dengan event lama sehingga dashboard yang sudah ada
tetap kompatibel.

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
EVIDENCE_THUMBNAIL_WIDTH=320
EVIDENCE_DEFAULT_RETENTION_DAYS=90
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

### Topologi fasilitas

Admin dan super admin dapat membuka **Administrasi → Topologi fasilitas** untuk
mengatur gedung, zona, peran kamera, cakupan kamera, adjacency antarzona, serta
virtual line. Model terstruktur ini mencegah korelasi kamera menghubungkan
perjalanan yang secara fisik tidak mungkin.

Konfigurasi lama tetap kompatibel: migration membentuk gedung/zona awal dari
kolom lokasi kamera, sedangkan virtual line utama tetap disinkronkan ke endpoint
crossing lama. Detail implementasi dan kontrak API tersedia di
[`docs/audits/2026-07-24-phase2-topology-report.md`](docs/audits/2026-07-24-phase2-topology-report.md).

### Capture event dan evidence immutable

Phase 3 menambahkan `capture_events` sebagai envelope operasional dan
`evidence_assets` sebagai katalog file sensitif. Endpoint metadata:

```text
GET  /api/v1/capture-events
GET  /api/v1/capture-events/{id}
GET  /api/v1/capture-events/{id}/assets
POST /api/v1/capture-events/assets/{asset_id}/verify
POST /api/v1/evidence/assets/{asset_id}/access
GET  /api/v1/evidence/assets/{asset_id}/content
```

Daftar capture dan asset tidak mengekspos path filesystem atau storage key.
Konten hanya dapat dibuka melalui grant singkat yang terikat ke user, versi
sesi, asset ID, dan grant ID. Grant dan pembacaan konten selalu masuk audit log.

Migration mempertahankan `events` dan `snapshots`. Record lama dibackfill
menjadi capture event dan asset berstatus `UNVERIFIED`; endpoint verifikasi
melakukan hashing streaming lalu mengenrol checksum pertama atau menandai file
`MISSING`/`CORRUPT`. Detail tersedia di
[`docs/audits/2026-07-24-phase3-capture-evidence-report.md`](docs/audits/2026-07-24-phase3-capture-evidence-report.md).

### Antrean asynchronous dan AI processing jobs

Phase 4 memisahkan capture kamera dari pekerjaan AI lanjutan menggunakan
antrean durable di PostgreSQL. Penyimpanan capture dan pembuatan job dilakukan
dalam transaksi yang sama. Worker mengambil job berdasarkan prioritas
`HIGH → NORMAL → LOW` dengan `FOR UPDATE SKIP LOCKED`, sehingga beberapa worker
dapat berjalan tanpa mengerjakan record yang sama.

Status job:

```text
QUEUED → PROCESSING → COMPLETED
                    ↘ RETRYING → PROCESSING
                    ↘ FAILED
                    ↘ CANCELLED
```

Setiap claim memiliki lease dan heartbeat. Jika proses mati, lease kedaluwarsa
akan dikembalikan ke `RETRYING`, atau menjadi `FAILED` jika batas percobaan
habis. Retry memakai exponential backoff. Pada Phase 4 handler
`CAPTURE_INGESTION` memvalidasi manifest evidence; model deteksi AI aktual
ditambahkan pada phase berikutnya.

Endpoint observasi dan administrasi:

```text
GET  /api/v1/processing-jobs
GET  /api/v1/processing-jobs/statistics
GET  /api/v1/processing-jobs/{job_id}
POST /api/v1/processing-jobs/{job_id}/retry   # ADMIN / SUPER_ADMIN
POST /api/v1/processing-jobs/{job_id}/cancel  # ADMIN / SUPER_ADMIN
```

Konfigurasi worker berasal dari `.env`, terutama `ENABLE_AI_WORKER`,
`AI_WORKER_CONCURRENCY`, `AI_JOB_LEASE_SECONDS`,
`AI_JOB_HEARTBEAT_SECONDS`, `AI_JOB_TIMEOUT_SECONDS`,
`AI_JOB_MAX_ATTEMPTS`, serta pengaturan retry dan recovery. Detail desain dan
verifikasi tersedia di
[`docs/audits/2026-07-24-phase4-async-processing-report.md`](docs/audits/2026-07-24-phase4-async-processing-report.md).

### Person detection, local tracking, dan transisi zona

Phase 5 memakai YOLO dan ByteTrack yang sudah tersedia sebagai capture-time
lightweight pipeline, tetapi sekarang menyimpan local track sebagai observasi
yang lebih lengkap: bounding box terakhir, centroid, confidence, direction,
model detector, `started_at`, dan `last_seen_at`.

Runtime kamera memuat seluruh virtual line aktif dari PostgreSQL. Setiap line
memiliki state crossing dan hysteresis sendiri, sehingga satu kamera dapat
memantau beberapa batas zona tanpa mencampur status track. Untuk line dengan
`from_zone_id` dan `to_zone_id`, satu crossing menghasilkan dua record immutable
dengan `transition_id` yang sama:

```text
ZONE_EXIT zona asal + ZONE_ENTER zona tujuan
```

Arah sebaliknya otomatis menukar zona asal dan tujuan. Pembuatan legacy event,
capture, evidence, processing job, dan pasangan zone event berada dalam satu
transaksi. Occupancy antarzona belum diubah pada phase ini; pemrosesannya
dilakukan oleh Occupancy Engine pada Phase 9.

Endpoint histori Phase 5:

```text
GET /api/v1/zone-events
GET /api/v1/zone-events/{event_id}
GET /api/v1/local-tracks
```

Detail implementasi dan batas phase tersedia di
[`docs/audits/2026-07-24-phase5-local-zone-transition-report.md`](docs/audits/2026-07-24-phase5-local-zone-transition-report.md).

### Okupansi tahan gangguan kamera

Jumlah orang saat ini berasal dari sesi keberadaan yang dibuka oleh event
`ENTER` dan ditutup oleh `EXIT`, bukan dari banyaknya tracking yang sedang aktif.
Jika kamera berhenti mengirim frame, sesi terbuka tetap dihitung tetapi berubah
menjadi `UNCERTAIN`. Dashboard menampilkan jumlah total dan jumlah yang belum
pasti secara terpisah. Ketika ReID kembali melihat orang yang sama, sesi kembali
`ACTIVE`; event `EXIT` akan menutup sesi tersebut.

`CAMERA_STALE_TIMEOUT_SECONDS` menentukan berapa detik tanpa frame baru sebelum
kamera ditandai `OFFLINE`. Status ini dikirim langsung melalui WebSocket, jadi
dashboard tidak perlu menunggu polling berkala.

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
├── models/       Entitas ORM termasuk topology, local track, zone event, evidence, dan AI job
├── repository/   Query, transaksi capture/transition, evidence, dan durable queue
├── services/     Kamera, multi-line crossing, worker AI, topology, backup/DR, dan scheduler
├── detector/     Adapter YOLOv11
├── tracker/      Adapter ByteTrack + riwayat centroid
├── reid/         OSNet/TorchReID dan pencocokan embedding
├── storage/      Evidence image/JSON atomik dengan checksum
├── dashboard/    WebSocket hub realtime
└── utils/        Logging, runtime CPU/GPU, dan CLI cutover DR offline
alembic/          Migrasi PostgreSQL
dashboard/        React + Vite + Material UI
tests/            Unit test tanpa RTSP, GPU, maupun database nyata
docker/           Entrypoint container untuk migrasi otomatis
```
