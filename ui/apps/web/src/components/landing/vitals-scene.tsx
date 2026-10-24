import { useEffect, useRef } from "react";
import * as THREE from "three";

import { PEOPLE_POS } from "./vitals-geometry";

const ORANGE = 0xff5a1f;

function mat(color: number, emissive = 0x000000) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.7, metalness: 0.05, emissive });
}

function capsule(r: number, len: number, m: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 12), m);
  mesh.castShadow = true;
  return mesh;
}

/** Small quadcopter: X frame, motors, spinning props, camera pod and LED. */
function buildDrone() {
  const drone = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.14, 0.32), mat(0x2b2b2a));
  body.castShadow = true;
  drone.add(body);
  const shell = new THREE.Mesh(new THREE.BoxGeometry(0.36, 0.06, 0.24), mat(ORANGE));
  shell.position.y = 0.1;
  drone.add(shell);
  const props: THREE.Mesh[] = [];
  for (const [x, z] of [
    [0.42, 0.42],
    [0.42, -0.42],
    [-0.42, 0.42],
    [-0.42, -0.42],
  ] as const) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.04, 0.06), mat(0x3a3a38));
    arm.position.set(x / 2, 0, z / 2);
    arm.rotation.y = Math.atan2(-z, x);
    drone.add(arm);
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.1, 16), mat(0x151515));
    motor.position.set(x, 0.03, z);
    drone.add(motor);
    const guard = new THREE.Mesh(new THREE.TorusGeometry(0.24, 0.012, 6, 32), mat(0x8a8a86));
    guard.rotation.x = Math.PI / 2;
    guard.position.set(x, 0.09, z);
    drone.add(guard);
    const prop = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.008, 0.05), mat(0x111111));
    prop.position.set(x, 0.1, z);
    drone.add(prop);
    props.push(prop);
  }
  const pod = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), mat(0x0d0d0d));
  pod.position.set(0.27, -0.04, 0);
  drone.add(pod);
  const lens = new THREE.Mesh(new THREE.CircleGeometry(0.04, 16), new THREE.MeshBasicMaterial({ color: 0x5b8cff }));
  lens.position.set(0.345, -0.04, 0);
  lens.rotation.y = Math.PI / 2;
  drone.add(lens);
  const led = new THREE.Mesh(new THREE.SphereGeometry(0.022, 8, 8), new THREE.MeshBasicMaterial({ color: ORANGE }));
  led.position.set(-0.26, 0.04, 0);
  drone.add(led);
  return { drone, props };
}

/** Low-poly mannequins in the three poses the section talks about. */
function buildPeople() {
  const people: { group: THREE.Group; skin: THREE.MeshStandardMaterial }[] = [];
  const poses = ["lying", "sitting", "debris"] as const;
  poses.forEach((pose, i) => {
    const skin = mat(0xd8d8d4);
    const g = new THREE.Group();
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.15, 16, 12), skin);
    head.castShadow = true;
    if (pose === "lying" || pose === "debris") {
      const torso = capsule(0.17, 0.55, skin);
      torso.rotation.z = Math.PI / 2;
      torso.position.set(0, 0.18, 0);
      head.position.set(0.55, 0.17, 0);
      const legL = capsule(0.08, 0.7, skin);
      legL.rotation.z = Math.PI / 2;
      legL.position.set(-0.72, 0.1, 0.1);
      const legR = legL.clone();
      legR.position.z = -0.1;
      const arm = capsule(0.06, 0.45, skin);
      arm.rotation.set(0, 0.5, Math.PI / 2);
      arm.position.set(0.15, 0.1, 0.32);
      g.add(torso, head, legL, legR, arm);
      if (pose === "debris") {
        const slabMat = mat(0x6e6e6a);
        const slab = new THREE.Mesh(new THREE.BoxGeometry(1.1, 0.08, 0.9), slabMat);
        slab.position.set(0.35, 0.42, 0);
        slab.rotation.set(0.15, 0.2, -0.32);
        slab.castShadow = true;
        const beam = new THREE.Mesh(new THREE.BoxGeometry(1.4, 0.12, 0.14), slabMat);
        beam.position.set(-0.2, 0.35, -0.25);
        beam.rotation.set(0, -0.4, 0.22);
        beam.castShadow = true;
        g.add(slab, beam);
      }
    } else {
      const torso = capsule(0.15, 0.42, skin);
      torso.position.set(0, 0.48, 0);
      head.position.set(0, 0.95, 0);
      const thighL = capsule(0.075, 0.38, skin);
      thighL.rotation.z = Math.PI / 2;
      thighL.position.set(0.28, 0.12, 0.1);
      const thighR = thighL.clone();
      thighR.position.z = -0.1;
      const armL = capsule(0.055, 0.36, skin);
      armL.position.set(0.05, 0.42, 0.22);
      armL.rotation.x = 0.25;
      const armR = armL.clone();
      armR.position.z = -0.22;
      armR.rotation.x = -0.25;
      const wall = new THREE.Mesh(new THREE.BoxGeometry(0.12, 1.4, 1.6), mat(0xbdbdb8));
      wall.position.set(-0.32, 0.7, 0);
      wall.receiveShadow = true;
      g.add(torso, head, thighL, thighR, armL, armR, wall);
    }
    const [x, z] = PEOPLE_POS[i]!;
    g.position.set(x, 0, z);
    // Face the drone at the origin (local +x points at the drone).
    g.rotation.y = Math.atan2(z, -x);
    people.push({ group: g, skin });
  });
  return people;
}

/**
 * Three.js view of a drone choosing who to look at. `yaw` turns the drone,
 * `focus` is the index of the person being read and `lock` (0..1) fades in
 * the camera's view cone.
 */
export function VitalsScene({ yaw, focus, lock }: { yaw: number; focus: number; lock: number }) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef({ yaw, focus, lock });
  state.current = { yaw, focus, lock };

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
    camera.position.set(7.2, 6.6, 9.2);
    camera.lookAt(-0.2, 0.3, -0.6);

    scene.add(new THREE.HemisphereLight(0xffffff, 0xcfcfca, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(4, 9, 5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.camera.left = -6;
    sun.shadow.camera.right = 6;
    sun.shadow.camera.top = 6;
    sun.shadow.camera.bottom = -6;
    scene.add(sun);

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), new THREE.ShadowMaterial({ opacity: 0.14 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);
    // Floor as a dotted scan, matching the point cloud look.
    const dots: number[] = [];
    for (let x = -6; x <= 6; x += 0.25) for (let z = -6; z <= 6; z += 0.25) if (x * x + z * z < 30) dots.push(x, 0.001, z);
    const dotGeo = new THREE.BufferGeometry();
    dotGeo.setAttribute("position", new THREE.Float32BufferAttribute(dots, 3));
    scene.add(new THREE.Points(dotGeo, new THREE.PointsMaterial({ color: 0xa3a3a0, size: 0.035 })));

    const { drone, props } = buildDrone();
    drone.position.set(0, 1.5, 0);
    scene.add(drone);
    const people = buildPeople();
    people.forEach((p) => scene.add(p.group));

    // View cone from the camera pod to the person being read.
    const coneMat = new THREE.MeshBasicMaterial({ color: ORANGE, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide });
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.55, 1, 32, 1, true), coneMat);
    cone.geometry.translate(0, -0.5, 0);
    cone.geometry.rotateX(-Math.PI / 2);
    scene.add(cone);
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.58, 40), new THREE.MeshBasicMaterial({ color: ORANGE, transparent: true, opacity: 0 }));
    ring.rotation.x = -Math.PI / 2;
    scene.add(ring);

    const resize = () => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(1, h);
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(el);

    let frame = 0;
    let shownYaw = state.current.yaw;
    const clock = new THREE.Clock();
    const tick = () => {
      const dt = clock.getDelta();
      const time = clock.elapsedTime;
      const { yaw: targetYaw, focus: f, lock: l } = state.current;
      shownYaw += (targetYaw - shownYaw) * Math.min(1, dt * 8);
      drone.rotation.y = shownYaw;
      drone.position.y = 1.5 + Math.sin(time * 2.2) * 0.04;
      drone.rotation.z = Math.sin(time * 1.7) * 0.02;
      props.forEach((p, i) => (p.rotation.y += dt * (i % 2 ? 40 : -40)));

      people.forEach((p, i) => {
        p.skin.emissive.setHex(i === f ? 0xff5a1f : 0x000000);
        p.skin.emissiveIntensity = i === f ? 0.18 + 0.2 * l : 0;
        p.skin.color.setHex(i === f ? 0xe6e6e2 : 0xc8c8c4);
      });

      const target = PEOPLE_POS[f]!;
      const from = new THREE.Vector3(0.28, -0.05, 0).applyEuler(drone.rotation).add(drone.position);
      const to = new THREE.Vector3(target[0], f === 1 ? 0.75 : 0.25, target[1]);
      cone.position.copy(from);
      cone.lookAt(to);
      cone.scale.set(1, 1, from.distanceTo(to));
      coneMat.opacity = 0.16 * l;
      ring.position.set(target[0], 0.01, target[1]);
      ring.scale.setScalar(1.2 + 0.15 * Math.sin(time * 4));
      (ring.material as THREE.MeshBasicMaterial).opacity = 0.8 * l;

      renderer.render(scene, camera);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      renderer.dispose();
      scene.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof THREE.Points) {
          o.geometry.dispose();
          const m = o.material as THREE.Material | THREE.Material[];
          (Array.isArray(m) ? m : [m]).forEach((x) => x.dispose());
        }
      });
      el.removeChild(renderer.domElement);
    };
  }, []);

  return <div ref={host} className="absolute inset-0" aria-label="3D drone turning to look at people" role="img" />;
}

