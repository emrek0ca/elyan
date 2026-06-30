'use client';

import { useEffect, useRef } from 'react';
import { motion, useScroll, useTransform } from 'motion/react';

interface QuantumFieldProps {
  className?: string;
  density?: number; // Size of grid cell
}

export function QuantumField({ className = '', density = 30 }: QuantumFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const { scrollYProgress } = useScroll({
    target: containerRef,
    offset: ['start end', 'end start'],
  });
  
  const yParallax = useTransform(scrollYProgress, [0, 1], [50, -50]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let mouse = { x: -1000, y: -1000 };
    let targetMouse = { x: -1000, y: -1000 }; // For smooth interpolation
    let cols = 0;
    let rows = 0;

    const resize = () => {
      if (canvas.parentElement) {
        // High DPI canvas support
        const dpr = window.devicePixelRatio || 1;
        const rect = canvas.parentElement.getBoundingClientRect();
        
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        
        ctx.scale(dpr, dpr);
        canvas.style.width = `${rect.width}px`;
        canvas.style.height = `${rect.height}px`;

        cols = Math.floor(rect.width / density) + 1;
        rows = Math.floor(rect.height / density) + 1;
      }
    };

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const width = rect.width;
      const height = rect.height;

      ctx.clearRect(0, 0, width, height);
      
      const isDark = document.documentElement.classList.contains('theme-dark');
      const strokeColor = isDark ? 'rgba(255, 255, 255, 0.15)' : 'rgba(47, 62, 50, 0.15)';
      const activeColor = isDark ? 'rgba(196, 216, 199, 0.8)' : 'rgba(47, 62, 50, 0.8)';

      // Interpolate mouse for smooth tracking
      mouse.x += (targetMouse.x - mouse.x) * 0.1;
      mouse.y += (targetMouse.y - mouse.y) * 0.1;

      for (let i = 0; i < cols; i++) {
        for (let j = 0; j < rows; j++) {
          const x = i * density;
          const y = j * density;
          
          const dx = mouse.x - x;
          const dy = mouse.y - y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          
          // Calculate angle pointing to mouse
          const angle = Math.atan2(dy, dx);
          
          // Size and opacity change based on distance
          const maxDist = 300;
          const intensity = Math.max(0, 1 - dist / maxDist);
          
          const lineLength = 8 + (intensity * 12); // Lines grow as mouse gets closer

          ctx.save();
          ctx.translate(x, y);
          
          // If mouse is near, rotate towards it, otherwise default rotation
          if (dist < maxDist) {
            ctx.rotate(angle);
            ctx.strokeStyle = `rgba(
              ${isDark ? '196, 216, 199' : '47, 62, 50'}, 
              ${0.15 + (intensity * 0.65)}
            )`;
          } else {
            // Default ambient rotation (slight diagonal)
            ctx.rotate(Math.PI / 4);
            ctx.strokeStyle = strokeColor;
          }

          ctx.lineWidth = 1.5;
          ctx.beginPath();
          ctx.moveTo(-lineLength / 2, 0);
          ctx.lineTo(lineLength / 2, 0);
          ctx.stroke();
          ctx.restore();
        }
      }

      animationFrameId = requestAnimationFrame(draw);
    };

    window.addEventListener('resize', resize);
    
    const handleMouseMove = (e: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      targetMouse.x = e.clientX - rect.left;
      targetMouse.y = e.clientY - rect.top;
    };
    
    const handleMouseLeave = () => {
      targetMouse.x = -1000;
      targetMouse.y = -1000;
    };

    canvas.addEventListener('mousemove', handleMouseMove);
    canvas.addEventListener('mouseleave', handleMouseLeave);

    resize();
    draw();

    return () => {
      window.removeEventListener('resize', resize);
      canvas.removeEventListener('mousemove', handleMouseMove);
      canvas.removeEventListener('mouseleave', handleMouseLeave);
      cancelAnimationFrame(animationFrameId);
    };
  }, [density]);

  return (
    <div ref={containerRef} className={`relative overflow-hidden w-full h-full bg-[var(--surface-1)] border border-[var(--outline)] shadow-[var(--shadow-soft)] rounded-[var(--radius-lg)] ${className}`}>
      <motion.div style={{ y: yParallax }} className="absolute inset-0 w-full h-[120%] -top-[10%]">
        <canvas 
          ref={canvasRef} 
          className="absolute inset-0 block cursor-crosshair mix-blend-multiply dark:mix-blend-screen"
        />
      </motion.div>
      <div className="absolute inset-0 pointer-events-none flex flex-col items-center justify-center p-8 text-center z-10 bg-gradient-to-t from-[var(--surface-1)] via-transparent to-transparent">
         {/* We can put slot content here if needed, or leave it purely decorative */}
      </div>
    </div>
  );
}
