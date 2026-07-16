# Third-party 3D asset licenses

The files in this directory are unmodified, ready-made GLB models downloaded
from Poly Pizza on 2026-07-15. Each model page identifies the work as
**Public Domain (CC0)** in GLTF format. CC0 does not require attribution, but
the original creators and source pages are recorded here for provenance.

License text: [Creative Commons CC0 1.0 Universal](https://creativecommons.org/publicdomain/zero/1.0/)

| Local file | Work and creator | Source page | Direct download | SHA-256 |
| --- | --- | --- | --- | --- |
| `smartphone.glb` | Smartphone by smallbigsquare | https://poly.pizza/m/4DRZmTs3jq | https://static.poly.pizza/68a8586b-e540-431c-b42e-e3c6bc691e11.glb | `868e2d7b191defae7b7c8e2908d3cd41d1c7be1a940945737010590e89b35e90` |
| `laptop.glb` | Laptop by Kenney | https://poly.pizza/m/GnbwSUiVty | https://static.poly.pizza/8190e659-7079-442f-9ed9-083f67b1746b.glb | `387328b3c6530213770fb579545fa8cc27cc4ee6cf710f3f01bb28873da99b5e` |
| `globe.glb` | Globe by CreativeTrio | https://poly.pizza/m/Y4Dof9b2p5 | https://static.poly.pizza/002557d4-03f3-4201-a86c-f66e0af82182.glb | `68c54e28d592469c748db4f3b8c2c4bbbbd2e24cce18892918da5f89d7d43e71` |
| `antenna.glb` | Antenna by Quaternius | https://poly.pizza/m/OuHQCigiUR | https://static.poly.pizza/08f832ca-e268-4834-9711-d03986f042e8.glb | `8229cfaaa2475fdd429c87f861bd094249747f92a0d17e9f8eac97ace47c659d` |

## Intended website usage

- `laptop.glb`: desktop/local-runtime section; restrained hinge-open view with a
  slow camera orbit or scroll-linked turn.
- `smartphone.glb`: mobile handoff and App Store section; transition from the
  laptop to the phone by camera movement, not by reshaping either model.
- `globe.glb`: backend/control-plane or connected-ecosystem transition; keep it
  large and partially cropped so the supplied model reads as a spatial scene.
- `antenna.glb`: pairing/realtime connectivity section; position near the globe
  and animate only model rotation or camera parallax.

These models should remain visually authored by their original creators. Site
motion may transform the supplied GLB objects or camera, but should not add
procedurally drawn replacement geometry.
