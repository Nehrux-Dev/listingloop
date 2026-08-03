import { Link } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext.tsx'

/** Shown when an authenticated user hits a route their role does not allow. */
export default function ForbiddenPage() {
  const { user } = useAuth()

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-6">
      <div className="max-w-md text-center">
        <p className="text-sm font-medium text-slate-400">403</p>
        <h1 className="mt-1 text-xl font-semibold tracking-tight text-slate-900">
          You do not have access to this page
        </h1>
        <p className="mt-2 text-sm text-slate-500">
          Your role ({user?.role_display ?? 'unknown'}) does not include this area. If you
          think that is wrong, ask an administrator to review your permissions.
        </p>
        <Link
          to="/"
          className="mt-6 inline-block rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
        >
          Back to dashboard
        </Link>
      </div>
    </main>
  )
}
