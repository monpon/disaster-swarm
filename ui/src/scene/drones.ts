import * as THREE from "three";
import { CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import { MODE_COLORS, yawOf, type CameraModel, type DroneState } from "../types";
import { FrustumView } from "./frustum";

const ARM = 0.25;
const MAX_PATH_POINTS = 64;
const TRAIL_POINTS = 240;
const INTERP_DELAY_MS = 60;

export interface Layers {
  paths: boolean;
  footprints: boolean;
  links: boolean;
  trails: boolean;
  labels: boolean;
}

interface Sample {
  t: number;
  s: DroneState;
}

const tmpA = new THREE.Quaternion();
const tmpB = new THREE.Quaternion();

class DroneView {
  readonly body = new THREE.Group(); // scaled visual model
  readonly hit: THREE.Mesh;
  readonly pos = new THREE.Vector3();
  readonly quat = new THREE.Quaternion();
  private rotors: THREE.Mesh[] = [];
  private led: THREE.Mesh;
  private ledMat: THREE.MeshBasicMaterial;
  private frustum: FrustumView;
  private path: THREE.Line;
  private pathMat: THREE.LineDashedMaterial;
  private link: THREE.Line;
  private linkMat: THREE.LineBasicMaterial;
  private trail: THREE.Line;
  private trailBuf = new Float32Array(TRAIL_POINTS * 3);
  private trailCount = 0;
  private lastTrail = 0;
  private halo: THREE.Mesh;
  private label: CSS2DObject;
  private labelEl: HTMLDivElement;
  private prev: Sample | null = null;
  private next: Sample | null = null;
  private spin = 0;
  state: DroneState;

  constructor(readonly id: number, s: DroneState, parent: THREE.Group, scale: number, cam: CameraModel) {
    this.state = s;
    const color = MODE_COLORS[s.mode];

    // --- body model (real dimensions, scaled up for visibility)
    const frame = new THREE.MeshStandardMaterial({ color: "#d9dee8", roughness: 0.5, metalness: 0.2 });
    const dark = new THREE.MeshStandardMaterial({ color: "#272c36", roughness: 0.6 });
    const hub = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.16, 0.08), frame);
    hub.castShadow = true;
    this.body.add(hub);
    // Forward-facing camera pod on the nose (lens tinted so heading reads at a glance).
    const pod = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.07, 0.06), dark);
    pod.position.set(0.14, 0, -0.03);
    const lens = new THREE.Mesh(
      new THREE.CylinderGeometry(0.022, 0.022, 0.02, 12).rotateZ(Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: "#5ec8ff" }),
    );
    lens.position.set(0.18, 0, -0.03);
    this.body.add(pod, lens);
    for (let i = 0; i < 4; i++) {
      const a = Math.PI / 4 + (i * Math.PI) / 2;
      const arm = new THREE.Mesh(new THREE.BoxGeometry(ARM, 0.025, 0.02), dark);
      arm.position.set((Math.cos(a) * ARM) / 2, (Math.sin(a) * ARM) / 2, 0);
      arm.rotation.z = a;
      this.body.add(arm);
      const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 0.04, 10).rotateX(Math.PI / 2), dark);
      motor.position.set(Math.cos(a) * ARM, Math.sin(a) * ARM, 0.02);
      this.body.add(motor);
      const rotor = new THREE.Mesh(
        new THREE.BoxGeometry(0.24, 0.022, 0.004),
        new THREE.MeshStandardMaterial({ color: "#aab3c5", transparent: true, opacity: 0.85 }),
      );
      rotor.position.set(Math.cos(a) * ARM, Math.sin(a) * ARM, 0.045);
      this.rotors.push(rotor);
      this.body.add(rotor);
    }
    this.ledMat = new THREE.MeshBasicMaterial({ color });
    this.led = new THREE.Mesh(new THREE.SphereGeometry(0.035, 10, 8), this.ledMat);
    this.led.position.set(0, 0, 0.06);
    this.body.add(this.led);
    this.body.scale.setScalar(scale);

    this.halo = new THREE.Mesh(
      new THREE.RingGeometry(0.55, 0.62, 40),
      new THREE.MeshBasicMaterial({ color: "#ffffff", transparent: true, opacity: 0.9, depthWrite: false, side: THREE.DoubleSide }),
    );
    this.halo.visible = false;
    this.body.add(this.halo);

    // Picking proxy (unscaled world size, generous radius).
    this.hit = new THREE.Mesh(new THREE.SphereGeometry(4, 8, 6), new THREE.MeshBasicMaterial({ visible: false }));
    this.hit.userData.droneId = id;

    // --- forward camera view frustum
    this.frustum = new FrustumView(cam, color);

    // --- planned path (dashed), uplink to master, flown trail
    const pathGeo = new THREE.BufferGeometry();
    pathGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(MAX_PATH_POINTS * 3), 3));
    this.pathMat = new THREE.LineDashedMaterial({ color, dashSize: 2, gapSize: 1.5, transparent: true, opacity: 0.8 });
    this.path = new THREE.Line(pathGeo, this.pathMat);
    this.path.frustumCulled = false;

    const linkGeo = new THREE.BufferGeometry();
    linkGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
    this.linkMat = new THREE.LineBasicMaterial({ color: "#5ec8ff", transparent: true, opacity: 0.18 });
    this.link = new THREE.Line(linkGeo, this.linkMat);
    this.link.frustumCulled = false;

    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(this.trailBuf, 3));
    trailGeo.setDrawRange(0, 0);
    this.trail = new THREE.Line(
      trailGeo,
      new THREE.LineBasicMaterial({ color: "#d9e2f2", transparent: true, opacity: 0.25 }),
    );
    this.trail.frustumCulled = false;

    // --- label
    this.labelEl = document.createElement("div");
    this.labelEl.className = "drone-label";
    this.labelEl.textContent = `D${id}`;
    this.label = new CSS2DObject(this.labelEl);
    this.label.center.set(0.5, 1.6);

    parent.add(this.body, this.hit, this.frustum.group, this.path, this.link, this.trail);
    this.body.add(this.label);
    this.push(s, performance.now());
  }

  push(s: DroneState, t: number): void {
    this.prev = this.next ?? { t: t - 50, s };
    this.next = { t, s };
    const modeChanged = s.mode !== this.state.mode;
    this.state = s;
    if (modeChanged) {
      const c = new THREE.Color(MODE_COLORS[s.mode]);
      this.ledMat.color.copy(c);
      this.frustum.setColor(c);
      this.pathMat.color.copy(c);
    }
    this.labelEl.style.borderColor = MODE_COLORS[s.mode];
    this.labelEl.classList.toggle("crashed", s.crashed);
  }

  update(now: number, dt: number, antenna: THREE.Vector3, layers: Layers): void {
    if (!this.prev || !this.next) return;
    const rt = now - INTERP_DELAY_MS;
    const span = Math.max(this.next.t - this.prev.t, 1);
    const a = THREE.MathUtils.clamp((rt - this.prev.t) / span, 0, 1);
    const p0 = this.prev.s.p;
    const p1 = this.next.s.p;
    this.pos.set(p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a, p0[2] + (p1[2] - p0[2]) * a);
    const q0 = this.prev.s.q;
    const q1 = this.next.s.q;
    tmpA.set(q0[1], q0[2], q0[3], q0[0]);
    tmpB.set(q1[1], q1[2], q1[3], q1[0]);
    this.quat.slerpQuaternions(tmpA, tmpB, a);

    const s = this.state;
    this.body.position.copy(this.pos);
    this.body.quaternion.copy(this.quat);
    this.hit.position.copy(this.pos);

    this.spin += dt * (s.crashed ? 0 : 20 + 140 * s.throttle);
    this.rotors.forEach((r, i) => (r.rotation.z = (i % 2 ? -1 : 1) * this.spin + i));

    const showFoot = layers.footprints && s.cam_on;
    this.frustum.group.visible = showFoot;
    if (showFoot) this.frustum.update(this.pos, this.yaw(), s.agl);

    this.path.visible = layers.paths && s.path.length > 0;
    if (this.path.visible) {
      const attr = this.path.geometry.getAttribute("position") as THREE.BufferAttribute;
      attr.setXYZ(0, this.pos.x, this.pos.y, this.pos.z);
      const n = Math.min(s.path.length, MAX_PATH_POINTS - 1);
      for (let i = 0; i < n; i++) attr.setXYZ(i + 1, s.path[i][0], s.path[i][1], s.path[i][2]);
      attr.needsUpdate = true;
      this.path.geometry.setDrawRange(0, n + 1);
      this.path.computeLineDistances();
    }

    const connected = !s.crashed && s.link_age !== null && s.link_age < 2;
    this.link.visible = layers.links && connected && !s.grounded;
    if (this.link.visible) {
      const attr = this.link.geometry.getAttribute("position") as THREE.BufferAttribute;
      attr.setXYZ(0, this.pos.x, this.pos.y, this.pos.z);
      attr.setXYZ(1, antenna.x, antenna.y, antenna.z);
      attr.needsUpdate = true;
      this.linkMat.opacity = 0.08 + 0.25 * Math.max(0, 1 - (s.link_age ?? 0) / 1.0);
    }

    this.trail.visible = layers.trails;
    if (now - this.lastTrail > 250 && !s.grounded) {
      this.lastTrail = now;
      if (this.trailCount === TRAIL_POINTS) {
        this.trailBuf.copyWithin(0, 3);
        this.trailCount--;
      }
      this.trailBuf.set([this.pos.x, this.pos.y, this.pos.z], this.trailCount * 3);
      this.trailCount++;
      const geo = this.trail.geometry;
      geo.getAttribute("position").needsUpdate = true;
      geo.setDrawRange(0, this.trailCount);
    }

    this.label.visible = layers.labels;
    this.ledMat.color.setStyle(
      s.crashed ? MODE_COLORS.crashed : (Math.floor(now / 400) % 2 === 0 || s.grounded ? MODE_COLORS[s.mode] : "#111111"),
    );
  }

  /** Heading from the interpolated attitude. */
  yaw(): number {
    const q = this.quat;
    return yawOf([q.w, q.x, q.y, q.z]);
  }

  setScale(scale: number): void {
    this.body.scale.setScalar(scale);
  }

  setSelected(sel: boolean): void {
    this.halo.visible = sel;
    this.labelEl.classList.toggle("selected", sel);
  }

  dispose(parent: THREE.Group): void {
    this.body.remove(this.label);
    this.labelEl.remove();
    parent.remove(this.body, this.hit, this.frustum.group, this.path, this.link, this.trail);
    for (const o of [this.body, this.hit, this.path, this.link, this.trail]) {
      o.traverse((c) => (c as THREE.Mesh).geometry?.dispose());
    }
    this.frustum.dispose();
  }
}

export class SwarmView {
  readonly group = new THREE.Group();
  private views = new Map<number, DroneView>();
  scale = 6;
  selected: number | null = null;
  camera: CameraModel = { pitch: 0.61, tanH: 1, tanV: 0.58, range: 60 };

  sync(states: DroneState[]): void {
    const now = performance.now();
    const seen = new Set<number>();
    for (const s of states) {
      seen.add(s.id);
      const v = this.views.get(s.id);
      if (v) v.push(s, now);
      else this.views.set(s.id, new DroneView(s.id, s, this.group, this.scale, this.camera));
    }
    for (const [id, v] of this.views) {
      if (!seen.has(id)) {
        v.dispose(this.group);
        this.views.delete(id);
      }
    }
    this.select(this.selected !== null && this.views.has(this.selected) ? this.selected : null);
  }

  clear(): void {
    for (const v of this.views.values()) v.dispose(this.group);
    this.views.clear();
    this.selected = null;
  }

  update(dt: number, antenna: THREE.Vector3, layers: Layers): void {
    const now = performance.now();
    for (const v of this.views.values()) v.update(now, dt, antenna, layers);
  }

  setScale(scale: number): void {
    this.scale = scale;
    for (const v of this.views.values()) v.setScale(scale);
  }

  select(id: number | null): void {
    this.selected = id;
    for (const v of this.views.values()) v.setSelected(v.id === id);
  }

  get(id: number): DroneView | undefined {
    return this.views.get(id);
  }

  hitTargets(): THREE.Object3D[] {
    return [...this.views.values()].map((v) => v.hit);
  }
}
