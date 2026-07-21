import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, AppBar, Box, Button, Card, CardContent, Chip, Container, Dialog, DialogContent, DialogTitle, Grid, IconButton, InputAdornment, Paper, Stack, Table, TableBody, TableCell, TableHead, TablePagination, TableRow, TextField, Toolbar, Typography } from '@mui/material'
import LogoutIcon from '@mui/icons-material/Logout'
import SearchIcon from '@mui/icons-material/Search'
import CameraSidebar from './components/CameraSidebar'
import LiveGrid from './components/LiveGrid'
import { API_BASE, api, login } from './api'
import { useDashboardSocket } from './useDashboardSocket'

function Login({ onLogin }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const submit = async event => {
    event.preventDefault()
    try { setError(''); onLogin((await login(username, password)).access_token) } catch (err) { setError(err.message) }
  }
  return <Container maxWidth="xs" sx={{ pt: 14 }}><Paper sx={{ p: 3 }} component="form" onSubmit={submit}>
    <Typography variant="h5" mb={2}>CCTV People Flow</Typography><Stack spacing={2}>
      <TextField label="Username" value={username} onChange={event => setUsername(event.target.value)} />
      <TextField label="Password" type="password" value={password} onChange={event => setPassword(event.target.value)} error={!!error} helperText={error} />
      <Button type="submit" variant="contained">Masuk</Button>
    </Stack>
  </Paper></Container>
}

function Metric({ label, value, color = 'primary.main' }) {
  return <Card variant="outlined"><CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h4" color={color}>{value}</Typography></CardContent></Card>
}

function EventHistory({ events, total, page, rowsPerPage, date, onDate, onPage, onRowsPerPage, onSnapshot }) {
  return <Paper sx={{ p: 2, mt: 2 }}>
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" gap={1} mb={1}>
      <Typography variant="h6">Riwayat Event</Typography>
      <TextField size="small" type="date" label="Tanggal" InputLabelProps={{ shrink: true }} value={date} onChange={event => onDate(event.target.value)} />
    </Stack>
    <Box sx={{ overflowX: 'auto' }}><Table size="small"><TableHead><TableRow><TableCell>Waktu</TableCell><TableCell>Kamera</TableCell><TableCell>Lokasi</TableCell><TableCell>Status</TableCell><TableCell>Tracking</TableCell><TableCell>Snapshot</TableCell></TableRow></TableHead>
      <TableBody>{events.map(event => <TableRow key={event.id} hover><TableCell>{new Date(event.occurred_at).toLocaleString()}</TableCell><TableCell>{event.camera_name || '—'}</TableCell><TableCell>{event.camera_location || '—'}</TableCell><TableCell><Chip size="small" color={event.event_type === 'ENTER' ? 'success' : 'error'} label={event.event_type === 'ENTER' ? 'MASUK' : 'KELUAR'} /></TableCell><TableCell>{event.tracking_id}</TableCell><TableCell><Button size="small" onClick={() => onSnapshot(event.snapshot_url)} disabled={!event.snapshot_url}>Preview</Button></TableCell></TableRow>)}</TableBody>
    </Table></Box>
    <TablePagination component="div" count={total} page={page} rowsPerPage={rowsPerPage} rowsPerPageOptions={[10, 20, 50]} onPageChange={(_, value) => onPage(value)} onRowsPerPageChange={event => onRowsPerPage(Number(event.target.value))} />
  </Paper>
}

function App() {
  const [token, setToken] = useState(() => localStorage.getItem('cctv-token') || '')
  const [cameras, setCameras] = useState([])
  const [selectedIds, setSelectedIds] = useState([])
  const [gridSize, setGridSize] = useState(4)
  const [frames, setFrames] = useState({})
  const [stats, setStats] = useState({ enter_count: 0, exit_count: 0, current_person_count: 0 })
  const [events, setEvents] = useState([])
  const [eventTotal, setEventTotal] = useState(0)
  const [eventPage, setEventPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(20)
  const [persons, setPersons] = useState([])
  const [occupancy, setOccupancy] = useState(0)
  const [cameraSearch, setCameraSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [personSearch, setPersonSearch] = useState('')
  const [date, setDate] = useState('')
  const [snapshot, setSnapshot] = useState(null)
  const [socketStatus, setSocketStatus] = useState('disconnected')
  const [error, setError] = useState('')
  const [clock, setClock] = useState(Date.now())
  const initializedSelection = useRef(false)

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
    setOccupancy(summary.current_person_count)
    setEvents(eventResult.items)
    setEventTotal(eventResult.total)
  }, [token, date, eventPage, rowsPerPage])

  useEffect(() => {
    if (!token) return undefined
    Promise.all([loadCameras(), loadDashboard()]).catch(err => setError(err.message))
    const refresh = window.setInterval(() => Promise.all([loadCameras(), loadDashboard()]).catch(err => setError(err.message)), 30000)
    return () => window.clearInterval(refresh)
  }, [token, loadCameras, loadDashboard])
  useEffect(() => { const timer = window.setInterval(() => setClock(Date.now()), 5000); return () => window.clearInterval(timer) }, [])
  useEffect(() => {
    if (!token) return
    api(`/persons?limit=20${personSearch ? `&name=${encodeURIComponent(personSearch)}` : ''}`, token).then(page => setPersons(page.items)).catch(err => setError(err.message))
  }, [token, personSearch])

  useDashboardSocket(token, selectedIds, message => {
    if (message.type === 'frame') setFrames(current => ({ ...current, [message.camera_id]: { ...message, receivedAt: Date.now() } }))
    if (message.type === 'occupancy') setOccupancy(message.count)
    if (message.type === 'event') {
      setEvents(current => [message.payload, ...current].slice(0, rowsPerPage))
      setEventTotal(current => current + 1)
    }
    if (message.type === 'error') setError(message.detail)
  }, setSocketStatus)

  const camerasWithStatus = useMemo(() => cameras.map(camera => {
    const frame = frames[camera.id]
    const frameIsRecent = frame && clock - frame.receivedAt < 15000
    return { ...camera, effectiveStatus: frameIsRecent ? 'ONLINE' : (camera.status || 'OFFLINE') }
  }), [cameras, frames, clock])
  const selectedCameras = selectedIds.map(id => camerasWithStatus.find(camera => camera.id === id)).filter(Boolean)
  const onlineCount = camerasWithStatus.filter(camera => camera.effectiveStatus === 'ONLINE').length
  const offlineCount = camerasWithStatus.length - onlineCount
  const snapshotUrl = value => value ? `${API_BASE.replace(/\/api\/v1$/, '')}${value}` : null

  const changeGridSize = value => {
    setGridSize(value)
    setSelectedIds(current => current.slice(0, value))
  }
  const toggleCamera = cameraId => setSelectedIds(current => current.includes(cameraId) ? current.filter(id => id !== cameraId) : current.length < gridSize ? [...current, cameraId] : current)
  const logout = () => {
    localStorage.removeItem('cctv-token')
    initializedSelection.current = false
    setToken('')
    setCameras([])
    setSelectedIds([])
  }

  if (!token) return <Login onLogin={value => { localStorage.setItem('cctv-token', value); setToken(value) }} />
  return <>
    <AppBar position="sticky"><Toolbar><Typography variant="h6" sx={{ flexGrow: 1 }}>CCTV People Flow</Typography><Chip size="small" sx={{ mr: 1 }} color={socketStatus === 'connected' ? 'success' : 'warning'} label={`Realtime: ${socketStatus}`} /><IconButton color="inherit" onClick={logout}><LogoutIcon /></IconButton></Toolbar></AppBar>
    <Container maxWidth={false} sx={{ py: 2 }}>
      {error && <Alert severity="error" onClose={() => setError('')} sx={{ mb: 2 }}>{error}</Alert>}
      <Grid container spacing={1.5} mb={2}>
        <Grid item xs={6} md={2}><Metric label="Total Kamera" value={cameras.length} /></Grid><Grid item xs={6} md={2}><Metric label="Online" value={onlineCount} color="success.main" /></Grid><Grid item xs={6} md={2}><Metric label="Offline" value={offlineCount} color="error.main" /></Grid><Grid item xs={6} md={2}><Metric label="Masuk Hari Ini" value={stats.enter_count} color="success.main" /></Grid><Grid item xs={6} md={2}><Metric label="Keluar Hari Ini" value={stats.exit_count} color="error.main" /></Grid><Grid item xs={6} md={2}><Metric label="Orang Saat Ini" value={occupancy} /></Grid>
      </Grid>
      <Paper variant="outlined" sx={{ display: { xs: 'block', lg: 'flex' }, overflow: 'hidden' }}>
        <CameraSidebar cameras={camerasWithStatus} selectedIds={selectedIds} limit={gridSize} search={cameraSearch} statusFilter={statusFilter} onSearch={setCameraSearch} onStatusFilter={setStatusFilter} onToggle={toggleCamera} />
        <Box sx={{ p: 2, flex: 1, borderLeft: { lg: 1 }, borderColor: 'divider' }}><LiveGrid cameras={selectedCameras} frames={frames} gridSize={gridSize} onGridSize={changeGridSize} /></Box>
      </Paper>
      <Grid container spacing={2}>
        <Grid item xs={12} lg={9}><EventHistory events={events} total={eventTotal} page={eventPage} rowsPerPage={rowsPerPage} date={date} onDate={value => { setDate(value); setEventPage(0) }} onPage={setEventPage} onRowsPerPage={value => { setRowsPerPage(value); setEventPage(0) }} onSnapshot={value => setSnapshot(snapshotUrl(value))} /></Grid>
        <Grid item xs={12} lg={3}><Paper sx={{ p: 2, mt: 2 }}><Typography variant="h6">Pencarian Identitas</Typography><TextField fullWidth size="small" sx={{ my: 2 }} label="Nama / ReID key" value={personSearch} onChange={event => setPersonSearch(event.target.value)} InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon /></InputAdornment> }} />{persons.map(person => <Box key={person.id} sx={{ py: 1, borderBottom: 1, borderColor: 'divider' }}><Typography>{person.display_name || person.reid_key || 'Tanpa nama'}</Typography><Typography variant="caption">Terakhir terlihat: {new Date(person.last_seen_at).toLocaleString()}</Typography></Box>)}</Paper></Grid>
      </Grid>
    </Container>
    <Dialog open={!!snapshot} onClose={() => setSnapshot(null)} maxWidth="md" fullWidth><DialogTitle>Preview Snapshot</DialogTitle><DialogContent>{snapshot && <Box component="img" src={snapshot} alt="Snapshot" sx={{ width: '100%' }} />}</DialogContent></Dialog>
  </>
}

export default App
