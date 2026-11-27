# Topology Patches: handover

Everything a new maintainer needs. The user guide is the [README](README.md); a compact version of this file for AI assistants is [AGENTS.md](AGENTS.md).

## What the project is

A Blender add-on (packaged as a Blender **extension**) that replaces faces of a mesh with another mesh, the *patch*. The patch is stretched so its open border lands on existing vertices of the target, and the two are welded into one closed mesh. It is a modal tool: you hover the target, see a preview, and click to stamp.

- **Author:** Matteo Fontana. Not a fork: there is no upstream project.
- **License:** GPL-3.0-or-later (`LICENSE`, also shipped in the package).
- **Supported:** Blender **5.3.x only** (`blender_version_min = "5.3.0"`, `blender_version_max = "5.4.0"`, exclusive).
- **Repository:** <https://github.com/mttfntn/topology-patches-blender> (public), branch `main`.
- **Earlier working name:** "Topology Sticker" (before 1.4). As an extension, 1.2 and 1.3 had the id `topology_sticker`; 1.4 changed it to `topology_patches`, which Blender treats as a different extension (an old install has to be removed by hand). The internal code was renamed from "sticker" to "patch" in 1.5.

## What you need

- **Blender 5.3** to run the add-on and the tests. On Windows the test runner finds `C:\Program Files\Blender Foundation\Blender 5.3*\blender.exe`; elsewhere pass `--blender PATH` or set `$BLENDER`.
- **Python 3.9+** to start the test runner (`tests/run.py`) and to compare snapshots. Both use only the standard library.
- Nothing else: the add-on has no dependencies outside Blender.

## How the code is organised

| Path | What it is |
|---|---|
| `topology_patches/__init__.py` | The whole add-on, one module (~1800 lines), in sections; see below |
| `topology_patches/blender_manifest.toml` | Extension manifest: id, version, supported Blender versions, license, build excludes |
| `topology_patches/LICENSE` | Copy of `LICENSE`, so it ships in the package (CI checks they are identical) |
| `tests/run.py` | Starts an isolated background Blender (factory settings, throw-away profile) and runs a script in it |
| `tests/test_topology_patches.py` | The test suite (unittest), 24 tests |
| `tests/fixtures.py` | Builds test scenes procedurally (target sphere, frame / round / single-face patches) and hides the naming differences between add-on versions |
| `tests/behaviour_snapshot.py` | Records what the add-on produces for 1168 cases, to compare two versions |
| `tests/compare_snapshots.py` | Compares two snapshots (no Blender needed) |
| `.github/workflows/tests.yml` | CI: tests from source and on the built package, Blender 5.3 on Linux |
| `.github/workflows/release.yml` | CI: on a `vX.Y.Z` tag, tests, builds and publishes the GitHub release |
| `.github/actions/setup-blender/action.yml` | Downloads Blender (mirrors, retries), checks its SHA-256, caches it |
| `.github/release-size.json` | Data for the README's download-size badge; written by `release.yml` |
| `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md` | Issue forms and PR checklist |
| `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `HANDOVER.md`, `AGENTS.md` | Docs (not in the package: only the `topology_patches` folder is packaged) |

### Sections of `__init__.py`, in order

1. **Module docstring:** the user guide in short, then "How the code fits together".
2. **Constants and preferences lookup:** `SHRINKWRAP_NAME`, `REF_SUFFIX`, the legacy `OLD_*` names, `DEFAULTS` (preview colours), `_pref()`.
3. **Geometry helpers:** `_corner_indices`, `_newell`, `_wachspress` (convex borders), `_mean_value` (concave borders), `_to_grid`.
4. **`Patch`:** analyses the patch mesh once (`_analyse`): border loop, corners, sides, A × B grid or round border (`frame`, `turn_in_place`), every vertex as weights over the border corners plus a height. Also rigid islands (`_rigid_islands`, `_apply_rigid`) and what a stamp carries over (`_read_data`). Mapping: `map_points` (single face) and `map_grid` (A × B block).
5. **`Target`:** a bmesh copy of one target plus a BVH. `ray_cast`, `plan` (`_plan_face` / `_plan_grid`: what a stamp would do, without changing anything; `_plan_grid` = cursor-centred start + `_walk_block` + `_grid_plan`), `plan_selection` (Edit Mode: one selected face, or the orientations in which `_walk_block` covers exactly the selected block, from `_selection_blocks`), `commit` (`_open_grid` / `_open_face` open the hole, then faces, UVs, materials and edge flags are built), `snapshot` / `restore` (in-tool undo), `prepare_shrinkwrap` / `_drop_shrinkwrap`, `prepare_data`.
6. **`Session`:** the tool without UI. Hover (`pick`), `rotate`, `scale_depth`, toggles (curve, rigid, flip: flip negates the depth, which mirrors every height above the border plane), `make_plan`, `apply`, `stamp_selection` (Edit Mode), `undo`, `replay`, and the GPU preview (`_build_batches`, `draw`).
7. **Operator `OBJECT_OT_topology_patches`:** `invoke` starts the modal tool around a Session; `modal` maps keys and mouse; every stamp is recorded in the `stamps` collection so that `execute` can replay them for **Adjust Last Operation**. **`MESH_OT_topology_patches_replace`** (Edit Mode, Face menu): `_roles` picks the patch, the one selected mesh outside Edit Mode (what Ctrl+click in the viewport gives) or else the active mesh, and the targets, the meshes in Edit Mode. Its poll only asks for Edit Mode, so a missing patch is reported instead of greying out the button; it leaves Edit Mode (so the meshes are written), stamps each target's selected faces through `Session.stamp_selection` (the new faces become the selection) and goes back to Edit Mode. Its redo simply runs again on the restored selection.
8. **UI and registration:** `TopologyPatchesSettings` (scene options), `TopologyPatchesPreferences` (colours), `VIEW3D_PT_topology_patches` (sidebar), Object menu entry, `register` / `unregister`.

## How the main feature works

1. **Analysis.** `Patch._analyse` walks the single open border loop in face-winding order and marks corners where the outline turns by more than 1°. The border is projected onto its best-fit plane. Every inner vertex becomes Wachspress coordinates over the corners (mean value coordinates if the border is concave) plus a signed height above that plane.
2. **Mode.** A border with 4 corners and equal opposite sides is a **grid** (A × B). A border with more than 4 corners and an even vertex count is **round**: its N vertices are spread around the outline of an A × B block with 2(A + B) = N. Anything else replaces a **single face** with the same number of corners.
3. **Plan.** On hover, `Target.plan` walks the quads around the hovered face (`_grid_step`) to collect the block, centred on the cursor, and refuses non-quads, poles and too-small meshes. `Patch.map_grid` then places every patch vertex: with **Curve** on, by bilinear interpolation on the original cells and along interpolated vertex normals; with Curve off, on a Coons patch with one normal. `map_points` does the same for a single face. **Rigid** islands are then replaced by their best similarity transform in the surface's own x and y, so they keep their shape; along the normal each rigid vertex keeps the lift of the stretched surface under it (`_apply_rigid` inverts the local stretch to find that point), so the island bends with a curved target instead of standing off it.
4. **Commit.** `Session.apply` snapshots the bmesh, sets up the shrinkwrap if asked, adds the layers and material slots the patch needs, plans again and calls `Target.commit`. Commit deletes the block (or face), maps border vertices to the existing ones (or splits edges in single-face mode), creates the new vertices and faces, and copies materials, UVs, edge flags and vertex-group weights. Finally the bmesh is written to the object.
5. **Undo and redo.** Inside the tool, **Ctrl + Z** restores the last snapshot (and removes the shrinkwrap setup if that stamp created it). After the tool, Blender's undo takes back the whole run. **Adjust Last Operation** makes Blender undo the run and call `execute`, which refreshes the scene (`view_layer.update()`, see pitfalls) and replays the recorded stamps, the last one with the panel's values. `Patch.turn_in_place` keeps a redo rotation on the same faces.

## How to make a change

1. Read the section of `__init__.py` you'll change, and the pitfalls below.
2. Make the change. Keep it in the matching section; give new functions a docstring.
3. Run the tests: `python tests/run.py`.
4. **If you fix a bug,** add a test to `tests/test_topology_patches.py` that fails without the fix. Check that it does: run it with `--addon-dir` pointing at a copy without the fix.
5. **If results could change,** compare behaviour with the previous commit:

   ```
   git worktree add ../tp-old HEAD
   python tests/run.py --addon-dir ../tp-old --script tests/behaviour_snapshot.py -- old.json
   python tests/run.py --script tests/behaviour_snapshot.py -- new.json
   python tests/compare_snapshots.py old.json new.json
   git worktree remove ../tp-old
   ```

   Two runs of the same code give 0 differences, so every difference is real: explain each one in the commit message.
6. Try it by hand in Blender if you touched the modal tool, the preview or the panel: the tests can't move a mouse.
7. Commit in small steps; say in the message how you verified the change.

## How to run the tests

| What | Command |
|---|---|
| Tests from source | `python tests/run.py` |
| Another Blender | `python tests/run.py --blender "C:\path\to\blender.exe"` (or set `$BLENDER`) |
| Code from another folder | `python tests/run.py --addon-dir ../other-checkout` |
| Build the package | `mkdir dist` then `blender -b --factory-startup --command extension build --source-dir topology_patches --output-dir dist` |
| Tests on the built package | `python tests/run.py --installed dist/topology_patches-1.5.0.zip` |
| Validate the manifest | `blender -b --factory-startup --command extension validate topology_patches` |

Expected: `TOPOLOGY_PATCHES_TESTS ran=24 failures=0 errors=0`. The two preview tests initialise the GPU module (`gpu.init()`) and skip themselves where that fails.

The runner always uses `--factory-startup` and a temporary `BLENDER_USER_RESOURCES`, so your installed add-ons, preferences and open files are never touched.

**Not covered by tests:** the modal tool's mouse and key handling, and the panel. A background Blender has no 3D Viewport, so the tests drive the same code through `Session` and call the operator's `execute` directly.

## How to make a release

1. Bump the version in **three places**: `blender_manifest.toml`, `bl_info` in `__init__.py`, and the README (version line and history table).
2. Run the tests from source, build the package, and run the tests on it (commands above).
3. Commit and push to `main`, and wait for the **tests** workflow to pass.
4. Tag with the release notes as the tag message, and push the tag:

   ```
   git tag -a v1.5.1 -m "What changed, for users"
   git push origin v1.5.1
   ```

5. `release.yml` then runs the tests, checks that the tag equals the manifest version, fetches the annotated tag (its message becomes the notes), builds `topology_patches-X.Y.Z.zip`, publishes the release **"Topology Patches X.Y.Z"** with the zip, and commits the new download size to `.github/release-size.json` on `main`.
6. Check the release page, then `git pull` before your next change (CI committed to `main`).

The README badges are live (shields.io and GitHub): don't hard-code versions in them.

## Updates from the original project

None: this is an original project, not a fork.

## Things to know (pitfalls found in this project)

- **Redo runs on an un-evaluated scene.** Right after Blender's undo, objects have no updated `matrix_world`. `execute` calls `context.view_layer.update()` before reading anything; without it the recorded rays hit other faces or miss (the 1.4.1 bug; `test_redo_after_the_object_moved_without_an_update`).
- **Recorded stamps are world positions.** The ray is replayed from just above the recorded hit point, so it finds the same face even if the view changed.
- **A non-square block can't do quarter turns in place:** a 2 × 4 patch turned 90° needs a 4 × 2 block, which is other faces. `turn_in_place` only does half turns for it; ←/→ in the tool still do quarter turns on purpose.
- **`create_uvsphere` doesn't number faces the same way on every run.** Never key test results on face indices; the snapshot uses face centres.
- **Background Blender has no GPU module** until `gpu.init()`; the preview tests call it and skip if it fails.
- **Installed preferences are 32-bit floats:** compare colours with a tolerance.
- **Moving the target along the ray hides a stale-matrix bug:** the ray still hits the same face from behind. The regression test moves it sideways.
- **Legacy names:** keep `OLD_SHRINKWRAP_NAME` ("Sticker Shrinkwrap") and `OLD_REF_SUFFIX` ("_sticker_ref"). Scenes made before 1.4 use them.
- **The UV option's identifier changed** from `STICKER` to `PATCH` in 1.5. It kept its index, so saved scenes keep their choice.
- **Panels, preferences and property groups:** use `#` comments, not docstrings (Blender shows them as descriptions). The operator's docstring is its tooltip: write it for users.
- **Manifest:** the tagline must be ≤ 64 characters, and `extension build` needs an existing output folder.

## Known limits

- Object Mode only. Blocks need regular quads (no triangles, n-gons or poles inside).
- A patch can't be scaled over more faces than its border has edges.
- A round border with an odd vertex count only fits a face with that many corners.
- Adjust Last Operation changes only the last stamp of a run.
- Each stamp copies the whole target mesh for the in-tool undo, and rebuilds the ray-cast tree twice (measured on a 131k-face sphere: 148 ms per stamp, of which 27 ms is the second rebuild). Hovering is not affected (0.2 ms per ray cast).
- Not tested by hand on macOS or Linux; CI runs on Linux in background mode.

## Repository and community files

- Issue forms (bug report, feature request; blank issues disabled) and contact links in `.github/ISSUE_TEMPLATE/`.
- PR checklist: `.github/pull_request_template.md`.
- `CONTRIBUTING.md`: how to report, set up, test and style code; `SECURITY.md`: private vulnerability reports.
- **Keep `.github/release-size.json` on `main`:** the download-size badge reads it.
