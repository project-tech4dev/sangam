"use client";

export function PillTabs({
  tabs,
  active,
  onPick,
}: {
  tabs: { id: string; label: string }[];
  active: string;
  onPick: (id: string) => void;
}) {
  return (
    <div role="tablist" style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={isActive}
            onClick={() => onPick(tab.id)}
            className="pill"
            data-active={isActive}
            style={
              isActive
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
