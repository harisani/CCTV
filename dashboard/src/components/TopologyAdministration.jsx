/* Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4 */
import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
} from '@mui/material'
import AccountTreeOutlinedIcon from '@mui/icons-material/AccountTreeOutlined'
import AddIcon from '@mui/icons-material/Add'
import DomainOutlinedIcon from '@mui/icons-material/DomainOutlined'
import LinkOutlinedIcon from '@mui/icons-material/LinkOutlined'
import VideocamOutlinedIcon from '@mui/icons-material/VideocamOutlined'
import { api } from '../api'
import {
  cameraRoleLabels,
  parseNormalizedPoints,
  topologyIndex,
  zonePath,
} from '../topology'

const emptyGraph = {
  buildings: [],
  zones: [],
  camera_mappings: [],
  adjacencies: [],
  virtual_lines: [],
}

function FacilityDialog({ kind, open, token, buildings, onClose, onSaved }) {
  const [form, setForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    setError('')
    setForm(kind === 'building'
      ? { code: '', name: '', address: '', timezone: 'Asia/Jakarta', enabled: true }
      : {
          building_id: buildings[0]?.id || '',
          code: '',
          name: '',
          floor_name: '',
          area_name: '',
          room_name: '',
          roi: '',
          sensitivity: 'STANDARD',
          processing_priority: 'NORMAL',
          retention_days: 90,
          enabled: true,
        })
  }, [open, kind, buildings])

  const update = field => event => setForm(current => ({
    ...current,
    [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value,
  }))
  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const payload = { ...form }
      if (kind === 'zone') {
        payload.roi_polygon = parseNormalizedPoints(payload.roi)
        payload.retention_days = Number(payload.retention_days)
        delete payload.roi
      }
      await api(`/topology/${kind === 'building' ? 'buildings' : 'zones'}`, token, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      await onSaved(kind === 'building' ? 'Gedung berhasil ditambahkan.' : 'Zona berhasil ditambahkan.')
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="md">
    <form onSubmit={submit}>
      <DialogTitle>{kind === 'building' ? 'Tambahkan gedung' : 'Tambahkan zona'}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">
          {kind === 'building'
            ? 'Gedung menjadi akar pemetaan lokasi operasional.'
            : 'Zona adalah unit perpindahan dan okupansi; koordinat ROI selalu relatif terhadap frame.'}
        </p>
        {error && <Alert severity="error">{error}</Alert>}
        <div className="admin-form-grid">
          {kind === 'zone' && <TextField className="light-field admin-form-grid__wide" select required label="Gedung" value={form.building_id || ''} onChange={update('building_id')}>
            {buildings.filter(item => item.enabled).map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
          </TextField>}
          <TextField className="light-field" required label="Kode" value={form.code || ''} onChange={update('code')} helperText="Huruf, angka, titik, strip, atau underscore." />
          <TextField className="light-field" required label="Nama" value={form.name || ''} onChange={update('name')} />
          {kind === 'building'
            ? <>
                <TextField className="light-field admin-form-grid__wide" label="Alamat" value={form.address || ''} onChange={update('address')} />
                <TextField className="light-field" required label="Timezone" value={form.timezone || ''} onChange={update('timezone')} />
              </>
            : <>
                <TextField className="light-field" label="Lantai" value={form.floor_name || ''} onChange={update('floor_name')} />
                <TextField className="light-field" label="Area" value={form.area_name || ''} onChange={update('area_name')} />
                <TextField className="light-field" label="Ruang" value={form.room_name || ''} onChange={update('room_name')} />
                <TextField className="light-field" select label="Sensitivitas" value={form.sensitivity || 'STANDARD'} onChange={update('sensitivity')}>
                  {['STANDARD', 'RESTRICTED', 'CRITICAL'].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
                </TextField>
                <TextField className="light-field" select label="Prioritas pemrosesan" value={form.processing_priority || 'NORMAL'} onChange={update('processing_priority')}>
                  {['LOW', 'NORMAL', 'HIGH'].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
                </TextField>
                <TextField className="light-field" type="number" label="Retensi (hari)" value={form.retention_days || 90} onChange={update('retention_days')} inputProps={{ min: 1, max: 3650 }} />
                <TextField className="light-field admin-form-grid__wide" multiline minRows={3} label="ROI polygon (opsional)" value={form.roi || ''} onChange={update('roi')} placeholder={'0.10,0.20\n0.80,0.20\n0.80,0.90'} helperText="Satu titik x,y per baris. Nilai 0–1 agar tidak bergantung resolusi kamera." />
              </>}
          <FormControlLabel control={<Checkbox checked={Boolean(form.enabled)} onChange={update('enabled')} />} label="Aktif" />
        </div>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Batal</Button>
        <Button type="submit" variant="contained" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan'}</Button>
      </DialogActions>
    </form>
  </Dialog>
}

function CameraTopologyDialog({ kind, open, token, cameras, zones, onClose, onSaved }) {
  const [form, setForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    setError('')
    setForm(kind === 'role'
      ? { camera_id: cameras[0]?.id || '', role: 'TRANSITION', enabled: true }
      : {
          camera_id: cameras[0]?.id || '',
          zone_id: zones[0]?.id || '',
          coverage: '',
          is_primary: false,
          enabled: true,
        })
  }, [open, kind, cameras, zones])
  const update = field => event => setForm(current => ({
    ...current,
    [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value,
  }))
  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const payload = { ...form }
      if (kind === 'coverage') {
        payload.coverage_polygon = parseNormalizedPoints(payload.coverage)
        delete payload.coverage
      }
      await api(
        `/topology/${kind === 'role' ? 'camera-roles' : 'camera-zone-mappings'}`,
        token,
        { method: 'POST', body: JSON.stringify(payload) },
      )
      await onSaved(kind === 'role' ? 'Peran kamera ditambahkan.' : 'Cakupan kamera ditambahkan.')
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }
  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="sm">
    <form onSubmit={submit}>
      <DialogTitle>{kind === 'role' ? 'Tetapkan peran kamera' : 'Petakan kamera ke zona'}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">{kind === 'role' ? 'Satu kamera dapat memiliki beberapa peran.' : 'Kamera dapat mencakup lebih dari satu zona, tetapi hanya satu yang menjadi zona utama.'}</p>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack spacing={2}>
          <TextField className="light-field" select required label="Kamera" value={form.camera_id || ''} onChange={update('camera_id')}>
            {cameras.filter(item => item.enabled).map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
          </TextField>
          {kind === 'role'
            ? <TextField className="light-field" select required label="Peran" value={form.role || 'TRANSITION'} onChange={update('role')}>
                {Object.entries(cameraRoleLabels).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
              </TextField>
            : <>
                <TextField className="light-field" select required label="Zona" value={form.zone_id || ''} onChange={update('zone_id')}>
                  {zones.filter(item => item.enabled).map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
                </TextField>
                <TextField className="light-field" multiline minRows={3} label="Coverage polygon (opsional)" value={form.coverage || ''} onChange={update('coverage')} placeholder={'0.10,0.10\n0.90,0.10\n0.90,0.90'} helperText="Koordinat normalized 0–1, satu x,y per baris." />
                <FormControlLabel control={<Checkbox checked={Boolean(form.is_primary)} onChange={update('is_primary')} />} label="Zona utama kamera" />
              </>}
          <FormControlLabel control={<Checkbox checked={Boolean(form.enabled)} onChange={update('enabled')} />} label="Aktif" />
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Batal</Button><Button type="submit" variant="contained" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan'}</Button></DialogActions>
    </form>
  </Dialog>
}

function TransitionDialog({ kind, open, token, cameras, zones, onClose, onSaved }) {
  const [form, setForm] = useState({})
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!open) return
    setError('')
    setForm(kind === 'adjacency'
      ? {
          source_zone_id: zones[0]?.id || '',
          target_zone_id: zones[1]?.id || '',
          minimum_travel_seconds: 0,
          maximum_travel_seconds: 300,
          bidirectional: true,
          enabled: true,
        }
      : {
          camera_id: cameras[0]?.id || '',
          line_key: '',
          name: '',
          line_type: 'horizontal',
          position_percent: 50,
          points: '',
          enter_direction: 'down',
          from_zone_id: '',
          to_zone_id: '',
          is_primary: false,
          display_order: 0,
          enabled: true,
        })
  }, [open, kind, cameras, zones])
  const update = field => event => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm(current => field === 'line_type'
      ? { ...current, line_type: value, enter_direction: value === 'vertical' ? 'right' : 'down' }
      : { ...current, [field]: value })
  }
  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      const payload = { ...form }
      if (kind === 'adjacency') {
        payload.minimum_travel_seconds = Number(payload.minimum_travel_seconds)
        payload.maximum_travel_seconds = Number(payload.maximum_travel_seconds)
      } else {
        payload.position = payload.line_type === 'polygon' ? null : Number(payload.position_percent) / 100
        payload.points = payload.line_type === 'polygon' ? parseNormalizedPoints(payload.points) : null
        payload.from_zone_id = payload.from_zone_id || null
        payload.to_zone_id = payload.to_zone_id || null
        payload.display_order = Number(payload.display_order) || 0
        delete payload.position_percent
      }
      await api(`/topology/${kind === 'adjacency' ? 'adjacencies' : 'virtual-lines'}`, token, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      await onSaved(kind === 'adjacency' ? 'Jalur antarzona ditambahkan.' : 'Virtual line ditambahkan.')
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }
  const directionOptions = form.line_type === 'vertical' ? ['left', 'right'] : ['up', 'down']
  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="md">
    <form onSubmit={submit}>
      <DialogTitle>{kind === 'adjacency' ? 'Hubungkan zona' : 'Tambahkan virtual line'}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">{kind === 'adjacency' ? 'Waktu perjalanan menjadi batas untuk menolak korelasi kamera yang tidak masuk akal.' : 'Buat adjacency terlebih dahulu bila garis menghubungkan dua zona internal.'}</p>
        {error && <Alert severity="error">{error}</Alert>}
        <div className="admin-form-grid">
          {kind === 'adjacency'
            ? <>
                <TextField className="light-field" select required label="Zona asal" value={form.source_zone_id || ''} onChange={update('source_zone_id')}>
                  {zones.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
                </TextField>
                <TextField className="light-field" select required label="Zona tujuan" value={form.target_zone_id || ''} onChange={update('target_zone_id')}>
                  {zones.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
                </TextField>
                <TextField className="light-field" type="number" label="Minimum perjalanan (detik)" value={form.minimum_travel_seconds ?? 0} onChange={update('minimum_travel_seconds')} inputProps={{ min: 0 }} />
                <TextField className="light-field" type="number" label="Maksimum perjalanan (detik)" value={form.maximum_travel_seconds ?? 300} onChange={update('maximum_travel_seconds')} inputProps={{ min: 0 }} />
                <FormControlLabel control={<Checkbox checked={Boolean(form.bidirectional)} onChange={update('bidirectional')} />} label="Berlaku dua arah" />
              </>
            : <>
                <TextField className="light-field admin-form-grid__wide" select required label="Kamera" value={form.camera_id || ''} onChange={update('camera_id')}>
                  {cameras.filter(item => item.enabled).map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
                </TextField>
                <TextField className="light-field" required label="Kunci garis" value={form.line_key || ''} onChange={update('line_key')} helperText="Contoh: mixing-entry" />
                <TextField className="light-field" required label="Nama garis" value={form.name || ''} onChange={update('name')} />
                <TextField className="light-field" select label="Tipe" value={form.line_type || 'horizontal'} onChange={update('line_type')}>
                  {['horizontal', 'vertical', 'polygon'].map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
                </TextField>
                {form.line_type !== 'polygon' && <TextField className="light-field" type="number" label="Posisi (%)" value={form.position_percent ?? 50} onChange={update('position_percent')} inputProps={{ min: 0, max: 100 }} />}
                {form.line_type === 'polygon' && <TextField className="light-field admin-form-grid__wide" multiline minRows={3} required label="Titik polygon" value={form.points || ''} onChange={update('points')} placeholder={'0.10,0.20\n0.80,0.20\n0.80,0.90'} />}
                <TextField className="light-field" select label="Arah ENTER" value={form.enter_direction || directionOptions[0]} onChange={update('enter_direction')}>
                  {directionOptions.map(value => <MenuItem key={value} value={value}>{value}</MenuItem>)}
                </TextField>
                <TextField className="light-field" select label="Zona asal (opsional)" value={form.from_zone_id || ''} onChange={update('from_zone_id')}>
                  <MenuItem value="">Di luar area</MenuItem>
                  {zones.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
                </TextField>
                <TextField className="light-field" select label="Zona tujuan (opsional)" value={form.to_zone_id || ''} onChange={update('to_zone_id')}>
                  <MenuItem value="">Di luar area</MenuItem>
                  {zones.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
                </TextField>
                <FormControlLabel control={<Checkbox checked={Boolean(form.is_primary)} onChange={update('is_primary')} />} label="Garis utama kamera" />
              </>}
          <FormControlLabel control={<Checkbox checked={Boolean(form.enabled)} onChange={update('enabled')} />} label="Aktif" />
        </div>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Batal</Button><Button type="submit" variant="contained" disabled={saving}>{saving ? 'Menyimpan…' : 'Simpan'}</Button></DialogActions>
    </form>
  </Dialog>
}

export default function TopologyAdministration({ token, cameras }) {
  const [view, setView] = useState('zones')
  const [graph, setGraph] = useState(emptyGraph)
  const [roles, setRoles] = useState([])
  const [validation, setValidation] = useState({ valid: true, errors: [], warnings: [] })
  const [dialog, setDialog] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const [nextGraph, nextRoles, nextValidation] = await Promise.all([
        api('/topology/graph', token),
        api('/topology/camera-roles', token),
        api('/topology/validate', token),
      ])
      setGraph(nextGraph)
      setRoles(nextRoles)
      setValidation(nextValidation)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [token])

  const index = useMemo(() => topologyIndex(graph), [graph])
  const camerasById = useMemo(() => new Map(cameras.map(item => [item.id, item])), [cameras])
  const onSaved = async message => {
    setNotice(message)
    await load()
  }
  const deactivate = async (path, message) => {
    setError('')
    try {
      await api(path, token, { method: 'PATCH', body: JSON.stringify({ enabled: false }) })
      await onSaved(message)
    } catch (err) {
      setError(err.message)
    }
  }
  const archive = async (path, message) => {
    setError('')
    try {
      await api(path, token, { method: 'DELETE' })
      await onSaved(message)
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading && !graph.buildings.length) return <div className="topology-loading"><CircularProgress size={22} /><span>Memuat topologi fasilitas…</span></div>

  return <section className="admin-section topology-admin">
    <div className="section-heading">
      <div>
        <h2 className="section-title">Topologi fasilitas</h2>
        <p className="section-copy">Hubungkan lokasi fisik dengan kamera dan jalur perpindahan yang mungkin.</p>
      </div>
      <div className="topology-readiness" data-valid={validation.valid}>
        <AccountTreeOutlinedIcon fontSize="small" />
        <span>{validation.valid ? 'Struktur valid' : `${validation.errors.length} masalah`}</span>
      </div>
    </div>
    {error && <Alert className="error-banner" severity="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert className="error-banner" severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    {validation.warnings.length > 0 && <Alert className="topology-warning" severity="warning">
      {validation.warnings.slice(0, 3).join(' · ')}
    </Alert>}
    <div className="topology-stats" aria-label="Ringkasan topologi">
      <span><strong>{graph.buildings.filter(item => item.enabled).length}</strong> gedung</span>
      <span><strong>{graph.zones.filter(item => item.enabled).length}</strong> zona</span>
      <span><strong>{graph.camera_mappings.filter(item => item.enabled).length}</strong> cakupan</span>
      <span><strong>{graph.adjacencies.filter(item => item.enabled).length}</strong> jalur</span>
    </div>
    <Tabs className="topology-tabs" value={view} onChange={(_, value) => setView(value)} variant="scrollable" scrollButtons="auto">
      <Tab value="zones" label="Gedung & zona" icon={<DomainOutlinedIcon />} iconPosition="start" />
      <Tab value="cameras" label="Peran & cakupan" icon={<VideocamOutlinedIcon />} iconPosition="start" />
      <Tab value="transitions" label="Jalur & garis" icon={<LinkOutlinedIcon />} iconPosition="start" />
    </Tabs>

    {view === 'zones' && <div className="topology-workbench">
      <div className="section-heading topology-actions">
        <div><h3>Lokasi terstruktur</h3><p>Arsipkan lokasi yang tidak digunakan; histori lama tetap aman.</p></div>
        <div className="row-actions">
          <Button variant="outlined" startIcon={<AddIcon />} onClick={() => setDialog('building')}>Gedung</Button>
          <Button variant="contained" startIcon={<AddIcon />} disabled={!graph.buildings.some(item => item.enabled)} onClick={() => setDialog('zone')}>Zona</Button>
        </div>
      </div>
      <div className="ledger-table-wrap"><table className="ledger-table admin-table"><thead><tr><th>Zona</th><th>Lokasi</th><th>Kebijakan</th><th>Status</th><th>Aksi</th></tr></thead><tbody>
        {graph.zones.map(zone => <tr key={zone.id}>
          <td data-label="Zona"><strong>{zone.name}</strong><span className="table-secondary">{zone.code}</span></td>
          <td data-label="Lokasi">{zonePath(zone, index.buildings)}</td>
          <td data-label="Kebijakan">{zone.sensitivity} · {zone.processing_priority} · {zone.retention_days} hari</td>
          <td data-label="Status">{zone.enabled ? 'Aktif' : 'Arsip'}</td>
          <td data-label="Aksi">{zone.enabled && <Button size="small" color="warning" onClick={() => archive(`/topology/zones/${zone.id}`, 'Zona dinonaktifkan.')}>Nonaktifkan</Button>}</td>
        </tr>)}
        {!graph.zones.length && <tr><td colSpan="5"><p className="empty-copy">Belum ada zona. Tambahkan gedung terlebih dahulu.</p></td></tr>}
      </tbody></table></div>
      <div className="topology-building-list">
        {graph.buildings.map(building => <div key={building.id}>
          <span><strong>{building.name}</strong><small>{building.code} · {building.timezone}</small></span>
          <Chip size="small" label={building.enabled ? 'Aktif' : 'Arsip'} />
          {building.enabled && <Button size="small" color="warning" onClick={() => archive(`/topology/buildings/${building.id}`, 'Gedung dan zonanya dinonaktifkan.')}>Nonaktifkan</Button>}
        </div>)}
      </div>
    </div>}

    {view === 'cameras' && <div className="topology-workbench">
      <div className="section-heading topology-actions">
        <div><h3>Kamera dalam konteks</h3><p>Tetapkan fungsi kamera dan zona yang benar-benar terlihat.</p></div>
        <div className="row-actions">
          <Button variant="outlined" startIcon={<AddIcon />} onClick={() => setDialog('role')}>Peran</Button>
          <Button variant="contained" startIcon={<AddIcon />} disabled={!graph.zones.some(item => item.enabled)} onClick={() => setDialog('coverage')}>Cakupan</Button>
        </div>
      </div>
      <div className="topology-camera-grid">
        {cameras.map(camera => {
          const cameraRoles = roles.filter(item => item.camera_id === camera.id && item.enabled)
          const mappings = graph.camera_mappings.filter(item => item.camera_id === camera.id && item.enabled)
          return <article key={camera.id}>
            <header><span><strong>{camera.name}</strong><small>{camera.location || 'Lokasi belum dipetakan'}</small></span><Chip size="small" label={camera.status} /></header>
            <dl>
              <div><dt>Peran</dt><dd>{cameraRoles.length ? cameraRoles.map(item => cameraRoleLabels[item.role]).join(', ') : 'Belum ditetapkan'}</dd></div>
              <div><dt>Zona</dt><dd>{mappings.length ? mappings.map(item => index.zones.get(item.zone_id)?.name || 'Zona').join(', ') : 'Belum dipetakan'}</dd></div>
            </dl>
            <div className="topology-chip-row">
              {cameraRoles.map(item => <Chip key={item.id} size="small" label={cameraRoleLabels[item.role]} onDelete={() => deactivate(`/topology/camera-roles/${item.id}`, 'Peran kamera dinonaktifkan.')} />)}
              {mappings.map(item => <Chip key={item.id} size="small" variant="outlined" label={`${item.is_primary ? 'Utama · ' : ''}${index.zones.get(item.zone_id)?.name || 'Zona'}`} onDelete={() => deactivate(`/topology/camera-zone-mappings/${item.id}`, 'Cakupan kamera dinonaktifkan.')} />)}
            </div>
          </article>
        })}
      </div>
    </div>}

    {view === 'transitions' && <div className="topology-workbench">
      <div className="section-heading topology-actions">
        <div><h3>Perpindahan yang mungkin</h3><p>Virtual line hanya boleh menghubungkan zona yang bersebelahan.</p></div>
        <div className="row-actions">
          <Button variant="outlined" startIcon={<AddIcon />} disabled={graph.zones.length < 2} onClick={() => setDialog('adjacency')}>Hubungkan zona</Button>
          <Button variant="contained" startIcon={<AddIcon />} disabled={!graph.camera_mappings.some(item => item.enabled)} onClick={() => setDialog('line')}>Virtual line</Button>
        </div>
      </div>
      <div className="topology-route-list">
        {graph.adjacencies.map(route => <article key={route.id} data-enabled={route.enabled}>
          <AccountTreeOutlinedIcon />
          <span><strong>{index.zones.get(route.source_zone_id)?.name || 'Zona'} → {index.zones.get(route.target_zone_id)?.name || 'Zona'}</strong><small>{route.bidirectional ? 'Dua arah' : 'Satu arah'} · {route.minimum_travel_seconds}–{route.maximum_travel_seconds} detik</small></span>
          {route.enabled && <Button size="small" color="warning" onClick={() => deactivate(`/topology/adjacencies/${route.id}`, 'Jalur dinonaktifkan.')}>Nonaktifkan</Button>}
        </article>)}
        {!graph.adjacencies.length && <p className="empty-copy">Belum ada adjacency antarzona.</p>}
      </div>
      <div className="ledger-table-wrap topology-line-table"><table className="ledger-table admin-table"><thead><tr><th>Virtual line</th><th>Kamera</th><th>Transisi</th><th>Geometri</th><th>Aksi</th></tr></thead><tbody>
        {graph.virtual_lines.map(line => <tr key={line.id}>
          <td data-label="Virtual line"><strong>{line.name}</strong><span className="table-secondary">{line.line_key}{line.is_primary ? ' · utama' : ''}</span></td>
          <td data-label="Kamera">{camerasById.get(line.camera_id)?.name || 'Kamera tidak tersedia'}</td>
          <td data-label="Transisi">{index.zones.get(line.from_zone_id)?.name || 'Luar'} → {index.zones.get(line.to_zone_id)?.name || 'Luar'}</td>
          <td data-label="Geometri">{line.line_type}{line.position != null ? ` · ${Math.round(line.position * 100)}%` : ''} · {line.enter_direction}</td>
          <td data-label="Aksi">{line.enabled && <Button size="small" color="warning" onClick={() => deactivate(`/topology/virtual-lines/${line.id}`, 'Virtual line dinonaktifkan.')}>Nonaktifkan</Button>}</td>
        </tr>)}
        {!graph.virtual_lines.length && <tr><td colSpan="5"><p className="empty-copy">Belum ada virtual line.</p></td></tr>}
      </tbody></table></div>
    </div>}

    <FacilityDialog kind={dialog} open={['building', 'zone'].includes(dialog)} token={token} buildings={graph.buildings} onClose={() => setDialog(null)} onSaved={onSaved} />
    <CameraTopologyDialog kind={dialog} open={['role', 'coverage'].includes(dialog)} token={token} cameras={cameras} zones={graph.zones} onClose={() => setDialog(null)} onSaved={onSaved} />
    <TransitionDialog kind={dialog} open={['adjacency', 'line'].includes(dialog)} token={token} cameras={cameras} zones={graph.zones} onClose={() => setDialog(null)} onSaved={onSaved} />
  </section>
}
