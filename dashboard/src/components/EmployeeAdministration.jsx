import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  InputAdornment,
  MenuItem,
  Stack,
  Switch,
  TablePagination,
  TextField,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined'
import CreditCardOutlinedIcon from '@mui/icons-material/CreditCardOutlined'
import EditOutlinedIcon from '@mui/icons-material/EditOutlined'
import SearchIcon from '@mui/icons-material/Search'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import { api } from '../api'
import '../styles/employee-administration.css'

const cardStatuses = ['ACTIVE', 'BLOCKED', 'LOST', 'EXPIRED']
const statusLabels = {
  ACTIVE: 'Aktif',
  BLOCKED: 'Diblokir',
  LOST: 'Hilang',
  EXPIRED: 'Kedaluwarsa',
}

const emptyEmployee = {
  employee_number: '',
  full_name: '',
  department: '',
  is_active: true,
}

const emptyCard = {
  card_number: '',
  label: '',
  status: 'ACTIVE',
  valid_from: '',
  valid_until: '',
}

const toLocalInput = value => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

const toApiTimestamp = value => value ? new Date(value).toISOString() : null

const formatDateTime = value => {
  if (!value) return 'Tanpa batas'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString('id-ID')
}

function EmployeeDialog({ open, employee, token, onClose, onSaved }) {
  const [form, setForm] = useState(emptyEmployee)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setForm(employee ? { ...emptyEmployee, ...employee, department: employee.department || '' } : emptyEmployee)
    setError('')
  }, [open, employee])

  const update = field => event => setForm(current => ({
    ...current,
    [field]: event.target.type === 'checkbox' ? event.target.checked : event.target.value,
  }))

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    try {
      await api(employee ? `/employees/${employee.id}` : '/employees', token, {
        method: employee ? 'PATCH' : 'POST',
        body: JSON.stringify({
          employee_number: form.employee_number.trim(),
          full_name: form.full_name.trim(),
          department: form.department.trim() || null,
          is_active: form.is_active,
        }),
      })
      await onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="sm">
    <form onSubmit={submit}>
      <DialogTitle>{employee ? 'Ubah data pegawai' : 'Tambah pegawai'}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">Nomor pegawai menjadi identitas operasional dan harus unik.</p>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack spacing={2}>
          <TextField
            className="light-field"
            label="Nomor pegawai"
            value={form.employee_number}
            onChange={update('employee_number')}
            helperText="Gunakan huruf, angka, titik, garis miring, atau tanda hubung."
            inputProps={{ maxLength: 80, pattern: '[A-Za-z0-9._/-]+' }}
            required
            autoFocus
          />
          <TextField
            className="light-field"
            label="Nama lengkap"
            value={form.full_name}
            onChange={update('full_name')}
            inputProps={{ maxLength: 150, minLength: 2 }}
            required
          />
          <TextField
            className="light-field"
            label="Departemen"
            value={form.department}
            onChange={update('department')}
            inputProps={{ maxLength: 120 }}
          />
          <FormControlLabel
            control={<Switch checked={form.is_active} onChange={update('is_active')} />}
            label="Pegawai aktif"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Batal</Button>
        <Button type="submit" variant="contained" disabled={saving}>
          {saving ? 'Menyimpan…' : 'Simpan pegawai'}
        </Button>
      </DialogActions>
    </form>
  </Dialog>
}

function CardDialog({ open, card, employee, token, onClose, onSaved }) {
  const [form, setForm] = useState(emptyCard)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setForm(card ? {
      ...emptyCard,
      ...card,
      label: card.label || '',
      valid_from: toLocalInput(card.valid_from),
      valid_until: toLocalInput(card.valid_until),
    } : emptyCard)
    setError('')
  }, [open, card])

  const update = field => event => setForm(current => ({ ...current, [field]: event.target.value }))

  const submit = async event => {
    event.preventDefault()
    setSaving(true)
    setError('')
    const payload = {
      label: form.label.trim() || null,
      status: form.status,
      valid_from: toApiTimestamp(form.valid_from),
      valid_until: toApiTimestamp(form.valid_until),
    }
    if (!card) payload.card_number = form.card_number.trim()
    try {
      await api(
        card
          ? `/employees/${employee.id}/cards/${card.id}`
          : `/employees/${employee.id}/cards`,
        token,
        {
          method: card ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
        },
      )
      await onSaved()
      onClose()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return <Dialog className="admin-dialog" open={open} onClose={onClose} fullWidth maxWidth="sm">
    <form onSubmit={submit}>
      <DialogTitle>{card ? 'Ubah kartu RFID' : 'Daftarkan kartu RFID'}</DialogTitle>
      <DialogContent>
        <p className="dialog-intro">
          Kartu akan terhubung ke <strong>{employee?.full_name}</strong> ({employee?.employee_number}).
        </p>
        {error && <Alert severity="error">{error}</Alert>}
        <Stack spacing={2}>
          <TextField
            className="light-field"
            label="Nomor kartu"
            value={form.card_number}
            onChange={update('card_number')}
            helperText={card ? 'Nomor kartu tidak dapat diubah.' : 'Masukkan UID yang dibaca perangkat RFID.'}
            inputProps={{ maxLength: 128, pattern: '[A-Za-z0-9:_-]+' }}
            disabled={Boolean(card)}
            required={!card}
            autoFocus={!card}
          />
          <TextField
            className="light-field"
            label="Label kartu"
            value={form.label}
            onChange={update('label')}
            helperText="Contoh: Kartu utama atau Kartu pengganti."
            inputProps={{ maxLength: 120 }}
          />
          <TextField className="light-field" select label="Status" value={form.status} onChange={update('status')}>
            {cardStatuses.map(value => <MenuItem key={value} value={value}>{statusLabels[value]}</MenuItem>)}
          </TextField>
          <div className="rfid-validity-grid">
            <TextField
              className="light-field"
              type="datetime-local"
              label="Berlaku mulai"
              InputLabelProps={{ shrink: true }}
              value={form.valid_from}
              onChange={update('valid_from')}
            />
            <TextField
              className="light-field"
              type="datetime-local"
              label="Berlaku sampai"
              InputLabelProps={{ shrink: true }}
              value={form.valid_until}
              onChange={update('valid_until')}
              error={Boolean(form.valid_from && form.valid_until && form.valid_until < form.valid_from)}
              helperText={form.valid_from && form.valid_until && form.valid_until < form.valid_from
                ? 'Waktu akhir harus setelah waktu mulai.'
                : 'Kosongkan jika tidak dibatasi.'}
            />
          </div>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Batal</Button>
        <Button
          type="submit"
          variant="contained"
          disabled={saving || Boolean(form.valid_from && form.valid_until && form.valid_until < form.valid_from)}
        >
          {saving ? 'Menyimpan…' : card ? 'Simpan kartu' : 'Daftarkan kartu'}
        </Button>
      </DialogActions>
    </form>
  </Dialog>
}

export default function EmployeeAdministration({ token }) {
  const [employees, setEmployees] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(25)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [activeFilter, setActiveFilter] = useState('ALL')
  const [department, setDepartment] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [cards, setCards] = useState([])
  const [cardsLoading, setCardsLoading] = useState(false)
  const [employeeDialog, setEmployeeDialog] = useState({ open: false, employee: null })
  const [cardDialog, setCardDialog] = useState({ open: false, card: null })
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loading, setLoading] = useState(true)
  const [importing, setImporting] = useState(false)
  const fileInputRef = useRef(null)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(0)
      setSearch(searchInput.trim())
    }, 250)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  const loadEmployees = useCallback(async (pageOverride = page) => {
    setLoading(true)
    setError('')
    const query = new URLSearchParams({
      offset: String(pageOverride * rowsPerPage),
      limit: String(rowsPerPage),
    })
    if (search) query.set('search', search)
    if (department.trim()) query.set('department', department.trim())
    if (activeFilter !== 'ALL') query.set('is_active', String(activeFilter === 'ACTIVE'))
    try {
      const result = await api(`/employees?${query}`, token)
      setEmployees(result.items)
      setTotal(result.total)
      setSelectedId(current => {
        if (result.items.some(employee => employee.id === current)) return current
        return result.items[0]?.id || null
      })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [token, page, rowsPerPage, search, department, activeFilter])

  useEffect(() => { loadEmployees() }, [loadEmployees])

  const selectedEmployee = useMemo(
    () => employees.find(employee => employee.id === selectedId) || null,
    [employees, selectedId],
  )

  const loadCards = useCallback(async () => {
    if (!selectedId) {
      setCards([])
      return
    }
    setCardsLoading(true)
    try {
      const result = await api(`/employees/${selectedId}/cards?limit=100`, token)
      setCards(result.items)
    } catch (err) {
      setError(err.message)
    } finally {
      setCardsLoading(false)
    }
  }, [selectedId, token])

  useEffect(() => { loadCards() }, [loadCards])

  const importCsv = async event => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setImporting(true)
    setError('')
    setNotice('')
    const body = new FormData()
    body.append('file', file)
    try {
      const result = await api('/employees/import', token, { method: 'POST', body })
      setNotice(`${result.imported_count} pegawai ditambahkan dari CSV.`)
      setPage(0)
      await loadEmployees(0)
    } catch (err) {
      setError(err.message)
    } finally {
      setImporting(false)
    }
  }

  return <section className="admin-section employee-admin" aria-labelledby="employee-management-title">
    <div className="employee-admin__head">
      <div>
        <h2 className="section-title" id="employee-management-title">Employee Management</h2>
        <p className="section-copy">
          {total} pegawai pada direktori. Pilih satu pegawai untuk mengelola kartu RFID.
        </p>
      </div>
      <div className="employee-admin__actions">
        <input
          ref={fileInputRef}
          className="employee-file-input"
          type="file"
          accept=".csv,text/csv"
          onChange={importCsv}
          tabIndex={-1}
        />
        <Button
          variant="outlined"
          startIcon={<UploadFileOutlinedIcon />}
          disabled={importing}
          onClick={() => fileInputRef.current?.click()}
        >
          {importing ? 'Mengimpor…' : 'Import CSV'}
        </Button>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setEmployeeDialog({ open: true, employee: null })}
        >
          Tambah pegawai
        </Button>
      </div>
    </div>

    {error && <Alert className="error-banner" severity="error" onClose={() => setError('')}>{error}</Alert>}
    {notice && <Alert className="employee-notice" severity="success" onClose={() => setNotice('')}>{notice}</Alert>}

    <div className="employee-toolbar">
      <TextField
        className="light-field"
        size="small"
        label="Cari pegawai"
        value={searchInput}
        onChange={event => setSearchInput(event.target.value)}
        InputProps={{
          startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
        }}
      />
      <TextField
        className="light-field"
        size="small"
        label="Departemen"
        value={department}
        onChange={event => { setPage(0); setDepartment(event.target.value) }}
      />
      <TextField
        className="light-field"
        size="small"
        select
        label="Status"
        value={activeFilter}
        onChange={event => { setPage(0); setActiveFilter(event.target.value) }}
      >
        <MenuItem value="ALL">Semua</MenuItem>
        <MenuItem value="ACTIVE">Aktif</MenuItem>
        <MenuItem value="INACTIVE">Nonaktif</MenuItem>
      </TextField>
    </div>

    <div className="employee-catalogue">
      <div className="employee-directory">
        <div className="ledger-table-wrap">
          <table className="ledger-table admin-table employee-table">
            <thead><tr><th>Pegawai</th><th>Departemen</th><th>Status</th><th>Aksi</th></tr></thead>
            <tbody>
              {employees.map(employee => <tr key={employee.id} data-selected={employee.id === selectedId}>
                <td data-label="Pegawai">
                  <button
                    type="button"
                    className="employee-select"
                    onClick={() => setSelectedId(employee.id)}
                    aria-pressed={employee.id === selectedId}
                  >
                    <span className="employee-select__icon" aria-hidden="true"><BadgeOutlinedIcon /></span>
                    <span>
                      <strong>{employee.full_name}</strong>
                      <small>{employee.employee_number}</small>
                    </span>
                  </button>
                </td>
                <td data-label="Departemen">{employee.department || 'Belum diisi'}</td>
                <td data-label="Status">
                  <Chip
                    size="small"
                    label={employee.is_active ? 'Aktif' : 'Nonaktif'}
                    color={employee.is_active ? 'success' : 'default'}
                  />
                </td>
                <td data-label="Aksi">
                  <Button
                    size="small"
                    startIcon={<EditOutlinedIcon />}
                    onClick={() => setEmployeeDialog({ open: true, employee })}
                  >
                    Ubah
                  </Button>
                </td>
              </tr>)}
              {!loading && !employees.length && <tr><td colSpan="4">
                <div className="employee-empty">
                  <BadgeOutlinedIcon aria-hidden="true" />
                  <strong>Pegawai tidak ditemukan.</strong>
                  <span>Ubah filter atau tambahkan pegawai pertama.</span>
                </div>
              </td></tr>}
              {loading && <tr><td colSpan="4"><p className="empty-copy">Memuat direktori pegawai…</p></td></tr>}
            </tbody>
          </table>
        </div>
        <TablePagination
          component="div"
          count={total}
          page={page}
          rowsPerPage={rowsPerPage}
          rowsPerPageOptions={[10, 25, 50]}
          labelRowsPerPage="Baris"
          onPageChange={(_, value) => setPage(value)}
          onRowsPerPageChange={event => { setPage(0); setRowsPerPage(Number(event.target.value)) }}
        />
      </div>

      <aside className="employee-card-panel" aria-labelledby="rfid-card-title">
        {selectedEmployee ? <>
          <div className="employee-card-panel__head">
            <div>
              <h3 id="rfid-card-title">{selectedEmployee.full_name}</h3>
              <p>{selectedEmployee.employee_number} · {selectedEmployee.department || 'Tanpa departemen'}</p>
            </div>
            <Button
              variant="outlined"
              startIcon={<AddIcon />}
              disabled={!selectedEmployee.is_active}
              onClick={() => setCardDialog({ open: true, card: null })}
            >
              Daftar kartu
            </Button>
          </div>
          {!selectedEmployee.is_active && <Alert severity="warning">
            Aktifkan pegawai sebelum mendaftarkan kartu baru.
          </Alert>}
          <ul className="rfid-card-list">
            {cards.map(card => <li key={card.id}>
              <div className="rfid-card-list__identity">
                <CreditCardOutlinedIcon aria-hidden="true" />
                <span><strong>{card.card_number}</strong><small>{card.label || 'Tanpa label'}</small></span>
              </div>
              <div className="rfid-card-list__meta">
                <Chip
                  size="small"
                  label={statusLabels[card.status] || card.status}
                  color={card.status === 'ACTIVE' ? 'success' : card.status === 'LOST' ? 'error' : 'default'}
                />
                <span>{formatDateTime(card.valid_until)}</span>
                <Button size="small" onClick={() => setCardDialog({ open: true, card })}>Ubah</Button>
              </div>
            </li>)}
          </ul>
          {!cardsLoading && !cards.length && <div className="employee-empty employee-empty--cards">
            <CreditCardOutlinedIcon aria-hidden="true" />
            <strong>Belum ada kartu RFID.</strong>
            <span>Daftarkan UID kartu untuk pegawai ini.</span>
          </div>}
          {cardsLoading && <p className="empty-copy">Memuat kartu RFID…</p>}
        </> : <div className="employee-empty employee-empty--cards">
          <BadgeOutlinedIcon aria-hidden="true" />
          <strong>Pilih pegawai.</strong>
          <span>Detail kartu RFID akan muncul di panel ini.</span>
        </div>}
      </aside>
    </div>

    <p className="employee-import-note">
      Format CSV: <code>employee_number,full_name,department,is_active</code>. Maksimal 5.000 baris dan 2 MB.
    </p>

    <EmployeeDialog
      open={employeeDialog.open}
      employee={employeeDialog.employee}
      token={token}
      onClose={() => setEmployeeDialog({ open: false, employee: null })}
      onSaved={loadEmployees}
    />
    <CardDialog
      open={cardDialog.open}
      card={cardDialog.card}
      employee={selectedEmployee}
      token={token}
      onClose={() => setCardDialog({ open: false, card: null })}
      onSaved={loadCards}
    />
  </section>
}
