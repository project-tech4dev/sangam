import Link from "next/link";
import { apiGet } from "@/lib/api";

type Row = Record<string, unknown>;

type TableAccess = {
  table: string;
  allowed: boolean;
  rows: Row[];
};

type AccessCheck = {
  db_role: string;
  user_id: string | null;
  is_staff: boolean;
  my_orgs: Row[];
  tables: TableAccess[];
};

type PublicTable = TableAccess & { group: string; count: number };

type PublicTables = {
  db_role: string;
  is_staff: boolean;
  tables: PublicTable[];
};

type FlagCount = { kind: string; you_see: number; in_table: number };

type FlagTable = { table: string; counts: FlagCount[]; rows: Row[] };

type FlagTables = {
  db_role: string;
  is_staff: boolean;
  my_org_ids: number[];
  tables: FlagTable[];
};

type Tab = "access" | "public" | "flag" | "staff";

const TABS: { id: Tab; label: string; href: string }[] = [
  { id: "access", label: "My access", href: "/access-check" },
  { id: "public", label: "Public tables", href: "/access-check?tab=public" },
  { id: "flag", label: "Public by flag", href: "/access-check?tab=flag" },
  { id: "staff", label: "Staff only", href: "/access-check?tab=staff" },
];

function cell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  return text.length > 60 ? `${text.slice(0, 57)}…` : text;
}

function label(column: string): string {
  return column.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

function TableCard({
  table,
  allowed,
  rows,
  empty,
  count,
}: TableAccess & { empty?: string; count?: number }) {
  const columns = rows.length ? Object.keys(rows[0]) : [];
  return (
    <section className="rounded-lg border border-neutral-300 bg-white p-5">
      <div className="mb-3 flex items-baseline justify-between gap-4">
        <h2 className="font-mono text-lg font-semibold">{table}</h2>
        <span className="text-sm text-neutral-700">
          {!allowed
            ? "403 — not granted to this role"
            : count !== undefined && count > rows.length
              ? `${count} rows · first ${rows.length} shown`
              : `${count ?? rows.length} row${(count ?? rows.length) === 1 ? "" : "s"}`}
        </span>
      </div>
      {allowed && rows.length === 0 && (
        <p className="text-sm text-neutral-600">{empty ?? "0 rows — the table is empty, or RLS hid every row."}</p>
      )}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-neutral-300">
                {columns.map((c) => (
                  <th key={c} className="px-2 py-1.5 font-medium text-neutral-700">
                    {label(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={i} className="border-b border-neutral-200 last:border-0">
                  {columns.map((c) => (
                    <td key={c} className="px-2 py-1.5 whitespace-nowrap">
                      {cell(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Tabs({ active }: { active: Tab }) {
  return (
    <nav role="tablist" className="flex flex-wrap gap-2">
      {TABS.map((t) => (
        <Link
          key={t.id}
          href={t.href}
          role="tab"
          aria-selected={t.id === active}
          className="pill"
          data-active={t.id === active}
          style={
            t.id === active
              ? { background: "var(--color-accent-750)", borderColor: "var(--color-accent-750)", color: "#fff" }
              : undefined
          }
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}

async function MyAccess() {
  const data = await apiGet<AccessCheck>("/api/me/access-check");
  return (
    <>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-neutral-600">Postgres role</dt>
        <dd className="font-mono">{data.db_role}</dd>
        <dt className="text-neutral-600">app.user_id()</dt>
        <dd className="font-mono">{cell(data.user_id)}</dd>
        <dt className="text-neutral-600">app.is_staff()</dt>
        <dd className="font-mono">{String(data.is_staff)}</dd>
      </dl>
      <TableCard
        table="My orgs"
        allowed
        rows={data.my_orgs}
        empty={data.user_id === null ? "Signed out — sign in to see your orgs." : "You belong to no org."}
      />
      {data.tables.map((t) => (
        <TableCard key={t.table} {...t} />
      ))}
    </>
  );
}

async function PublicTablesTab() {
  const data = await apiGet<PublicTables>("/api/me/access-check/public");
  const groups = [...new Set(data.tables.map((t) => t.group))];
  return (
    <>
      <p className="rounded-lg border border-neutral-300 bg-neutral-100 p-4 text-sm">
        <strong>If you sign out, you will still see all of this data.</strong> These {data.tables.length} tables
        are granted to both <code>anon</code> and <code>authenticated</code>, and their RLS rule is{" "}
        <code>USING (true)</code>: every row, for everyone. You are reading them as{" "}
        <code className="font-semibold">{data.db_role}</code>.
      </p>
      {groups.map((group) => (
        <section key={group} className="flex flex-col gap-4">
          <h2 className="text-lg font-semibold">{group}</h2>
          {data.tables
            .filter((t) => t.group === group)
            .map((t) => (
              <TableCard key={t.table} {...t} empty="0 rows — this table is empty locally." />
            ))}
        </section>
      ))}
    </>
  );
}

function staffVerdict(role: string, isStaff: boolean): string {
  if (role === "anon") return "You are signed out, so every table below is 403: anon was never granted them.";
  if (isStaff) return "You are staff, so the rule lets every row through.";
  return "You are signed in but not staff: the grant lets you in, and the rule returns 0 rows.";
}

async function StaffOnlyTab() {
  const data = await apiGet<PublicTables>("/api/me/access-check/staff");
  return (
    <>
      <div className="flex flex-col gap-2 rounded-lg border border-neutral-300 bg-neutral-100 p-4 text-sm">
        <p>
          <strong>Only staff see these rows.</strong> They are Sangam Import&apos;s tables: its runs, the
          research it did and the names waiting to be matched. They are granted to{" "}
          <code>authenticated</code> only, and their RLS rule is <code>USING (app.is_staff())</code>.
        </p>
        <table className="w-fit text-left">
          <tbody>
            <tr>
              <td className="pr-6 text-neutral-600">Signed out</td>
              <td>403 — not granted to anon</td>
            </tr>
            <tr>
              <td className="pr-6 text-neutral-600">Signed in, not staff</td>
              <td>0 rows — granted, but the rule hides every row</td>
            </tr>
            <tr>
              <td className="pr-6 text-neutral-600">Staff</td>
              <td>Every row</td>
            </tr>
          </tbody>
        </table>
        <p>
          You are <code className="font-semibold">{data.db_role}</code>
          {data.db_role !== "anon" && (
            <>
              , staff <code className="font-semibold">{String(data.is_staff)}</code>
            </>
          )}
          . {staffVerdict(data.db_role, data.is_staff)}
        </p>
      </div>
      {data.tables.map((t) => (
        <TableCard
          key={t.table}
          {...t}
          empty={data.is_staff ? "0 rows — this table is empty locally." : "0 rows — RLS hides every row from non-staff."}
        />
      ))}
    </>
  );
}

const FLAG_EXPECTED: Record<string, string> = {
  public: "everyone, signed out too",
  "my org, private": "you, as one of the org's people",
  "other org, private": "only that org's people and staff",
  "funder, private": "staff only — a funder has no members",
};

function expectedSee(kind: string, inTable: number, role: string, isStaff: boolean): number {
  if (kind === "public" || isStaff) return inTable;
  if (kind === "my org, private" && role !== "anon") return inTable;
  return 0;
}

function FlagCounts({ counts, role, isStaff }: { counts: FlagCount[]; role: string; isStaff: boolean }) {
  return (
    <table className="mb-4 w-full text-left text-sm">
      <thead>
        <tr className="border-b border-neutral-300">
          <th className="px-2 py-1.5 font-medium text-neutral-700">Kind of row</th>
          <th className="px-2 py-1.5 font-medium text-neutral-700">Who may see it</th>
          <th className="px-2 py-1.5 text-right font-medium text-neutral-700">You see</th>
          <th className="px-2 py-1.5 text-right font-medium text-neutral-700">In table</th>
          <th className="px-2 py-1.5 font-medium text-neutral-700">Check</th>
        </tr>
      </thead>
      <tbody>
        {counts.map((c) => {
          const ok = c.you_see === expectedSee(c.kind, c.in_table, role, isStaff);
          return (
            <tr key={c.kind} className="border-b border-neutral-200 last:border-0">
              <td className="px-2 py-1.5 font-medium">{c.kind}</td>
              <td className="px-2 py-1.5 text-neutral-700">{FLAG_EXPECTED[c.kind]}</td>
              <td className="px-2 py-1.5 text-right font-mono">{c.you_see}</td>
              <td className="px-2 py-1.5 text-right font-mono text-neutral-600">{c.in_table}</td>
              <td className="px-2 py-1.5">{ok ? "✔ as expected" : "✘ unexpected"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

async function FlagTab() {
  const data = await apiGet<FlagTables>("/api/me/access-check/flag");
  const who =
    data.db_role === "anon"
      ? "signed out, so only public rows come back"
      : data.is_staff
        ? "staff, so every row comes back"
        : data.my_org_ids.length
          ? `in org ${data.my_org_ids.join(", ")}, so you see public rows plus those orgs' private rows`
          : "signed in but in no org, so you see exactly what a signed-out visitor sees";
  return (
    <>
      <div className="flex flex-col gap-2 rounded-lg border border-neutral-300 bg-neutral-100 p-4 text-sm">
        <p>
          <strong>Public rows go to everyone; private rows only to that org&apos;s people and staff.</strong> These
          tables are granted to both <code>anon</code> and <code>authenticated</code>, and each row carries an{" "}
          <code>is_public</code> flag. The rule is{" "}
          <code>is_public OR org_id IN (SELECT app.my_org_ids()) OR app.is_staff()</code>.
        </p>
        <p>
          You are <code className="font-semibold">{data.db_role}</code>: {who}.
        </p>
        <p className="text-neutral-700">
          &quot;In table&quot; is read as the owner, which RLS does not apply to, so the two columns show what
          the rule hid from you.
        </p>
      </div>
      {data.tables.map((t) => {
        const columns = t.rows.length ? Object.keys(t.rows[0]) : [];
        return (
          <section key={t.table} className="rounded-lg border border-neutral-300 bg-white p-5">
            <h2 className="mb-3 font-mono text-lg font-semibold">{t.table}</h2>
            <FlagCounts counts={t.counts} role={data.db_role} isStaff={data.is_staff} />
            {t.rows.length > 0 && (
              <>
                <p className="mb-2 text-sm text-neutral-600">
                  Rows you see, private first ({t.rows.length} shown):
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-neutral-300">
                        {columns.map((c) => (
                          <th key={c} className="px-2 py-1.5 font-medium text-neutral-700">
                            {label(c)}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {t.rows.map((row, i) => (
                        <tr key={i} className="border-b border-neutral-200 last:border-0">
                          {columns.map((c) => (
                            <td key={c} className="px-2 py-1.5 whitespace-nowrap">
                              {c === "public" ? (row[c] ? "yes" : "no") : cell(row[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        );
      })}
    </>
  );
}

export async function AccessCheckPage({ tab }: { tab: Tab }) {
  return (
    <div className="sangam-ui">
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-10">
        <header className="flex flex-col gap-3">
          <h1 className="text-2xl font-semibold">Access check</h1>
          <p className="text-sm text-neutral-700">
            Each table is read with no filter, as you. Whatever shows below is what the grants and RLS let
            through.
          </p>
          <Tabs active={tab} />
        </header>
        {tab === "public" ? (
          <PublicTablesTab />
        ) : tab === "flag" ? (
          <FlagTab />
        ) : tab === "staff" ? (
          <StaffOnlyTab />
        ) : (
          <MyAccess />
        )}
      </main>
    </div>
  );
}
