import os
import shutil
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("delivery_engine")

class DeliveryEngine:
    def __init__(self):
        self.workspace = Path.home() / ".elyan" / "projects" / "delivery"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.templates_dir = Path(__file__).parent / "templates"

    async def create_project(self, name: str, template_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a high-fidelity project from a template"""
        project_path = self.workspace / name
        project_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Creating project '{name}' using template '{template_type}'")
        
        if template_type == "gsap_landing":
            return await self._generate_gsap_landing(project_path, data)
        elif template_type == "threejs_showcase":
            return await self._generate_threejs_showcase(project_path, data)
        else:
            return {"success": False, "error": f"Template {template_type} not found"}

    async def _generate_gsap_landing(self, path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        index_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{data.get('title', 'Elyan Project')}</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/ScrollTrigger.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background: #000; color: #fff; overflow-x: hidden; }}
        .hero-text {{ opacity: 0; transform: translateY(50px); }}
    </style>
</head>
<body>
    <section class="h-screen flex items-center justify-center">
        <h1 class="hero-text text-6xl font-bold tracking-tighter">{data.get('hero_title', 'Future is here')}</h1>
    </section>
    <section class="h-screen bg-white text-black p-20">
        <h2 class="text-4xl reveal">Elyan Delivery Engine</h2>
        <p class="mt-4 text-xl">{data.get('description', 'High performance autonomous delivery.')}</p>
    </section>

    <script>
        gsap.registerPlugin(ScrollTrigger);
        gsap.to(".hero-text", {{ opacity: 1, y: 0, duration: 1.5, ease: "expo.out" }});
        
        gsap.from(".reveal", {{
            scrollTrigger: ".reveal",
            opacity: 0,
            x: -100,
            duration: 1
        }});
    </script>
</body>
</html>"""
        (path / "index.html").write_text(index_html)
        return {"success": True, "url": f"file://{path}/index.html", "path": str(path)}

    async def _generate_threejs_showcase(self, path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
        # Minimal Three.js Template
        index_html = """<!DOCTYPE html>
<html>
<head><title>3D Showcase</title><style>body { margin: 0; background: #000; }</style></head>
<body>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/0.158.0/three.min.js"></script>
    <script>
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(window.innerWidth, window.innerHeight);
        document.body.appendChild(renderer.domElement);

        const geometry = new THREE.IcosahedronGeometry(1, 1);
        const material = new THREE.MeshNormalMaterial({ wireframe: true });
        const sphere = new THREE.Mesh(geometry, material);
        scene.add(sphere);

        camera.position.z = 5;
        function animate() {
            requestAnimationFrame(animate);
            sphere.rotation.x += 0.01;
            sphere.rotation.y += 0.01;
            renderer.render(scene, camera);
        }
        animate();
    </script>
</body>
</html>"""
        (path / "index.html").write_text(index_html)
        return {"success": True, "url": f"file://{path}/index.html", "path": str(path)}

# Global instance
delivery_engine = DeliveryEngine()
