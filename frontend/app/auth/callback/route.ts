import { NextResponse } from 'next/server'

// The client you created from the Server-Side Auth instructions
import { safeNextPath } from '@/lib/safe-next-path'
import { createClient } from '@/lib/supabase/server'

// Behind a proxy (Caddy on EC2) request.url carries the container's address, so the public host comes from the proxy.
function publicOrigin(request: Request, origin: string) {
  if (process.env.NODE_ENV === 'development') return origin
  const host = request.headers.get('x-forwarded-host')
  if (!host) return origin
  const proto = request.headers.get('x-forwarded-proto') ?? 'https'
  return `${proto}://${host}`
}

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url)
  const code = searchParams.get('code')
  // Only a same-origin path: a bare startsWith('/') check lets //evil.com through.
  const next = safeNextPath(searchParams.get('next'), '/', origin)
  const base = publicOrigin(request, origin)

  if (code) {
    const supabase = await createClient()
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) return NextResponse.redirect(`${base}${next}`)
  }

  // return the user to an error page with instructions
  return NextResponse.redirect(`${base}/auth/error`)
}
