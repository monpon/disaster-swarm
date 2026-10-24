import * as THREE from "three";
import type { CameraModel } from "../types";

/**
 * Translucent view pyramid for a drone's forward camera. The camera is gimbal-stabilized,
 * so the pyramid follows heading only and keeps a fixed downward pitch.
 */
export class FrustumView {
  readonly group = new THREE.Group();
  private faces: THREE.Mesh;
  private edges: THREE.LineSegments;
  private faceMat: THREE.MeshBasicMaterial;
  private edgeMat: THREE.LineBasicMaterial;

  constructor(private cam: CameraModel, color: THREE.ColorRepresentation, opacity = 0.08) {
    const { tanH: h, tanV: v } = cam;
    // Apex at origin, looking along +x, unit depth.
    const c = [
      [1, h, v],
      [1, -h, v],
      [1, -h, -v],
      [1, h, -v],
    ];
    const pos: number[] = [];
    for (let i = 0; i < 4; i++) {
      const a = c[i];
      const b = c[(i + 1) % 4];
      pos.push(0, 0, 0, ...a, ...b);
    }
    const faceGeo = new THREE.BufferGeometry();
    faceGeo.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    this.faceMat = new THREE.MeshBasicMaterial({
      color,
      transparent: true,
      opacity,
      depthWrite: false,
      side: THREE.DoubleSide,
    });
    this.faces = new THREE.Mesh(faceGeo, this.faceMat);
    this.faces.renderOrder = 4;

    const ep: number[] = [];
    for (let i = 0; i < 4; i++) ep.push(0, 0, 0, ...c[i], ...c[i], ...c[(i + 1) % 4]);
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute("position", new THREE.Float32BufferAttribute(ep, 3));
    this.edgeMat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: Math.min(1, opacity * 6) });
    this.edges = new THREE.LineSegments(edgeGeo, this.edgeMat);

    this.group.add(this.faces, this.edges);
  }

  setColor(color: THREE.ColorRepresentation): void {
    this.faceMat.color.set(color);
    this.edgeMat.color.set(color);
  }

  /** Place at the drone, facing `yaw`. Depth reaches the ground along the center ray, capped at range. */
  update(pos: THREE.Vector3, yaw: number, agl: number): void {
    this.group.position.copy(pos);
    this.group.rotation.set(0, 0, 0);
    this.group.rotateZ(yaw);
    this.group.rotateY(this.cam.pitch);
    const depth = Math.min(this.cam.range, Math.max(agl, 1) / Math.sin(this.cam.pitch));
    this.group.scale.setScalar(depth);
  }

  dispose(): void {
    this.faces.geometry.dispose();
    this.edges.geometry.dispose();
    this.faceMat.dispose();
    this.edgeMat.dispose();
  }
}
