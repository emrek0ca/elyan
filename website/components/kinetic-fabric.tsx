'use client';

import { useEffect, useRef } from 'react';

interface KineticFabricProps {
  className?: string;
}

class Point {
  x: number;
  y: number;
  baseX: number;
  baseY: number;
  vx: number = 0;
  vy: number = 0;

  constructor(x: number, y: number) {
    this.x = x;
    this.y = y;
    this.baseX = x;
    this.baseY = y;
  }

  update(mouse: { x: number; y: number; isActive: boolean }, config: any) {
    if (mouse.isActive) {
      const dx = mouse.x - this.x;
      const dy = mouse.y - this.y;
      const dist = Math.sqrt(dx * dx + dy * dy);

      // Push points away if cursor is near
      if (dist < config.interactionRadius) {
        const force = (config.interactionRadius - dist) / config.interactionRadius;
        this.vx -= (dx / dist) * force * config.repelStrength;
        this.vy -= (dy / dist) * force * config.repelStrength;
      }
    }

    // Spring logic (pulling back to original position)
    this.vx += (this.baseX - this.x) * config.springStiffness;
    this.vy += (this.baseY - this.y) * config.springStiffness;

    // Friction / damping
    this.vx *= config.damping;
    this.vy *= config.damping;

    this.x += this.vx;
    this.y += this.vy;
  }
}

export function KineticFabric({ className = '' }: KineticFabricProps = {}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext('2d', { alpha: true });
    if (!ctx) return;

    // Physics configuration
    const config = {
      spacing: 40,
      interactionRadius: 150,
      repelStrength: 4.5,
      springStiffness: 0.03,
      damping: 0.88,
    };

    let points: Point[][] = [];
    let cols = 0;
    let rows = 0;
    let animationFrameId: number;
    let isDark = true;

    const mouse = { x: -1000, y: -1000, isActive: false };

    const initGrid = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = container.getBoundingClientRect();
      
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;

      isDark = document.documentElement.classList.contains('theme-dark');

      // Add extra row/col to ensure lines go off screen seamlessly
      cols = Math.ceil(rect.width / config.spacing) + 2;
      rows = Math.ceil(rect.height / config.spacing) + 2;

      points = [];
      for (let i = 0; i < cols; i++) {
        points[i] = [];
        for (let j = 0; j < rows; j++) {
          // Center the grid
          const offsetX = (rect.width - (cols - 1) * config.spacing) / 2;
          const offsetY = (rect.height - (rows - 1) * config.spacing) / 2;
          points[i][j] = new Point(i * config.spacing + offsetX, j * config.spacing + offsetY);
        }
      }
    };

    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      
      // Clear background to be transparent
      ctx.clearRect(0, 0, rect.width, rect.height);
      
      const baseColor = isDark ? 'rgba(255, 255, 255, 0.04)' : 'rgba(0, 0, 0, 0.06)';
      const activeRGB = isDark ? '255, 255, 255' : '0, 0, 0';

      // Update points
      for (let i = 0; i < cols; i++) {
        for (let j = 0; j < rows; j++) {
          points[i][j].update(mouse, config);
        }
      }

      ctx.lineWidth = 1;
      
      // Draw Grid Lines (Horizontal & Vertical in one pass per cell)
      for (let i = 0; i < cols; i++) {
        for (let j = 0; j < rows; j++) {
          const p = points[i][j];
          
          ctx.beginPath();
          let drawn = false;

          // Right connection
          if (i < cols - 1) {
            const right = points[i+1][j];
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(right.x, right.y);
            drawn = true;
          }
          // Bottom connection
          if (j < rows - 1) {
            const down = points[i][j+1];
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(down.x, down.y);
            drawn = true;
          }

          if (drawn) {
            // Calculate average stretch for this cell to apply dynamic glow
            const distFromBase = Math.sqrt(Math.pow(p.x - p.baseX, 2) + Math.pow(p.y - p.baseY, 2));
            if (distFromBase > 3) {
              const intensity = Math.min(1, (distFromBase - 3) / 20);
              ctx.strokeStyle = `rgba(${activeRGB}, ${0.04 + intensity * 0.4})`;
            } else {
              ctx.strokeStyle = baseColor;
            }
            ctx.stroke();
          }

          // Draw node points if stretched
          const distFromBase = Math.sqrt(Math.pow(p.x - p.baseX, 2) + Math.pow(p.y - p.baseY, 2));
          if (distFromBase > 5) {
             const intensity = Math.min(1, (distFromBase - 5) / 15);
             ctx.beginPath();
             ctx.arc(p.x, p.y, 1.5 + intensity * 1.5, 0, Math.PI * 2);
             ctx.fillStyle = `rgba(${activeRGB}, ${intensity * 0.9})`;
             ctx.fill();
          }
        }
      }

      animationFrameId = requestAnimationFrame(draw);
    };

    const updateMouse = (clientX: number, clientY: number, isActive: boolean) => {
      const rect = canvas.getBoundingClientRect();
      mouse.x = clientX - rect.left;
      mouse.y = clientY - rect.top;
      mouse.isActive = isActive;
    };

    const handlePointerMove = (e: PointerEvent) => {
      updateMouse(e.clientX, e.clientY, true);
    };
    
    const handlePointerLeave = () => {
      mouse.isActive = false;
    };

    // Initialize
    initGrid();
    draw();

    window.addEventListener('resize', initGrid);
    canvas.addEventListener('pointermove', handlePointerMove);
    canvas.addEventListener('pointerleave', handlePointerLeave);
    canvas.addEventListener('pointerdown', handlePointerMove); // Support tapping on mobile

    return () => {
      window.removeEventListener('resize', initGrid);
      canvas.removeEventListener('pointermove', handlePointerMove);
      canvas.removeEventListener('pointerleave', handlePointerLeave);
      canvas.removeEventListener('pointerdown', handlePointerMove);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div 
      ref={containerRef} 
      className={className || "relative w-full h-[450px] overflow-hidden flex flex-col group cursor-crosshair select-none"}
    >
      <canvas 
        ref={canvasRef} 
        className="absolute inset-0 block w-full h-full"
      />
    </div>
  );
}
