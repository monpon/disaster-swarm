import { useEffect, useRef } from "react";
import * as THREE from "three";

const ORANGE = 0xff5a1f;
const DRONE_POS = new THREE.Vector3(-0.8, 1.55, 0.35);
const PERSON_POS = new THREE.Vector3(0.95, 0, -0.45);
/** Point on the person's chest the camera locks onto. */
const CHEST = new THREE.Vector3(0.93, 1.22, -0.38);

function mat(color: number) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.75, metalness: 0.02 });
}

function capsule(r: number, len: number, m: THREE.Material) {
  const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 14), m);
  mesh.castShadow = true;
  return mesh;
}

function buildDrone() {
  const drone = new THREE.Group();
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.14, 0.32), mat(0x4a4a48));
  body.castShadow = true;
  const shell = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.06, 0.26), mat(ORANGE));
  shell.position.y = 0.1;
  drone.add(body, shell);
  const props: THREE.Mesh[] = [];
  for (const [x, z] of [
    [0.42, 0.42],
    [0.42, -0.42],
    [-0.42, 0.42],
    [-0.42, -0.42],
  ] as const) {
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.62, 0.04, 0.06), mat(0x5c5c59));
    arm.position.set(x / 2, 0, z / 2);
    arm.rotation.y = Math.atan2(-z, x);
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 0.1, 16), mat(0x2b2b2a));
    motor.position.set(x, 0.03, z);
    const guard = new THREE.Mesh(new THREE.TorusGeometry(0.24, 0.014, 6, 32), mat(0xb5b5af));
    guard.rotation.x = Math.PI / 2;
    guard.position.set(x, 0.09, z);
    const prop = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.008, 0.05), mat(0x2b2b2a));
    prop.position.set(x, 0.1, z);
    drone.add(arm, motor, guard, prop);
    props.push(prop);
  }
  const pod = new THREE.Mesh(new THREE.SphereGeometry(0.075, 16, 12), mat(0x1c1c1b));
  pod.position.set(0.27, -0.04, 0);
  const lens = new THREE.Mesh(new THREE.CircleGeometry(0.04, 16), new THREE.MeshBasicMaterial({ color: 0x5b8cff }));
  lens.position.set(0.346, -0.04, 0);
  lens.rotation.y = Math.PI / 2;
  drone.add(pod, lens);
  return { drone, props };
}

/**
 * Standing figure leaning back on a wall, waving. Built facing +z; arms hang
 * from shoulder pivots so they stay attached as they move.
 */
function buildPerson(skin: THREE.MeshStandardMaterial) {
  const person = new THREE.Group();
  const legL = capsule(0.085, 0.66, skin);
  legL.position.set(-0.1, 0.45, 0);
  const legR = legL.clone();
  legR.position.x = 0.1;
  person.add(legL, legR);

  // Everything above the hips leans back as one piece.
  const upper = new THREE.Group();
  upper.position.set(0, 0.86, 0);
  upper.rotation.x = -0.13;
  person.add(upper);
  const torso = capsule(0.17, 0.42, skin);
  torso.position.y = 0.3;
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.14, 20, 16), skin);
  head.position.y = 0.78;
  head.castShadow = true;
  upper.add(torso, head);

  const shoulderY = 0.52;
  // Resting arm.
  const restPivot = new THREE.Group();
  restPivot.position.set(-0.22, shoulderY, 0);
  restPivot.rotation.z = -0.12;
  const restArm = capsule(0.055, 0.46, skin);
  restArm.position.y = -0.29;
  restPivot.add(restArm);
  // Waving arm: upper arm out to the side, forearm raised from the elbow.
  const wavePivot = new THREE.Group();
  wavePivot.position.set(0.22, shoulderY, 0);
  const upperArm = capsule(0.055, 0.22, skin);
  upperArm.position.y = 0.16;
  wavePivot.add(upperArm);
  const elbow = new THREE.Group();
  elbow.position.y = 0.32;
  const forearm = capsule(0.05, 0.22, skin);
  forearm.position.y = 0.16;
  const hand = new THREE.Mesh(new THREE.SphereGeometry(0.065, 12, 10), skin);
  hand.position.y = 0.34;
  elbow.add(forearm, hand);
  wavePivot.add(elbow);
  upper.add(restPivot, wavePivot);

  return { person, wavePivot, elbow };
}

/**
 * Bright, close-up scene: the drone sweeps the room (`phase` 0..0.45), turns
 * to the person (0.45..0.6) and locks on with its view cone (`lock` 0..1).
 */
export function VitalsScene({ phase, lock }: { phase: number; lock: number }) {
  const host = useRef<HTMLDivElement>(null);
  const state = useRef({ phase, lock });
  state.current = { phase, lock };

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 50);
    camera.position.set(0.15, 1.85, 4.9);
    camera.lookAt(0.1, 1.2, -0.2);

    scene.add(new THREE.HemisphereLight(0xffffff, 0xe6e6e1, 2.4));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(-2, 6, 4);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.radius = 6;
    scene.add(sun);

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(20, 20), new THREE.ShadowMaterial({ opacity: 0.08 }));
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    scene.add(floor);
    const dots: number[] = [];
    for (let x = -4; x <= 4; x += 0.2) for (let z = -3; z <= 3; z += 0.2) dots.push(x, 0.001, z);
    const dotGeo = new THREE.BufferGeometry();
    dotGeo.setAttribute("position", new THREE.Float32BufferAttribute(dots, 3));
    scene.add(new THREE.Points(dotGeo, new THREE.PointsMaterial({ color: 0xc6c6c2, size: 0.03 })));

    const wall = new THREE.Mesh(new THREE.BoxGeometry(2.4, 2.3, 0.12), mat(0xe7e7e3));
    wall.position.set(PERSON_POS.x + 0.2, 1.15, PERSON_POS.z - 0.36);
    wall.receiveShadow = true;
    scene.add(wall);

    const skin = mat(0xdedbd5);
    const { person, wavePivot, elbow } = buildPerson(skin);
    person.position.copy(PERSON_POS);
    person.rotation.y = -0.4; // turn toward the drone
    scene.add(person);

    const { drone, props } = buildDrone();
    drone.position.copy(DRONE_POS);
    drone.scale.setScalar(1.1);
    scene.add(drone);

    const coneMat = new THREE.MeshBasicMaterial({ color: ORANGE, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide });
    const cone = new THREE.Mesh(new THREE.ConeGeometry(0.2, 1, 32, 1, true), coneMat);
    cone.geometry.translate(0, -0.5, 0);
    cone.geometry.rotateX(-Math.PI / 2);
    scene.add(cone);
    const scanMat = new THREE.MeshBasicMaterial({ color: ORANGE, transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide });
    const scan = new THREE.Mesh(new THREE.ConeGeometry(0.9, 1, 32, 1, true), scanMat);
    scan.geometry.translate(0, -0.5, 0);
    scan.geometry.rotateX(-Math.PI / 2);
    scene.add(scan);

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

    const lockYaw = Math.atan2(-(CHEST.z - DRONE_POS.z), CHEST.x - DRONE_POS.x);
    let frame = 0;
    const clock = new THREE.Clock();
    const tick = () => {
      const dt = clock.getDelta();
      const time = clock.elapsedTime;
      const { phase: ph, lock: l } = state.current;

      // Sweep left and right, then turn to the person.
      const sweep = lockYaw + 0.9 + Math.sin(Math.min(ph / 0.45, 1) * Math.PI * 2) * 0.9;
      const turn = Math.min(1, Math.max(0, (ph - 0.45) / 0.15));
      const k = turn * turn * (3 - 2 * turn);
      drone.rotation.y = sweep * (1 - k) + lockYaw * k;
      drone.position.y = DRONE_POS.y + Math.sin(time * 2.2) * 0.035;
      drone.rotation.z = Math.sin(time * 1.6) * 0.025;
      props.forEach((p, i) => (p.rotation.y += dt * (i % 2 ? 38 : -38)));

      wavePivot.rotation.z = -1.15 + Math.sin(time * 5.5) * 0.12;
      elbow.rotation.z = 1.05 + Math.sin(time * 5.5 + 0.6) * 0.4;

      skin.emissive.setHex(ORANGE);
      skin.emissiveIntensity = 0.22 * l;

      const from = new THREE.Vector3(0.28, -0.05, 0).multiplyScalar(1.1).applyEuler(drone.rotation).add(drone.position);
      cone.position.copy(from);
      cone.lookAt(CHEST);
      cone.scale.set(1, 1, from.distanceTo(CHEST));
      coneMat.opacity = 0.16 * l;

      const ahead = new THREE.Vector3(1, -0.35, 0).applyEuler(drone.rotation).multiplyScalar(2.4).add(from);
      scan.position.copy(from);
      scan.lookAt(ahead);
      scan.scale.set(1, 1, 2.4);
      scanMat.opacity = ph < 0.6 ? 0.08 * (1 - k) : 0;

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

  return <div ref={host} className="absolute inset-0" aria-label="A drone scans a room, then locks onto a person waving by the wall" role="img" />;
}
