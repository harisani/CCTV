import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import KeyOutlinedIcon from '@mui/icons-material/KeyOutlined'
import WifiTetheringIcon from '@mui/icons-material/WifiTethering'
import { api } from '../api'
import BackupAdministration from './BackupAdministration'
import IdentityAdministration from './IdentityAdministration'
import EmployeeAdministration from './EmployeeAdministration'
import RFIDSimulator from './RFIDSimulator'

const roles = ['SUPER_ADMIN', 'ADMIN', 'SUPERVISOR', 'OPERATOR', 'AUDITOR']
const roleLabel = value => value?.replaceAll('_', ' ') || '—'

const emptyCamera = {
  name: '', rtsp_url: '', enabled: true, location: '', building: '', floor: '', zone: '', display_order: 0,
}
const emptyUser = {
  username: '', full_name: '', password: '', role: 'OPERATOR', is_active: true,
}

function CameraDialog({ open, camera, token, onClose, onSaved }) {
  const [form, setForm] = useState(emptyCamera)
  const [saving, setSaving] = useState(false)
  const [probe, setProbe] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    setForm(camera ? { ...emptyCamera, ...camera, rtsp_url: '' } : emptyCamera)
    setProbe(null)
    setError('')
  }, [open, camera])

  const update = field => event => setForm(current => ({
    ...current,
    [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value,
  }))

  const testConnection = async () => {
    setProbe({ loading: true })
    setError('')
    try {
      const result = await api('/camera/test-connection', token, {
        method: 'POST', body: JSON.stringify({ rtsp_url: form.rtsp_url }),
      })
      setProbe(result)
    } catch (err) {
      setProbe(null)
      setError(err.message)
    }
  }

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    const payload = { ...form, display_order: Number(form.display_order) || 0 }
    if (camera && !payload.rtsp_url) delete payload.rtsp_url
    try {
      await api(camera ? `/camera/${camera.id}` : '/camera', token, {
        method: camera ? 'PATCH' : 'POST', body: JSON.stringify(payload),
      })
      await onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="md">
    <form onSubmit={submit}>
      <DialogTitle>{camera ? 'Ubah konfigurasi kamera' : 'Tambahkan kamera'}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">Isi lokasi operasional dan uji sumber video sebelum menyimpan.</p>
        {error && <Alert severity="error">{error}</Alert>}
        <div className="admin-form-grid">
          <TextField className="light-field" label="Nama kamera" value={form.name} onChange={update('name')} required />
          <TextField className="light-field" label="Urutan tampil" type="number" value={form.display_order} onChange={update('display_order')} inputProps={{ min: 0 }} />
          <TextField className="light-field admin-form-grid__wide" label={camera ? 'URL baru (kosongkan jika tidak berubah)' : 'RTSP / HLS URL'} value={form.rtsp_url} onChange={update('rtsp_url')} required={!camera} />
          <TextField className="light-field" label="Gedung" value={form.building || ''} onChange={update('building')} />
          <TextField className="light-field" label="Lantai" value={form.floor || ''} onChange={update('floor')} />
          <TextField className="light-field" label="Zona" value={form.zone || ''} onChange={update('zone')} />
          <TextField className="light-field" label="Lokasi detail" value={form.location || ''} onChange={update('location')} />
          <FormControlLabel control={<Switch checked={form.enabled} onChange={update('enabled')} />} label="Kamera aktif" />
        </div>
        <div className="connection-test">
          <Button variant="outlined" startIcon={<WifiTetheringIcon />} disabled={!form.rtsp_url || probe?.loading} onClick={testConnection}>
            {probe?.loading ? 'Menguji…' : 'Test connection'}
          </Button>
          {probe && !probe.loading && <span data-status={probe.connected ? 'success' : 'error'}>
            {probe.connected ? `${probe.width}×${probe.height} · ${probe.latency_ms} ms` : probe.detail}
          </span>}
        </div>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Batal</Button><Button type="submit" variant="contained" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan kamera'}</Button></DialogActions>
    </form>
  </Dialog>
}

function UserDialog({ open, user, token, onClose, onSaved }) {
  const [form, setForm] = useState(emptyUser)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (!open) return
    setForm(user ? { ...emptyUser, ...user, password: '' } : emptyUser)
    setError('')
  }, [open, user])
  const update = field => event => setForm(current => ({ ...current, [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value }))
  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    const payload = user
      ? { full_name: form.full_name, role: form.role, is_active: form.is_active }
      : form
    try {
      await api(user ? `/users/${user.id}` : '/users', token, { method: user ? 'PATCH' : 'POST', body: JSON.stringify(payload) })
      await onSaved()
      onClose()
    } catch (err) { setError(err.message) } finally { setSaving(false) }
  }
  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="sm">
    <form onSubmit={submit}>
      <DialogTitle>{user ? 'Ubah akses pengguna' : 'Buat pengguna baru'}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">Role menentukan menu dan tindakan yang dapat digunakan akun.</p>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack spacing={2}>
          <TextField className="light-field" label="Nama lengkap" value={form.full_name} onChange={update('full_name')} required />
          {!user && <TextField className="light-field" label="Username" value={form.username} onChange={update('username')} required />}
          {!user && <TextField className="light-field" label="Password sementara" type="password" helperText="Minimal 12 karakter; pengguna diminta menggantinya." value={form.password} onChange={update('password')} required />}
          <TextField className="light-field" select label="Role" value={form.role} onChange={update('role')} required>
            {roles.map(role => <MenuItem key={role} value={role}>{roleLabel(role)}</MenuItem>)}
          </TextField>
          <FormControlLabel control={<Switch checked={form.is_active} onChange={update('is_active')} />} label="Akun aktif" />
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Batal</Button><Button type="submit" variant="contained" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan pengguna'}</Button></DialogActions>
    </form>
  </Dialog>
}

function ResetPasswordDialog({ open, user, token, onClose, onSaved }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    if (!open) return
    setPassword('')
    setError('')
  }, [open, user])
  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api(`/users/${user.id}/reset-password`, token, {
        method: 'POST', body: JSON.stringify({ password }),
      })
      onSaved(`Password @${user.username} berhasil direset. Semua sesi lamanya telah dibatalkan.`)
      onClose()
    } catch (err) { setError(err.message) } finally { setSaving(false) }
  }
  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="xs">
    <form onSubmit={submit}>
      <DialogTitle>Reset password</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">Tetapkan password sementara untuk @{user?.username}. Pengguna wajib menggantinya saat login berikutnya.</p>
        {error && <Alert severity="error">{error}</Alert>}
        <TextField className="light-field" fullWidth autoFocus label="Password sementara" type="password" helperText="Minimal 12 karakter." value={password} onChange={event => setPassword(event.target.value)} required inputProps={{ minLength: 12 }} />
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Batal</Button><Button type="submit" variant="contained" disabled={saving}>{saving ? 'Mereset…' : 'Reset password'}</Button></DialogActions>
    </form>
  </Dialog>
}

function DeleteCameraDialog({ camera, token, onClose, onDeleted }) {
  const [error, setError] = useState('')
  const [deleting, setDeleting] = useState(false)
  useEffect(() => { setError('') }, [camera])
  const remove = async () => {
    setDeleting(true)
    setError('')
    try {
      await api(`/camera/${camera.id}`, token, { method: 'DELETE' })
      await onDeleted()
      onClose()
    } catch (err) { setError(err.message) } finally { setDeleting(false) }
  }
  return <Dialog className="admin-dialog" open={Boolean(camera)} onClose={onClose} fullWidth maxWidth="xs">
    <DialogTitle>Nonaktifkan kamera?</DialogTitle>
    <DialogContent>
      <p className="dialog-intro">Kamera <strong>{camera?.name}</strong> akan dihentikan dari pemantauan realtime. Histori event dan snapshot tetap dipertahankan.</p>
      {error && <Alert severity="error">{error}</Alert>}
    </DialogContent>
    <DialogActions><Button onClick={onClose}>Batal</Button><Button color="error" variant="contained" disabled={deleting} onClick={remove}>{deleting ? 'Menonaktifkan…' : 'Nonaktifkan kamera'}</Button></DialogActions>
  </Dialog>
}

export default function Administration({ token, currentUser, cameras, onReloadCameras, section, onSectionChange }) {
  const [users, setUsers] = useState([])
  const [cameraDialog, setCameraDialog] = useState({ open: false, camera: null })
  const [userDialog, setUserDialog] = useState({ open: false, user: null })
  const [resetTarget, setResetTarget] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const canManageUsers = currentUser?.role === 'SUPER_ADMIN'
  const canManageIdentities = ['SUPER_ADMIN', 'ADMIN'].includes(currentUser?.role)
  const canManageEmployees = ['SUPER_ADMIN', 'ADMIN'].includes(currentUser?.role)

  const loadUsers = async () => {
    if (!canManageUsers) return
    try { setUsers((await api('/users?limit=100', token)).items) } catch (err) { setError(err.message) }
  }
  useEffect(() => { loadUsers() }, [token, canManageUsers])
  useEffect(() => {
    if (!canManageUsers && ['users', 'backups'].includes(section)) onSectionChange('cameras')
  }, [canManageUsers, section, onSectionChange])

  const activeCameras = useMemo(() => cameras.filter(camera => camera.enabled).length, [cameras])
  return <main className="dashboard-main admin-main">
    <section className="dashboard-intro admin-intro">
      <div><h1>Administrasi sistem</h1><p>Kelola sumber video dan hak akses tanpa menyentuh konfigurasi server.</p></div>
      <div className="admin-summary"><span>{activeCameras}/{cameras.length} kamera aktif</span><span>{canManageUsers ? `${users.length} pengguna` : roleLabel(currentUser?.role)}</span></div>
    </section>
    {error && <Alert className="error-banner" severity="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert className="error-banner" severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    {section === 'cameras' && <section className="admin-section">
      <div className="section-heading"><div><h2 className="section-title">Camera Management</h2><p className="section-copy">Tambah, uji, aktifkan, dan kelompokkan kamera.</p></div><Button variant="contained" startIcon={<AddIcon />} onClick={() => setCameraDialog({ open: true, camera: null })}>Tambah kamera</Button></div>
      <div className="ledger-table-wrap"><table className="ledger-table admin-table"><thead><tr><th>Kamera</th><th>Lokasi</th><th>Status</th><th>Aktif</th><th>Aksi</th></tr></thead><tbody>
        {cameras.map(camera => <tr key={camera.id}><td data-label="Kamera"><strong>{camera.name}</strong></td><td data-label="Lokasi">{[camera.building, camera.floor, camera.zone].filter(Boolean).join(' · ') || camera.location || '—'}</td><td data-label="Status"><Chip size="small" label={camera.status} color={camera.status === 'ONLINE' ? 'success' : camera.status === 'RECONNECTING' ? 'warning' : 'default'} /></td><td data-label="Aktif">{camera.enabled ? 'Ya' : 'Tidak'}</td><td data-label="Aksi"><div className="row-actions"><Button size="small" startIcon={<EditOutlinedIcon />} onClick={() => setCameraDialog({ open: true, camera })}>Ubah</Button>{camera.enabled && <Button color="error" size="small" startIcon={<DeleteOutlineIcon />} onClick={() => setDeleteTarget(camera)}>Nonaktifkan</Button>}</div></td></tr>)}
        {!cameras.length && <tr><td colSpan="5"><p className="empty-copy">Belum ada kamera.</p></td></tr>}
      </tbody></table></div>
    </section>}

    {section === 'users' && canManageUsers && <section className="admin-section">
      <div className="section-heading"><div><h2 className="section-title">User Management</h2><p className="section-copy">Atur role, status akun, dan reset password.</p></div><Button variant="contained" startIcon={<AddIcon />} onClick={() => setUserDialog({ open: true, user: null })}>Tambah pengguna</Button></div>
      <div className="ledger-table-wrap"><table className="ledger-table admin-table"><thead><tr><th>Pengguna</th><th>Role</th><th>Status</th><th>Login terakhir</th><th>Aksi</th></tr></thead><tbody>
        {users.map(user => <tr key={user.id}><td data-label="Pengguna"><strong>{user.full_name}</strong><span className="table-secondary">@{user.username}</span></td><td data-label="Role"><Chip size="small" label={roleLabel(user.role)} /></td><td data-label="Status">{user.is_active ? 'Aktif' : 'Nonaktif'}</td><td data-label="Login terakhir">{user.last_login_at ? new Date(user.last_login_at).toLocaleString('id-ID') : 'Belum pernah'}</td><td data-label="Aksi"><div className="row-actions"><Button size="small" startIcon={<EditOutlinedIcon />} onClick={() => setUserDialog({ open: true, user })}>Ubah</Button>{user.id !== currentUser?.id && <Button size="small" startIcon={<KeyOutlinedIcon />} onClick={() => setResetTarget(user)}>Reset</Button>}</div></td></tr>)}
      </tbody></table></div>
    </section>}

    {section === 'employees' && canManageEmployees && <EmployeeAdministration token={token} />}
    {section === 'rfid-simulator' && canManageEmployees && <RFIDSimulator token={token} />}
    {section === 'backups' && canManageUsers && <BackupAdministration token={token} />}
    {section === 'identities' && canManageIdentities && <IdentityAdministration token={token} />}

    <CameraDialog open={cameraDialog.open} camera={cameraDialog.camera} token={token} onClose={() => setCameraDialog({ open: false, camera: null })} onSaved={onReloadCameras} />
    <UserDialog open={userDialog.open} user={userDialog.user} token={token} onClose={() => setUserDialog({ open: false, user: null })} onSaved={loadUsers} />
    <ResetPasswordDialog open={Boolean(resetTarget)} user={resetTarget} token={token} onClose={() => setResetTarget(null)} onSaved={setNotice} />
    <DeleteCameraDialog camera={deleteTarget} token={token} onClose={() => setDeleteTarget(null)} onDeleted={onReloadCameras} />
  </main>
}
