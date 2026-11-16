# Topology Patches

A Blender add-on that replaces faces of a mesh with another mesh (the *patch*). The patch is stretched so that its open border lands exactly on existing vertices of the target, and everything is welded together, so the result stays one clean, closed mesh.

It is made for kitbashing details such as holes, vents and panels into a surface without booleans and without breaking the edge flow.

Requires Blender 4.2 or newer.

## Install

1. Download or clone this repository.
2. Zip the **contents** of the `topology_patches` folder, so that `__init__.py` and `blender_manifest.toml` sit at the top level of the zip.
3. In Blender: **Edit > Preferences > Get Extensions > ▾ (top right) > Install from Disk…** and pick that zip.

The zip GitHub offers for the whole repository cannot be installed directly, because the add-on files are one folder down.

## Quick start

1. In Object Mode, select the mesh (or meshes) you want to stamp onto, then select the patch **last** so it is the active object. If only the patch is selected, every visible mesh is a target.
2. Run **Object > Topology Patches**, or use the button in the sidebar (`N`) under the **Patches** tab.
3. Hover the target. The faces that will be replaced are highlighted and the stretched patch is previewed. Click to stamp; the tool keeps running so you can stamp again.

| Key | Action |
| --- | --- |
| Left mouse | Stamp |
| ← / → or Ctrl + wheel | Rotate the patch |
| ↑ / ↓ | Depth multiplier |
| C | Curve onto the original surface on/off |
| R | Keep rigid shapes on/off |
| Ctrl + Z | Undo the last stamp while the tool is running |
| Esc / right mouse / Enter | Finish |

Navigation (orbit, pan, zoom, numpad views) works while the tool is running.

After finishing, one Ctrl + Z in Blender takes back every stamp of that run. The **Adjust Last Operation** panel (bottom left of the viewport, or `F9`) lets you change the rotation, depth, curve and rigid setting of the last stamp. Rotating there never moves the stamp to other faces.

## Making a patch

A patch is any mesh with exactly **one open border loop**. The shape of that border decides what it replaces:

| Border | Replaces |
| --- | --- |
| 4 corners, same number of edges on opposite sides (A and B) | An A × B block of quads. A plain square replaces one face, 2 edges per side replaces 2 × 2 faces, and so on. Every border vertex welds to an existing vertex. |
| Round (more than 4 corners, even number N of vertices) | An A × B block of quads with 2 × (A + B) = N. 8 vertices take a 2 × 2 block, 16 take 4 × 4. Rotation moves one border vertex at a time. |
| Anything else (triangle, pentagon, uneven sides, concave…) | One face with the same number of corners. Extra border vertices split the edges of that face. |

A round patch hovered over a face that has exactly N corners replaces that single face instead.

The block under the cursor must be regular quads; the preview turns red and says why when the patch does not fit.

## Options

### Curve (`C`)

- **On:** every patch vertex is laid onto the original surface of the block it replaces, and depth is pushed along the interpolated vertex normals, so the patch bends with the mesh.
- **Off:** only the border follows the mesh; the inside is a smooth membrane stretched between the border vertices, with a single depth direction.

### Keep Rigid Shapes (`R`)

Stretching a patch to fit distorts it: a circle becomes an oval when the block is not a flat square. Paint a vertex group named `rigid` on the **patch** over the vertices that must keep their proportions. Each connected island of that group is moved, rotated and uniformly scaled as one piece, never sheared or bent. Weights between 0 and 1 blend between rigid and stretched. Border vertices always weld to the target and ignore the group.

### Shrinkwrap to Original

Paint a vertex group named `base` on the **patch** over the vertices that must stay on the target's surface. With the option on, the first stamp on a target:

- hides a copy of the target named `<name>_patch_ref`,
- adds a Shrinkwrap modifier onto that copy, placed before the first Subdivision modifier,
- limits it to the `base` group, which the target's own vertices join.

Stamped vertices inherit the patch's `base` weights, so everything outside the group keeps the patch's shape. Vertices kept rigid are left out of the group.

Both group names can be changed in the sidebar panel.

### UVs

| Setting | Result |
| --- | --- |
| Auto | Patch faces that have their own material keep the patch's UVs; all other faces continue the UVs of the target. |
| Patch | Always copy the patch's UVs. |
| Target | Always continue the UVs of the faces that are replaced. |

## What a stamp carries over

- **Materials:** a patch face with a material keeps it, and the material is added to the target if needed. Faces without one take the material of the face they replace.
- **Edges:** sharp, seam, crease and bevel weight of the patch's inner edges, plus vertex creases. Border edges keep what the target had.
- **Shading:** smooth/flat of the patch faces, unless the whole patch is flat; then the faces are shaded like the face they replace.

## Preferences

**Edit > Preferences > Add-ons > Topology Patches** sets the preview colours (patch edges, target outline and fill, rotation marker, "cannot stamp") and the two line widths.

## Limitations

- Object Mode only.
- Blocks larger than one face need regular quads; triangles, n-gons and poles inside the block are rejected.
- A patch cannot be scaled over more faces than its border has edges.
- A round border with an odd number of vertices only fits a face with that many corners.
- No default keyboard shortcut is assigned; right-click the menu entry to add one.

## License

GPL-3.0-or-later.
