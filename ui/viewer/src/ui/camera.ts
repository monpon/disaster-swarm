import * as THREE from "three";
import type { Stage } from "../scene/setup";
import type { SwarmView } from "../scene/drones";

const FOLLOW_OFFSET = new THREE.Vector3(-9, -11, 7);
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
  overviewPos = new THREE.Vector3(30, -40, 95);
  overviewTarget = new THREE.Vector3(96, 64, 4);

  constructor(
    private stage: Stage,
    private swarms: SwarmView[],
    private onSelect: (id: number | null) => void,
    others: Stage[] = [],
  ) {
    for (const st of [stage, ...others]) {
      const el = st.renderer.domElement;
      el.addEventListener("pointerdown", (e) => (this.down = { x: e.clientX, y: e.clientY }));
      el.addEventListener("pointerup", (e) => {
        if (Math.hypot(e.clientX - this.down.x, e.clientY - this.down.y) > 4) return;
        const id = this.pickId(e, el, st.camera);
        if (id !== null) this.follow(id);
      });
      el.addEventListener("dblclick", (e) => {
        if (this.pickId(e, el, st.camera) === null) this.unfollow();
      });
    }
  }

  private pickId(e: MouseEvent, el: HTMLCanvasElement, camera: THREE.Camera): number | null {
    const rect = el.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, camera);
    for (const s of this.swarms) {
      const hit = this.raycaster.intersectObjects(s.hitTargets(), false)[0];
      if (hit) return hit.object.userData.droneId as number;
    }
    return null;
  }

  follow(id: number): void {
    this.following = id;
    this.swarms.forEach((s) => s.select(id));
    this.onSelect(id);
    const { camera, controls } = this.stage;
    this.flight = { fromPos: camera.position.clone(), fromTarget: controls.target.clone(), t0: performance.now() };
  }

  unfollow(): void {
    this.following = null;
    this.flight = null;
  }

  overview(immediate = false): void {
    this.following = null;
    const { camera, controls } = this.stage;
    if (immediate) {
      camera.position.copy(this.overviewPos);
      controls.target.copy(this.overviewTarget);
      this.flight = null;
      return;
    }
    this.flight = {
      fromPos: camera.position.clone(),
      fromTarget: controls.target.clone(),
      t0: performance.now(),
      toFixed: { pos: this.overviewPos.clone(), target: this.overviewTarget.clone() },
    };
  }

  update(): void {
    const { camera, controls } = this.stage;
    const view = this.following !== null ? this.swarms[0].get(this.following) : undefined;
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
      const delta = view.pos.clone().sub(controls.target);
      controls.target.add(delta);
      camera.position.add(delta);
    }
    controls.update();
  }
}
