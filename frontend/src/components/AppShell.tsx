import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import {
  ReceiptIcon,
  ChartBarIcon,
  SparkleIcon,
  SignOutIcon,
  PlusIcon,
} from '@phosphor-icons/react'
import { Button } from '@radix-ui/themes'
import { useAuth } from '../auth/AuthProvider'
import { ErrorNotice } from './Feedback'

export function AppShell() {
  const { user, logout } = useAuth()
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const links = [
    { to: '/receipts', label: 'Чеки', Icon: ReceiptIcon },
    { to: '/analytics', label: 'Аналитика', Icon: ChartBarIcon },
    { to: '/reports', label: 'Отчёты', Icon: SparkleIcon },
  ]
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        К содержимому
      </a>
      <aside className="sidebar">
        <NavLink className="brand" to="/receipts">
          <ReceiptIcon size={30} weight="duotone" />
          Покупки
        </NavLink>
        <NavLink className="upload-nav" to="/upload">
          <PlusIcon size={20} />
          Добавить чек
        </NavLink>
        <nav aria-label="Основная навигация">
          {links.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
            >
              <Icon size={22} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <p className="sidebar-tip">Проверьте распознанные товары, прежде чем подтвердить чек.</p>
          <div className="account">
            <span className="avatar">{user!.user_name.slice(0, 1).toUpperCase()}</span>
            <div>
              <strong>{user!.user_name}</strong>
              <small>{user!.user_mail}</small>
            </div>
            <Button
              variant="ghost"
              color="gray"
              aria-label="Выйти"
              loading={busy}
              onClick={async () => {
                setBusy(true)
                setError(null)
                try {
                  await logout()
                } catch (e) {
                  setError(e)
                } finally {
                  setBusy(false)
                }
              }}
            >
              <SignOutIcon size={21} />
            </Button>
          </div>
          {error != null && <ErrorNotice error={error} />}
        </div>
      </aside>
      <main id="main" className="workspace">
        <Outlet />
      </main>
    </div>
  )
}
