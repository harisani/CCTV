import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  ButtonGroup,
  Chip,
  InputAdornment,
  MenuItem,
  TextField,
} from '@mui/material'
import CreditCardOutlinedIcon from '@mui/icons-material/CreditCardOutlined'
import InputOutlinedIcon from '@mui/icons-material/InputOutlined'
import OutputOutlinedIcon from '@mui/icons-material/OutputOutlined'
import RefreshOutlinedIcon from '@mui/icons-material/RefreshOutlined'
import SensorsOutlinedIcon from '@mui/icons-material/SensorsOutlined'
import { api } from '../api'
import '../styles/rfid-simulator.css'

const manualCardValue = '__manual__'
const eventStatusLabels = {
  PENDING: 'Menunggu kamera',
  VERIFIED: 'Terverifikasi',
  UNMATCHED: 'Tidak cocok',
  AMBIGUOUS: 'Ambigu',
  EXPIRED: 'Kedaluwarsa',
  REJECTED: 'Ditolak',
}

const formatTime = value => {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('id-ID')
}

const statusColor = status => {
  if (status === 'VERIFIED') return 'success'
  if (status === 'PENDING') return 'warning'
  if (status === 'REJECTED') return 'error'
  return 'default'
}

export default function RFIDSimulator({ token }) {
  const [options, setOptions] = useState(null)
  const [events, setEvents] = useState([])
  const [total, setTotal] = useState(0)
  const [cardChoice, setCardChoice] = useState('')
  const [manualCard, setManualCard] = useState('')
  const [direction, setDirection] = useState('ENTER')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [latestEventId, setLatestEventId] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [optionResult, eventResult] = await Promise.all([
        api('/rfid/simulator/options', token),
        api('/rfid/simulator/events?limit=25', token),
      ])
      setOptions(optionResult)
      setEvents(eventResult.items)
      setTotal(eventResult.total)
      setCardChoice(current => (
        current || optionResult.cards[0]?.card_number || manualCardValue
      ))
    } catch (err) {
      setOptions(null)
      setEvents([])
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  const selectedCardNumber = useMemo(
    () => cardChoice === manualCardValue ? manualCard.trim() : cardChoice,
    [cardChoice, manualCard],
  )

  const simulate = async event => {
    event.preventDefault()
    if (!selectedCardNumber) return
    setSubmitting(true)
    setError('')
    try {
      const result = await api('/rfid/simulator/tap', token, {
        method: 'POST',
        body: JSON.stringify({
          card_number: selectedCardNumber,
          direction,
          idempotency_key: `dashboard-${crypto.randomUUID()}`,
        }),
      })
      setLatestEventId(result.event.id)
      const eventResult = await api('/rfid/simulator/events?limit=25', token)
      setEvents(eventResult.items)
      setTotal(eventResult.total)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return <section className="admin-section rfid-simulator" aria-busy="true">
      <h2 className="section-title">RFID Simulator</h2>
      <p className="empty-copy">Memuat konfigurasi simulator…</p>
    </section>
  }

  if (!options) {
    return <section className="admin-section rfid-simulator" aria-labelledby="rfid-simulator-title">
      <h2 className="section-title" id="rfid-simulator-title">RFID Simulator</h2>
      <Alert severity="warning">
        {error || 'Simulator tidak tersedia.'} Aktifkan hanya untuk testing, lalu restart service API.
      </Alert>
      <pre className="rfid-simulator__env">ENABLE_RFID_SIMULATOR=true</pre>
    </section>
  }

  return <section className="admin-section rfid-simulator" aria-labelledby="rfid-simulator-title">
    <div className="rfid-simulator__heading">
      <div>
        <h2 className="section-title" id="rfid-simulator-title">RFID Simulator</h2>
        <p className="section-copy">
          Kirim tap virtual melalui service dan repository yang sama dengan reader fisik.
        </p>
      </div>
      <Button
        variant="outlined"
        startIcon={<RefreshOutlinedIcon />}
        onClick={load}
        disabled={submitting}
      >
        Muat ulang
      </Button>
    </div>

    {error && <Alert className="error-banner" severity="error" onClose={() => setError('')}>
      {error}
    </Alert>}

    <div className="rfid-simulator__layout">
      <form className="rfid-simulator__console" onSubmit={simulate}>
        <div className="rfid-simulator__reader">
          <SensorsOutlinedIcon aria-hidden="true" />
          <span>
            <strong>{options.reader.name}</strong>
            <small>{options.reader.code} · {options.reader.location || 'Tanpa lokasi'}</small>
          </span>
        </div>

        <TextField
          className="light-field"
          select
          label="Kartu RFID"
          value={cardChoice}
          onChange={event => setCardChoice(event.target.value)}
          helperText={`${options.cards.length} kartu aktif tersedia untuk simulasi.`}
          required
        >
          {options.cards.map(card => <MenuItem key={card.card_number} value={card.card_number}>
            {card.employee_name} · {card.employee_number} · {card.card_number}
          </MenuItem>)}
          <MenuItem value={manualCardValue}>Masukkan UID manual</MenuItem>
        </TextField>

        {cardChoice === manualCardValue && <TextField
          className="light-field"
          label="UID kartu manual"
          value={manualCard}
          onChange={event => setManualCard(event.target.value.toUpperCase())}
          helperText="Gunakan UID belum terdaftar untuk menguji event REJECTED."
          inputProps={{ maxLength: 128, pattern: '[A-Za-z0-9:_-]+' }}
          InputProps={{
            startAdornment: <InputAdornment position="start">
              <CreditCardOutlinedIcon fontSize="small" />
            </InputAdornment>,
          }}
          required
        />}

        <div className="rfid-simulator__direction">
          <span>Arah akses</span>
          <ButtonGroup fullWidth aria-label="Arah akses virtual">
            <Button
              variant={direction === 'ENTER' ? 'contained' : 'outlined'}
              startIcon={<InputOutlinedIcon />}
              aria-pressed={direction === 'ENTER'}
              onClick={() => setDirection('ENTER')}
            >
              Masuk
            </Button>
            <Button
              variant={direction === 'EXIT' ? 'contained' : 'outlined'}
              startIcon={<OutputOutlinedIcon />}
              aria-pressed={direction === 'EXIT'}
              onClick={() => setDirection('EXIT')}
            >
              Keluar
            </Button>
          </ButtonGroup>
        </div>

        <Button
          className="rfid-simulator__submit"
          type="submit"
          variant="contained"
          disabled={submitting || !selectedCardNumber}
        >
          {submitting ? 'Mengirim tap…' : 'Kirim tap virtual'}
        </Button>
        <p className="rfid-simulator__note">
          Event valid berstatus PENDING selama {options.event_ttl_seconds} detik untuk menunggu korelasi kamera.
        </p>
      </form>

      <div className="rfid-simulator__ledger" aria-live="polite">
        <div className="rfid-simulator__ledger-head">
          <div>
            <h3>Event simulator terbaru</h3>
            <p>{total} event tersimpan pada reader virtual.</p>
          </div>
        </div>
        <div className="ledger-table-wrap">
          <table className="ledger-table admin-table">
            <thead>
              <tr><th>Waktu</th><th>Pegawai / UID</th><th>Arah</th><th>Status</th></tr>
            </thead>
            <tbody>
              {events.map(item => <tr
                key={item.id}
                data-latest={item.id === latestEventId}
                data-event-status={item.status}
              >
                <td data-label="Waktu">{formatTime(item.occurred_at)}</td>
                <td data-label="Pegawai / UID">
                  <strong>{item.employee_name || 'Kartu tidak dikenal'}</strong>
                  <span className="table-secondary">
                    {item.employee_number ? `${item.employee_number} · ` : ''}{item.card_number}
                  </span>
                  {item.status_reason && <span className="table-secondary">{item.status_reason}</span>}
                </td>
                <td data-label="Arah">
                  {item.direction === 'ENTER' ? 'Masuk' : 'Keluar'}
                </td>
                <td data-label="Status">
                  <Chip
                    size="small"
                    label={eventStatusLabels[item.status] || item.status}
                    color={statusColor(item.status)}
                  />
                </td>
              </tr>)}
              {!events.length && <tr><td colSpan="4">
                <div className="rfid-simulator__empty">
                  <SensorsOutlinedIcon aria-hidden="true" />
                  <strong>Belum ada tap virtual.</strong>
                  <span>Pilih kartu dan arah, lalu kirim event pertama.</span>
                </div>
              </td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
}
