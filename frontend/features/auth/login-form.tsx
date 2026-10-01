'use client'

import { useRouter } from 'next/navigation'
import { useState, useSyncExternalStore } from 'react'
import { createPortal } from 'react-dom'

import { createClient } from '@/lib/supabase/client'

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.9-2.26 5.36-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59A14.5 14.5 0 019.5 24c0-1.59.27-3.13.76-4.59l-7.98-6.19A23.9 23.9 0 000 24c0 3.87.93 7.52 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.82l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  )
}

const subscribe = () => () => {}

export function LoginForm({ onCancel }: { onCancel?: () => void }) {
  const router = useRouter()
  const cancel = onCancel ?? (() => router.push('/'))
  const mounted = useSyncExternalStore(subscribe, () => true, () => false)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const signInWithGoogle = async () => {
    setIsLoading(true)
    setError(null)

    const { error } = await createClient().auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    })

    if (error) {
      setError(error.message)
      setIsLoading(false)
    }
  }

  if (!mounted) return null

  return createPortal(
    <div className="dialog-backdrop" onClick={cancel}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="sign-in-title"
        className="dialog flex flex-col gap-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sign-in-title" className="dialog-title">
          Sign in to Sangam
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <button
          type="button"
          className="btn btn-primary self-center gap-2 px-4 py-2 text-sm"
          onClick={signInWithGoogle}
          disabled={isLoading}
        >
          <GoogleIcon />
          {isLoading ? 'Redirecting…' : 'Continue with Google'}
        </button>
        <div className="dialog-actions">
          <button type="button" className="btn btn-ghost" onClick={cancel}>
            Cancel
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
