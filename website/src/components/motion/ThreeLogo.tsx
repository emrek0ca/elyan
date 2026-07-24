import React, { useRef, useEffect, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useTexture, Float } from '@react-three/drei';
import * as THREE from 'three';

interface LogoMeshProps {
  logoUrl: string;
}

function SceneContent({ logoUrl }: LogoMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const materialRef = useRef<THREE.MeshStandardMaterial>(null);
  const lightRef = useRef<THREE.PointLight>(null);
  const texture = useTexture(logoUrl);
  const mouse = useRef({ x: 0, y: 0 });
  const scrollY = useRef(0);
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 768);
    };
    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  const planeSize = isMobile ? 1.55 : 5.15;
  const meshY = isMobile ? 1.95 : 0; // Desktop is 0 (dead-center at 50vh)

  useEffect(() => {
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.magFilter = THREE.LinearFilter;
    texture.anisotropy = 16;
    
    const onMouseMove = (e: MouseEvent) => {
      mouse.current.x = (e.clientX / window.innerWidth) * 2 - 1;
      mouse.current.y = -(e.clientY / window.innerHeight) * 2 + 1;
    };
    
    const onScroll = () => {
      scrollY.current = window.scrollY;
    };

    window.addEventListener('mousemove', onMouseMove, { passive: true });
    window.addEventListener('scroll', onScroll, { passive: true });
    
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('scroll', onScroll);
    };
  }, [texture]);

  useFrame(() => {
    if (meshRef.current) {
      // Reduced subtle tilt animation
      const targetRotationX = mouse.current.y * 0.03;
      const targetRotationY = mouse.current.x * 0.03 + (scrollY.current * 0.0001);
      
      meshRef.current.rotation.x += (targetRotationX - meshRef.current.rotation.x) * 0.05;
      meshRef.current.rotation.y += (targetRotationY - meshRef.current.rotation.y) * 0.05;
    }

    if (materialRef.current) {
      // Mobile and desktop both start crisp, then fade as the page scrolls.
      const startOpacity = isMobile ? 0.72 : 0.58;
      const scrollProgress = Math.min(1, Math.max(0, scrollY.current / 400));
      const targetOpacity = startOpacity - (scrollProgress * (startOpacity - 0.05));
      materialRef.current.opacity += (targetOpacity - materialRef.current.opacity) * 0.1;
    }

    if (lightRef.current) {
      // Light follows the mouse
      const targetLightX = mouse.current.x * 5;
      const targetLightY = mouse.current.y * 5;
      
      lightRef.current.position.x += (targetLightX - lightRef.current.position.x) * 0.1;
      lightRef.current.position.y += (targetLightY - lightRef.current.position.y) * 0.1;
    }
  });

  return (
    <>
      <ambientLight intensity={0.2} />
      <pointLight 
        ref={lightRef}
        position={[0, 0, 2]} 
        intensity={2.5} 
        distance={10}
        color="#ffffff"
      />
      <Float
        speed={1.2} 
        rotationIntensity={0.03} 
        floatIntensity={0.2}
        floatingRange={[-0.05, 0.05]}
      >
        <mesh ref={meshRef} position={[0, meshY, 0]}>
          <planeGeometry args={[planeSize, planeSize]} />
          <meshStandardMaterial 
            ref={materialRef}
            map={texture} 
            transparent 
            opacity={0.65} 
            color="#18181b" 
            side={THREE.DoubleSide} 
            depthWrite={false}
            roughness={0.4}
            metalness={0.6}
          />
        </mesh>
      </Float>
    </>
  );
}

export default function ThreeLogo({ logoUrl }: { logoUrl: string }) {
  return (
    <div 
      className="fixed top-0 left-0 w-full md:w-1/2 h-screen pointer-events-none z-[1] flex items-start justify-center pt-10 md:items-center md:justify-start md:pt-0 md:-ml-8" 
      aria-hidden="true"
    >
      <Canvas 
        camera={{ position: [0, 0, 8], fov: 45 }}
        gl={{ alpha: true, antialias: true }}
      >
        <React.Suspense fallback={null}>
          <SceneContent logoUrl={logoUrl} />
        </React.Suspense>
      </Canvas>
    </div>
  );
}
