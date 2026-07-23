import { Alert, Button } from '@mui/material'
import '../styles/rfid-simulator.css'

const previews = [
  { label: 'Default', props: {}, text: 'Kirim tap virtual' },
  { label: 'Hover', props: { className: 'is-hover' }, text: 'Kirim tap virtual' },
  { label: 'Focus', props: { className: 'is-focus' }, text: 'Kirim tap virtual' },
  { label: 'Active', props: { className: 'is-active' }, text: 'Kirim tap virtual' },
  { label: 'Disabled', props: { disabled: true }, text: 'Kirim tap virtual' },
  { label: 'Loading', props: { disabled: true }, text: 'Mengirim tap…' },
]

export default function RFIDSimulatorPreview() {
  return <main className="rfid-simulator-preview">
    <h1>RFID Simulator — interaction states</h1>
    {previews.map(item => <div className="rfid-simulator-preview__row" key={item.label}>
      <span>{item.label}</span>
      <Button
        {...item.props}
        className={`rfid-simulator__submit ${item.props.className || ''}`}
        variant="contained"
      >
        {item.text}
      </Button>
    </div>)}
    <div className="rfid-simulator-preview__row">
      <span>Error</span>
      <Alert severity="error">UID kartu tidak dapat diproses. Periksa format kartu.</Alert>
    </div>
    <div className="rfid-simulator-preview__row">
      <span>Success</span>
      <Alert severity="success">Tap tersimpan dan terlihat pada ledger event.</Alert>
    </div>
  </main>
}
