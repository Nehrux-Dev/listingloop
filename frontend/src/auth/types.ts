export const ROLES = {
  AGENT: 'agent',
  BROKERAGE_ADMIN: 'brokerage_admin',
  NEHRUX_ADMIN: 'nehrux_admin',
} as const

export type Role = (typeof ROLES)[keyof typeof ROLES]

/** Privilege ordering — must stay in sync with ROLE_LEVELS on the backend. */
export const ROLE_LEVELS: Record<Role, number> = {
  [ROLES.AGENT]: 10,
  [ROLES.BROKERAGE_ADMIN]: 20,
  [ROLES.NEHRUX_ADMIN]: 30,
}

export const ROLE_LABELS: Record<Role, string> = {
  [ROLES.AGENT]: 'Agent',
  [ROLES.BROKERAGE_ADMIN]: 'Brokerage Admin',
  [ROLES.NEHRUX_ADMIN]: 'Nehrux Admin',
}

export type User = {
  id: number
  email: string
  first_name: string
  last_name: string
  full_name: string
  role: Role
  role_display: string
  /**
   * True when this user administers at least one brokerage — which an Agent
   * does if they created their firm during onboarding. Separate from `role`
   * on purpose: administering one brokerage is not a rank.
   */
  administers_brokerage: boolean
  is_active: boolean
  date_joined: string
}

export type LoginResponse = {
  access: string
  user: User
}

export type Credentials = {
  email: string
  password: string
}

/** True when `role` is `minimum` or more privileged. */
export function hasRoleAtLeast(role: Role, minimum: Role): boolean {
  return (ROLE_LEVELS[role] ?? 0) >= (ROLE_LEVELS[minimum] ?? 0)
}
