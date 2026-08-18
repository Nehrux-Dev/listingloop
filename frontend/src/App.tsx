import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { AuthProvider } from './auth/AuthContext.tsx'
import { ProtectedRoute, RequireRole } from './auth/ProtectedRoute.tsx'
import { ROLES } from './auth/types.ts'
import AdminLayout from './components/AdminLayout.tsx'
import AppLayout from './components/AppLayout.tsx'
import { ComplianceNoticeProvider } from './components/ComplianceNotice.tsx'
import PlatformLayout from './components/PlatformLayout.tsx'
import AdminHomePage from './pages/admin/AdminHomePage.tsx'
import TemplateUploadPage from './pages/platform/TemplateUploadPage.tsx'
import BrandKitPage from './pages/BrandKitPage.tsx'
import BrokeragePage from './pages/BrokeragePage.tsx'
import ContentCalendarPage from './pages/ContentCalendarPage.tsx'
import RoleHome from './pages/RoleHome.tsx'
import DesignEditorPage from './pages/DesignEditorPage.tsx'
import DesignsPage from './pages/DesignsPage.tsx'
import EnquiriesPage from './pages/EnquiriesPage.tsx'
import ForbiddenPage from './pages/ForbiddenPage.tsx'
import ListingFormPage from './pages/ListingFormPage.tsx'
import ListingImportPage from './pages/ListingImportPage.tsx'
import ListingsPage from './pages/ListingsPage.tsx'
import LoginPage from './pages/LoginPage.tsx'
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
            {/* The editor is deliberately OUTSIDE the app shell.
                A design occupies the whole screen the way it does in every
                tool of this kind: the rail's ten destinations are not what an
                agent is choosing between while they are moving a photo two
                pixels, and the editor's own header carries the way back out.
                It keeps its own compliance provider because it no longer has
                the shell's one above it. */}
            <Route
              path="designs/:id/edit"
              element={
                <ComplianceNoticeProvider>
                  <DesignEditorPage />
                </ComplianceNoticeProvider>
              }
            />
            {/* ---------------------------------------------------------------
                THREE DASHBOARDS, ONE APPLICATION.

                Agents make marketing. Agency admins run the firm that bought
                the product. Nehrux runs the platform the firms buy from. Those
                are three jobs, not three permission levels on one job, so each
                gets its own shell with its own navigation.

                `RoleHome` at "/" is what sends each of them to their own front
                door, so nobody has to know which URL their dashboard lives at.
                The rails are presentation; every route below is guarded and
                every endpoint re-checks.
            --------------------------------------------------------------- */}

            {/* -- 3. Nehrux, the platform owner --------------------------- */}
            {/* One job and one screen: turn a PDF into a template and put it
                in front of the agents. Overview, library and account screens
                lived here briefly and were removed — this dashboard exists to
                do the one thing no customer can do, and anything else on it is
                something to scroll past on the way to doing it. */}
            <Route element={<RequireRole roles={[ROLES.NEHRUX_ADMIN]} />}>
              <Route path="platform" element={<PlatformLayout />}>
                <Route index element={<TemplateUploadPage />} />
                {/* Kept so the links written while this had sub-pages still
                    land somewhere real. */}
                <Route path="upload" element={<Navigate to="/platform" replace />} />
                <Route path="*" element={<Navigate to="/platform" replace />} />
              </Route>
            </Route>

            {/* -- 2. The buying agency ------------------------------------ */}
            <Route
              element={
                <RequireRole minimumRole={ROLES.BROKERAGE_ADMIN} orBrokerageAdministrator />
              }
            >
              <Route path="admin" element={<AdminLayout />}>
                <Route index element={<AdminHomePage />} />
                <Route path="brokerage" element={<BrokeragePage />} />
                <Route path="brand-kit" element={<BrandKitPage />} />
                <Route path="listings" element={<ListingsPage />} />
                <Route path="designs" element={<DesignsPage />} />
                <Route path="enquiries" element={<EnquiriesPage />} />
              </Route>
            </Route>

            {/* -- 1. The agent -------------------------------------------- */}
            <Route element={<AppLayout />}>
              {/* Registration lands here. There is no setup wizard in between:
                  the profile, brokerage and brand kit are all optional, live in
                  Settings, and are enforced at export instead. */}
              <Route index element={<RoleHome />} />

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
              {/* Two screens, not one. The gallery is the catalogue you start
                  from; the designs panel is your own work in progress. */}
              <Route path="templates" element={<TemplateLibraryPage />} />
              <Route path="designs" element={<DesignsPage />} />
              {/* Editing is its own screen, not a mode of the designs list.
                  The bare /designs/:id is kept as a redirect: it is what
                  every link written before the editor moved still points
                  at, and a dead link is a worse answer than a hop. */}
              <Route path="designs/:id" element={<Navigate to="edit" replace />} />

              {/* Kept as redirects: these are what every link and bookmark
                  written before the split still points at, and a dead link is
                  a worse answer than a hop. */}
              <Route path="brokerage" element={<Navigate to="/admin/brokerage" replace />} />
            </Route>
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
