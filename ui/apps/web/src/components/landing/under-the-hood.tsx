import { ChevronDown } from "lucide-react";

const ROWS: [string, string, string][] = [
  ["On each drone", "Raspberry Pi running ROS 2, an IMU, a mono camera and a Wi-Fi relay", "The Pi stabilizes the drone, converts the camera to mono for mapping, and repeats Wi-Fi so ROS 2 traffic reaches the base without a second radio."],
  ["Mapping", "Visual SLAM into one shared point cloud", "Each drone's camera and IMU feed one map. The IMU gives the single camera real-world scale."],
  ["Shared computer", "ASUS Ascent GX10 in the truck", "One edge box batches detection and mapping for every drone, so each drone can stay small and cheap."],
  ["Finding things", "Batched object detection", "People, doors (open, closed or blocked), collapsed passages and hazards are pinned to the room where they were seen."],
  ["Flying together", "Central scheduler, collision checks and a geofence", "The base assigns rooms, keeps drones apart and inside the fence, and keeps remapping as rescuers open doors."],
  ["Works with", "Hardware-agnostic adapters", "Our prototype uses E58 camera drones. Other airframes, like Tello EDU or custom builds, are meant to plug in through adapters."],
];

/** Technical detail for judges, kept out of the main story. */
export function UnderTheHood() {
  return (
    <section id="judges" className="flex flex-col gap-10 px-4 py-24 md:flex-row md:gap-16 md:px-[100px] md:py-32">
      <div className="flex w-full max-w-[360px] shrink-0 flex-col gap-3">
        <span className="text-sm font-semibold text-orange-edge">For curious judges</span>
        <h2 className="text-[32px] leading-[1.15] font-bold tracking-[-0.025em] md:text-[36px]">How it works under the hood.</h2>
        <p className="text-base leading-6 text-muted">Built at Cal Hacks. Speed and cost benefits are what we are designing for, not results we have measured yet.</p>
      </div>
      <div className="flex flex-1 flex-col border-t border-line">
        {ROWS.map(([title, summary, detail]) => (
          <details key={title} className="group border-b border-line">
            <summary className="flex cursor-pointer list-none items-center gap-4 py-4 [&::-webkit-details-marker]:hidden">
              <span className="w-40 shrink-0 text-[17px] font-semibold">{title}</span>
              <span className="flex-1 text-[15px] text-muted">{summary}</span>
              <ChevronDown className="size-4 text-muted transition-transform group-open:rotate-180" />
            </summary>
            <p className="pb-4 pl-0 text-[15px] leading-6 text-muted md:pl-44">{detail}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
