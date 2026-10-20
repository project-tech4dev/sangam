import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";

describe("Button and Badge", () => {
  it("click through, carry their variant, and can render as a child link", async () => {
    const onClick = vi.fn();
    render(<><Button variant="outline" size="sm" onClick={onClick}>Save</Button><Badge variant="secondary">New</Badge>
      <Button asChild><a href="/ask">Ask</a></Button><Badge asChild><a href="/t">Tag</a></Badge></>);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Save" })).toHaveAttribute("data-variant", "outline");
    expect(screen.getByText("New")).toHaveAttribute("data-variant", "secondary");
    expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("data-slot", "button");
    expect(screen.getByRole("link", { name: "Tag" })).toHaveAttribute("data-slot", "badge");
  });

  it("a disabled button ignores clicks", async () => {
    const onClick = vi.fn();
    render(<Button disabled onClick={onClick}>Go</Button>);
    await userEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Card, Input, Avatar", () => {
  it("render their content", async () => {
    const onChange = vi.fn();
    render(
      <Card><CardHeader><CardTitle>Title</CardTitle><CardDescription>Desc</CardDescription><CardAction>Act</CardAction></CardHeader>
        <CardContent><Input aria-label="Name" onChange={(e) => onChange(e.target.value)} /></CardContent><CardFooter>Foot</CardFooter></Card>,
    );
    for (const t of ["Title", "Desc", "Act", "Foot"]) expect(screen.getByText(t)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "a");
    expect(onChange).toHaveBeenCalledWith("a");
    render(<Avatar><AvatarFallback>SS</AvatarFallback></Avatar>);
    expect(screen.getByText("SS")).toBeInTheDocument();
  });
});

describe("Checkbox", () => {
  it("toggles and reports its state", async () => {
    const onCheckedChange = vi.fn();
    render(<Checkbox aria-label="Public websites" onCheckedChange={onCheckedChange} />);
    const box = screen.getByRole("checkbox", { name: "Public websites" });
    expect(box).not.toBeChecked();
    await userEvent.click(box);
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    expect(box).toBeChecked();
  });
});

describe("Dialog", () => {
  it("shows its title and closes from the close button", async () => {
    const onOpenChange = vi.fn();
    render(
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent><DialogTitle>Delete chat?</DialogTitle><DialogDescription>It cannot be undone.</DialogDescription>
          <DialogFooter><DialogClose>Cancel</DialogClose></DialogFooter></DialogContent>
      </Dialog>,
    );
    expect(screen.getByRole("dialog", { name: "Delete chat?" })).toHaveAccessibleDescription("It cannot be undone.");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("DropdownMenu", () => {
  it("opens from its trigger and reports a picked item", async () => {
    const onSelect = vi.fn();
    render(
      <DropdownMenu>
        <DropdownMenuTrigger>Account</DropdownMenuTrigger>
        <DropdownMenuContent><DropdownMenuLabel>Signed in</DropdownMenuLabel><DropdownMenuSeparator />
          <DropdownMenuItem onSelect={onSelect}>Sign out</DropdownMenuItem></DropdownMenuContent>
      </DropdownMenu>,
    );
    expect(screen.queryByRole("menu")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(screen.getByText("Signed in")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    expect(onSelect).toHaveBeenCalledOnce();
  });
});
