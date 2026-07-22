/* Hallmark · pre-emit critique: P5 H5 E5 S5 R5 V4
 * component: geometry editor · genre: modern-minimal · theme: Cobalt
 * states: default · hover · focus · active · disabled · loading · error · success
 * contrast: pass (46–50)
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material'
import DeleteSweepOutlinedIcon from '@mui/icons-material/DeleteSweepOutlined'
import UndoOutlinedIcon from '@mui/icons-material/UndoOutlined'
import { api } from '../api'

const defaultConfig = {
  enabled: true,
  line_id: 'main-door',
  line_type: 'horizontal',
  position: 0.5,
  enter_direction: 'down',
  polygon_points: [],
}

const directionOptions = {
  horizontal: [['down', 'Atas → bawah'], ['up', 'Bawah → atas']],
  vertical: [['right', 'Kiri → kanan'], ['left', 'Kanan → kiri']],
  polygon: [['down', 'Luar → dalam']],
}

export function CrossingOverlay({ config, editable = false }) {
  if (!config?.enabled) return null
  const points = config.polygon_points || []
  return <svg
    className={`crossing-overlay${editable ? ' crossing-overlay--editable' : ''}`}
    viewBox="0 0 1 1"
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    {config.line_type === 'horizontal' && <line x1="0" y1={config.position} x2="1" y2={config.position} />}
    {config.line_type === 'vertical' && <line x1={config.position} y1="0" x2={config.position} y2="1" />}
    {config.line_type === 'polygon' && points.length > 0 && <>
      <polygon points={points.map(point => `${point.x},${point.y}`).join(' ')} />
      {points.map((point, index) => <circle key={`${point.x}-${point.y}-${index}`} cx={point.x} cy={point.y} r="0.012" />)}
    </>}
  </svg>
}

export default function CrossingConfigDialog({ camera, frame, token, open, onClose, onSaved }) {
  const [config, setConfig] = useState(defaultConfig)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const stageRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setConfig({ ...defaultConfig, ...(camera?.crossing_config || {}) })
    setSaving(false)
    setSaved(false)
    setError('')
  }, [open, camera])

  const directionItems = useMemo(() => directionOptions[config.line_type], [config.line_type])
  const geometryReady = !config.enabled || config.line_type !== 'polygon' || config.polygon_points.length >= 3

  const changeType = (_, lineType) => {
    if (!lineType) return
    const direction = lineType === 'horizontal' ? 'down' : lineType === 'vertical' ? 'right' : 'down'
    setConfig(current => ({
      ...current,
      line_type: lineType,
      enter_direction: direction,
      position: current.position ?? 0.5,
      polygon_points: lineType === 'polygon' ? current.polygon_points : [],
    }))
    setSaved(false)
  }

  const draw = event => {
    if (!config.enabled || !stageRef.current) return
    const rect = stageRef.current.getBoundingClientRect()
    const x = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width))
    const y = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height))
    setConfig(current => current.line_type === 'polygon'
      ? { ...current, polygon_points: [...current.polygon_points, { x, y }].slice(0, 20) }
      : { ...current, position: current.line_type === 'horizontal' ? y : x })
    setError('')
    setSaved(false)
  }

  const undo = () => setConfig(current => current.line_type === 'polygon'
    ? { ...current, polygon_points: current.polygon_points.slice(0, -1) }
    : { ...current, position: 0.5 })

  const clear = () => setConfig(current => ({ ...current, position: 0.5, polygon_points: [] }))

  const save = async () => {
    if (!geometryReady) {
      setError('Polygon membutuhkan minimal tiga titik.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const result = await api(`/camera/${camera.id}/crossing-config`, token, {
        method: 'PUT',
        body: JSON.stringify(config),
      })
      setConfig(result)
      setSaved(true)
      await onSaved()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const ratio = frame?.width && frame?.height ? frame.width / frame.height : 16 / 9

  return <Dialog className="crossing-dialog" open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="lg">
    <DialogTitle>Atur area crossing · {camera?.name}</DialogTitle>
    <DialogContent>
      <div className="crossing-dialog__intro">
        <p>Klik pada gambar untuk menempatkan garis. Pada mode polygon, klik setiap sudut area secara berurutan.</p>
        <FormControlLabel
          control={<Switch checked={config.enabled} onChange={event => setConfig(current => ({ ...current, enabled: event.target.checked }))} />}
          label="Deteksi crossing aktif"
        />
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {saved && <Alert severity="success">Konfigurasi tersimpan dan akan diterapkan otomatis pada pipeline.</Alert>}
      <div className="crossing-editor-layout">
        <div className="crossing-stage" ref={stageRef} style={{ '--crossing-ratio': ratio }} onPointerDown={draw} data-disabled={!config.enabled}>
          {frame?.image
            ? <img src={`data:image/jpeg;base64,${frame.image}`} alt={`Frame konfigurasi ${camera?.name}`} draggable="false" />
            : <div className="crossing-stage__empty">Frame belum tersedia. Geometri tetap dapat disiapkan pada bidang referensi.</div>}
          <CrossingOverlay config={config} editable />
          <span className="crossing-stage__hint">{config.line_type === 'polygon' ? `${config.polygon_points.length} titik` : `${Math.round((config.position ?? 0.5) * 100)}%`}</span>
        </div>
        <div className="crossing-controls">
          <ToggleButtonGroup exclusive fullWidth size="small" value={config.line_type} onChange={changeType} disabled={!config.enabled} aria-label="Bentuk area crossing">
            <ToggleButton value="horizontal">Horizontal</ToggleButton>
            <ToggleButton value="vertical">Vertical</ToggleButton>
            <ToggleButton value="polygon">Polygon</ToggleButton>
          </ToggleButtonGroup>
          <TextField
            className="light-field"
            label="ID garis"
            value={config.line_id}
            onChange={event => setConfig(current => ({ ...current, line_id: event.target.value }))}
            inputProps={{ maxLength: 100 }}
            disabled={!config.enabled}
            required
          />
          <TextField
            className="light-field"
            select
            label="Arah dianggap masuk"
            value={config.enter_direction}
            onChange={event => setConfig(current => ({ ...current, enter_direction: event.target.value }))}
            disabled={!config.enabled || config.line_type === 'polygon'}
          >
            {directionItems.map(([value, label]) => <MenuItem value={value} key={value}>{label}</MenuItem>)}
          </TextField>
          <p className="crossing-controls__note">
            {config.line_type === 'polygon'
              ? 'Masuk terjadi saat centroid orang berpindah dari luar ke dalam area.'
              : `Sisi ${config.enter_direction === 'down' ? 'bawah' : config.enter_direction === 'up' ? 'atas' : config.enter_direction === 'right' ? 'kanan' : 'kiri'} dihitung sebagai arah masuk.`}
          </p>
          <div className="crossing-controls__actions">
            <Button startIcon={<UndoOutlinedIcon />} onClick={undo} disabled={!config.enabled}>Undo</Button>
            <Button startIcon={<DeleteSweepOutlinedIcon />} onClick={clear} disabled={!config.enabled}>Reset</Button>
          </div>
        </div>
      </div>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={saving}>Tutup</Button>
      <Button variant="contained" onClick={save} disabled={saving || !config.line_id.trim() || !geometryReady}>
        {saving ? 'Menyimpan…' : saved ? 'Tersimpan' : 'Simpan konfigurasi'}
      </Button>
    </DialogActions>
  </Dialog>
}
