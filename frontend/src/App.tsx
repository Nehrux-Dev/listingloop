import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider } from './auth/AuthContext.tsx'
import { ProtectedRoute, RequireRole } from './auth/ProtectedRoute.tsx'
import { ROLES } from './auth/types.ts'
import AppLayout from './components/AppLayout.tsx'
import BrokeragePage from './pages/BrokeragePage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import ForbiddenPage from './pages/ForbiddenPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import PlatformAdminPage from './pages/PlatformAdminPage.tsx'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forbidden" element={<ForbiddenPage />} />

          {/* Everything below requires a session. Unauthenticated visitors are
              redirected to /login with the attempted path in location state. */}
          <Route element={<ProtectedRoute />}>
            <Route element={<AppLayout />}>
              <Route index element={<DashboardPage />} />

              {/* Hierarchical guard: Brokerage Admins and Nehrux Admins. */}
              <Route element={<RequireRole minimumRole={ROLES.BROKERAGE_ADMIN} />}>
                <Route path="brokerage" element={<BrokeragePage />} />
              </Route>

              {/* Exact-role guard: Nehrux Admins only. An Agent who types
                  /platform into the address bar lands on /forbidden. */}
              <Route element={<RequireRole roles={[ROLES.NEHRUX_ADMIN]} />}>
                <Route path="platform" element={<PlatformAdminPage />} />
              </Route>
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
