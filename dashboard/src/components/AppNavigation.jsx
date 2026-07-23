import { Drawer, IconButton, useMediaQuery } from '@mui/material'
import AccountCircleOutlinedIcon from '@mui/icons-material/AccountCircleOutlined'
import BadgeOutlinedIcon from '@mui/icons-material/BadgeOutlined'
import CloseIcon from '@mui/icons-material/Close'
import ContactlessOutlinedIcon from '@mui/icons-material/ContactlessOutlined'
import DashboardOutlinedIcon from '@mui/icons-material/DashboardOutlined'
import FingerprintOutlinedIcon from '@mui/icons-material/FingerprintOutlined'
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined'
import LogoutIcon from '@mui/icons-material/Logout'
import ManageAccountsOutlinedIcon from '@mui/icons-material/ManageAccountsOutlined'
import SettingsOutlinedIcon from '@mui/icons-material/SettingsOutlined'
import VideocamOutlinedIcon from '@mui/icons-material/VideocamOutlined'

const administrationItems = [
  { value: 'cameras', label: 'Kamera', icon: VideocamOutlinedIcon, roles: ['SUPER_ADMIN', 'ADMIN'] },
  { value: 'employees', label: 'Pegawai & RFID', icon: BadgeOutlinedIcon, roles: ['SUPER_ADMIN', 'ADMIN'] },
  { value: 'rfid-simulator', label: 'Simulator RFID', icon: ContactlessOutlinedIcon, roles: ['SUPER_ADMIN', 'ADMIN'] },
  { value: 'users', label: 'Pengguna & role', icon: ManageAccountsOutlinedIcon, roles: ['SUPER_ADMIN'] },
  { value: 'identities', label: 'Identitas ReID', icon: FingerprintOutlinedIcon, roles: ['SUPER_ADMIN', 'ADMIN'] },
  { value: 'backups', label: 'Backup & arsip', icon: Inventory2OutlinedIcon, roles: ['SUPER_ADMIN'] },
]

const roleLabel = value => value?.replaceAll('_', ' ') || 'Memuat akun'

export default function AppNavigation({
  open,
  page,
  adminSection,
  canAdminister,
  currentUser,
  socketStatus,
  onClose,
  onPageChange,
  onAdminSectionChange,
  onLogout,
}) {
  const desktop = useMediaQuery('(min-width:60rem)')
  const visibleAdminItems = administrationItems.filter(item => item.roles.includes(currentUser?.role))

  const choosePage = value => {
    onPageChange(value)
    onClose()
  }

  const chooseAdminSection = value => {
    onPageChange('administration')
    onAdminSectionChange(value)
    onClose()
  }

  return <Drawer
    className="app-navigation"
    variant={desktop ? 'permanent' : 'temporary'}
    open={desktop || open}
    onClose={onClose}
    ModalProps={{ keepMounted: true }}
  >
    <aside className="app-navigation__panel" aria-label="Navigasi aplikasi">
      <div className="app-navigation__brand">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">PF</span>
          <div className="brand-copy">
            <strong>People Flow Control</strong>
            <span>Realtime operations</span>
          </div>
        </div>
        {!desktop && <IconButton className="icon-action" onClick={onClose} aria-label="Tutup navigasi">
          <CloseIcon />
        </IconButton>}
      </div>

      <nav className="app-navigation__menus" aria-label="Menu utama">
        <button
          className="navigation-item"
          type="button"
          data-active={page === 'monitoring'}
          aria-current={page === 'monitoring' ? 'page' : undefined}
          onClick={() => choosePage('monitoring')}
        >
          <DashboardOutlinedIcon aria-hidden="true" />
          <span>Monitoring</span>
        </button>

        {canAdminister && <button
          className="navigation-item"
          type="button"
          data-active={page === 'administration'}
          aria-expanded={page === 'administration'}
          onClick={() => choosePage('administration')}
        >
          <SettingsOutlinedIcon aria-hidden="true" />
          <span>Administrasi</span>
        </button>}

        {canAdminister && page === 'administration' && <div className="administration-navigation" aria-label="Menu administrasi">
          {visibleAdminItems.map(item => {
            const ItemIcon = item.icon
            return <button
              className="administration-navigation__item"
              type="button"
              key={item.value}
              data-active={adminSection === item.value}
              aria-current={adminSection === item.value ? 'page' : undefined}
              onClick={() => chooseAdminSection(item.value)}
            >
              <ItemIcon aria-hidden="true" />
              <span>{item.label}</span>
            </button>
          })}
        </div>}
      </nav>

      <div className="app-navigation__footer">
        <div className="navigation-account">
          <AccountCircleOutlinedIcon aria-hidden="true" />
          <div>
            <strong>{currentUser?.full_name || currentUser?.username || 'Akun operator'}</strong>
            <span>{roleLabel(currentUser?.role)}</span>
          </div>
        </div>
        <div className="connection-pill">
          <span className="status-dot" data-status={socketStatus} />
          {socketStatus === 'connected' ? 'Realtime aktif' : socketStatus}
        </div>
        <button className="navigation-logout" type="button" onClick={onLogout}>
          <LogoutIcon aria-hidden="true" />
          <span>Keluar</span>
        </button>
      </div>
    </aside>
  </Drawer>
}
