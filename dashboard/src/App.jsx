import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  InputAdornment,
  Stack,
  TablePagination,
  TextField,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import LogoutIcon from '@mui/icons-material/Logout'
import SearchIcon from '@mui/icons-material/Search'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined'
import CameraSidebar from './components/CameraSidebar'
import LiveGrid from './components/LiveGrid'
import Administration from './components/Administration'
import { api, login, requestSnapshotBlob } from './api'
import { createSnapshotPreviewManager } from './snapshotPreview'
import { useDashboardSocket } from './useDashboardSocket'

const formatDateTime = value => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('id-ID')
}

function Login({ onLogin }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async event => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      onLogin((await login(username, password)).access_token)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return <main className="login-shell">
    <section className="login-context" aria-labelledby="login-context-title">
      <div>
        <h1 id="login-context-title">Satu ruang kendali. Semua kamera.</h1>
        <p>Pantau pergerakan orang, kondisi kamera, dan event lintas garis dari satu layar operasional.</p>
      </div>
    </section>
    <section className="login-panel">
      <form className="login-form" onSubmit={submit}>
        <h2>Masuk ke ruang kendali</h2>
        <p>Gunakan akun operator yang dikonfigurasi pada server.</p>
        <Stack spacing={2}>
          <TextField
            className="light-field"
            label="Username"
            value={username}
            onChange={event => setUsername(event.target.value)}
            autoComplete="username"
            required
            fullWidth
          />
          <TextField
            className="light-field"
            label="Password"
            type="password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            autoComplete="current-password"
            error={Boolean(error)}
            helperText={error || ' '}
            required
            fullWidth
          />
          <Button className="login-submit" type="submit" variant="contained" disabled={loading}>
            {loading ? 'Memeriksa akun…' : 'Masuk'}
          </Button>
        </Stack>
      </form>
    </section>
  </main>
}

function PasswordChangeDialog({ open, token, onChanged }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const submit = async event => {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      const result = await api('/auth/change-password', token, {
        method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      onChanged(result.access_token)
      setCurrentPassword('')
      setNewPassword('')
    } catch (err) { setError(err.message) } finally { setLoading(false) }
  }
  return <Dialog className="admin-dialog" open={open} disableEscapeKeyDown fullWidth maxWidth="xs">
    <form onSubmit={submit}>
      <DialogTitle>Ganti password sementara</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">Sebelum melanjutkan, buat password pribadi minimal 12 karakter.</p>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack spacing={2}>
          <TextField className="light-field" type="password" label="Password sementara" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} required />
          <TextField className="light-field" type="password" label="Password baru" value={newPassword} onChange={event => setNewPassword(event.target.value)} helperText="Minimal 12 karakter" required />
        </Stack>
      </DialogContent>
      <DialogActions><Button type="submit" variant="contained" disabled={loading}>{loading ? 'Mengganti…' : 'Ganti password'}</Button></DialogActions>
    </form>
  </Dialog>
}

function Metric({ label, value, tone = 'neutral' }) {
  return <div className="metric-cell tnum" data-tone={tone}>
    <span>{label}</span>
    <strong aria-live="polite">{value}</strong>
  </div>
}

function EventHistory({ events, total, page, rowsPerPage, date, onDate, onPage, onRowsPerPage, onSnapshot }) {
  return <section className="event-ledger" id="event-history" aria-labelledby="event-history-title">
    <div className="section-heading">
      <div>
        <h2 className="section-title" id="event-history-title">Riwayat pergerakan</h2>
        <p className="section-copy">Event terbaru dari seluruh kamera aktif.</p>
      </div>
      <TextField
        className="light-field"
        size="small"
        type="date"
        label="Tanggal event"
        InputLabelProps={{ shrink: true }}
        value={date}
        onChange={event => onDate(event.target.value)}
      />
    </div>
    <div className="ledger-table-wrap">
      <table className="ledger-table">
        <thead>
          <tr>
            <th>Waktu</th>
            <th>Kamera</th>
            <th>Lokasi</th>
            <th>Status</th>
            <th>Tracking</th>
            <th>Snapshot</th>
          </tr>
        </thead>
        <tbody>
          {events.map(event => <tr key={event.id}>
            <td data-label="Waktu">{formatDateTime(event.occurred_at)}</td>
            <td data-label="Kamera">{event.camera_name || '—'}</td>
            <td data-label="Lokasi">{event.camera_location || '—'}</td>
            <td data-label="Status">
              <span className="event-status" data-event={event.event_type}>
                <span className="status-dot" data-status={event.event_type === 'ENTER' ? 'ONLINE' : 'ERROR'} />
                {event.event_type === 'ENTER' ? 'MASUK' : 'KELUAR'}
              </span>
            </td>
            <td data-label="Tracking">#{event.byte_track_id ?? event.tracking_id ?? '—'}</td>
            <td data-label="Snapshot">
              <Button
                className="action-button"
                size="small"
                variant="outlined"
                onClick={() => onSnapshot(event.snapshot_id)}
                disabled={!event.snapshot_id}
              >
                Lihat foto
              </Button>
            </td>
          </tr>)}
          {!events.length && <tr><td colSpan="6"><p className="empty-copy">Belum ada event untuk filter ini.</p></td></tr>}
        </tbody>
      </table>
    </div>
    <TablePagination
      component="div"
      count={total}
      page={page}
      rowsPerPage={rowsPerPage}
      rowsPerPageOptions={[10, 20, 50]}
      labelRowsPerPage="Baris"
      onPageChange={(_, value) => onPage(value)}
      onRowsPerPageChange={event => onRowsPerPage(Number(event.target.value))}
    />
  </section>
}

function IdentityPanel({ persons, search, onSearch }) {
  return <aside className="identity-panel" id="identity-panel" aria-labelledby="identity-title">
    <div>
      <h2 className="section-title" id="identity-title">Identitas terakhir</h2>
      <p className="section-copy">Cari nama atau kunci ReID.</p>
    </div>
    <TextField
      className="light-field"
      fullWidth
      size="small"
      label="Nama / ReID key"
      value={search}
      onChange={event => onSearch(event.target.value)}
      InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
    />
    <ul className="person-list">
      {persons.map(person => {
        const label = person.display_name || person.reid_key || 'Tanpa nama'
        return <li key={person.id}>
          <span className="person-avatar" aria-hidden="true">{label.slice(0, 2).toUpperCase()}</span>
          <div className="person-meta">
            <strong>{label}</strong>
            <span>Terlihat {formatDateTime(person.last_seen_at)}</span>
          </div>
        </li>
      })}
    </ul>
    {!persons.length && <p className="empty-copy">Identitas tidak ditemukan.</p>}
  </aside>
}

function CommandPalette({ open, query, activeIndex, items, onQuery, onActiveIndex, onChoose, onClose }) {
  const inputRef = useRef(null)

  useEffect(() => {
    if (open) window.setTimeout(() => inputRef.current?.focus(), 0)
  }, [open])

  const handleKeyDown = event => {
    if (!items.length) return
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      onActiveIndex((activeIndex + 1) % items.length)
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      onActiveIndex((activeIndex - 1 + items.length) % items.length)
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      onChoose(items[activeIndex] || items[0])
    }
  }

  const groups = items.reduce((result, item, index) => {
    result[item.group] = [...(result[item.group] || []), { ...item, flatIndex: index }]
    return result
  }, {})

  return <Dialog className="command-dialog" open={open} onClose={onClose} fullWidth maxWidth="sm">
    <div className="command-dialog__head">
      <SearchIcon aria-hidden="true" />
      <input
        ref={inputRef}
        value={query}
        onChange={event => { onQuery(event.target.value); onActiveIndex(0) }}
        onKeyDown={handleKeyDown}
        placeholder="Cari kamera, orang, atau event…"
        aria-label="Pencarian cepat"
        aria-controls="command-results"
      />
      <kbd>esc</kbd>
    </div>
    <div className="command-results" id="command-results" role="listbox">
      {Object.entries(groups).map(([group, groupItems]) => <section key={group}>
        <p className="command-group">{group}</p>
        {groupItems.map(item => <button
          type="button"
          className="command-item"
          key={item.key}
          data-active={item.flatIndex === activeIndex}
          role="option"
          aria-selected={item.flatIndex === activeIndex}
          onMouseEnter={() => onActiveIndex(item.flatIndex)}
          onClick={() => onChoose(item)}
        >
          <span><strong>{item.label}</strong><span>{item.description}</span></span>
          <code>{item.meta}</code>
        </button>)}
      </section>)}
      {!items.length && <p className="command-empty">Tidak ada kamera, orang, atau event yang cocok.</p>}
    </div>
  </Dialog>
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('cctv-token') || '')
  const [cameras, setCameras] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [gridSize, setGridSize] = useState(4)
  const [frames, setFrames] = useState({})
  const [stats, setStats] = useState({
    enter_count: 0,
    exit_count: 0,
    current_person_count: 0,
    confirmed_person_count: 0,
    uncertain_person_count: 0,
  })
  const [events, setEvents] = useState([])
  const [eventTotal, setEventTotal] = useState(0)
  const [eventPage, setEventPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(20)
  const [persons, setPersons] = useState([])
  const [occupancy, setOccupancy] = useState({ total: 0 })
  const [cameraSearch, setCameraSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [personSearch, setPersonSearch] = useState('')
  const [date, setDate] = useState('')
  const [snapshot, setSnapshot] = useState(null)
  const [socketStatus, setSocketStatus] = useState('disconnected')
  const [error, setError] = useState('')
  const [clock, setClock] = useState(Date.now())
  const [commandOpen, setCommandOpen] = useState(false)
  const [commandQuery, setCommandQuery] = useState('')
  const [commandIndex, setCommandIndex] = useState(0)
  const [currentUser, setCurrentUser] = useState(null)
  const [page, setPage] = useState('monitoring')
  const initializedSelection = useRef(false)
  const snapshotManager = useMemo(() => createSnapshotPreviewManager({
    requestBlob: requestSnapshotBlob,
    onPreview: setSnapshot,
    onError: err => setError(err.message),
  }), [])

  useEffect(() => () => snapshotManager.dispose(), [snapshotManager])

  const loadCameras = useCallback(async () => {
    if (!token) return
    const page = await api('/camera?limit=200', token)
    setCameras(page.items)
    const validIds = new Set(page.items.filter(camera => camera.enabled).map(camera => camera.id))
    setSelectedIds(current => {
      const valid = current.filter(id => validIds.has(id)).slice(0, gridSize)
      if (valid.length || initializedSelection.current) return valid
      initializedSelection.current = true
      return page.items.filter(camera => camera.enabled).slice(0, gridSize).map(camera => camera.id)
    })
  }, [token, gridSize])

  const loadDashboard = useCallback(async () => {
    if (!token) return
    const offset = eventPage * rowsPerPage
    const dateQuery = date ? `&start_at=${date}T00:00:00Z&end_at=${date}T23:59:59Z` : ''
    const [summary, eventResult] = await Promise.all([
      api('/statistics', token),
      api(`/events?offset=${offset}&limit=${rowsPerPage}${dateQuery}`, token),
    ])
    setStats(summary)
    setEvents(eventResult.items)
    setEventTotal(eventResult.total)
  }, [token, date, eventPage, rowsPerPage])

  useEffect(() => {
    if (!token) return undefined
    Promise.all([loadCameras(), loadDashboard(), api('/auth/me', token).then(setCurrentUser)]).catch(err => setError(err.message))
    const refresh = window.setInterval(
      () => Promise.all([loadCameras(), loadDashboard()]).catch(err => setError(err.message)),
      30000,
    )
    return () => window.clearInterval(refresh)
  }, [token, loadCameras, loadDashboard])

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 5000)
    return () => window.clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!token) return
    api(`/persons?limit=20${personSearch ? `&name=${encodeURIComponent(personSearch)}` : ''}`, token)
      .then(page => setPersons(page.items))
      .catch(err => setError(err.message))
  }, [token, personSearch])

  useEffect(() => {
    const openCommand = event => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(true)
      }
    }
    window.addEventListener('keydown', openCommand)
    return () => window.removeEventListener('keydown', openCommand)
  }, [])

  useDashboardSocket(token, selectedIds, message => {
    if (message.type === 'frame') setFrames(current => ({ ...current, [message.camera_id]: { ...message, receivedAt: Date.now() } }))
    if (message.type === 'occupancy') {
      setOccupancy({ total: message.total ?? message.count ?? 0 })
    }
    if (message.type === 'camera_status') {
      setCameras(current => current.map(camera => camera.id === message.camera_id
        ? {
            ...camera,
            status: message.status,
            last_frame_at: message.last_frame_at,
            last_error: message.last_error,
          }
        : camera))
    }
    if (message.type === 'event') {
      setEvents(current => [message.payload, ...current].slice(0, rowsPerPage))
      setEventTotal(current => current + 1)
      setStats(current => ({
        ...current,
        enter_count: current.enter_count + (message.payload.event_type === 'ENTER' ? 1 : 0),
        exit_count: current.exit_count + (message.payload.event_type === 'EXIT' ? 1 : 0),
      }))
      api('/persons?limit=20', token).then(page => setPersons(page.items)).catch(() => {})
    }
    if (message.type === 'error') setError(message.detail)
  }, setSocketStatus)

  const camerasWithStatus = useMemo(() => cameras.map(camera => {
    const frame = frames[camera.id]
    const frameIsRecent = frame && clock - frame.receivedAt < 7000
    const backendOffline = camera.status === 'OFFLINE' || camera.status === 'RECONNECTING'
    return {
      ...camera,
      effectiveStatus: backendOffline ? camera.status : (frameIsRecent ? 'ONLINE' : (camera.status || 'OFFLINE')),
    }
  }), [cameras, frames, clock])

  const selectedCameras = selectedIds.map(id => camerasWithStatus.find(camera => camera.id === id)).filter(Boolean)
  const onlineCount = camerasWithStatus.filter(camera => camera.effectiveStatus === 'ONLINE').length
  const offlineCount = camerasWithStatus.length - onlineCount
  const changeGridSize = value => {
    setGridSize(value)
    setSelectedIds(current => current.slice(0, value))
  }

  const toggleCamera = cameraId => setSelectedIds(current => {
    if (current.includes(cameraId)) return current.filter(id => id !== cameraId)
    return current.length < gridSize ? [...current, cameraId] : current
  })

  const focusCamera = cameraId => {
    setSelectedIds(current => {
      if (current.includes(cameraId)) return current
      if (current.length < gridSize) return [...current, cameraId]
      return [...current.slice(1), cameraId]
    })
    document.querySelector('.workbench-band')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const logout = () => {
    transitionToken('')
    initializedSelection.current = false
    setCameras([])
    setSelectedIds([])
    setCurrentUser(null)
    setPage('monitoring')
  }

  const canAdminister = ['SUPER_ADMIN', 'ADMIN'].includes(currentUser?.role)

  const transitionToken = useCallback(value => {
    snapshotManager.invalidate()
    if (value) localStorage.setItem('cctv-token', value)
    else localStorage.removeItem('cctv-token')
    setToken(value)
  }, [snapshotManager])

  const openSnapshot = useCallback(
    snapshotId => snapshotManager.open(snapshotId, token),
    [snapshotManager, token],
  )

  const commandItems = useMemo(() => {
    const normalized = commandQuery.trim().toLowerCase()
    const matches = value => !normalized || value.toLowerCase().includes(normalized)
    const cameraItems = camerasWithStatus
      .filter(camera => matches(`${camera.name} ${camera.location || ''} ${camera.zone || ''}`))
      .slice(0, 6)
      .map(camera => ({
        key: `camera-${camera.id}`,
        group: 'Kamera',
        label: camera.name,
        description: camera.location || camera.zone || 'Lokasi belum diisi',
        meta: camera.effectiveStatus,
        action: () => focusCamera(camera.id),
      }))
    const personItems = persons
      .filter(person => matches(`${person.display_name || ''} ${person.reid_key || ''}`))
      .slice(0, 5)
      .map(person => ({
        key: `person-${person.id}`,
        group: 'Identitas',
        label: person.display_name || person.reid_key || 'Tanpa nama',
        description: `Terlihat ${formatDateTime(person.last_seen_at)}`,
        meta: 'REID',
        action: () => {
          setPersonSearch(person.display_name || person.reid_key || '')
          document.getElementById('identity-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        },
      }))
    const eventItems = events
      .filter(event => matches(`${event.camera_name || ''} ${event.camera_location || ''} ${event.event_type || ''} ${event.byte_track_id || event.tracking_id || ''}`))
      .slice(0, 5)
      .map(event => ({
        key: `event-${event.id}`,
        group: 'Event terbaru',
        label: `${event.event_type === 'ENTER' ? 'Masuk' : 'Keluar'} · ${event.camera_name || 'Kamera'}`,
        description: formatDateTime(event.occurred_at),
        meta: `#${event.tracking_id ?? '—'}`,
        action: () => {
          document.getElementById('event-history')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
          if (event.snapshot_id) openSnapshot(event.snapshot_id)
        },
      }))
    return [...cameraItems, ...personItems, ...eventItems]
  }, [commandQuery, camerasWithStatus, persons, events, gridSize, openSnapshot])

  const chooseCommand = item => {
    item?.action()
    setCommandOpen(false)
    setCommandQuery('')
    setCommandIndex(0)
  }

  if (!token) return <Login onLogin={transitionToken} />

  return <div className="app-shell">
    <header className="control-nav">
      <div className="control-nav__inner">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">PF</span>
          <div className="brand-copy"><strong>People Flow Control</strong><span>Realtime operations</span></div>
        </div>
        <button className="search-trigger" type="button" onClick={() => setCommandOpen(true)} aria-label="Buka pencarian cepat">
          <SearchIcon fontSize="small" aria-hidden="true" />
          <span className="search-trigger__label">Cari kamera, orang, atau event</span>
          <kbd>⌘ K</kbd>
        </button>
        <div className="control-nav__actions">
          {canAdminister && <div className="view-switch" aria-label="Navigasi utama">
            <button type="button" data-active={page === 'monitoring'} onClick={() => setPage('monitoring')} aria-label="Buka monitoring"><DashboardOutlinedIcon fontSize="small" /><span>Monitoring</span></button>
            <button type="button" data-active={page === 'administration'} onClick={() => setPage('administration')} aria-label="Buka administrasi"><SettingsOutlinedIcon fontSize="small" /><span>Administrasi</span></button>
          </div>}
          <span className="connection-pill">
            <span className="status-dot" data-status={socketStatus} />
            {socketStatus === 'connected' ? 'Realtime aktif' : socketStatus}
          </span>
          <IconButton className="icon-action" onClick={logout} aria-label="Keluar dari dashboard"><LogoutIcon /></IconButton>
        </div>
      </div>
    </header>

    {page === 'administration' && canAdminister
      ? <Administration token={token} currentUser={currentUser} cameras={camerasWithStatus} onReloadCameras={loadCameras} />
      : <main className="dashboard-main">
      {error && <Alert className="error-banner" severity="error" onClose={() => setError('')}>{error}</Alert>}

      <section className="dashboard-intro" aria-labelledby="dashboard-title">
        <h1 id="dashboard-title">Pusat monitoring CCTV</h1>
        <p>Pilih feed yang memerlukan perhatian, periksa pergerakan terbaru, lalu telusuri identitas tanpa berpindah layar.</p>
      </section>

      <section className="metric-strip" aria-label="Ringkasan operasional hari ini">
        <Metric label="Total kamera" value={cameras.length} />
        <Metric label="Online" value={onlineCount} tone="success" />
        <Metric label="Offline" value={offlineCount} tone="error" />
        <Metric label="Masuk hari ini" value={stats.enter_count} tone="success" />
        <Metric label="Keluar hari ini" value={stats.exit_count} tone="error" />
        <Metric label="Orang saat ini" value={occupancy.total} />
      </section>

      <section className="workbench-band" aria-labelledby="live-workbench-title">
        <div className="workbench-heading">
          <h2 id="live-workbench-title">Live workbench</h2>
          <p>Frame hanya dikirim untuk kamera yang dipilih—maksimal 16 feed per layar.</p>
        </div>
        <div className="workbench-layout">
          <CameraSidebar
            cameras={camerasWithStatus}
            selectedIds={selectedIds}
            limit={gridSize}
            search={cameraSearch}
            statusFilter={statusFilter}
            onSearch={setCameraSearch}
            onStatusFilter={setStatusFilter}
            onToggle={toggleCamera}
          />
          <LiveGrid
            cameras={selectedCameras}
            frames={frames}
            gridSize={gridSize}
            onGridSize={changeGridSize}
            token={token}
            canConfigure={canAdminister}
            onReloadCameras={loadCameras}
          />
        </div>
      </section>

      <div className="data-section">
        <EventHistory
          events={events}
          total={eventTotal}
          page={eventPage}
          rowsPerPage={rowsPerPage}
          date={date}
          onDate={value => { setDate(value); setEventPage(0) }}
          onPage={setEventPage}
          onRowsPerPage={value => { setRowsPerPage(value); setEventPage(0) }}
          onSnapshot={openSnapshot}
        />
        <IdentityPanel persons={persons} search={personSearch} onSearch={setPersonSearch} />
      </div>

      <footer className="system-footer">
        <span>People Flow Control · CCTV Operations</span>
        <span className="tnum">{onlineCount}/{cameras.length} kamera online · {socketStatus}</span>
      </footer>
      </main>}

    <CommandPalette
      open={commandOpen}
      query={commandQuery}
      activeIndex={commandIndex}
      items={commandItems}
      onQuery={setCommandQuery}
      onActiveIndex={setCommandIndex}
      onChoose={chooseCommand}
      onClose={() => { setCommandOpen(false); setCommandQuery(''); setCommandIndex(0) }}
    />

    <Dialog className="snapshot-dialog" open={Boolean(snapshot)} onClose={snapshotManager.close} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        Preview snapshot
        <IconButton className="icon-action" onClick={snapshotManager.close} aria-label="Tutup preview"><CloseIcon /></IconButton>
      </DialogTitle>
      <DialogContent>{snapshot && <img className="snapshot-image" src={snapshot} alt="Snapshot event CCTV" />}</DialogContent>
    </Dialog>
    <PasswordChangeDialog
      open={Boolean(currentUser?.must_change_password)}
      token={token}
      onChanged={value => {
        transitionToken(value)
        api('/auth/me', value).then(setCurrentUser).catch(err => setError(err.message))
      }}
    />
  </div>
}

export default App
