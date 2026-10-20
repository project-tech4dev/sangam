import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { LoginForm } from "@/features/auth/login-form";
import { SignInButton } from "@/features/auth/sign-in-button";
import { navigation } from "@/tests/setup";

// The Supabase keys are read when login-form loads, so they are set before any import.
vi.hoisted(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://x.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "pk";
});

const supabase = vi.hoisted(() => ({
  session: null as null | { user: object },
  onChange: (() => {}) as (event: string, session: { user: object } | null) => void,
  signInWithOAuth: vi.fn(),
  signOut: vi.fn(async () => ({})),
  unsubscribe: vi.fn(),
}));

vi.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      signInWithOAuth: supabase.signInWithOAuth,
      signOut: supabase.signOut,
      getSession: async () => ({ data: { session: supabase.session } }),
      onAuthStateChange: (cb: typeof supabase.onChange) => {
        supabase.onChange = cb;
        return { data: { subscription: { unsubscribe: supabase.unsubscribe } } };
      },
    },
  }),
}));

const dev = vi.hoisted(() => ({ on: false, email: null as string | null, set: vi.fn() }));
vi.mock("@/lib/devAuth", () => ({
  get DEV_LOGIN() {
    return dev.on;
  },
  DEV_USERS: ["admin@local.test", "member@local.test"],
  devEmail: () => dev.email,
  setDevEmail: dev.set,
}));

afterAll(() => {
  delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  delete process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
});

beforeEach(() => {
  supabase.session = null;
  supabase.signInWithOAuth.mockReset();
  dev.on = false;
  dev.email = null;
  dev.set.mockReset();
});

describe("LoginForm", () => {
  it("sends Google sign-in back through the callback with the next path", async () => {
    const before = vi.fn();
    supabase.signInWithOAuth.mockReturnValue(new Promise(() => {}));
    render(<LoginForm next="/ask?q=1" onBeforeRedirect={before} onOpenChange={vi.fn()} />);
    expect(screen.getByText("Sign in with Google to ask questions and see your workspace.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(before).toHaveBeenCalledOnce();
    const { redirectTo } = supabase.signInWithOAuth.mock.calls[0][0].options;
    expect(supabase.signInWithOAuth.mock.calls[0][0].provider).toBe("google");
    expect(new URL(redirectTo).pathname).toBe("/auth/callback");
    expect(new URL(redirectTo).searchParams.get("next")).toBe("/ask?q=1");
    expect(screen.getByRole("button", { name: "Redirecting…" })).toBeDisabled();
  });

  it("shows the provider's error and lets the person try again", async () => {
    supabase.signInWithOAuth.mockResolvedValue({ error: { message: "Provider is disabled" } });
    render(<LoginForm onOpenChange={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(await screen.findByText("Provider is disabled")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with Google" })).toBeEnabled();
  });

  it("Cancel with no handler goes home", async () => {
    render(<LoginForm />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(navigation.router.replace).toHaveBeenCalledWith("/");
  });
});

describe("SignInButton", () => {
  it("offers Sign in when signed out and opens the dialog", async () => {
    render(<SignInButton />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(screen.getByRole("dialog", { name: "Sign in to Sangam" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the user's menu once signed in, and logs out", async () => {
    supabase.session = { user: { email: "asha.k@k.org", user_metadata: { full_name: "Asha Kumari" } } };
    const { unmount } = render(<SignInButton />);
    expect(await screen.findByText("AK")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Asha Kumari/ }));
    expect(screen.getByText("Signed in — asha.k@k.org")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Settings" }));
    expect(navigation.router.push).toHaveBeenCalledWith("/settings");
    await userEvent.click(screen.getByRole("button", { name: /Asha Kumari/ }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Log out" }));
    expect(supabase.signOut).toHaveBeenCalled();
    expect(navigation.router.refresh).toHaveBeenCalled();
    unmount();
    expect(supabase.unsubscribe).toHaveBeenCalled();
  });

  it("follows an auth change, using the email when there is no name", async () => {
    render(<SignInButton />);
    await screen.findByRole("button", { name: "Sign in" });
    act(() => supabase.onChange("SIGNED_IN", { user: { email: "ravi@k.org", user_metadata: {} } }));
    expect(screen.getByText("RK")).toBeInTheDocument();
    act(() => supabase.onChange("SIGNED_OUT", null));
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("in dev login, picks a seeded user and refreshes", async () => {
    dev.on = true;
    dev.email = "member@local.test";
    render(<SignInButton />);
    const select = screen.getByRole("combobox", { name: "Sign in as" });
    expect(select).toHaveValue("member@local.test");
    await userEvent.selectOptions(select, "admin@local.test");
    expect(dev.set).toHaveBeenCalledWith("admin@local.test");
    expect(navigation.router.refresh).toHaveBeenCalled();
    await userEvent.selectOptions(select, "");
    expect(dev.set).toHaveBeenLastCalledWith(null);
    expect(select).toHaveValue("");
  });
});
