import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import * as THREE from 'three';

const vertexShader = `
  varying vec2 vUv;

  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const fragmentShader = `
  precision highp float;

  varying vec2 vUv;
  uniform float uTime;
  uniform vec2 uResolution;
  uniform float uIntensity;
  uniform float uMotion;

  float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
  }

  float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(
      mix(hash(i + vec2(0.0, 0.0)), hash(i + vec2(1.0, 0.0)), u.x),
      mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
      u.y
    );
  }

  float directionalWave(vec2 p, vec2 direction, float frequency, float speed, float phase, float strength) {
    return sin(dot(p, normalize(direction)) * frequency + phase + uTime * speed) * strength;
  }

  void main() {
    vec2 uv = vUv;
    vec2 aspect = vec2(uResolution.x / max(uResolution.y, 1.0), 1.0);
    vec2 p = (uv - 0.5) * aspect * 2.0;

    float t = uTime * uMotion;
    float n1 = noise(p * 1.7 + vec2(t * 0.018, -t * 0.014));
    float n2 = noise(p * 3.4 + vec2(-t * 0.026, t * 0.018));
    vec2 warp = vec2(n1 - 0.5, n2 - 0.5) * 0.34;
    vec2 q = p + warp;

    float ocean =
      directionalWave(q, vec2(0.94, 0.34), 7.2, 0.34, 0.4, 0.42) +
      directionalWave(q, vec2(-0.45, 0.89), 11.6, -0.22, 1.8, 0.28) +
      directionalWave(q, vec2(0.18, 0.98), 17.5, 0.18, 4.1, 0.18) +
      directionalWave(q, vec2(-0.86, 0.51), 23.0, -0.13, 2.7, 0.12);

    float foam = smoothstep(0.48, 0.86, ocean + n2 * 0.34);
    float trough = smoothstep(0.62, 0.05, ocean - n1 * 0.18);
    float diagonal = smoothstep(0.88, 1.0, sin(dot(q, normalize(vec2(0.78, 0.42))) * 28.0 + t * 0.38) * 0.5 + 0.5);

    float vignette = smoothstep(1.42, 0.18, length((uv - 0.5) * vec2(1.08, 0.92)));

    vec3 green = vec3(0.439, 0.557, 0.435);
    vec3 ink = vec3(0.071, 0.071, 0.071);
    vec3 color = mix(ink, green, 0.76);

    float alpha = (foam * 0.082 + trough * 0.025 + diagonal * 0.035) * vignette * uIntensity;
    alpha *= smoothstep(0.0, 0.12, uv.y) * smoothstep(1.0, 0.84, uv.y);
    alpha = clamp(alpha, 0.0, 0.118);

    gl_FragColor = vec4(color, alpha);
  }
`;

function useReducedMotion() {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setReduced(media.matches);
    sync();
    media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);

  return reduced;
}

function WaterPlane({ reducedMotion }: { reducedMotion: boolean }) {
  const materialRef = useRef<THREE.ShaderMaterial>(null);
  const [resolution, setResolution] = useState(() => new THREE.Vector2(1, 1));

  useEffect(() => {
    const syncResolution = () => {
      setResolution(new THREE.Vector2(window.innerWidth, window.innerHeight));
    };
    syncResolution();
    window.addEventListener('resize', syncResolution);
    return () => window.removeEventListener('resize', syncResolution);
  }, []);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uResolution: { value: resolution },
      uIntensity: { value: 1 },
      uMotion: { value: reducedMotion ? 0 : 1 },
    }),
    []
  );

  useEffect(() => {
    uniforms.uResolution.value.copy(resolution);
  }, [resolution, uniforms]);

  useEffect(() => {
    uniforms.uMotion.value = reducedMotion ? 0 : 1;
    uniforms.uIntensity.value = reducedMotion ? 0.55 : 1;
  }, [reducedMotion, uniforms]);

  useFrame(({ clock }) => {
    if (!materialRef.current || reducedMotion) return;
    materialRef.current.uniforms.uTime.value = clock.elapsedTime;
  });

  return (
    <mesh frustumCulled={false}>
      <planeGeometry args={[2, 2, 1, 1]} />
      <shaderMaterial
        ref={materialRef}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        depthTest={false}
        blending={THREE.NormalBlending}
      />
    </mesh>
  );
}

export default function WaterBackground() {
  const reducedMotion = useReducedMotion();
  const [dpr, setDpr] = useState(1);

  useEffect(() => {
    const isMobile = window.innerWidth < 768;
    setDpr(isMobile ? 0.8 : Math.min(window.devicePixelRatio || 1, 1.25));
  }, []);

  return (
    <div className="fixed inset-0 pointer-events-none z-0" aria-hidden="true">
      <Canvas
        orthographic
        camera={{ position: [0, 0, 1], zoom: 1 }}
        dpr={dpr}
        frameloop={reducedMotion ? 'demand' : 'always'}
        gl={{
          alpha: true,
          antialias: false,
          powerPreference: 'low-power',
          depth: false,
          stencil: false,
        }}
      >
        <WaterPlane reducedMotion={reducedMotion} />
      </Canvas>
    </div>
  );
}
