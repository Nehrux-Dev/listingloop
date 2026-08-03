import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider } from './auth/AuthContext.tsx'
import { ProtectedRoute, RequireRole } from './auth/ProtectedRoute.tsx'
import { ROLES } from './auth/types.ts'
import AppLayout from './components/AppLayout.tsx'
import BrandKitPage from './pages/BrandKitPage.tsx'
import BrokeragePage from './pages/BrokeragePage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import ForbiddenPage from './pages/ForbiddenPage.tsx'
import ListingFormPage from './pages/ListingFormPage.tsx'
import ListingImportPage from './pages/ListingImportPage.tsx'
import ListingsPage from './pages/ListingsPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import PlatformAdminPage from './pages/PlatformAdminPage.tsx'
import ProfilePage from './pages/ProfilePage.tsx'

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

              {/* Any authenticated user with an agent profile. Both pages
                  address the caller's own record via /me/ and /mine/. */}
              <Route path="profile" element={<ProfilePage />} />
              <Route path="brand-kit" element={<BrandKitPage />} />

              {/* Listings are scoped server-side: an agent's queryset only
                  ever contains their own, so no extra guard is needed here. */}
              <Route path="listings" element={<ListingsPage />} />
              <Route path="listings/new" element={<ListingFormPage />} />
              <Route path="listings/import" element={<ListingImportPage />} />
              <Route path="listings/:id" element={<ListingFormPage />} />

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
