import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Footer } from "@/components/layout/Footer";
import { NavBar } from "@/components/layout/NavBar";
import { navigation } from "@/tests/setup";

// The real button reaches Supabase; the nav only needs it to render.
vi.mock("@/features/auth/sign-in-button", () => ({ SignInButton: () => <button type="button">Sign in</button> }));

const current = () => screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current") === "page").map((a) => a.textContent);

describe("NavBar", () => {
  it("marks the section the path belongs to, old paths included", () => {
    for (const [path, label] of [["/ask", "Ask Sangam"], ["/funders/tata", "Registry"], ["/taxonomy", "Resources"]]) {
      navigation.pathname = path;
      const { unmount } = render(<NavBar />);
      expect(current()).toEqual([label]);
      unmount();
    }
    navigation.pathname = "/";
    render(<NavBar />);
    expect(current()).toEqual([]);
  });

  it("opens the phone menu and closes it when a link is followed", async () => {
    navigation.pathname = "/registry";
    render(<NavBar />);
    const toggle = screen.getByRole("button", { name: "Open menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
    const menuLinks = document.getElementById("nav-menu")!.querySelectorAll("a");
    expect([...menuLinks].map((a) => a.textContent)).toEqual(["Registry", "Ask Sangam", "Resources"]);
    await userEvent.click(menuLinks[1]);
    expect(document.getElementById("nav-menu")).toBeNull();
  });
});

it("Footer links to the terms", () => {
  render(<Footer />);
  expect(screen.getByRole("link", { name: "Terms & Privacy" })).toHaveAttribute("href", "/terms");
});
