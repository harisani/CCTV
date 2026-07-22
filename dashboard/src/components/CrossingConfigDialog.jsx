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

const SVG_WIDTH = 1000

const clampUnit = value => Math.min(1, Math.max(0, value))

export function CrossingOverlay({ config, editable = false, aspectRatio = 16 / 9 }) {
  if (!config?.enabled) return null
  const points = config.polygon_points || []
  const safeRatio = Math.min(4, Math.max(0.25, Number(aspectRatio) || 16 / 9))
  const svgHeight = SVG_WIDTH / safeRatio
  const scaledPoints = points.map(point => ({ x: point.x * SVG_WIDTH, y: point.y * svgHeight }))
  const openPointList = scaledPoints.map(point => `${point.x},${point.y}`).join(' ')
  const pointList = points.length >= 3 ? `${openPointList} ${scaledPoints[0].x},${scaledPoints[0].y}` : openPointList
  const position = clampUnit(config.position ?? 0.5) * (config.line_type === 'horizontal' ? svgHeight : SVG_WIDTH)
  const isHorizontal = config.line_type === 'horizontal'
  const isVertical = config.line_type === 'vertical'
  const enterOnPositiveSide = config.enter_direction === 'down' || config.enter_direction === 'right'
  const labelPrimary = enterOnPositiveSide ? 'EXIT' : 'ENTER'
  const labelSecondary = enterOnPositiveSide ? 'ENTER' : 'EXIT'

  return <svg
    className={`crossing-overlay${editable ? ' crossing-overlay--editable' : ''}`}
    viewBox={`0 0 ${SVG_WIDTH} ${svgHeight}`}
    preserveAspectRatio="none"
    aria-hidden="true"
  >
    {(isHorizontal || isVertical) && <>
      <line className="crossing-overlay__halo" x1={isHorizontal ? 0 : position} y1={isHorizontal ? position : 0} x2={isHorizontal ? SVG_WIDTH : position} y2={isHorizontal ? position : svgHeight} />
      <line className="crossing-overlay__line" x1={isHorizontal ? 0 : position} y1={isHorizontal ? position : 0} x2={isHorizontal ? SVG_WIDTH : position} y2={isHorizontal ? position : svgHeight} />
      {editable && <>
        <circle className="crossing-overlay__handle" cx={isHorizontal ? 28 : position} cy={isHorizontal ? position : 28} r="14" />
        <circle className="crossing-overlay__handle" cx={isHorizontal ? SVG_WIDTH - 28 : position} cy={isHorizontal ? position : svgHeight - 28} r="14" />
        <g className="crossing-overlay__direction-labels">
          <text x={isHorizontal ? 28 : position - 22} y={isHorizontal ? Math.max(30, position - 24) : 38} textAnchor={isHorizontal ? 'start' : 'end'}>{labelPrimary}</text>
          <text x={isHorizontal ? 28 : position + 22} y={isHorizontal ? Math.min(svgHeight - 18, position + 42) : 38} textAnchor={isHorizontal ? 'start' : 'start'}>{labelSecondary}</text>
        </g>
      </>}
    </>}
    {config.line_type === 'polygon' && points.length > 0 && <>
      {points.length >= 3 && <polygon className="crossing-overlay__polygon-fill" points={pointList} />}
      <polyline className="crossing-overlay__halo" points={pointList} />
      <polyline className="crossing-overlay__line" points={pointList} />
      {editable && scaledPoints.map((point, index) => <circle className="crossing-overlay__handle" key={`${point.x}-${point.y}-${index}`} cx={point.x} cy={point.y} r="14" />)}
      {editable && points.length >= 3 && <text className="crossing-overlay__area-label" x={scaledPoints.reduce((sum, point) => sum + point.x, 0) / scaledPoints.length} y={scaledPoints.reduce((sum, point) => sum + point.y, 0) / scaledPoints.length}>AREA ENTER</text>}
    </>}
  </svg>
}

export default function CrossingConfigDialog({ camera, frame, token, open, onClose, onSaved }) {
  const [config, setConfig] = useState(defaultConfig)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [imageRatio, setImageRatio] = useState(null)
  const [dragging, setDragging] = useState(false)
  const stageRef = useRef(null)

  useEffect(() => {
    if (!open) return
    setConfig({ ...defaultConfig, ...(camera?.crossing_config || {}) })
    setSaving(false)
    setSaved(false)
    setError('')
    setImageRatio(null)
    setDragging(false)
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

  const positionFromPointer = event => {
    const rect = stageRef.current.getBoundingClientRect()
    return {
      x: clampUnit((event.clientX - rect.left) / rect.width),
      y: clampUnit((event.clientY - rect.top) / rect.height),
    }
  }

  const updateLineFromPointer = event => {
    if (!config.enabled || !stageRef.current || config.line_type === 'polygon') return
    const { x, y } = positionFromPointer(event)
    setConfig(current => ({ ...current, position: current.line_type === 'horizontal' ? y : x }))
    setError('')
    setSaved(false)
  }

  const startDrawing = event => {
    if (!config.enabled || !stageRef.current) return
    const { x, y } = positionFromPointer(event)
    if (config.line_type === 'polygon') {
      setConfig(current => ({ ...current, polygon_points: [...current.polygon_points, { x, y }].slice(0, 20) }))
    } else {
      event.currentTarget.setPointerCapture?.(event.pointerId)
      setDragging(true)
      updateLineFromPointer(event)
    }
    setError('')
    setSaved(false)
  }

  const continueDrawing = event => {
    if (dragging) updateLineFromPointer(event)
  }

  const stopDrawing = event => {
    if (!dragging) return
    event.currentTarget.releasePointerCapture?.(event.pointerId)
    setDragging(false)
  }

  const moveWithKeyboard = event => {
    if (!config.enabled || config.line_type === 'polygon') return
    const delta = event.shiftKey ? 0.05 : 0.01
    const negative = event.key === 'ArrowUp' || event.key === 'ArrowLeft'
    const positive = event.key === 'ArrowDown' || event.key === 'ArrowRight'
    if (!negative && !positive) return
    event.preventDefault()
    setConfig(current => ({ ...current, position: clampUnit((current.position ?? 0.5) + (negative ? -delta : delta)) }))
    setSaved(false)
  }

  const undo = () => {
    setConfig(current => current.line_type === 'polygon'
      ? { ...current, polygon_points: current.polygon_points.slice(0, -1) }
      : { ...current, position: 0.5 })
    setSaved(false)
  }

  const clear = () => {
    setConfig(current => ({ ...current, position: 0.5, polygon_points: [] }))
    setSaved(false)
  }

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
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const ratio = imageRatio || (frame?.width && frame?.height ? frame.width / frame.height : 16 / 9)
  const coordinateLabel = config.line_type === 'polygon'
    ? `${config.polygon_points.length} titik relatif`
    : `${config.line_type === 'horizontal' ? 'Y' : 'X'} ${Math.round((config.position ?? 0.5) * 100)}%`

  return <Dialog className="crossing-dialog" open={open} onClose={saving ? undefined : onClose} fullWidth maxWidth="lg">
    <DialogTitle>Atur area crossing · {camera?.name}</DialogTitle>
    <DialogContent>
      <div className="crossing-dialog__intro">
        <p>Gambar langsung di atas kamera—koordinat menyesuaikan resolusi secara otomatis. Untuk garis, tekan lalu geser. Untuk polygon, klik setiap sudut secara berurutan.</p>
        <FormControlLabel
          control={<Switch checked={config.enabled} onChange={event => {
            setConfig(current => ({ ...current, enabled: event.target.checked }))
            setSaved(false)
          }} />}
          label="Deteksi crossing aktif"
        />
      </div>
      {error && <Alert severity="error">{error}</Alert>}
      {saved && <Alert severity="success">Konfigurasi tersimpan dan akan diterapkan otomatis pada pipeline.</Alert>}
      <div className="crossing-editor-layout">
        <div
          className="crossing-stage"
          ref={stageRef}
          style={{ '--crossing-ratio': ratio }}
          onPointerDown={startDrawing}
          onPointerMove={continueDrawing}
          onPointerUp={stopDrawing}
          onPointerCancel={stopDrawing}
          onKeyDown={moveWithKeyboard}
          data-disabled={!config.enabled}
          data-dragging={dragging}
          role="group"
          tabIndex={config.enabled ? 0 : -1}
          aria-label={`Editor ${config.line_type} kamera ${camera?.name}. ${coordinateLabel}`}
        >
          {frame?.image
            ? <img
                src={`data:image/jpeg;base64,${frame.image}`}
                alt={`Frame konfigurasi ${camera?.name}`}
                draggable="false"
                onLoad={event => {
                  const { naturalWidth, naturalHeight } = event.currentTarget
                  if (naturalWidth && naturalHeight) setImageRatio(naturalWidth / naturalHeight)
                }}
              />
            : <div className="crossing-stage__empty">Frame belum tersedia. Geometri tetap dapat disiapkan pada bidang referensi.</div>}
          <CrossingOverlay config={config} editable aspectRatio={ratio} />
          <span className="crossing-stage__hint">{coordinateLabel}</span>
          <span className="crossing-stage__legend"><i aria-hidden="true" /> Garis crossing</span>
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
