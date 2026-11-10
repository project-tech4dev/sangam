import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState, type ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ImportAccess, VaultFile } from "../../lib/access";
import { EMPTY_SOURCES, type SourcesChoice } from "../../lib/sourcePick";
import { status, stubFetch } from "./fakes";

type Config = {
  enabled: (e: { value: unknown }) => boolean;
  render: (p: { event: { value: unknown }; resolve: (v: unknown) => void }) => ReactElement;
};
const pause = vi.hoisted(() => ({ event: null as { value: unknown } | null, resolve: vi.fn() }));

// Renders the card only while the faked pause is one the component claims.
vi.mock("@copilotkit/react-core/v2", () => ({
  useInterrupt: (cfg: Config) => (pause.event && cfg.enabled(pause.event) ? cfg.render({ event: pause.event, resolve: pause.resolve }) : null),
}));
vi.mock("@/lib/api/auth-headers", () => ({ authHeaders: async () => ({ Authorization: "Bearer t" }) }));

import { SourcePicker } from "../SourcePicker";
import { SourcesCard } from "../SourcesCard";

const STAFF: ImportAccess = { staff: true, stewardOf: [], orgs: [{ slug: "a", name: "A" }] };
const STEWARD: ImportAccess = { staff: false, stewardOf: ["Org A"], orgs: [{ slug: "a", name: "Org A" }, { slug: "b", name: "Org B" }] };
const vault: VaultFile[] = [
  { id: 1, title: "Annual report", doc_type: null, org: "a", orgId: 10, orgName: "Org A" },
  { id: 2, title: null, doc_type: null, org: "a", orgId: 10, orgName: "Org A" },
  { id: 3, title: "Audit", doc_type: null, org: "b", orgId: 20, orgName: "Org B" },
];
const workbooks = [
  { path: "staff-sources/a.xlsx", name: "Cohort A", folder: "f", folder_label: "Cohort", size: 1, updated_at: "1 Oct" },
  { path: "staff-sources/b.xlsx", name: "Cohort B", folder: "f", folder_label: "", size: 1, updated_at: null },
];
const chooseSources = { action_requests: [{ name: "choose_sources", args: {} }] };

beforeEach(() => {
  pause.event = null;
  pause.resolve.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

function Picker({ staff, files = [], onChange = vi.fn() }: { staff: boolean; files?: VaultFile[]; onChange?: (c: SourcesChoice) => void }) {
  const [value, setValue] = useState(EMPTY_SOURCES);
  return (
    <SourcePicker
      value={value}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
      staff={staff}
      vaultFiles={files}
      showOrg
    />
  );
}

describe("SourcePicker", () => {
  it("lists the team's spreadsheets for staff and sends the ticked path", async () => {
    const fetchMock = stubFetch({ "/api/ingest/workbooks": workbooks });
    const onChange = vi.fn();
    render(<Picker staff onChange={onChange} />);
    expect(screen.getByText("Looking in your team's files…")).toBeInTheDocument();
    expect(await screen.findByText("Cohort A")).toBeInTheDocument();
    expect(screen.getByText("Cohort · added 1 Oct")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0]![0]).toContain("bucket=staff-sources");

    await userEvent.click(screen.getByRole("checkbox", { name: /Cohort B/ }));
    expect(onChange).toHaveBeenLastCalledWith({ ...EMPTY_SOURCES, staff_paths: ["staff-sources/b.xlsx"] });
    await userEvent.click(screen.getByRole("checkbox", { name: /Cohort B/ }));
    expect(onChange).toHaveBeenLastCalledWith(EMPTY_SOURCES);
  });

  it("does not ask for spreadsheets for a steward", () => {
    const fetchMock = stubFetch({});
    render(<Picker staff={false} />);
    expect(screen.queryByText("Team spreadsheets")).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says when there are no spreadsheets, and when listing them failed", async () => {
    stubFetch({ "/api/ingest/workbooks": [] });
    const { unmount } = render(<Picker staff />);
    expect(await screen.findByText("There are no team spreadsheets yet.")).toBeInTheDocument();
    unmount();
    stubFetch({ "/api/ingest/workbooks": status(500) });
    render(<Picker staff />);
    expect(await screen.findByText("Sangam couldn't list the team's spreadsheets.")).toBeInTheDocument();
  });

  it("ticks websites and library, and keeps Doc Vault picks to one organisation", async () => {
    const onChange = vi.fn();
    render(<Picker staff={false} files={vault} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: /Public websites/ }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Sangam's library/ }));
    expect(onChange).toHaveBeenLastCalledWith({ ...EMPTY_SOURCES, web: true, library: true });

    await userEvent.click(screen.getByRole("button", { name: /Annual report/ }));
    await userEvent.click(screen.getByRole("button", { name: /Document 2/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ vault_org: 10, vault_docs: [1, 2] }));
    expect(screen.getByRole("button", { name: /Annual report/ })).toHaveAttribute("aria-pressed", "true");

    // Another organisation's file starts a new pick.
    await userEvent.click(screen.getByRole("button", { name: /Audit/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ vault_org: 20, vault_docs: [3] }));
    expect(screen.getByRole("button", { name: /Annual report/ })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: /Audit/ }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ vault_org: null, vault_docs: [] }));
  });
});

describe("SourcesCard", () => {
  it("renders nothing until the run pauses on choose_sources", () => {
    pause.event = { value: { action_requests: [{ name: "promote_research" }] } };
    const { container } = render(
      <SourcesCard agentId="a" access={STEWARD} vaultFiles={[]} preset={null} onPaused={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("answers with exactly the sources ticked, and signals the pause", async () => {
    stubFetch({ "/api/ingest/workbooks": workbooks });
    pause.event = { value: JSON.stringify(chooseSources) };
    const onPaused = vi.fn();
    render(<SourcesCard agentId="a" access={STAFF} vaultFiles={[]} preset={null} onPaused={onPaused} />);
    expect(onPaused).toHaveBeenCalledWith(true);
    const start = screen.getByRole("button", { name: "Start reading" });
    expect(start).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox", { name: /Sangam's library/ }));
    await userEvent.click(await screen.findByRole("checkbox", { name: /Cohort A/ }));
    await userEvent.click(start);
    expect(pause.resolve).toHaveBeenCalledWith({
      decisions: [
        {
          type: "edit",
          edited_action: { name: "choose_sources", args: { ...EMPTY_SOURCES, library: true, staff_paths: ["staff-sources/a.xlsx"] } },
        },
      ],
    });
    expect(start).toBeDisabled();
    expect(screen.getByRole("button", { name: "Only public websites" })).toBeDisabled();
  });

  it("shows team spreadsheets to staff and not to a steward", async () => {
    stubFetch({ "/api/ingest/workbooks": workbooks });
    pause.event = { value: chooseSources };
    const { unmount } = render(<SourcesCard agentId="a" access={STAFF} vaultFiles={[]} preset={null} onPaused={vi.fn()} />);
    expect(await screen.findByText("Team spreadsheets")).toBeInTheDocument();
    unmount();
    render(<SourcesCard agentId="a" access={STEWARD} vaultFiles={vault} preset={null} onPaused={vi.fn()} />);
    expect(screen.queryByText("Team spreadsheets")).not.toBeInTheDocument();
    // A steward of two organisations sees whose file each one is.
    expect(screen.getByRole("button", { name: /Audit.*Org B/ })).toBeInTheDocument();
  });

  it("'Only public websites' answers with the web alone", async () => {
    pause.event = { value: chooseSources };
    render(<SourcesCard agentId="a" access={STEWARD} vaultFiles={[]} preset={null} onPaused={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Only public websites" }));
    expect(pause.resolve).toHaveBeenCalledWith({
      decisions: [{ type: "edit", edited_action: { name: "choose_sources", args: { ...EMPTY_SOURCES, web: true } } }],
    });
  });

  it("answers a pause on its own with the preset, once, and shows no card", async () => {
    pause.event = { value: chooseSources };
    const preset = { ...EMPTY_SOURCES, web: true, vault_org: 10, vault_docs: [1] };
    const { rerender } = render(<SourcesCard agentId="a" access={STEWARD} vaultFiles={[]} preset={preset} onPaused={vi.fn()} />);
    await waitFor(() => expect(pause.resolve).toHaveBeenCalledOnce());
    expect(pause.resolve).toHaveBeenCalledWith({
      decisions: [{ type: "edit", edited_action: { name: "choose_sources", args: preset } }],
    });
    expect(screen.queryByRole("region", { name: "Where Sangam reads from" })).not.toBeInTheDocument();
    act(() => rerender(<SourcesCard agentId="a" access={STEWARD} vaultFiles={[]} preset={preset} onPaused={vi.fn()} />));
    expect(pause.resolve).toHaveBeenCalledOnce();
  });
});
