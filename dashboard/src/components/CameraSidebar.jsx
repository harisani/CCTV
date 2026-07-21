import {
  Checkbox,
  FormControl,
  InputAdornment,
  InputLabel,
  ListItemButton,
  ListItemText,
  MenuItem,
  Select,
  TextField,
} from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'

const groupName = camera => camera.building || camera.location || 'Lokasi belum ditentukan'

function CameraStatus({ status }) {
  return <span className="status-label">
    <span className="status-dot" data-status={status} />
    {status}
  </span>
}

export default function CameraSidebar({ cameras, selectedIds, limit, search, statusFilter, onSearch, onStatusFilter, onToggle }) {
  const filtered = cameras.filter(camera => {
    const haystack = `${camera.name} ${camera.location || ''} ${camera.building || ''} ${camera.floor || ''} ${camera.zone || ''}`.toLowerCase()
    const matchesSearch = haystack.includes(search.toLowerCase())
    const matchesStatus = statusFilter === 'ALL' || camera.effectiveStatus === statusFilter
    return matchesSearch && matchesStatus
  })
  const groups = Object.groupBy
    ? Object.groupBy(filtered, groupName)
    : filtered.reduce((result, camera) => ({ ...result, [groupName(camera)]: [...(result[groupName(camera)] || []), camera] }), {})

  return <aside className="camera-sidebar" aria-labelledby="camera-sidebar-title">
    <div className="camera-sidebar__head">
      <h3 id="camera-sidebar-title">Daftar kamera</h3>
      <span className="selection-count">{selectedIds.length}/{limit} dipilih</span>
    </div>
    <div className="camera-filter-stack">
      <TextField
        className="dark-field"
        size="small"
        value={search}
        onChange={event => onSearch(event.target.value)}
        label="Cari kamera atau lokasi"
        InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
      />
      <FormControl className="dark-field" size="small" fullWidth>
        <InputLabel>Status kamera</InputLabel>
        <Select label="Status kamera" value={statusFilter} onChange={event => onStatusFilter(event.target.value)}>
          <MenuItem value="ALL">Semua status</MenuItem>
          <MenuItem value="ONLINE">Online</MenuItem>
          <MenuItem value="OFFLINE">Offline</MenuItem>
          <MenuItem value="ERROR">Error</MenuItem>
          <MenuItem value="RECONNECTING">Reconnecting</MenuItem>
        </Select>
      </FormControl>
    </div>
    <div className="camera-groups">
      {Object.entries(groups).map(([group, items]) => <section className="camera-group" key={group}>
        <span className="camera-group__name">{group}</span>
        {items.map(camera => {
          const selected = selectedIds.includes(camera.id)
          const disabled = !selected && selectedIds.length >= limit
          const detail = [camera.floor, camera.zone].filter(Boolean).join(' · ') || camera.location || 'Tanpa detail lokasi'
          return <ListItemButton
            className="camera-row"
            key={camera.id}
            disabled={disabled}
            selected={selected}
            onClick={() => onToggle(camera.id)}
            aria-label={`${selected ? 'Lepas' : 'Pilih'} ${camera.name}`}
          >
            <Checkbox edge="start" size="small" checked={selected} tabIndex={-1} disableRipple />
            <ListItemText primary={camera.name} secondary={detail} />
            <CameraStatus status={camera.effectiveStatus} />
          </ListItemButton>
        })}
      </section>)}
      {!filtered.length && <p className="camera-sidebar__empty">Tidak ada kamera yang cocok dengan filter ini.</p>}
    </div>
  </aside>
}
