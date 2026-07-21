import { Box, Checkbox, Chip, Divider, FormControl, InputAdornment, InputLabel, List, ListItemButton, ListItemText, MenuItem, Select, Stack, TextField, Typography } from '@mui/material'
import SearchIcon from '@mui/icons-material/Search'

const groupName = camera => camera.building || camera.location || 'Lokasi belum ditentukan'

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

  return <Box sx={{ width: { xs: '100%', lg: 300 }, flexShrink: 0 }}>
    <Stack spacing={1.5} sx={{ p: 2 }}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <Typography variant="h6">Kamera</Typography>
        <Chip size="small" label={`${selectedIds.length}/${limit} dipilih`} />
      </Stack>
      <TextField size="small" value={search} onChange={event => onSearch(event.target.value)} placeholder="Cari kamera/lokasi" InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }} />
      <FormControl size="small" fullWidth><InputLabel>Status</InputLabel><Select label="Status" value={statusFilter} onChange={event => onStatusFilter(event.target.value)}>
        <MenuItem value="ALL">Semua status</MenuItem><MenuItem value="ONLINE">Online</MenuItem><MenuItem value="OFFLINE">Offline</MenuItem><MenuItem value="ERROR">Error</MenuItem><MenuItem value="RECONNECTING">Reconnecting</MenuItem>
      </Select></FormControl>
    </Stack>
    <Divider />
    <List dense sx={{ maxHeight: { xs: 320, lg: 'calc(100vh - 270px)' }, overflowY: 'auto' }}>
      {Object.entries(groups).map(([group, items]) => <Box key={group}>
        <Typography variant="overline" color="text.secondary" sx={{ px: 2 }}>{group}</Typography>
        {items.map(camera => {
          const selected = selectedIds.includes(camera.id)
          const disabled = !selected && selectedIds.length >= limit
          return <ListItemButton key={camera.id} disabled={disabled} selected={selected} onClick={() => onToggle(camera.id)}>
            <Checkbox edge="start" size="small" checked={selected} tabIndex={-1} disableRipple />
            <ListItemText primary={camera.name} secondary={[camera.floor, camera.zone].filter(Boolean).join(' · ') || camera.location || 'Tanpa detail lokasi'} />
            <Chip size="small" color={camera.effectiveStatus === 'ONLINE' ? 'success' : camera.effectiveStatus === 'ERROR' ? 'error' : 'default'} label={camera.effectiveStatus} sx={{ ml: 1, fontSize: 10 }} />
          </ListItemButton>
        })}
      </Box>)}
      {!filtered.length && <Typography color="text.secondary" sx={{ p: 2 }}>Kamera tidak ditemukan.</Typography>}
    </List>
  </Box>
}
