import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider } from './auth/AuthContext.tsx'
import { ProtectedRoute, RequireRole } from './auth/ProtectedRoute.tsx'
import { ROLES } from './auth/types.ts'
import AppLayout from './components/AppLayout.tsx'
import BrandKitPage from './pages/BrandKitPage.tsx'
import BrokeragePage from './pages/BrokeragePage.tsx'
import ContentCalendarPage from './pages/ContentCalendarPage.tsx'
import DashboardPage from './pages/DashboardPage.tsx'
import DesignEditorPage from './pages/DesignEditorPage.tsx'
import DesignsPage from './pages/DesignsPage.tsx'
import EnquiriesPage from './pages/EnquiriesPage.tsx'
import ForbiddenPage from './pages/ForbiddenPage.tsx'
import ListingFormPage from './pages/ListingFormPage.tsx'
import ListingImportPage from './pages/ListingImportPage.tsx'
import ListingsPage from './pages/ListingsPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
import OnboardingPage from './pages/OnboardingPage.tsx'
import PlatformAdminPage from './pages/PlatformAdminPage.tsx'
import ProfilePage from './pages/ProfilePage.tsx'
import PublicListingPage from './pages/PublicListingPage.tsx'
import RegisterPage from './pages/RegisterPage.tsx'
import TemplateLibraryPage from './pages/TemplateLibraryPage.tsx'

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          {/* Public — no session required, and deliberately outside the app
              shell: these pages are shared with people who have no account. */}
          <Route path="/p/:slug" element={<PublicListingPage />} />

          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forbidden" element={<ForbiddenPage />} />

          {/* Everything below requires a session. Unauthenticated visitors are
              redirected to /login with the attempted path in location state. */}
          <Route element={<ProtectedRoute />}>
            {/* Onboarding needs a session but not the app shell — it is the
                bridge between registering and having a usable workspace. */}
            <Route path="/onboarding" element={<OnboardingPage />} />
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
              <Route path="enquiries" element={<EnquiriesPage />} />

              {/* Templates are read-only product content; designs are scoped
                  server-side to the caller, so no extra guard is needed. */}
              <Route path="calendar" element={<ContentCalendarPage />} />
              <Route path="templates" element={<TemplateLibraryPage />} />
              <Route path="designs" element={<DesignsPage />} />
              <Route path="designs/:id" element={<DesignEditorPage />} />

              {/* Hierarchical guard: Brokerage Admins and Nehrux Admins —
                  plus any agent who created their own firm during onboarding
                  and therefore administers it. The server independently checks
                  `administers(user, brokerage)` on every write. */}
              <Route
                element={
                  <RequireRole
                    minimumRole={ROLES.BROKERAGE_ADMIN}
                    orBrokerageAdministrator
                  />
                }
              >
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
