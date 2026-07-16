import { Suspense, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import type { Group } from "three";

function LicensedModel({
  src,
  position,
  rotation,
  scale,
}: {
  src: string;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: number;
}) {
  const { scene } = useGLTF(src);
  return (
    <primitive
      object={scene.clone()}
      position={position}
      rotation={rotation}
      scale={scale}
    />
  );
}

function LicensedScene() {
  const group = useRef<Group>(null);
  useFrame((state) => {
    if (
      !group.current ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    const pointerShift = state.pointer.x * 0.11;
    group.current.rotation.y +=
      (pointerShift - group.current.rotation.y) * 0.025;
    group.current.position.y = Math.sin(state.clock.elapsedTime * 0.34) * 0.06;
  });
  return (
    <group ref={group} rotation={[0.08, -0.18, 0]}>
      <LicensedModel
        src="/assets/3d/laptop.glb"
      position={[0.35, -0.45, 0]}
      rotation={[-0.12, 2.75, 0]}
      scale={6.8}
      />
      <LicensedModel
        src="/assets/3d/smartphone.glb"
      position={[1.25, 0.15, 0.7]}
      rotation={[-1.5, -0.35, 0.08]}
      scale={6.4}
      />
    </group>
  );
}

useGLTF.preload("/assets/3d/laptop.glb");
useGLTF.preload("/assets/3d/smartphone.glb");

export default function HeroScene() {
  return (
    <div
      className="scene"
      aria-label="CC0 lisanslı laptop, telefon ve bağlantı anteni 3B sahnesi"
    >
      <Canvas camera={{ position: [0, 0.15, 6.2], fov: 40 }} dpr={[1, 1.45]}>
        <ambientLight intensity={2.7} />
        <directionalLight
          position={[3, 4, 4]}
          intensity={4.2}
          color="#d8e5d3"
        />
        <directionalLight
          position={[-3, 1, 2]}
          intensity={2.4}
          color="#d49a68"
        />
        <Suspense fallback={null}>
          <LicensedScene />
        </Suspense>
      </Canvas>
    </div>
  );
}
