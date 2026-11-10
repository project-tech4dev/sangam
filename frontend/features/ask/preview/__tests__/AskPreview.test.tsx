import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const savePendingQuestion = vi.fn();
vi.mock("@/features/ask/lib/pendingQuestion", () => ({ savePendingQuestion: (q: string) => savePendingQuestion(q) }));
vi.mock("@/features/auth/login-form", () => ({
  LoginForm: ({ open, next, onOpenChange, onBeforeRedirect }: { open: boolean; next: string; onOpenChange: (o: boolean) => void; onBeforeRedirect: () => void }) =>
    open ? (
      <div role="dialog" aria-label="Sign in" data-next={next}>
        <button type="button" onClick={onBeforeRedirect}>
          Continue with Google
        </button>
        <button type="button" onClick={() => onOpenChange(false)}>
          Close
        </button>
      </div>
    ) : null,
}));
vi.mock("@/lib/AgentProviders", () => ({ AgentProviders: ({ children }: { children: ReactNode }) => <div data-testid="providers">{children}</div> }));
vi.mock("@/features/ask/AskWorkspace", () => ({
  AskWorkspace: ({ initialQuestion }: { initialQuestion: string | null }) => <p>workspace {initialQuestion}</p>,
}));
// The lazy boundary shows its loading state; the workspace it loads is tested on its own.
vi.mock("next/dynamic", () => ({ default: (_load: unknown, opts: { loading: () => ReactNode }) => () => opts.loading() }));

import { SignedInWorkspace } from "@/features/ask/SignedInWorkspace";
import { WorkspaceLoader } from "@/features/ask/WorkspaceLoader";
import { AskPreview } from "@/features/ask/preview/AskPreview";
import type { IndexPayload } from "@/features/ask/AskWorkspace";

afterEach(() => vi.clearAllMocks());

describe("AskPreview", () => {
  it("shows a sample answer with its citations and criteria", () => {
    render(<AskPreview />);
    expect(screen.getByRole("heading", { name: "What an answer looks like" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "org:1" })[0]).toHaveAttribute("href", "/registry/kabil");
    expect(screen.getByText("Why this match — 7 criteria")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ask Sangam" })).toBeDisabled();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens sign-in on a typed question and saves it before leaving", async () => {
    render(<AskPreview />);
    await userEvent.type(screen.getByRole("textbox"), "Who funds Assam?");
    await userEvent.click(screen.getByRole("button", { name: "Ask Sangam" }));
    const dialog = screen.getByRole("dialog", { name: "Sign in" });
    expect(dialog).toHaveAttribute("data-next", "/");
    await userEvent.click(screen.getByRole("button", { name: "Continue with Google" }));
    expect(savePendingQuestion).toHaveBeenCalledWith("Who funds Assam?");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("takes an example or a follow-up as the question, and ⌘↵ asks", async () => {
    render(<AskPreview initialQuestion="Prefilled" />);
    expect(screen.getByRole("textbox")).toHaveValue("Prefilled");
    await userEvent.click(screen.getByRole("button", { name: "Which funders back livelihoods work?" }));
    expect(screen.getByRole("textbox")).toHaveValue("Which funders back livelihoods work?");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await userEvent.click(screen.getByRole("button", { name: "Which other funders fit KABIL well? →" }));
    expect(screen.getByRole("textbox")).toHaveValue("Which other funders fit KABIL well?");
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.type(screen.getByRole("textbox"), "   {Meta>}{Enter}{/Meta}");
    expect(screen.queryByRole("dialog")).toBeNull();
    await userEvent.type(screen.getByRole("textbox"), "x{Meta>}{Enter}{/Meta}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("workspace loading", () => {
  const payload = { orgs: [], funders: [], scores: [], activities: [], stats: {}, canScout: false, me: null } as IndexPayload;

  it("wraps the workspace in the agent providers", () => {
    render(<SignedInWorkspace payload={payload} initialQuestion="Hi" />);
    expect(screen.getByTestId("providers")).toHaveTextContent("workspace Hi");
  });

  it("shows a loading line while the workspace downloads", () => {
    render(<WorkspaceLoader payload={payload} initialQuestion={null} />);
    expect(screen.getByText("Opening your workspace…")).toBeInTheDocument();
  });
});
