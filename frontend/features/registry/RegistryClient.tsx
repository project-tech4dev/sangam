"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { EntityMark, StatusChip } from "@/components/ui";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { RegistryEntry } from "@/features/registry/entries";

const ACTIVE =
  "data-[state=on]:bg-secondary data-[state=on]:text-secondary-foreground";

export function RegistryClient({
  entries,
  initialType,
}: {
  entries: RegistryEntry[];
  initialType: "all" | "CSO" | "Funder";
}) {
  const [q, setQ] = useState("");
  const [type, setType] = useState<"all" | "CSO" | "Funder">(initialType);
  const [place, setPlace] = useState("All places");

  const places = useMemo(
    () => [
      "All places",
      ...Array.from(new Set(entries.flatMap((e) => e.states))).sort(),
    ],
    [entries]
  );

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return entries.filter((entry) => {
      if (type !== "all" && entry.kind !== type) return false;
      if (place !== "All places" && !entry.states.includes(place)) return false;
      if (!needle) return true;
      const haystack = `${entry.name} ${entry.where} ${
        entry.blurb ?? ""
      } ${entry.tags.join(" ")} ${entry.kind}`.toLowerCase();
      return haystack.includes(needle);
    });
  }, [entries, q, type, place]);

  const vetting = entries.filter((e) => e.status === "partial").length;

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1.5">
        <div className="eyebrow">The Registry</div>
        <h1 className="text-4xl">Every organisation and funder in the base</h1>
        <p className="m-0 max-w-160 text-muted-foreground">
          Hand-vetted profiles of North East India CSOs and the funders active
          around them. Every field traces to a source.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-3.5">
        <Input
          className="max-w-105"
          placeholder="Search organisations, funders, districts, sectors…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <ToggleGroup
          type="single"
          variant="outline"
          spacing={0}
          value={type}
          onValueChange={(value) => value && setType(value as typeof type)}
        >
          {(["all", "CSO", "Funder"] as const).map((option) => (
            <ToggleGroupItem key={option} value={option} className={ACTIVE}>
              {option === "all" ? "All" : option === "CSO" ? "CSOs" : "Funders"}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        <span className="ml-auto text-xs text-muted-foreground">
          {shown.length} of {entries.length} entries
        </span>
      </div>

      <ToggleGroup
        type="single"
        variant="outline"
        size="sm"
        className="flex-wrap"
        value={place}
        onValueChange={(value) => value && setPlace(value)}
      >
        {places.map((p) => (
          <ToggleGroupItem key={p} value={p} className={ACTIVE}>
            {p}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>

      {shown.length === 0 ? (
        <Card className="items-center py-10 text-center">
          <CardHeader className="w-full">
            <CardTitle className="font-bold">Nothing matches</CardTitle>
            <CardDescription>
              Try a different search, or clear the filters.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-4.5">
          {shown.map((entry) => (
            <Card key={`${entry.kind}-${entry.id}`} className="gap-3">
              <CardHeader className="gap-2">
                <div className="flex items-center gap-3">
                  <EntityMark name={entry.name} />
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline">{entry.kind}</Badge>
                    <StatusChip status={entry.status} />
                  </div>
                </div>
                <CardTitle className="text-xl font-bold">
                  {entry.name}
                </CardTitle>
                <CardDescription className="text-xs">
                  {entry.where}
                </CardDescription>
              </CardHeader>
              <CardContent className="gap-2.5">
                {entry.blurb && (
                  <p className="m-0 text-sm text-muted-foreground">
                    {entry.blurb}
                  </p>
                )}
                {entry.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {entry.tags.map((tag) => (
                      <Badge key={tag} variant="secondary">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
              <CardFooter className="mt-auto justify-between gap-2.5 pt-2">
                <span className="text-xs text-sand-500">{entry.meta}</span>
                <Button
                  variant="outline"
                  size="sm"
                  asChild
                  className="text-foreground hover:no-underline"
                >
                  <Link href={entry.href}>Open profile →</Link>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {vetting > 0 && (
        <Card className="bg-secondary py-4 text-secondary-foreground shadow-none ring-0">
          <CardContent className="text-sm">
            {vetting} of {entries.length} entries are still in vetting — their
            profiles show exactly what has and hasn&apos;t been verified yet.
          </CardContent>
        </Card>
      )}
    </div>
  );
}
