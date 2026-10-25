import { Button } from "@swarm/ui/components/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@swarm/ui/components/resizable";
import { Segmented } from "@swarm/ui/components/segmented";
import { createFileRoute } from "@tanstack/react-router";
import { ChevronDown, ChevronUp, Megaphone } from "lucide-react";
import { useState } from "react";

import { CrewChannel } from "@/components/live/crew-channel";
import { FeedStrip, FocusedFeed } from "@/components/live/feed-strip";
import { FindingsPanel } from "@/components/live/findings-panel";
import { ScanMap } from "@/components/live/scan-map";
import { Timeline } from "@/components/live/timeline";
import { ConsoleBody } from "@/components/shell/console-body";
import { TopBar } from "@/components/shell/top-bar";
import { useConsole } from "@/lib/console";
import { mission as demoMission } from "@/lib/mock";
import { store } from "@/lib/swarm";
import { usePaneCollapse } from "@/lib/use-pane-collapse";

export const Route = createFileRoute("/_app/live")({
  head: () => ({ meta: [{ title: `Live: ${demoMission.address}` }] }),
  component: LivePage,
});

type SwarmMode = "explore" | "hold" | "return";

function LivePage() {
  const c = useConsole();
  const mission = c.mission;
  const [mode, setMode] = useState<SwarmMode>("explore");
  const changeMode = (m: SwarmMode) => {
    setMode(m);
    if (c.live) store.command(m === "explore" ? "play" : "pause");
  };
  const [drone, setDrone] = useState("D2");
  const [focus, setFocus] = useState<string | null>(null);
  const [finding, setFinding] = useState<string | null>("p1");
  const feeds = usePaneCollapse();
  const crew = usePaneCollapse();

  return (
    <>
      <TopBar
        actions={
          <>
            <Segmented
              value={mode}
              onChange={changeMode}
              className="p-[3px]"
              options={[
                {
                  value: "explore",
                  label: (
                    <>
                      <span className="size-1.5 rounded-full bg-ok" />
                      Explore
                    </>
                  ),
                },
                { value: "hold", label: "Hold" },
                { value: "return", label: "Return" },
              ]}
            />
            <Button variant="primary">
              <Megaphone />
              Brief crew
            </Button>
          </>
        }
      >
        <button type="button" className="flex h-[34px] items-center gap-2 rounded-lg px-2.5 shadow-[inset_0_0_0_1px_var(--color-line)] hover:bg-panel">
          <span className="text-sm font-semibold">{mission.address}</span>
          <span className="text-[13px] text-muted">{mission.type}</span>
          <ChevronDown className="size-3 text-muted" />
        </button>
        <span className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-person" />
          <span className="font-mono text-[13px] font-medium">{mission.elapsed}</span>
        </span>
      </TopBar>
      <ConsoleBody>
        <ResizablePanelGroup orientation="horizontal" className="min-w-0 flex-1">
          <ResizablePanel defaultSize="72%" minSize="45%">
            <ResizablePanelGroup orientation="vertical">
              <ResizablePanel defaultSize="78%" minSize="35%">
                <div className="flex h-full flex-col">
                  <div className="min-h-0 flex-1">
                    {focus ? (
                      <FocusedFeed id={focus} onBack={() => setFocus(null)} />
                    ) : (
                      <ScanMap
                        selectedDrone={drone}
                        onSelectDrone={setDrone}
                        selectedFinding={finding}
                        onSelectFinding={setFinding}
                      />
                    )}
                  </div>
                  <Timeline />
                </div>
              </ResizablePanel>
              <ResizableHandle />
              <ResizablePanel
                defaultSize="186px"
                minSize="140px"
                maxSize="45%"
                collapsible
                collapsedSize="34px"
                panelRef={feeds.ref}
                onResize={feeds.onResize}
              >
                <div className="flex h-full flex-col bg-panel">
                  <div className="flex h-[34px] shrink-0 items-center gap-2 border-b border-line pr-1.5 pl-3">
                    <span className="text-[13px] font-semibold">Feeds</span>
                    <span className="text-xs text-muted">{c.live ? "all drones, scroll sideways (streams the visible ones)" : "4 live, mono 15 fps"}</span>
                    <div className="flex-1" />
                    <Button variant="ghost" size="icon" className="size-7" onClick={feeds.toggle} aria-label={feeds.collapsed ? "Expand feeds" : "Collapse feeds"}>
                      {feeds.collapsed ? <ChevronUp /> : <ChevronDown />}
                    </Button>
                  </div>
                  {!feeds.collapsed && (
                    <div className="min-h-0 flex-1">
                      <FeedStrip
                        selected={drone}
                        onSelect={(id) => {
                          setDrone(id);
                          if (focus) setFocus(id);
                        }}
                        onFocus={(id) => {
                          setDrone(id);
                          setFocus(id);
                        }}
                      />
                    </div>
                  )}
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize="368px" minSize="300px" maxSize="45%">
            <ResizablePanelGroup orientation="vertical" className="bg-white">
              <ResizablePanel defaultSize="70%" minSize="30%">
                <FindingsPanel selected={finding} onSelect={setFinding} />
              </ResizablePanel>
              <ResizableHandle />
              <ResizablePanel
                defaultSize="30%"
                minSize="150px"
                collapsible
                collapsedSize="104px"
                panelRef={crew.ref}
                onResize={crew.onResize}
              >
                <CrewChannel collapsed={crew.collapsed} onToggle={crew.toggle} />
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
        </ResizablePanelGroup>
      </ConsoleBody>
    </>
  );
}
