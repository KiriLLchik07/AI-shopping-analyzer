import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth/AuthProvider'
import { AppShell } from './components/AppShell'
import { LoginPage } from './pages/LoginPage'
import { ReceiptsPage } from './pages/ReceiptsPage'
import { UploadPage } from './pages/UploadPage'
import { ReceiptPage } from './pages/ReceiptPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { ReportsPage } from './pages/ReportsPage'
import { Empty } from './components/Feedback'
import { Link } from 'react-router-dom'

function Protected() {
  const { user } = useAuth()
  const location = useLocation()
  return user ? (
    <Outlet />
  ) : (
    <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  )
}
export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected />}>
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/receipts" replace />} />
          <Route path="receipts" element={<ReceiptsPage />} />
          <Route path="receipts/:receiptId" element={<ReceiptPage />} />
          <Route path="upload" element={<UploadPage />} />
          <Route path="analytics" element={<AnalyticsPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="reports/:reportId" element={<ReportsPage />} />
          <Route
            path="*"
            element={
              <Empty
                title="Страница не найдена"
                description="Проверьте адрес или вернитесь к чекам."
                action={<Link to="/receipts">К чекам</Link>}
              />
            }
          />
        </Route>
      </Route>
    </Routes>
  )
}
