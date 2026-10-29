import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Toast } from "@/components/ui";

afterEach(() => vi.useRealTimers());

describe("Toast", () => {
  it("announces its message politely", () => {
    render(<Toast onDismiss={vi.fn()}>Document deleted successfully.</Toast>);
    const toast = screen.getByRole("status");
    expect(toast).toHaveTextContent("Document deleted successfully.");
    expect(toast).toHaveAttribute("aria-live", "polite");
    expect(toast).toHaveClass("toast");
  });

  it("closes from its button", async () => {
    const onDismiss = vi.fn();
    render(<Toast onDismiss={onDismiss}>Saved.</Toast>);
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("hides itself after its time, and a re-render does not restart the clock", () => {
    vi.useFakeTimers();
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<Toast onDismiss={first} ms={1000}>Saved.</Toast>);
    act(() => vi.advanceTimersByTime(600));
    rerender(<Toast onDismiss={second} ms={1000}>Saved.</Toast>);
    act(() => vi.advanceTimersByTime(400));
    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });
});
