import type { ServerMessage } from "./types";

type Handler = (msg: ServerMessage) => void;
type StatusHandler = (connected: boolean) => void;

export class SimSocket {
  private ws: WebSocket | null = null;
  private retry = 500;
  onOpen: (() => void) | null = null;

  constructor(
    private readonly onMessage: Handler,
    private readonly onStatus: StatusHandler,
  ) {
    this.connect();
  }

  private connect(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 500;
      this.onStatus(true);
      this.onOpen?.();
    };
    ws.onmessage = (ev) => this.onMessage(JSON.parse(ev.data) as ServerMessage);
    ws.onclose = () => {
      this.onStatus(false);
      setTimeout(() => this.connect(), this.retry);
      this.retry = Math.min(this.retry * 2, 5000);
    };
  }

  select(drone: number | null): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "select", drone }));
  }

  control(cmd: string, extra: Record<string, unknown> = {}): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "control", cmd, ...extra }));
    }
  }
}
