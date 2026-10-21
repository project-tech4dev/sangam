'use client'

import type { User } from '@supabase/supabase-js'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { LoginForm } from '@/features/auth/login-form'
import { DEV_LOGIN, DEV_USERS, devEmail, setDevEmail } from '@/lib/devAuth'
import { createClient } from '@/lib/supabase/client'

function initials(user: User) {
  const name: string = user.user_metadata?.full_name ?? user.email ?? '?'
  const parts = name.split(/[\s@._-]+/).filter(Boolean)
  return parts.slice(0, 2).map((p) => p[0]!.toUpperCase()).join('')
}

function UserMenu({ user }: { user: User }) {
  const router = useRouter()
  const name: string = user.user_metadata?.full_name ?? user.email ?? 'Account'

  async function logOut() {
    await createClient().auth.signOut()
    // Server components (the /ask workspace above all) read the session; re-render them.
    router.refresh()
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="flex cursor-pointer items-center gap-2 rounded-full border-none bg-transparent py-1 pr-2.5 pl-1"
        >
          <Avatar className="size-7.5">
            <AvatarFallback>{initials(user)}</AvatarFallback>
          </Avatar>
          <span className="hidden text-sm text-(--color-text) sm:inline">{name}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel className="truncate">Signed in — {user.email}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => router.push('/settings')}>Settings</DropdownMenuItem>
        <DropdownMenuItem onSelect={() => router.push('/settings/graph')}>Knowledge graph</DropdownMenuItem>
        <DropdownMenuItem className="text-terracotta-750" onSelect={logOut}>
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// Local testing only: pick which seeded @local.test user the app runs as.
function DevSignIn() {
  const router = useRouter()
  const [email, setEmail] = useState<string | null>(null)
  useEffect(() => setEmail(devEmail()), [])
  function pick(value: string) {
    setDevEmail(value || null)
    setEmail(value || null)
    router.refresh()
  }
  return (
    <select className="input" aria-label="Sign in as" value={email ?? ''} onChange={(e) => pick(e.target.value)}>
      <option value="">Signed out</option>
      {DEV_USERS.map((u) => (
        <option key={u} value={u}>
          {u}
        </option>
      ))}
    </select>
  )
}

export function SignInButton() {
  if (DEV_LOGIN) return <DevSignIn />
  return <SupabaseSignIn />
}

function SupabaseSignIn() {
  const [user, setUser] = useState<User | null | undefined>(undefined)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const supabase = createClient()
    supabase.auth.getSession().then(({ data }) => setUser(data.session?.user ?? null))
    const { data } = supabase.auth.onAuthStateChange((_event, session) => setUser(session?.user ?? null))
    return () => data.subscription.unsubscribe()
  }, [])

  if (user === undefined) return null
  if (user) return <UserMenu user={user} />

  // Signing in from the navbar always lands in Ask Sangam.
  return (
    <>
      <button type="button" className="btn btn-primary shrink-0 px-4 py-2" onClick={() => setOpen(true)}>
        Sign in
      </button>
      <LoginForm open={open} onOpenChange={setOpen} next="/ask" />
    </>
  )
}
