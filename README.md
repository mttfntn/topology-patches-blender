# Topology Patches

[![Blender](https://img.shields.io/badge/dynamic/toml?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmttfntn%2Ftopology-patches-blender%2Fmain%2Ftopology_patches%2Fblender_manifest.toml&query=%24.blender_version_min&label=Blender&color=E87D0D&logo=blender&logoColor=white)](https://www.blender.org/download/)
[![Release](https://img.shields.io/github/v/release/mttfntn/topology-patches-blender)](https://github.com/mttfntn/topology-patches-blender/releases/latest)
[![Download size](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fmttfntn%2Ftopology-patches-blender%2Fmain%2F.github%2Frelease-size.json)](https://github.com/mttfntn/topology-patches-blender/releases/latest)
[![tests](https://github.com/mttfntn/topology-patches-blender/actions/workflows/tests.yml/badge.svg)](https://github.com/mttfntn/topology-patches-blender/actions/workflows/tests.yml)
[![License](https://img.shields.io/github/license/mttfntn/topology-patches-blender)](LICENSE)
[![Language](https://img.shields.io/github/languages/top/mttfntn/topology-patches-blender)](topology_patches/__init__.py)

A Blender add-on that replaces faces of a mesh with another mesh, the **patch**. The patch is stretched so that its open border lands exactly on existing vertices of the target, and everything is welded together, so the result stays one clean, closed mesh.

It is made for kitbashing details such as holes, vents and panels into a surface without booleans and without breaking the edge flow.

- **Version:** 1.5.0
- **Blender:** 5.3 (the only supported and tested version)
- **Location:** Object Mode › **Object › Topology Patches**, or 3D Viewport › Sidebar (N) › **Patches** tab
- **License:** GPL-3.0-or-later ([LICENSE](LICENSE))

Found a bug or have an idea? [Open an issue](https://github.com/mttfntn/topology-patches-blender/issues/new/choose). Want to change the code? See [CONTRIBUTING.md](CONTRIBUTING.md), [HANDOVER.md](HANDOVER.md) (people) and [AGENTS.md](AGENTS.md) (AI assistants).

---

## Contents

1. [Installation](#installation)
2. [Quick start](#quick-start)
3. [Making a patch](#making-a-patch)
4. [The tool](#the-tool)
5. [Options](#options)
6. [What a stamp carries over](#what-a-stamp-carries-over)
7. [What the add-on creates in your scene](#what-the-add-on-creates-in-your-scene)
8. [Preferences](#preferences)
9. [Troubleshooting](#troubleshooting)
10. [Known limitations](#known-limitations)
11. [Contributing](#contributing)
12. [Version history](#version-history)

---

## Installation

1. Download **`topology_patches-X.Y.Z.zip`** from the [Releases](https://github.com/mttfntn/topology-patches-blender/releases) page.
2. In Blender, open **Edit › Preferences › Get Extensions**.
3. Click the **⌄** menu at the top right and choose **Install from Disk…**
4. Select the zip. The add-on is enabled straight away.

You can also drag the zip into the Blender window. The package only installs on Blender 5.3.

**Updating:** install the new zip the same way. It replaces the old version and keeps your preferences.

> GitHub's green **Code › Download ZIP** button gives the source of the whole repository, which Blender can't install. Use the zip from the Releases page.

---

## Quick start

1. In Object Mode, select the mesh you want to stamp onto (the **target**), then **Shift-click the patch** so it is the **active** object.
2. Run **Object › Topology Patches**, or click **Topology Patches** in the sidebar's **Patches** tab.
3. Hover the target. The faces that will be replaced are highlighted and the stretched patch is previewed.
4. **Left click** to stamp. The tool keeps running, so you can stamp again. **Esc** finishes.

If only the patch is selected, every visible mesh is a target.

---

## Making a patch

A patch is any mesh with exactly **one open border loop**. Model it flat, with the border at the height of the surface and the detail below it (a hole) or above it (a boss). The shape of the border decides what it replaces:

| Border | Replaces |
|---|---|
| **4 corners**, the same number of edges on opposite sides (A and B) | An **A × B block of quads**. A plain square replaces one face, 2 edges per side replace 2 × 2 faces, and so on. Every border vertex welds to an existing vertex. |
| **Round** (more than 4 corners, an even number N of vertices) | An A × B block of quads with 2 × (A + B) = N: 8 vertices take a 2 × 2 block, 16 take 4 × 4. On a face that has exactly N corners it replaces that single face instead. |
| **Anything else** (triangle, pentagon, uneven sides, concave…) | **One face** with the same number of corners. Extra border vertices split the edges of that face. |

The block under the cursor must be regular quads. When the patch doesn't fit, the preview turns red and the header says why.

---

## The tool

| Input | Action |
|---|---|
| **Left click** | Stamp |
| **← / →** or **Ctrl + Wheel** | Rotate the patch: 90° for a square block, one border vertex for a round patch |
| **↑ / ↓** | Depth multiplier |
| **C** | Curve onto the original surface on/off |
| **R** | Keep rigid shapes on/off |
| **Ctrl + Z** | Undo the last stamp while the tool is running |
| **Esc** / **Right click** / **Enter** | Finish |
| **Middle mouse**, wheel, numpad | Navigate the view while the tool runs |

**What you see:** the faces to replace in orange (red when the patch doesn't fit), the edges of the stretched patch in blue, and a pink marker on the first side of the patch border, so you can see its rotation.

**After finishing:** one **Ctrl + Z** in Blender takes back every stamp of that run. The **Adjust Last Operation** panel (bottom left of the viewport, or **F9**) changes the **Rotation**, **Depth**, **Curve** and **Keep Rigid Shapes** of the last stamp. Rotating there never moves the stamp to other faces; a block that isn't square turns by half turns.

---

## Options

All options are in the sidebar's **Patches** tab and are stored per scene.

### Curve (C)

- **On:** every patch vertex is laid onto the original surface of the block it replaces, and its depth is pushed along the interpolated vertex normals, so the patch bends with the mesh.
- **Off:** only the border follows the mesh. The inside is a smooth membrane stretched between the border vertices, with a single depth direction.

### Keep Rigid Shapes (R)

Stretching a patch to fit distorts it: a circle becomes an oval when the block isn't a flat square. Paint a vertex group named **`rigid`** on the **patch** over the vertices that must keep their proportions. Each connected island of that group is moved, rotated and uniformly scaled as one piece, never sheared or bent. Weights between 0 and 1 blend between rigid and stretched, for a smooth transition. Border vertices always weld to the target and ignore the group.

### Shrinkwrap to Original

Paint a vertex group named **`base`** on the **patch** over the vertices that must stay on the target's surface. With the option on, the first stamp on a target:

- hides a copy of the target named `<name>_patch_ref`,
- adds a **Patch Shrinkwrap** modifier onto that copy, placed before the first Subdivision modifier,
- limits it to the `base` group, which the target's own vertices join.

Stamped vertices inherit the patch's `base` weights, so everything outside the group keeps the patch's shape. Vertices kept rigid are left out of the group.

### UVs

| Setting | Result |
|---|---|
| **Auto** | Patch faces that have their own material keep the patch's UVs; all other faces continue the UVs of the target. |
| **Patch** | Always copy the patch's UVs. |
| **Target** | Always continue the UVs of the faces that are replaced. |

The names of both vertex groups can be changed in the panel.

---

## What a stamp carries over

- **Materials:** a patch face with a material keeps it, and the material is added to the target if needed. Faces without one take the material of the face they replace.
- **Edges:** sharp, seam, crease and bevel weight of the patch's inner edges, plus vertex creases. The border edges keep what the target had.
- **Shading:** smooth or flat, from the patch faces. If the whole patch is flat, the faces are shaded like the face they replace.

---

## What the add-on creates in your scene

Only with **Shrinkwrap to Original**:

| Name | What it is |
|---|---|
| `<Target>_patch_ref` | A hidden copy of the target as it was before the first stamp. Hidden in the viewport and in renders. |
| **Patch Shrinkwrap** | A Shrinkwrap modifier on the target, onto that copy, limited to the `base` group. |
| `base` | A vertex group on the target (the name is the one set in the panel). |

Setups made by versions before 1.4 (a **Sticker Shrinkwrap** modifier and `<Target>_sticker_ref`) are recognised and reused.

Undoing the first stamp inside the tool removes the copy, the modifier and the group again, if that run created them.

---

## Preferences

**Edit › Preferences › Add-ons › Topology Patches** sets the preview colours (patch edges, target outline and fill, rotation marker, "cannot stamp") and the two line widths.

---

## Troubleshooting

| You see | Why / what to do |
|---|---|
| **The preview is red: "the patch needs quads only"** | The block under the cursor has a triangle or an n-gon, often near a pole. Move to an area of regular quads. |
| **"the faces here do not form a regular A x B grid"** | A pole (a vertex with 3 or 5+ edges) is inside the block. Move the cursor or use a smaller patch. |
| **"face has 4 corners, patch border has 5"** | The patch border isn't a grid or round border, so it needs a single face with the same number of corners. |
| **"The patch must have exactly one open border loop"** | The patch is closed, or has holes. Delete faces until exactly one border is left. |
| **The circle in my patch becomes an oval** | Add a `rigid` vertex group over it and turn **Keep Rigid Shapes** on. |
| **Shrinkwrap pulls my detail back to the surface** | Only vertices in `base` should touch the surface: remove the detail's vertices from `base`. |
| **Nothing happens on a click** | The cursor must be over a target mesh: a selected mesh other than the patch, or any visible mesh if only the patch is selected. |

---

## Known limitations

- **Object Mode only.**
- **Blocks larger than one face need regular quads.** Triangles, n-gons and poles inside the block are refused.
- A patch replaces as many faces as its border has edges; it can't be scaled over a bigger block.
- A round border with an odd number of vertices only fits a face with that many corners.
- **Adjust Last Operation** changes only the last stamp of a run.
- No keyboard shortcut is assigned by default: right-click the menu entry and choose **Assign Shortcut**.

---

## Contributing

Bug reports and ideas are welcome as [issues](https://github.com/mttfntn/topology-patches-blender/issues/new/choose). To change the code, read [CONTRIBUTING.md](CONTRIBUTING.md); [HANDOVER.md](HANDOVER.md) explains how the add-on is organised. Security problems: please report them privately, see [SECURITY.md](SECURITY.md).

---

## Version history

| Version | Changes |
|---|---|
| 1.5 | Blender 5.3 only. GPL-3.0 license in the package, test suite and CI, releases built by CI. The preview reports its first error instead of hiding it. No change in what the tool produces |
| 1.4.1 | Fix: changing Rotation in Adjust Last Operation could stamp onto other faces (objects had no updated world matrix right after Blender's undo) |
| 1.4 | Renamed to Topology Patches. Rotation in Adjust Last Operation turns the stamp in place |
| 1.3 | Adjust Last Operation: rotation, depth, curve and rigid of the last stamp |
| 1.2 | Materials, UVs, sharp edges, seams, creases and shading carried over; shrinkwrap before Subdivision, undone with the first stamp, rigid vertices left out; preview colours in the preferences; packaged as a Blender extension |
| 1.1 | Round borders on quad blocks, `rigid` group, Shrinkwrap to Original, concave borders, Ctrl+Z inside the tool |
| 1.0 | First version: A × B and single-face patches, curve, hover preview, rotation |
