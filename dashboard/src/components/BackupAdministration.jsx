import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  TextField,
} from '@mui/material'
import ArchiveOutlinedIcon from '@mui/icons-material/ArchiveOutlined'
import BackupOutlinedIcon from '@mui/icons-material/BackupOutlined'
import CloudDownloadOutlinedIcon from '@mui/icons-material/CloudDownloadOutlined'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import VisibilityOutlinedIcon from '@mui/icons-material/VisibilityOutlined'
import { api, apiBlob } from '../api'

const entities = [
  ['events', 'Event'],
  ['trackings', 'Tracking'],
  ['snapshots', 'Snapshot'],
  ['persons', 'Person'],
  ['cameras', 'Kamera'],
  ['users', 'Pengguna'],
  ['audit_logs', 'Audit log'],
]

const localDate = () => {
  const now = new Date()
  const offset = now.getTimezoneOffset() * 60_000
  return new Date(now.getTime() - offset).toISOString().slice(0, 10)
}

const formatBytes = value => {
  if (!Number.isFinite(value)) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 ** 2).toFixed(1)} MB`
}

const formatTime = value => value ? new Date(value).toLocaleString('id-ID') : '—'

function SnapshotPreview({ open, url, onClose }) {
  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="md">
    <DialogTitle>Snapshot dari arsip</DialogTitle>
    <DialogContent>{url && <img className="archive-preview" src={url} alt="Snapshot event dari backup" />}</DialogContent>
    <DialogActions><Button onClick={onClose}>Tutup</Button></DialogActions>
  </Dialog>
}

function ArchiveRecordsDialog({ archive, token, onClose }) {
  const [entity, setEntity] = useState('events')
  const [search, setSearch] = useState('')
  const [records, setRecords] = useState({ items: [], total: 0 })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [previewUrl, setPreviewUrl] = useState('')

  const load = async (selectedEntity = entity) => {
    setLoading(true)
    setError('')
    try {
      const query = new URLSearchParams({ limit: '100' })
      if (search.trim()) query.set('search', search.trim())
      setRecords(await api(`/backups/${archive.id}/records/${selectedEntity}?${query}`, token))
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }

  useEffect(() => { if (archive) load(entity) }, [archive, entity])
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  const changeEntity = event => {
    setSearch('')
    setEntity(event.target.value)
  }

  const preview = async snapshot => {
    setError('')
    try {
      const blob = await apiBlob(`/backups/${archive.id}/snapshots/${snapshot.id}`, token)
      if (previewUrl) URL.revokeObjectURL(previewUrl)
      setPreviewUrl(URL.createObjectURL(blob))
    } catch (err) { setError(err.message) }
  }

  const columns = useMemo(() => {
    if (entity === 'events') return [
      ['occurred_at', 'Waktu'], ['event_type', 'Status'], ['tracking_id', 'Tracking'], ['line_id', 'Garis'],
    ]
    if (entity === 'trackings') return [
      ['byte_track_id', 'ByteTrack ID'], ['camera_id', 'Kamera'], ['person_id', 'Person'], ['started_at', 'Mulai'], ['ended_at', 'Selesai'],
    ]
    if (entity === 'snapshots') return [
      ['saved_at', 'Waktu'], ['event_id', 'Event'], ['id', 'Snapshot'],
    ]
    if (entity === 'persons') return [
      ['display_name', 'Nama'], ['reid_key', 'ReID key'], ['first_seen_at', 'Pertama'], ['last_seen_at', 'Terakhir'],
    ]
    if (entity === 'cameras') return [
      ['name', 'Kamera'], ['building', 'Gedung'], ['floor', 'Lantai'], ['zone', 'Zona'], ['status', 'Status'],
    ]
    if (entity === 'users') return [
      ['username', 'Username'], ['full_name', 'Nama'], ['role', 'Role'], ['is_active', 'Aktif'],
    ]
    return [['created_at', 'Waktu'], ['action', 'Aksi'], ['resource_type', 'Resource'], ['resource_id', 'ID']]
  }, [entity])

  const displayValue = (key, value) => {
    if (value === null || value === undefined || value === '') return '—'
    if (typeof value === 'boolean') return value ? 'Ya' : 'Tidak'
    if (key.endsWith('_at')) return formatTime(value)
    return typeof value === 'object' ? JSON.stringify(value) : String(value)
  }

  return <>
    <Dialog className="admin-dialog archive-dialog" open={Boolean(archive)} onClose={onClose} fullWidth maxWidth="lg">
      <DialogTitle>Isi backup · {archive?.backup_date}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">Arsip dibuka dalam mode baca-saja. Data operasional yang sedang berjalan tidak berubah.</p>
        {error && <Alert severity="error">{error}</Alert>}
        <form className="archive-toolbar" onSubmit={event => { event.preventDefault(); load() }}>
          <TextField className="light-field" select label="Jenis data" value={entity} onChange={changeEntity}>
            {entities.map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
          </TextField>
          <TextField className="light-field" label="Cari dalam arsip" value={search} onChange={event => setSearch(event.target.value)} />
          <Button type="submit" variant="outlined" disabled={loading}>{loading ? 'Membaca…' : 'Cari'}</Button>
        </form>
        <p className="archive-count">{records.total} record ditemukan</p>
        <div className="ledger-table-wrap"><table className="ledger-table admin-table"><thead><tr>
          {columns.map(([, label]) => <th key={label}>{label}</th>)}
          {entity === 'snapshots' && <th>Aksi</th>}
        </tr></thead><tbody>
          {records.items.map((record, index) => <tr key={record.id || index}>
            {columns.map(([key, label]) => <td key={key} data-label={label}>{displayValue(key, record[key])}</td>)}
            {entity === 'snapshots' && <td data-label="Aksi"><Button size="small" startIcon={<VisibilityOutlinedIcon />} disabled={!record.archive_image_path} onClick={() => preview(record)}>Preview</Button></td>}
          </tr>)}
          {!records.items.length && <tr><td colSpan={columns.length + 1}><p className="empty-copy">Tidak ada record untuk filter ini.</p></td></tr>}
        </tbody></table></div>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Tutup arsip</Button></DialogActions>
    </Dialog>
    <SnapshotPreview open={Boolean(previewUrl)} url={previewUrl} onClose={() => { URL.revokeObjectURL(previewUrl); setPreviewUrl('') }} />
  </>
}

export default function BackupAdministration({ token }) {
  const [backups, setBackups] = useState([])
  const [backupDate, setBackupDate] = useState(localDate())
  const [selected, setSelected] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const fileRef = useRef(null)

  const loadBackups = async () => {
    try { setBackups((await api('/backups?limit=100', token)).items) } catch (err) { setError(err.message) }
  }
  useEffect(() => { loadBackups() }, [token])

  const createBackup = async () => {
    setBusy('create')
    setError('')
    setNotice('')
    try {
      await api('/backups', token, { method: 'POST', body: JSON.stringify({ backup_date: backupDate }) })
      setNotice(`Backup tanggal ${backupDate} berhasil dibuat.`)
      await loadBackups()
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  const importBackup = async event => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setBusy('import')
    setError('')
    setNotice('')
    const body = new FormData()
    body.append('archive_file', file)
    try {
      await api('/backups/import', token, { method: 'POST', body })
      setNotice(`${file.name} berhasil divalidasi dan ditambahkan sebagai arsip baca-saja.`)
      await loadBackups()
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  const download = async archive => {
    setBusy(archive.id)
    setError('')
    try {
      const blob = await apiBlob(`/backups/${archive.id}/download`, token)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `cctv_backup_${archive.backup_date.replaceAll('-', '')}.zip`
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) { setError(err.message) } finally { setBusy('') }
  }

  return <section className="admin-section backup-section">
    <div className="section-heading"><div><h2 className="section-title">Backup & arsip</h2><p className="section-copy">Simpan observasi per tanggal dan buka kembali tanpa mengubah database live.</p></div></div>
    {error && <Alert className="error-banner" severity="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert className="error-banner" severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    <div className="backup-actions">
      <div className="backup-action-block">
        <BackupOutlinedIcon />
        <div><strong>Buat backup tanggal tertentu</strong><p>Event, tracking, identitas terkait, audit, dan snapshot pada tanggal tersebut.</p></div>
        <TextField className="light-field" label="Tanggal backup" type="date" value={backupDate} onChange={event => setBackupDate(event.target.value)} InputLabelProps={{ shrink: true }} />
        <Button variant="contained" disabled={Boolean(busy)} onClick={createBackup}>{busy === 'create' ? 'Membuat…' : 'Buat backup'}</Button>
      </div>
      <div className="backup-action-block">
        <UploadFileOutlinedIcon />
        <div><strong>Import ZIP tervalidasi</strong><p>Checksum dan struktur diperiksa sebelum arsip dicatat.</p></div>
        <input ref={fileRef} className="visually-hidden" type="file" accept=".zip,application/zip" onChange={importBackup} />
        <Button variant="outlined" disabled={Boolean(busy)} onClick={() => fileRef.current?.click()}>{busy === 'import' ? 'Mengimpor…' : 'Pilih file ZIP'}</Button>
      </div>
    </div>
    <div className="ledger-table-wrap"><table className="ledger-table admin-table"><thead><tr><th>Tanggal</th><th>Sumber</th><th>Status</th><th>Ukuran</th><th>Isi</th><th>Aksi</th></tr></thead><tbody>
      {backups.map(archive => <tr key={archive.id}>
        <td data-label="Tanggal"><strong>{archive.backup_date}</strong><span className="table-secondary">{formatTime(archive.created_at)}</span></td>
        <td data-label="Sumber">{archive.source}</td>
        <td data-label="Status"><Chip size="small" label={archive.status} color={archive.status === 'READY' ? 'success' : archive.status === 'FAILED' ? 'error' : 'warning'} /></td>
        <td data-label="Ukuran">{formatBytes(archive.size_bytes)}</td>
        <td data-label="Isi"><span className="archive-record-summary">{Object.entries(archive.record_counts || {}).filter(([, count]) => count > 0).slice(0, 3).map(([name, count]) => `${name}: ${count}`).join(' · ') || 'Kosong'}</span></td>
        <td data-label="Aksi"><div className="row-actions">
          <Button size="small" startIcon={<ArchiveOutlinedIcon />} disabled={archive.status !== 'READY'} onClick={() => setSelected(archive)}>Buka</Button>
          <Button size="small" startIcon={<CloudDownloadOutlinedIcon />} disabled={archive.status !== 'READY' || busy === archive.id} onClick={() => download(archive)}>{busy === archive.id ? 'Menyiapkan…' : 'Unduh'}</Button>
        </div></td>
      </tr>)}
      {!backups.length && <tr><td colSpan="6"><p className="empty-copy">Belum ada backup. Buat satu backup atau import ZIP yang valid.</p></td></tr>}
    </tbody></table></div>
    <ArchiveRecordsDialog archive={selected} token={token} onClose={() => setSelected(null)} />
  </section>
}
