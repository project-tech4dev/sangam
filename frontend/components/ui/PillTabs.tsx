"use client";

/* `board` is the sage tab row of the Registry profiles; the default is the original pill row. */
export function PillTabs({
  tabs,
  active,
  onPick,
  variant = "default",
  label,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onPick: (id: string) => void;
  variant?: "default" | "board";
  label?: string;
}) {
  const board = variant === "board";
  return (
    <div role="tablist" aria-label={label} className={board ? "profile-tablist" : "pill-tabs"}>
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onPick(tab.id)}
            className={board ? "profile-tab-btn" : "pill"}
            data-active={isActive}
            style={
              !board && isActive
                ? { background: "var(--color-accent-750)", borderColor: "var(--color-accent-750)", color: "#fff" }
                : undefined
            }
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
