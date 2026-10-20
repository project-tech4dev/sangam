import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HomePage } from "@/features/home/HomePage";
import { HeroSlides } from "@/features/home/HeroSlides";

vi.mock("next/image", () => ({
  default: ({ alt, src }: { alt: string; src: string }) => <img alt={alt} src={src} />, // eslint-disable-line @next/next/no-img-element
}));

afterEach(() => vi.useRealTimers());

const shown = () => screen.getByText(/^\d \/ 3$/).textContent;

describe("HeroSlides", () => {
  it("moves to the next slide every eight seconds, wrapping round", () => {
    vi.useFakeTimers();
    render(<HeroSlides />);
    expect(shown()).toBe("1 / 3");
    act(() => vi.advanceTimersByTime(8000));
    expect(shown()).toBe("2 / 3");
    act(() => vi.advanceTimersByTime(16000));
    expect(shown()).toBe("1 / 3");
  });

  it("pauses while hovered", () => {
    vi.useFakeTimers();
    const { container } = render(<HeroSlides />);
    const panel = container.firstElementChild as HTMLElement;
    act(() => panel.dispatchEvent(new MouseEvent("mouseover", { bubbles: true })));
    act(() => vi.advanceTimersByTime(20000));
    expect(shown()).toBe("1 / 3");
    act(() => panel.dispatchEvent(new MouseEvent("mouseout", { bubbles: true })));
    act(() => vi.advanceTimersByTime(8000));
    expect(shown()).toBe("2 / 3");
  });

  it("jumps to a slide from its dot and hides the others from assistive tech", async () => {
    render(<HeroSlides />);
    await userEvent.click(screen.getByRole("button", { name: "For ecosystem players" }));
    expect(shown()).toBe("3 / 3");
    expect(screen.getByText("Spot the gaps, refer the right partners").closest("[aria-hidden]")).toHaveAttribute("aria-hidden", "false");
    expect(screen.getByText("Find the funders who fit your work").closest("[aria-hidden]")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("HomePage", () => {
  it("leads to Ask and the Registry and shows the steps, sources and partners", () => {
    render(<HomePage />);
    expect(screen.getByRole("heading", { level: 1, name: "Where funders and NGOs actually meet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask Sangam" })).toHaveAttribute("href", "/ask");
    expect(screen.getByRole("link", { name: "Explore the Registry" })).toHaveAttribute("href", "/registry");
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("05")).toBeInTheDocument();
    expect(screen.getByText("NGO profiles")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Project Tech4Dev" })).toHaveAttribute("src", "/partners/tech4dev.png");
    expect(screen.getByText("Bridgespan logo")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
  });
});
