/* Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V4 */
import { useCallback, useEffect, useMemo, useState } from 'react'
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
  TextField,
} from '@mui/material'
import CallMergeOutlinedIcon from '@mui/icons-material/CallMergeOutlined'
import CallSplitOutlinedIcon from '@mui/icons-material/CallSplitOutlined'
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined'
import { api } from '../api'

const personLabel = person => person.display_name || `Person ${person.reid_key?.slice(0, 8) || person.id.slice(0, 8)}`
const dateTime = value => value ? new Date(value).toLocaleString('id-ID') : 'Masih aktif'

export default function IdentityAdministration({ token }) {
  const [persons, setPersons] = useState([])
  const [config, setConfig] = useState(null)
  const [targetId, setTargetId] = useState('')
  const [sourceIds, setSourceIds] = useState([])
  const [splitPersonId, setSplitPersonId] = useState('')
  const [trackings, setTrackings] = useState([])
  const [trackingIds, setTrackingIds] = useState([])
  const [splitName, setSplitName] = useState('')
  const [confirm, setConfirm] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [page, settings] = await Promise.all([
        api('/persons?limit=100', token),
        api('/persons/reid-config', token),
      ])
      setPersons(page.items)
      setConfig(settings)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!splitPersonId) {
      setTrackings([])
      setTrackingIds([])
      return
    }
    setError('')
    api(`/persons/${splitPersonId}/trackings`, token)
      .then(items => {
        setTrackings(items)
        setTrackingIds([])
      })
      .catch(err => setError(err.message))
  }, [splitPersonId, token])

  const reviewCount = useMemo(() => persons.filter(person => person.needs_review).length, [persons])
  const target = persons.find(person => person.id === targetId)
  const sources = persons.filter(person => sourceIds.includes(person.id))
  const splitPerson = persons.find(person => person.id === splitPersonId)
  const selectedTrackings = trackings.filter(tracking => trackingIds.includes(tracking.id))

  const toggleSource = id => setSourceIds(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id])
  const toggleTracking = id => setTrackingIds(current => current.includes(id) ? current.filter(item => item !== id) : [...current, id])

  const runConfirmed = async () => {
    setSaving(true)
    setError('')
    try {
      if (confirm === 'merge') {
        await api('/persons/merge', token, {
          method: 'POST',
          body: JSON.stringify({ target_person_id: targetId, source_person_ids: sourceIds }),
        })
        setNotice(`${sourceIds.length} identitas digabung ke ${personLabel(target)}. Histori tetap tersimpan.`)
        setTargetId('')
        setSourceIds([])
      } else {
        await api(`/persons/${splitPersonId}/split`, token, {
          method: 'POST',
          body: JSON.stringify({ tracking_ids: trackingIds, display_name: splitName || null }),
        })
        setNotice(`${trackingIds.length} sesi dipisahkan menjadi identitas baru.`)
        setSplitPersonId('')
        setSplitName('')
      }
      setConfirm(null)
      await load()
    } catch (err) {
      setConfirm(null)
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return <section className="admin-section reid-admin" aria-labelledby="reid-admin-title">
    <div className="section-heading">
      <div>
        <h2 className="section-title" id="reid-admin-title">Koreksi identitas ReID</h2>
        <p className="section-copy">Tinjau hasil pencocokan pakaian/APD tanpa menghapus event, snapshot, atau perjalanan orang.</p>
      </div>
      <Button className="action-button" startIcon={<RefreshOutlinedIcon />} disabled={loading} onClick={load}>Muat ulang</Button>
    </div>
    {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
    {loading && <div className="reid-loading" role="status"><CircularProgress size={22} /><span>Memuat identitas…</span></div>}

    {!loading && <>
      <div className="reid-policy" aria-label="Kebijakan pencocokan aktif">
        <div><span>Threshold</span><strong>{config?.similarity_threshold?.toFixed(2)}</strong></div>
        <div><span>Margin ambigu</span><strong>{config?.ambiguity_margin?.toFixed(2)}</strong></div>
        <div><span>Retensi</span><strong>{config?.retention_days} hari</strong></div>
        <div><span>Perlu ditinjau</span><strong>{reviewCount}</strong></div>
      </div>

      <div className="reid-workbench">
        <section className="reid-operation" aria-labelledby="merge-title">
          <div className="reid-operation__heading">
            <CallMergeOutlinedIcon aria-hidden="true" />
            <div><h3 id="merge-title">Gabungkan identitas</h3><p>Gunakan jika dua ID ternyata orang yang sama.</p></div>
          </div>
          <TextField className="light-field" select fullWidth label="Identitas utama" value={targetId} onChange={event => { setTargetId(event.target.value); setSourceIds(current => current.filter(id => id !== event.target.value)) }}>
            {persons.map(person => <MenuItem key={person.id} value={person.id}>{personLabel(person)} · {person.embedding_count} template</MenuItem>)}
          </TextField>
          <div className="reid-selection-list" aria-label="Identitas yang akan digabung">
            {persons.filter(person => person.id !== targetId).map(person => <FormControlLabel key={person.id}
              control={<Checkbox checked={sourceIds.includes(person.id)} onChange={() => toggleSource(person.id)} />}
              label={<span><strong>{personLabel(person)}</strong><small>{person.tracking_count} tracking · {person.embedding_count} template {person.needs_review ? '· perlu ditinjau' : ''}</small></span>}
            />)}
            {!persons.length && <p className="empty-copy">Belum ada identitas untuk digabung.</p>}
          </div>
          <Button variant="contained" startIcon={<CallMergeOutlinedIcon />} disabled={!targetId || !sourceIds.length || saving} onClick={() => setConfirm('merge')}>Tinjau penggabungan</Button>
        </section>

        <section className="reid-operation" aria-labelledby="split-title">
          <div className="reid-operation__heading">
            <CallSplitOutlinedIcon aria-hidden="true" />
            <div><h3 id="split-title">Pisahkan identitas</h3><p>Gunakan jika satu ID berisi perjalanan orang berbeda.</p></div>
          </div>
          <TextField className="light-field" select fullWidth label="Identitas sumber" value={splitPersonId} onChange={event => setSplitPersonId(event.target.value)}>
            {persons.map(person => <MenuItem key={person.id} value={person.id}>{personLabel(person)} · {person.tracking_count} tracking</MenuItem>)}
          </TextField>
          <TextField className="light-field" fullWidth label="Nama identitas baru (opsional)" value={splitName} onChange={event => setSplitName(event.target.value)} />
          <div className="reid-selection-list" aria-label="Tracking yang akan dipisahkan">
            {trackings.map(tracking => <FormControlLabel key={tracking.id} disabled={tracking.is_active}
              control={<Checkbox checked={trackingIds.includes(tracking.id)} onChange={() => toggleTracking(tracking.id)} />}
              label={<span><strong>Track #{tracking.byte_track_id}</strong><small>{dateTime(tracking.started_at)} · {tracking.event_count} event · {tracking.embedding_count} template{tracking.is_active ? ' · sedang aktif' : ''}</small></span>}
            />)}
            {splitPersonId && !trackings.length && <p className="empty-copy">Identitas ini belum memiliki histori tracking.</p>}
          </div>
          <Button variant="contained" startIcon={<CallSplitOutlinedIcon />} disabled={!splitPersonId || !trackingIds.length || saving} onClick={() => setConfirm('split')}>Tinjau pemisahan</Button>
        </section>
      </div>
    </>}

    <Dialog className="admin-dialog" open={Boolean(confirm)} onClose={() => !saving && setConfirm(null)} fullWidth maxWidth="sm">
      <DialogTitle>{confirm === 'merge' ? 'Konfirmasi penggabungan' : 'Konfirmasi pemisahan'}</DialogTitle>
      <DialogContent>
        {confirm === 'merge' ? <p className="dialog-intro"><strong>{sources.map(personLabel).join(', ')}</strong> akan dialihkan ke <strong>{target ? personLabel(target) : 'identitas utama'}</strong>. Semua tracking, event, dan snapshot tetap tersedia. Tindakan dicatat di audit log.</p>
          : <p className="dialog-intro"><strong>{selectedTrackings.length} tracking</strong> akan dipindahkan dari <strong>{splitPerson ? personLabel(splitPerson) : 'identitas sumber'}</strong> ke identitas baru. Tindakan dicatat di audit log.</p>}
      </DialogContent>
      <DialogActions><Button disabled={saving} onClick={() => setConfirm(null)}>Batal</Button><Button variant="contained" disabled={saving} onClick={runConfirmed}>{saving ? 'Memproses…' : 'Konfirmasi'}</Button></DialogActions>
    </Dialog>
  </section>
}
