'use client'

import type { User } from '@supabase/supabase-js'
import { useEffect, useRef, useState } from 'react'

import { LoginForm } from '@/features/auth/login-form'
import { createClient } from '@/lib/supabase/client'

function initials(user: User) {
  const name: string = user.user_metadata?.full_name ?? user.email ?? '?'
  const parts = name.split(/[\s@._-]+/).filter(Boolean)
  return parts.slice(0, 2).map((p) => p[0]!.toUpperCase()).join('')
}

function UserMenu({ user }: { user: User }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const name: string = user.user_metadata?.full_name ?? user.email ?? 'Account'

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex cursor-pointer items-center gap-2 rounded-md border-none bg-transparent px-1.5 py-1"
      >
        <span className="flex size-7.5 items-center justify-center rounded-full bg-terracotta-600 font-(family-name:--font-heading) text-xs text-(--color-bg)">
          {initials(user)}
        </span>
        <span className="text-sm text-(--color-text)">{name}</span>
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-55 rounded-md border border-(--color-divider) bg-(--color-bg) p-2 shadow-(--shadow-md)"
        >
          <div className="truncate px-2.5 py-2 text-xs text-(--color-neutral-700)">
            Signed in — {user.email}
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={() => createClient().auth.signOut()}
            className="block w-full cursor-pointer rounded-sm border-none bg-transparent px-2.5 py-2 text-left text-sm text-terracotta-700 hover:bg-(--color-neutral-100)"
          >
            Log out
          </button>
        </div>
      )}
    </div>
  )
}

export function SignInButton() {
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

  return (
    <>
      <button type="button" className="btn btn-primary btn-square px-4 py-2" onClick={() => setOpen(true)}>
        Sign in
      </button>
      {open && <LoginForm onCancel={() => setOpen(false)} />}
    </>
  )
}
