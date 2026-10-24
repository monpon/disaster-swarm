import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";

// The simulator is z-up; we keep that convention in the viewer.
THREE.Object3D.DEFAULT_UP.set(0, 0, 1);

export interface Stage {
  renderer: THREE.WebGLRenderer;
  labels: CSS2DRenderer;
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  controls: OrbitControls;
  sun: THREE.DirectionalLight;
}

export function createStage(container: HTMLElement, background = "#0b0f17"): Stage {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  container.appendChild(renderer.domElement);

  const labels = new CSS2DRenderer();
  labels.setSize(container.clientWidth, container.clientHeight);
  labels.domElement.className = "label-layer";
  container.appendChild(labels.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(background);
  scene.fog = new THREE.Fog(background, 350, 900);

  const camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 0.5, 3000);
  camera.position.set(-170, -210, 170);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(0, 0, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.49;
  controls.minDistance = 5;
  controls.maxDistance = 900;

  scene.add(new THREE.HemisphereLight("#b9c8e6", "#1b1f29", 0.9));
  const sun = new THREE.DirectionalLight("#fff1dc", 1.6);
  sun.position.set(-120, -80, 200);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  const s = 140;
  Object.assign(sun.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 10, far: 600 });
  sun.shadow.bias = -0.0005;
  scene.add(sun);

  new ResizeObserver(() => {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h);
    labels.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }).observe(container);

  return { renderer, labels, scene, camera, controls, sun };
}
