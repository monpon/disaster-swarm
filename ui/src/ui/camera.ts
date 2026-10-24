import * as THREE from "three";
import type { Stage } from "../scene/setup";
import type { SwarmView } from "../scene/drones";

const OVERVIEW_POS = new THREE.Vector3(-170, -210, 170);
const OVERVIEW_TARGET = new THREE.Vector3(0, 0, 0);
const FOLLOW_OFFSET = new THREE.Vector3(-22, -26, 16);
const FLY_MS = 900;

interface Flight {
  fromPos: THREE.Vector3;
  fromTarget: THREE.Vector3;
  t0: number;
  toFixed?: { pos: THREE.Vector3; target: THREE.Vector3 };
}

/** Orbit camera with click-to-follow and smooth fly-to transitions. */
export class CameraRig {
  following: number | null = null;
  private flight: Flight | null = null;
  private raycaster = new THREE.Raycaster();
  private down = { x: 0, y: 0 };

  constructor(
    private stage: Stage,
    private swarm: SwarmView,
    private onSelect: (id: number | null) => void,
  ) {
    const el = stage.renderer.domElement;
    el.addEventListener("pointerdown", (e) => (this.down = { x: e.clientX, y: e.clientY }));
    el.addEventListener("pointerup", (e) => {
      if (Math.hypot(e.clientX - this.down.x, e.clientY - this.down.y) > 4) return;
      this.pick(e);
    });
    el.addEventListener("dblclick", (e) => {
      if (!this.pickId(e)) this.unfollow();
    });
  }

  private pickId(e: MouseEvent): number | null {
    const rect = this.stage.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.stage.camera);
    const hit = this.raycaster.intersectObjects(this.swarm.hitTargets(), false)[0];
    return hit ? (hit.object.userData.droneId as number) : null;
  }

  private pick(e: MouseEvent): void {
    const id = this.pickId(e);
    if (id !== null) this.follow(id);
  }

  follow(id: number): void {
    this.following = id;
    this.swarm.select(id);
    this.onSelect(id);
    const { camera, controls } = this.stage;
    this.flight = { fromPos: camera.position.clone(), fromTarget: controls.target.clone(), t0: performance.now() };
  }

  unfollow(): void {
    this.following = null;
    this.flight = null;
  }

  overview(): void {
    this.following = null;
    const { camera, controls } = this.stage;
    this.flight = {
      fromPos: camera.position.clone(),
      fromTarget: controls.target.clone(),
      t0: performance.now(),
      toFixed: { pos: OVERVIEW_POS.clone(), target: OVERVIEW_TARGET.clone() },
    };
  }

  update(): void {
    const { camera, controls } = this.stage;
    const view = this.following !== null ? this.swarm.get(this.following) : undefined;
    if (this.following !== null && !view) this.following = null;

    if (this.flight) {
      const k = Math.min((performance.now() - this.flight.t0) / FLY_MS, 1);
      const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
      const toTarget = this.flight.toFixed?.target ?? view?.pos;
      const toPos = this.flight.toFixed?.pos ?? (view ? view.pos.clone().add(FOLLOW_OFFSET) : undefined);
      if (toTarget && toPos) {
        controls.target.lerpVectors(this.flight.fromTarget, toTarget, e);
        camera.position.lerpVectors(this.flight.fromPos, toPos, e);
      }
      if (k >= 1) this.flight = null;
    } else if (view) {
      // Keep the user's orbit offset while translating with the drone.
      const delta = view.pos.clone().sub(controls.target);
      controls.target.add(delta);
      camera.position.add(delta);
    }
    controls.update();
  }
}
