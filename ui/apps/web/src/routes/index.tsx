import { Button } from "@swarm/ui/components/button";
import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowRight, Check, DoorClosed, Play, TriangleAlert, User, X } from "lucide-react";
import type { ReactNode } from "react";

import { Mark } from "@/components/icons";

export const Route = createFileRoute("/")({
  component: Landing,
});

const steps = [
  {
    n: "01",
    title: "Pick the building",
    body: "Type the address. We pull the floor plan from listing photos and the county record before the truck arrives.",
    image: <img src="/assets/streets.png" alt="" className="absolute top-[-280px] left-[-250px] h-[848px] w-[968px] max-w-none" />,
    overlay: (
      <svg width={28} height={36} viewBox="0 0 28 36" className="absolute top-[106px] left-[175px]" aria-hidden>
        <path d="M14 1C6.8 1 1 6.8 1 14c0 9.5 13 21 13 21s13-11.5 13-21C27 6.8 21.2 1 14 1Z" fill="var(--color-orange)" stroke="#fff" strokeWidth={2} />
        <circle cx={14} cy={14} r={5} fill="#fff" />
      </svg>
    ),
    bg: "bg-[#f0f0ee]",
  },
  {
    n: "02",
    title: "Launch the swarm",
    body: "Each drone takes its own rooms. The edge server keeps them apart and inside the fence you drew.",
    image: <img src="/assets/plan.png" alt="" className="absolute top-[-90px] left-[-60px] h-[509px] w-[611px] max-w-none" />,
    bg: "bg-[#f7f7f6]",
  },
  {
    n: "03",
    title: "Your crew hears the way in",
    body: "When a drone finds someone, the crew gets the room and the fastest clear route in their earpiece.",
    image: <img src="/assets/f2.png" alt="" className="absolute inset-0 size-full object-cover" />,
    overlay: (
      <div className="absolute top-[65%] left-[14%] h-[25%] w-[58%] border-2 border-[#ff3b2e]">
        <span className="absolute -top-[21px] -left-0.5 bg-[#ff3b2e] px-1.5 py-px font-mono text-[11px] font-semibold text-white">person 0.94</span>
      </div>
    ),
    bg: "bg-[#222]",
  },
];

function Landing() {
  return (
    <div className="min-h-svh bg-white">
      <header className="sticky top-0 z-20 flex h-[72px] items-center gap-9 border-b border-line-soft bg-white/90 px-6 backdrop-blur md:px-16">
        <Link to="/" className="flex items-center gap-2.5">
          <Mark />
          <span className="text-lg font-bold tracking-[-0.02em]">Swarm</span>
        </Link>
        <nav className="hidden items-center gap-7 text-sm font-medium text-[#3a3a38] lg:flex">
          <a href="#how">How it works</a>
          <a href="#hardware">Hardware</a>
          <a href="#honest">For departments</a>
          <a href="#map">Field tests</a>
        </nav>
        <div className="flex-1" />
        <Link to="/live" className="text-sm font-medium">
          Sign in
        </Link>
        <Button variant="primary" size="lg" className="h-10" render={<Link to="/incidents/new" />} nativeButton={false}>
          Book a drill
        </Button>
      </header>

      <section className="flex flex-col items-center gap-7 bg-[linear-gradient(180deg,#fff_0%,#fff_55%,var(--color-panel)_55%,var(--color-panel)_100%)] px-6 pt-[88px] pb-20">
        <span className="flex h-[30px] items-center gap-2 rounded-full bg-orange-tint pr-3 pl-1.5 text-[13px] font-medium text-orange-deep shadow-[inset_0_0_0_1px_#fbd3bf]">
          <span className="rounded-full bg-orange px-[7px] py-0.5 text-[11px] font-semibold text-white">New</span>
          Live crew routing through blocked rooms
        </span>
        <h1 className="max-w-[980px] text-center text-5xl leading-[1.05] font-semibold tracking-[-0.035em] md:text-[76px]">
          See inside the building before your crew goes in.
        </h1>
        <p className="max-w-[640px] text-center text-[19px] leading-[29px] text-muted">
          A swarm of small drones maps the interior in minutes, finds people and hazards, and tells your crew the way through.
        </p>
        <div className="flex flex-wrap justify-center gap-3">
          <Button variant="primary" size="xl" render={<Link to="/incidents/new" />} nativeButton={false}>
            Book a drill
            <ArrowRight />
          </Button>
          <Button size="xl" className="font-medium" render={<Link to="/live" />} nativeButton={false}>
            <span className="flex size-[22px] items-center justify-center rounded-full bg-ink">
              <Play className="size-2.5 fill-white text-white" />
            </span>
            Watch the 2-minute run
          </Button>
        </div>
        <Link
          to="/live"
          className="w-full max-w-[1240px] overflow-hidden rounded-[14px] bg-white shadow-[0_0_0_1px_var(--color-line-strong),0_30px_70px_rgb(21_21_21/0.18),0_8px_18px_rgb(21_21_21/0.08)]"
        >
          <img src="/assets/console-live.webp" alt="The live console: point cloud map, drone feeds and a person finding" className="block w-full" />
        </Link>
      </section>

      <section className="grid border-b border-line bg-panel px-6 py-14 md:grid-cols-3 md:px-[100px]">
        <Stat value="3:40" text="to map a two-story, 150 m² house with four drones in simulation." />
        <Stat value="1.4 s" text="from a drone seeing a person to the crew hearing where they are." border />
        <Stat value="0" text="cloud services needed. Everything runs on one box in the truck." border />
      </section>

      <section id="how" className="flex flex-col gap-12 px-6 py-[120px] md:px-[100px]">
        <SectionHead title="From the curb to the room in three steps." body="No pilots, no joysticks. The incident commander picks the building and the swarm does the rest." />
        <div className="grid gap-6 md:grid-cols-3">
          {steps.map((s) => (
            <div key={s.n} className="flex flex-col gap-[18px]">
              <div className={`relative h-[280px] overflow-hidden rounded-[14px] shadow-[0_0_0_1px_var(--color-line)] ${s.bg}`}>
                {s.image}
                {s.overlay}
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="font-mono text-[13px] font-semibold text-orange-edge">{s.n}</span>
                <h3 className="text-[21px] font-semibold tracking-[-0.01em]">{s.title}</h3>
                <p className="text-[15px] leading-[23px] text-muted">{s.body}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section id="map" className="flex flex-col items-center gap-10 bg-map py-[110px] pl-6 md:flex-row md:pl-[100px]">
        <div className="flex w-full max-w-[440px] shrink-0 flex-col gap-7 pr-6 md:pr-0">
          <h2 className="text-[48px] leading-[54px] font-semibold tracking-[-0.03em]">A live map, not a guess.</h2>
          <p className="text-[17px] leading-[27px] text-muted">
            Every drone feeds the same 3D model. Rooms fill in as they are flown. Rooms nobody has seen yet stay empty, so you always know what you don&apos;t
            know.
          </p>
          <ul className="flex flex-col gap-4">
            <Feature title="People, doors, debris and gas" body="Pinned to the room they were seen in." />
            <Feature title="Keeps mapping after you go in" body="Doors your crew opens show up in seconds." />
            <Feature title="Replay every second" body="Scrub the timeline for the after-action review." />
          </ul>
        </div>
        <div className="relative h-[600px] w-full min-w-0 flex-1 overflow-hidden">
          <img src="/assets/cloud.png" alt="Point cloud scan of a house" className="absolute top-[-30px] left-[-40px] h-[636px] w-[1019px] max-w-none" />
          <MapPin left={234} top={286} big className="bg-person">
            <User className="size-4" strokeWidth={2.2} />
          </MapPin>
          <span className="absolute top-[288px] left-[272px] rounded-md bg-white px-2.5 py-1 text-[13px] font-semibold shadow-[0_2px_8px_rgb(0_0_0/0.12)]">Person, Bedroom 1</span>
          <MapPin left={531} top={231} className="bg-ink">
            <X className="size-3" strokeWidth={2.6} />
          </MapPin>
          <MapPin left={686} top={275} className="bg-hazard">
            <TriangleAlert className="size-3" strokeWidth={2.4} />
          </MapPin>
          <MapPin left={594} top={373} className="bg-door">
            <DoorClosed className="size-3" strokeWidth={2.4} />
          </MapPin>
        </div>
      </section>

      <section id="hardware" className="flex flex-col gap-12 px-6 py-[120px] md:px-[100px]">
        <SectionHead
          title="Bring the drones you can afford."
          body="We don't sell airframes. A small companion computer turns cheap drones into mappers, and one edge box in the truck does the heavy lifting."
        />
        <div className="grid gap-6 md:grid-cols-2">
          <SpecCard
            title="On each drone"
            rows={[
              ["Raspberry Pi running ROS 2", "Stabilizes and streams"],
              ["IMU", "Real-world scale for the map"],
              ["Wi-Fi relay", "No extra radio to carry"],
              ["Works with", "E58, Tello EDU, custom 3-inch frames"],
            ]}
          />
          <SpecCard
            dark
            title="In the truck"
            badge="Works offline"
            rows={[
              ["ASUS Ascent GX10", "One box, 128 GB memory"],
              ["Visual SLAM", "Builds the 3D map"],
              ["Detection and collision avoidance", "Every frame, every drone"],
              ["Voice agent", "Talks to the crew channel"],
            ]}
          />
        </div>
      </section>

      <section id="honest" className="flex flex-col gap-10 px-6 pb-[120px] md:flex-row md:gap-16 md:px-[100px]">
        <h2 className="w-full max-w-[360px] shrink-0 text-[32px] leading-[38px] font-semibold tracking-[-0.02em]">Honest about what it can&apos;t do.</h2>
        <div className="grid flex-1 gap-8 md:grid-cols-3">
          <Honest title="Not for heavy smoke" body="Cameras need light. We built for collapses, earthquakes and welfare checks first." />
          <Honest title="Estimates, not diagnoses" body="Breathing and pulse readings come with confidence and never replace a medic." />
          <Honest title="A person stays in charge" body="The incident commander approves routes and can stop the swarm at any time." />
        </div>
      </section>

      <section className="px-4 pb-16 md:px-16">
        <div className="flex flex-col gap-8 rounded-3xl bg-[linear-gradient(135deg,#ff6a2e_0%,#e8480c_100%)] px-8 py-14 shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_4px_0_var(--color-orange-deep)] md:flex-row md:items-center md:gap-12 md:px-[72px] md:py-16">
          <div className="flex flex-1 flex-col gap-3">
            <h2 className="text-[40px] leading-[46px] font-semibold tracking-[-0.03em] text-white md:text-[48px] md:leading-[54px]">Run a drill with your crew.</h2>
            <p className="text-lg leading-7 text-white/90">We bring four drones and the edge box to your training building. Two hours, no cost.</p>
          </div>
          <div className="flex flex-col items-stretch gap-3">
            <Link
              to="/incidents/new"
              className="flex h-[54px] items-center justify-center gap-2 rounded-xl bg-[linear-gradient(180deg,#fff,#f4f4f3)] px-[26px] text-[17px] font-semibold shadow-[0_3px_0_var(--color-orange-deep),0_8px_18px_rgb(80_20_0/0.25)] active:translate-y-px"
            >
              Book a drill
              <ArrowRight className="size-4" />
            </Link>
            <span className="text-center text-sm text-white/90">or email crews@swarm.example</span>
          </div>
        </div>
      </section>

      <footer className="flex flex-col gap-10 border-t border-line-soft px-6 pt-10 pb-14 md:flex-row md:gap-16 md:px-[100px]">
        <div className="flex flex-1 flex-col gap-3">
          <span className="flex items-center gap-2.5">
            <Mark />
            <span className="text-[17px] font-bold tracking-[-0.02em]">Swarm</span>
          </span>
          <span className="text-sm text-muted">Indoor mapping for first responders.</span>
        </div>
        <FooterCol title="Product" links={["How it works", "Hardware", "Field tests"]} />
        <FooterCol title="Departments" links={["Book a drill", "Training", "Safety and privacy"]} />
        <FooterCol title="Project" links={["GitHub", "Team", "Contact"]} />
      </footer>
    </div>
  );
}

function Stat({ value, text, border }: { value: string; text: string; border?: boolean }) {
  return (
    <div className={`flex flex-col gap-1.5 py-6 md:px-8 md:py-0 ${border ? "border-line md:border-l" : "md:pl-0"}`}>
      <span className="text-[52px] font-semibold tracking-[-0.03em]">{value}</span>
      <span className="text-[15px] leading-[22px] text-muted">{text}</span>
    </div>
  );
}

function SectionHead({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col gap-6 md:flex-row md:items-end md:gap-12">
      <h2 className="flex-1 text-[40px] leading-[46px] font-semibold tracking-[-0.03em] md:text-[48px] md:leading-[54px]">{title}</h2>
      <p className="max-w-[420px] text-[17px] leading-[27px] text-muted">{body}</p>
    </div>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <li className="flex gap-3">
      <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-orange">
        <Check className="size-3 text-white" strokeWidth={3} />
      </span>
      <span className="flex flex-col gap-0.5">
        <span className="text-[15px] font-semibold">{title}</span>
        <span className="text-sm leading-[21px] text-muted">{body}</span>
      </span>
    </li>
  );
}

function MapPin({ left, top, big, className, children }: { left: number; top: number; big?: boolean; className: string; children: ReactNode }) {
  return (
    <span
      className={`absolute flex items-center justify-center rounded-[15px_15px_15px_2px] text-white shadow-[0_0_0_2px_#fff,0_3px_8px_rgb(0_0_0/0.25)] ${big ? "size-[30px]" : "size-6"} ${className}`}
      style={{ left, top }}
    >
      {children}
    </span>
  );
}

function SpecCard({ title, rows, dark, badge }: { title: string; rows: [string, string][]; dark?: boolean; badge?: string }) {
  return (
    <div
      className={`flex flex-col gap-5 rounded-2xl p-7 ${dark ? "bg-ink text-white" : "bg-white shadow-[0_0_0_1px_var(--color-line),0_2px_0_var(--color-line)]"}`}
    >
      <div className="flex items-center gap-3">
        <h3 className="flex-1 text-[21px] font-semibold">{title}</h3>
        {badge && (
          <span className="flex h-[26px] items-center gap-1.5 rounded-full bg-orange/15 px-2.5 text-xs font-semibold text-[#ff8a5c]">
            <span className="size-1.5 rounded-full bg-orange" />
            {badge}
          </span>
        )}
      </div>
      <dl className="flex flex-col">
        {rows.map(([k, v], i) => (
          <div key={k} className={`flex min-h-12 items-center gap-4 ${i < rows.length - 1 ? (dark ? "border-b border-[#2c2c2b]" : "border-b border-line-soft") : ""}`}>
            <dt className="flex-1 text-[15px]">{k}</dt>
            <dd className={`text-right text-sm ${dark ? "text-[#a3a3a0]" : "text-muted"}`}>{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Honest({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex flex-col gap-2 border-t-2 border-ink pt-4">
      <h3 className="text-base font-semibold">{title}</h3>
      <p className="text-sm leading-[22px] text-muted">{body}</p>
    </div>
  );
}

function FooterCol({ title, links }: { title: string; links: string[] }) {
  return (
    <div className="flex flex-col gap-2.5">
      <span className="text-[13px] font-semibold">{title}</span>
      {links.map((l) => (
        <span key={l} className="text-sm text-muted">
          {l}
        </span>
      ))}
    </div>
  );
}
