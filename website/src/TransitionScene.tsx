import { Suspense, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF } from "@react-three/drei";
import type { Group } from "three";

function ReadyMadeModels() {
  const group = useRef<Group>(null);
  const globe = useGLTF("/assets/3d/globe.glb");
  const antenna = useGLTF("/assets/3d/antenna.glb");
  useFrame((state) => {
    if (
      !group.current ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    group.current.rotation.y = state.clock.elapsedTime * 0.08;
  });
  return (
    <group ref={group} rotation={[0.08, -0.3, 0]}>
      <primitive
        object={globe.scene.clone()}
        position={[0, 0, 0]}
        scale={8.5}
      />
      <primitive
        object={antenna.scene.clone()}
        position={[1.7, -0.75, 0.4]}
        scale={0.8}
      />
    </group>
  );
}

useGLTF.preload("/assets/3d/globe.glb");
useGLTF.preload("/assets/3d/antenna.glb");

export default function TransitionScene() {
  return (
    <div
      className="transition-scene"
      aria-label="CC0 lisanslı küre ve bağlantı anteni 3B sahnesi"
    >
      <Canvas camera={{ position: [0, 0.2, 6], fov: 38 }} dpr={[1, 1.35]}>
        <ambientLight intensity={3.1} />
        <directionalLight position={[3, 4, 4]} intensity={4} color="#f2e7d3" />
        <directionalLight position={[-2, 1, 3]} intensity={2} color="#6f8b6d" />
        <Suspense fallback={null}>
          <ReadyMadeModels />
        </Suspense>
      </Canvas>
    </div>
  );
}
