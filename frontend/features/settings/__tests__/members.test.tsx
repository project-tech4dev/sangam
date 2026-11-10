import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OrgMembersCard } from "@/features/settings/OrgMembersCard";
import { StaffMembersCard } from "@/features/settings/StaffMembersCard";
import { membersRequest, type OrgMember } from "@/features/settings/members-api";

vi.mock("@/features/settings/members-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/settings/members-api")>()),
  membersRequest: vi.fn(),
}));

const request = vi.mocked(membersRequest);
// Braces matter: mockReset returns the mock, which beforeEach would run as teardown.
beforeEach(() => {
  request.mockReset();
});

const asha: OrgMember = { user_id: "u1", display_name: "Asha", email: "asha@k.org", role: "admin" };
const ravi: OrgMember = { user_id: "u2", display_name: null, email: "ravi@k.org", role: "member" };

describe("OrgMembersCard", () => {
  it("lists members, marks you, and invites the first one when empty", () => {
    const { unmount } = render(<OrgMembersCard orgId={7} orgName="KABIL" note="You are an admin." meId="u1" initialMembers={[asha, ravi]} />);
    expect(screen.getByRole("heading", { name: "Members of KABIL" })).toBeInTheDocument();
    expect(screen.getByText("(you)")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Role of ravi@k.org" })).toHaveValue("member");
    unmount();
    render(<OrgMembersCard orgId={7} orgName="KABIL" note="" meId="u1" initialMembers={[]} />);
    expect(screen.getByText("No members yet. Add the first one below.")).toBeInTheDocument();
  });

  it("adds a member with the chosen role and clears the email", async () => {
    request.mockResolvedValue({ members: [asha, ravi] });
    render(<OrgMembersCard orgId={7} orgName="KABIL" note="" meId="u1" initialMembers={[asha]} />);
    const email = screen.getByRole("textbox", { name: "Email of the person to add" });
    await userEvent.type(email, "ravi@k.org");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Role" }), "steward");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    expect(request).toHaveBeenCalledWith(7, "POST", "", { email: "ravi@k.org", role: "steward" });
    expect(await screen.findByText("ravi@k.org")).toBeInTheDocument();
    expect(email).toHaveValue("");
  });

  it("changes a role and removes a member", async () => {
    request.mockResolvedValueOnce({ members: [asha, { ...ravi, role: "steward" }] }).mockResolvedValueOnce({ members: [asha] });
    render(<OrgMembersCard orgId={7} orgName="KABIL" note="" meId="u1" initialMembers={[asha, ravi]} />);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Role of ravi@k.org" }), "steward");
    expect(request).toHaveBeenCalledWith(7, "PATCH", "/u2", { role: "steward" });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Role of ravi@k.org" })).toHaveValue("steward"));
    const row = screen.getByText("ravi@k.org").closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(request).toHaveBeenLastCalledWith(7, "DELETE", "/u2", undefined);
    await waitFor(() => expect(screen.queryByText("ravi@k.org")).not.toBeInTheDocument());
  });

  it("shows the server's error and keeps the email typed", async () => {
    request.mockResolvedValue({ error: "No Sangam user has that email." });
    render(<OrgMembersCard orgId={7} orgName="KABIL" note="" meId="u1" initialMembers={[asha]} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Email of the person to add" }), "x@y.org");
    await userEvent.click(screen.getByRole("button", { name: "Add member" }));
    expect(await screen.findByText("No Sangam user has that email.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Email of the person to add" })).toHaveValue("x@y.org");
    expect(screen.getByText("asha@k.org")).toBeInTheDocument();
  });
});

describe("StaffMembersCard", () => {
  const orgs = [{ id: 1, name: "KABIL" }, { id: 2, name: "Seva" }];

  it("loads the chosen organisation's members", async () => {
    request.mockResolvedValue({ members: [asha] });
    render(<StaffMembersCard orgs={orgs} meId="staff" />);
    expect(screen.queryByRole("button", { name: "Add member" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Organisation" }), "1");
    expect(request).toHaveBeenCalledWith(1);
    expect(await screen.findByText("asha@k.org")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Organisation" }), "");
    expect(screen.queryByText("asha@k.org")).not.toBeInTheDocument();
  });

  it("shows the error when members cannot be loaded", async () => {
    request.mockResolvedValue({ error: "Could not reach Sangam. Try again." });
    render(<StaffMembersCard orgs={orgs} meId="staff" />);
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Organisation" }), "2");
    expect(await screen.findByText("Could not reach Sangam. Try again.")).toBeInTheDocument();
  });

  it("never shows one organisation's members under another after a quick switch", async () => {
    const answers: ((v: { members: OrgMember[] }) => void)[] = [];
    request.mockImplementation(() => new Promise((r) => answers.push(r)));
    render(<StaffMembersCard orgs={orgs} meId="staff" />);
    const pick = screen.getByRole("combobox", { name: "Organisation" });
    await userEvent.selectOptions(pick, "1");
    await userEvent.selectOptions(pick, "2");
    await act(async () => answers[0]({ members: [asha] }));
    await act(async () => answers[1]({ members: [ravi] }));
    expect(pick).toHaveValue("2");
    expect(screen.queryByText("asha@k.org")).toBeNull();
  });
});
