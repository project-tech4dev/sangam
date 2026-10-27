import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Component, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));
const uploadToVault = vi.fn();
vi.mock("@/features/ask/lib/vault", () => ({ uploadToVault: (...a: unknown[]) => uploadToVault(...a) }));
const proposals = vi.hoisted(() => ({ rows: [] as unknown[], old: false }));
vi.mock("@/features/ask/views/proposals/api", () => ({
  useProposals: () => proposals.rows,
  hadBrowserProposals: () => proposals.old,
}));
vi.mock("@/features/ask/views/proposals/ProposalShell", () => ({
  ProposalShell: ({ id, onBack }: { id: number; onBack: () => void }) => (
    <button type="button" onClick={onBack}>
      Shell {id}
    </button>
  ),
}));

import { ChatsView } from "@/features/ask/views/ChatsView";
import { ComingSoonView } from "@/features/ask/views/ComingSoonView";
import { ProposalsView } from "@/features/ask/views/ProposalsView";
import { VaultView } from "@/features/ask/views/VaultView";

// Keeps a render crash inside the test instead of an unhandled error.
class Boundary extends Component<{ children: ReactNode }, { crashed: boolean }> {
  state = { crashed: false };
  static getDerivedStateFromError() {
    return { crashed: true };
  }
  render() {
    return this.state.crashed ? <p>crashed</p> : this.props.children;
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  proposals.rows = [];
  proposals.old = false;
});

describe("ChatsView", () => {
  const threads = [
    { id: "a", title: "Assam NGOs", createdAt: Date.UTC(2026, 9, 10) },
    { id: "b", title: "Tata fit", createdAt: Date.UTC(2026, 9, 2) },
    { id: "c", title: "Older one", createdAt: Date.UTC(2026, 7, 5) },
  ];

  it("groups chats by month and opens one", async () => {
    const onPick = vi.fn();
    render(<ChatsView threads={threads} onPick={onPick} />);
    expect(screen.getByText("October 2026")).toBeInTheDocument();
    expect(screen.getByText("August 2026")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Tata fit/ }));
    expect(onPick).toHaveBeenCalledWith("b");
  });

  it("searches titles and says when none match", async () => {
    render(<ChatsView threads={threads} onPick={vi.fn()} />);
    await userEvent.type(screen.getByRole("searchbox", { name: "Search your chats" }), "assam");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    await userEvent.type(screen.getByRole("searchbox"), "zzz");
    expect(screen.getByText("No chats match.")).toBeInTheDocument();
  });

  it("says when there are no chats", () => {
    render(<ChatsView threads={[]} onPick={vi.fn()} />);
    expect(screen.getByText("No past conversations yet.")).toBeInTheDocument();
  });
});

describe("ComingSoonView", () => {
  it("shows the title and what is coming", () => {
    render(<ComingSoonView title="RFP Watch" body="Calls, weekly." />);
    expect(screen.getByRole("heading", { name: "RFP Watch" })).toBeInTheDocument();
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
    expect(screen.getByText("Calls, weekly.")).toBeInTheDocument();
  });
});

describe("ProposalsView", () => {
  const props = { funder: null, onOpen: vi.fn(), onFunderMatch: vi.fn() };

  it("shows the list, with a notice about proposals kept in this browser", async () => {
    proposals.old = true;
    render(<ProposalsView {...props} open={null} />);
    expect(screen.getByText(/kept in this browser only/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open Funder Match →" }));
    expect(props.onFunderMatch).toHaveBeenCalled();
  });

  it("opens one proposal and goes back to the list", async () => {
    render(<ProposalsView {...props} open={7} />);
    await userEvent.click(screen.getByRole("button", { name: "Shell 7" }));
    expect(props.onOpen).toHaveBeenCalledWith(null);
    expect(screen.queryByText("Proposals")).toBeNull();
  });
});

describe("VaultView", () => {
  const ORGS = [
    { id: 1, slug: "kabil", name: "KABIL" },
    { id: 2, slug: "seva", name: "Seva" },
  ];
  const doc = { id: 1, title: "Annual report", doc_type: "annual_report", source_name: "Upload", source_url: null, fetched_at: "2026-10-01" };

  it("lists the first organisation's documents and switches organisation", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ items: [doc, { ...doc, id: 2, title: null, doc_type: null, source_name: null, fetched_at: null }] }) }));
    vi.stubGlobal("fetch", fetchMock);
    render(<VaultView orgs={ORGS} />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Annual report")).toBeInTheDocument();
    expect(screen.getByText("ANNUAL_REPOR")).toBeInTheDocument();
    expect(screen.getByText("Untitled document")).toBeInTheDocument();
    expect(screen.getByText("unknown source")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/documents?org=kabil&limit=100"), { headers: { Authorization: "Bearer t" } });
    await userEvent.click(screen.getByRole("button", { name: "Seva" }));
    await waitFor(() => expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("org=seva"), expect.anything()));
  });

  it("shows an empty vault when the load fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new Error("down"))));
    render(<VaultView orgs={ORGS} />);
    expect(await screen.findByText("No documents linked yet")).toBeInTheDocument();
  });

  it("shows the empty state when the server refuses the list", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 403, json: async () => ({ detail: "Forbidden" }) })));
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <Boundary>
        <VaultView orgs={ORGS} />
      </Boundary>,
    );
    expect(await screen.findByText("No documents linked yet")).toBeInTheDocument();
  });

  it("shows the empty state when a page comes back without items", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({}) })));
    render(<VaultView orgs={ORGS} />);
    expect(await screen.findByText("No documents linked yet")).toBeInTheDocument();
  });

  it("uploads a file and reloads, or shows why it failed", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ items: [] }) }));
    vi.stubGlobal("fetch", fetchMock);
    const { container } = render(<VaultView orgs={ORGS} />);
    await screen.findByText("No documents linked yet");
    const input = container.querySelector<HTMLInputElement>("input[type=file]")!;
    const file = new File(["x"], "report.pdf");
    uploadToVault.mockResolvedValueOnce(doc);
    await userEvent.upload(input, file);
    expect(uploadToVault).toHaveBeenCalledWith("kabil", file);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    uploadToVault.mockRejectedValueOnce(new Error("Storage is not configured"));
    await userEvent.upload(input, file);
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage is not configured");
  });
});
