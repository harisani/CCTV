import { ToggleButton, ToggleButtonGroup } from '@mui/material'
import VideocamOffIcon from '@mui/icons-material/VideocamOff'

function CameraStatus({ status }) {
  return <span className="status-label">
    <span className="status-dot" data-status={status} />
    {status}
  </span>
}

function CameraTile({ camera, frame }) {
  return <figure className="camera-tile">
    <figcaption className="camera-tile__head">
      <span className="camera-tile__identity">
        <strong>{camera.name}</strong>
        <span>{camera.location || camera.zone || 'Lokasi belum diisi'}</span>
      </span>
      <CameraStatus status={camera.effectiveStatus} />
    </figcaption>
    <div className="camera-frame">
      {!frame && <div className="camera-frame__empty"><VideocamOffIcon /><span>Menunggu frame realtime</span></div>}
      {frame && <img
        src={`data:image/jpeg;base64,${frame.image}`}
        alt={`Live feed ${camera.name}`}
        width={frame.width}
        height={frame.height}
      />}
      {frame?.tracks?.map(track => {
        const style = {
          '--track-x': `${track.bbox[0] / frame.width * 100}%`,
          '--track-y': `${track.bbox[1] / frame.height * 100}%`,
          '--track-w': `${(track.bbox[2] - track.bbox[0]) / frame.width * 100}%`,
          '--track-h': `${(track.bbox[3] - track.bbox[1]) / frame.height * 100}%`,
        }
        return <span className="tracking-box" key={track.tracking_id} style={style}>
          <span>ID {track.tracking_id} · {track.direction || 'STATIONARY'}</span>
        </span>
      })}
      {frame && <span className="frame-count">{frame.tracks?.length || 0} orang</span>}
    </div>
  </figure>
}

export default function LiveGrid({ cameras, frames, gridSize, onGridSize }) {
  const columns = gridSize === 1 ? 1 : gridSize === 4 ? 2 : gridSize === 9 ? 3 : 4
  return <section className="live-monitor" aria-labelledby="live-monitor-title">
    <div className="live-monitor__toolbar">
      <div>
        <h3 id="live-monitor-title">Feed terpilih</h3>
        <p>{cameras.length} feed aktif pada layout {gridSize} layar.</p>
      </div>
      <ToggleButtonGroup
        className="grid-switcher"
        exclusive
        size="small"
        value={gridSize}
        onChange={(_, value) => value && onGridSize(value)}
        aria-label="Jumlah kamera dalam grid"
      >
        {[1, 4, 9, 16].map(value => <ToggleButton key={value} value={value} aria-label={`${value} kamera`}>{value}</ToggleButton>)}
      </ToggleButtonGroup>
    </div>
    <div className={`camera-grid camera-grid--${columns}`}>
      {cameras.map(camera => <CameraTile key={camera.id} camera={camera} frame={frames[camera.id]} />)}
      {!cameras.length && <div className="live-empty"><p>Pilih kamera dari daftar untuk mulai menerima frame realtime.</p></div>}
    </div>
  </section>
}
