import { cn } from "@swarm/ui/lib/utils";
import { createFileRoute, Link, Outlet, useLocation } from "@tanstack/react-router";

import { ConsoleBody } from "@/components/shell/console-body";
import { TopBar } from "@/components/shell/top-bar";

export const Route = createFileRoute("/_app/settings")({
  component: SettingsLayout,
});

const groups: { title: string; items: { label: string; to?: string; dot?: boolean }[] }[] = [
  { title: "Department", items: [{ label: "General" }, { label: "People and roles" }, { label: "Units and stations" }] },
  {
    title: "Missions",
    items: [{ label: "Detection", to: "/settings/detection" }, { label: "Flight and search" }, { label: "Voice and crew channel" }],
  },
  {
    title: "System",
    items: [{ label: "Edge server", to: "/settings/edge", dot: true }, { label: "Drone adapters" }, { label: "CAD integration" }, { label: "Data retention" }],
  },
];

function SettingsLayout() {
  const { pathname } = useLocation();
  return (
    <>
      <TopBar>
        <span className="text-sm font-semibold">Settings</span>
      </TopBar>
      <ConsoleBody>
        <nav className="flex w-[248px] shrink-0 flex-col gap-[18px] border-r border-line bg-panel-2 px-3 py-[18px]">
          {groups.map((g) => (
            <div key={g.title} className="flex flex-col gap-0.5">
              <span className="px-2.5 pb-1.5 text-xs font-semibold text-faint">{g.title}</span>
              {g.items.map((item) => {
                const active = item.to !== undefined && pathname.startsWith(item.to);
                const cls = cn(
                  "flex h-8 items-center gap-2 rounded-[7px] px-2.5 text-sm",
                  active ? "bg-white font-semibold shadow-[0_0_0_1px_var(--color-line),0_1px_2px_rgb(0_0_0/0.05)]" : "hover:bg-ink/5",
                  !item.to && "cursor-default text-ink/80",
                );
                const body = (
                  <>
                    <span className="flex-1">{item.label}</span>
                    {item.dot && <span className="size-[7px] rounded-full bg-ok" />}
                  </>
                );
                return item.to ? (
                  <Link key={item.label} to={item.to} className={cls}>
                    {body}
                  </Link>
                ) : (
                  <span key={item.label} className={cls} title="Not in this mockup yet">
                    {body}
                  </span>
                );
              })}
            </div>
          ))}
        </nav>
        <div className="flex min-w-0 flex-1 flex-col">
          <Outlet />
        </div>
      </ConsoleBody>
    </>
  );
}
