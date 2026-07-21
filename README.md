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

Container API otomatis menjalankan migration `0003_camera_dashboard` saat
startup. Publisher realtime harus mengirim `camera_id` yang sama dengan ID pada
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
├── models/       Entitas ORM: Camera, Person, Tracking, Event, Snapshot
├── repository/   Query dan persistensi per entitas
├── services/     Kamera RTSP, line crossing, dan composition root
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
# CCTV
