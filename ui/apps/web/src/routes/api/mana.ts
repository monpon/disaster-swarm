import { createFileRoute } from "@tanstack/react-router";

import { hasMana, researchAddress } from "@/server/mana";

/**
 * Building research from Mana. GET says whether a Mana key is set. POST takes JSON `{ address, missionType }` and
 * returns the findings from the Mana research document that apply to the address, logging the lookup in Mana.
 */
export const Route = createFileRoute("/api/mana")({
  server: {
    handlers: {
      GET: () => Response.json({ mana: hasMana() }),
      POST: async ({ request }) => {
        if (!hasMana()) return Response.json({ error: "Mana isn't set up on this server (MANA_API_KEY)." }, { status: 503 });
        try {
          const { address, missionType } = (await request.json()) as { address?: string; missionType?: string };
          if (!address?.trim()) return Response.json({ error: "No address." }, { status: 400 });
          return Response.json(await researchAddress(address.trim().slice(0, 200), missionType?.slice(0, 60)));
        } catch (e) {
          console.error("mana research:", e);
          return Response.json({ error: "Couldn't reach Mana. Try again." }, { status: 502 });
        }
      },
    },
  },
});
