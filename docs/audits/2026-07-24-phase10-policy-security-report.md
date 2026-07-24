# Phase 10 — Policy Engine and Security Alerts

Tanggal verifikasi: 24 Juli 2026

Branch: `cctv/versi-1`

Migration head: `0018_policy_security_alerts`

## Hasil

Phase 10 menambahkan policy engine konservatif dan workflow security alert
yang dapat diaudit. Pipeline asynchronous sekarang lengkap sampai keputusan
kebijakan:

```text
CAPTURE_INGESTION
→ PERSON_DETECTION
→ IDENTITY_CORRELATION
→ BODY_REIDENTIFICATION
→ PPE_ANALYSIS
→ JOURNEY_CORRELATION
→ OCCUPANCY_UPDATE
→ POLICY_EVALUATION
```

Policy evaluation memakai occupancy fact sebagai input idempotent. Retry job
yang sama tidak membuat evaluation atau alert kedua.

## Policy context

Evaluator membaca:

- subject type dan identity decision;
- global journey correlation;
- zona serta sensitivity;
- status kamera;
- profil kebijakan person/external subject;
- department code opsional;
- observasi APD dan warna;
- end-to-end processing delay.

Profil kebijakan tidak menggantikan identity pipeline dan tidak menebak
employee dari pakaian. Ia hanya menambahkan konteks HR opsional setelah
identity tersedia.

Rule type:

```text
ZONE_AUTHORIZATION
DIVISION_PERMISSION
PPE_COLOR
PPE_COMPLETENESS
RESTRICTED_ZONE
UNKNOWN_PERSON
UNRESOLVED_PERSON
CAMERA_OFFLINE
PROCESSING_DELAY
IDENTITY_CONFLICT
```

Rule dapat global atau dibatasi ke satu zona, mempunyai priority, severity,
configuration JSON tervalidasi, dan status enabled.

## Fail-safe behavior

- APD tidak dinyatakan hilang hanya karena tidak terdeteksi.
- `PPE_INCOMPLETE` hanya dibuat dari state `MISSING` eksplisit.
- model APD unavailable/partial menghasilkan `INCONCLUSIVE`.
- department yang tidak tersedia menghasilkan `INCONCLUSIVE`.
- unknown EXIT tidak membuat unknown-entry alert.
- impossible travel selalu menghasilkan alert critical.
- ambiguous correlation menghasilkan duplicate-journey alert.
- terminal AI job failure menghasilkan capture-failure alert.
- kamera offline mempunyai paling banyak satu alert open/acknowledged dan
  alert tersebut auto-resolved ketika stream pulih.

## Alert lifecycle dan RBAC

```text
OPEN
├── ACKNOWLEDGED ──► RESOLVED
├── RESOLVED
└── DISMISSED
```

Alert terminal tidak dapat direview ulang. Setiap acknowledge, resolve,
dismiss, auto-resolution kamera, pembuatan profile, dan pembuatan rule masuk
ke `audit_logs`.

- rule/profile write: `SUPER_ADMIN`, `ADMIN`;
- alert review: `SUPER_ADMIN`, `ADMIN`, `SUPERVISOR`, `OPERATOR`;
- authenticated read: semua role lama, termasuk `AUDITOR`.

## Database

Migration `0018_policy_security_alerts` menambahkan:

- `subject_policy_profiles`;
- `policy_rules`;
- `policy_evaluations`;
- `security_alerts`;
- enum rule type, alert type, severity, status, dan evaluation status;
- unique key untuk subject, rule, evaluation, dan alert deduplication;
- foreign key ke zone, camera, journey, occupancy session, capture, person,
  user, dan occupancy fact.

## API

```text
GET|POST /api/v1/policies/rules
GET|POST /api/v1/policies/profiles
GET      /api/v1/policies/alerts
POST     /api/v1/policies/alerts/{alert_id}/review
GET      /api/v1/policies/evaluations
```

List alert mendukung pagination serta filter status, zone, dan alert type.
Swagger/OpenAPI memuat kelima path Phase 10.

## Backup

Archive observasional naik ke schema version 11 dan menambahkan:

- `subject_policy_profiles.jsonl`;
- `policy_rules.jsonl`;
- `policy_evaluations.jsonl`;
- `security_alerts.jsonl`.

Archive schema version 1–10 tetap dapat divalidasi.

## Struktur file Phase 10

```text
app/
├── api/
│   ├── policy_schemas.py
│   └── routes/policies.py
├── config/settings.py
├── models/entities.py
├── repository/policy_repository.py
└── services/
    ├── ai_processing_worker.py
    ├── camera_runtime_manager.py
    ├── policy_service.py
    └── backup_service.py
alembic/versions/0018_policy_security_alerts.py
tests/test_policy_service.py
```

## Verifikasi

- backend: 217 test lulus;
- Ruff 0.15.22: lulus;
- production image Python 3.12: build lulus;
- migration aktif `0017 → 0018`: lulus;
- rollback `0018 → 0017 → 0018`: lulus;
- endpoint Phase 10 terdaftar pada OpenAPI;
- database tetap bersih: satu bootstrap user dan nol camera/capture/rule/
  evaluation/alert.

## Batas Phase 10

Dashboard operasional khusus alert, manual occupancy correction, dan final
review workspace tetap menjadi Phase 11. Access-lock/RFID correlation tetap
Phase 12. Model APD site-specific dan threshold akhir harus dikalibrasi dari
dataset kamera aktual sebelum kebijakan APD dipakai untuk tindakan personel.
