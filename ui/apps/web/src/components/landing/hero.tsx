import { Button } from "@swarm/ui/components/button";
import { Link } from "@tanstack/react-router";
import { ArrowDown } from "lucide-react";

/** Headline, one-line explanation, and the console the crew actually uses. */
export function Hero() {
  return (
    <section className="flex flex-col items-center gap-7 bg-[linear-gradient(180deg,#fff_0%,#fff_58%,var(--color-panel)_58%,var(--color-panel)_100%)] px-4 pt-16 pb-20 md:px-6 md:pt-[84px]">
      <h1 className="text-center text-[44px] leading-[0.98] font-bold tracking-[-0.045em] sm:text-[64px] lg:text-[88px]">
        When Every Second Counts,
        <br />
        <span className="text-orange">Find Them Faster.</span>
      </h1>
      <p className="max-w-[720px] text-center text-lg leading-8 text-muted md:text-[20px] md:leading-[31px]">
        Instead of one expensive drone searching alone, we send a team of small, smart drones. They fly on their own, search together, and build a map to help
        rescuers find people faster.
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Button variant="primary" size="xl" render={<a href="#race" />} nativeButton={false}>
          See how it works
          <ArrowDown />
        </Button>
        <Button size="xl" className="font-medium" render={<Link to="/live" />} nativeButton={false}>
          Open the console
        </Button>
      </div>
      <Link
        to="/live"
        className="mt-2 w-full max-w-[1240px] overflow-hidden rounded-[14px] bg-white shadow-[0_0_0_1px_var(--color-line-strong),0_30px_70px_rgb(21_21_21/0.18),0_8px_18px_rgb(21_21_21/0.08)] transition-transform duration-300 hover:-translate-y-1"
      >
        <img src="/assets/console-live.webp" alt="The live console: the map the drones build, their camera feeds, and a person they found" className="block w-full" />
      </Link>
    </section>
  );
}
