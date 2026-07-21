import { Box, Chip, Paper, Stack, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material'
import VideocamOffIcon from '@mui/icons-material/VideocamOff'

function CameraTile({ camera, frame }) {
  return <Paper variant="outlined" sx={{ overflow: 'hidden', minHeight: 220 }}>
    <Stack direction="row" justifyContent="space-between" alignItems="center" sx={{ px: 1.5, py: 1 }}>
      <Box><Typography fontWeight={700}>{camera.name}</Typography><Typography variant="caption" color="text.secondary">{camera.location || camera.zone || 'Lokasi belum diisi'}</Typography></Box>
      <Chip size="small" color={camera.effectiveStatus === 'ONLINE' ? 'success' : 'default'} label={camera.effectiveStatus} />
    </Stack>
    <Box sx={{ position: 'relative', bgcolor: '#05090c', aspectRatio: '16 / 9', display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
      {!frame && <Stack alignItems="center" color="text.secondary"><VideocamOffIcon /><Typography variant="caption">Menunggu frame realtime</Typography></Stack>}
      {frame && <Box component="img" src={`data:image/jpeg;base64,${frame.image}`} alt={camera.name} sx={{ width: '100%', height: '100%', objectFit: 'contain' }} />}
      {frame?.tracks?.map(track => <Box key={track.tracking_id} sx={{ position: 'absolute', left: `${track.bbox[0] / frame.width * 100}%`, top: `${track.bbox[1] / frame.height * 100}%`, width: `${(track.bbox[2] - track.bbox[0]) / frame.width * 100}%`, height: `${(track.bbox[3] - track.bbox[1]) / frame.height * 100}%`, border: '2px solid #00e676', color: '#fff', bgcolor: 'rgba(0,0,0,.58)', fontSize: 11, lineHeight: 1.4, pointerEvents: 'none' }}>{`ID ${track.tracking_id} · ${track.direction}`}</Box>)}
      {frame && <Chip size="small" label={`${frame.tracks?.length || 0} orang`} sx={{ position: 'absolute', right: 8, bottom: 8, bgcolor: 'rgba(0,0,0,.7)' }} />}
    </Box>
  </Paper>
}

export default function LiveGrid({ cameras, frames, gridSize, onGridSize }) {
  const columns = gridSize === 1 ? 1 : gridSize === 4 ? 2 : gridSize === 9 ? 3 : 4
  return <Box sx={{ flex: 1, minWidth: 0 }}>
    <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" alignItems={{ xs: 'stretch', sm: 'center' }} gap={1} mb={1.5}>
      <Box><Typography variant="h5">Live Monitor</Typography><Typography variant="body2" color="text.secondary">Frame hanya dikirim untuk kamera yang dipilih.</Typography></Box>
      <ToggleButtonGroup exclusive size="small" value={gridSize} onChange={(_, value) => value && onGridSize(value)}>{[1, 4, 9, 16].map(value => <ToggleButton key={value} value={value}>{value}</ToggleButton>)}</ToggleButtonGroup>
    </Stack>
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: `repeat(${Math.min(columns, 2)}, 1fr)`, xl: `repeat(${columns}, 1fr)` }, gap: 1.5 }}>
      {cameras.map(camera => <CameraTile key={camera.id} camera={camera} frame={frames[camera.id]} />)}
      {!cameras.length && <Paper sx={{ minHeight: 360, display: 'grid', placeItems: 'center' }}><Typography color="text.secondary">Pilih kamera dari panel sebelah kiri.</Typography></Paper>}
    </Box>
  </Box>
}
