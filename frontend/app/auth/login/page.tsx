import { LoginForm } from '@/features/auth/login-form'

// Reached when the proxy turns away a signed-out request; `next` is where it was going.
export default async function Page({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams
  return <LoginForm next={next ?? '/'} />
}
