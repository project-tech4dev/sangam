import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/features/auth/login-form";

// Cleared before login-form loads, whatever the shell has set.
vi.hoisted(() => {
  delete process.env.NEXT_PUBLIC_SUPABASE_URL;
});

vi.mock("@/lib/supabase/client", () => ({ createClient: vi.fn() }));

describe("LoginForm without Supabase keys", () => {
  it("says sign-in is unavailable and offers no Google button", () => {
    render(<LoginForm onOpenChange={vi.fn()} />);
    expect(screen.getByText(/Sign-in is not available in this environment/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Continue with Google" })).not.toBeInTheDocument();
  });
});
