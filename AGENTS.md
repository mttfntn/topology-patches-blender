# AGENTS.md: Topology Patches

Compact guide for AI coding assistants. The human version, with more context, is [HANDOVER.md](HANDOVER.md).

## Project

- **What it is:** a Blender **5.3-only** extension (single module `topology_patches/__init__.py`, GPL-3.0-or-later, author Matteo Fontana, not a fork). A modal tool stamps a *patch* mesh onto a target: it replaces an A × B block of quads (or one face), stretches the patch onto it and welds the border.
- **Repo:** `https://github.com/mttfntn/topology-patches-blender` (public). Branch `main`; release tags `vX.Y.Z` (annotated; the message becomes the release notes).
- **Old working name:** "Topology Sticker". Code identifiers were renamed to "patch" in 1.5; only the legacy constants `OLD_SHRINKWRAP_NAME` / `OLD_REF_SUFFIX` still say "sticker", on purpose.

## Commands

Run from the repo root:

| Task | Command |
|---|---|
| Tests from source | `python tests/run.py` |
| Build | `mkdir dist` then `blender -b --factory-startup --command extension build --source-dir topology_patches --output-dir dist` |
| Tests on the built package | `python tests/run.py --installed dist/topology_patches-X.Y.Z.zip` |
| Validate the manifest | `blender -b --factory-startup --command extension validate topology_patches` |
| Behaviour snapshot | `python tests/run.py [--addon-dir OLD] --script tests/behaviour_snapshot.py -- out.json` |
| Compare snapshots | `python tests/compare_snapshots.py old.json new.json` (0 differences = same behaviour) |

- **Blender path:** `--blender PATH` or `$BLENDER`. On Windows the default is `C:\Program Files\Blender Foundation\Blender 5.3*\blender.exe`.
- **Isolation:** `run.py` always uses `--factory-startup` plus a temporary `BLENDER_USER_RESOURCES`. **Never** test against the user's running Blender or profile.
- **Expected result:** `TOPOLOGY_PATCHES_TESTS ran=34 failures=0 errors=0`.

## Architecture (`__init__.py`, top to bottom)

constants + `_pref` → geometry helpers (`_corner_indices`, `_newell`, `_wachspress`, `_mean_value`, `_to_grid`) → **`Patch`** (analysis: `_analyse`, `frame`, `turn_in_place`, `rot_steps`, `map_points`, `map_grid`, rigid islands, `_read_data`) → `_grid_step` → **`Target`** (`ray_cast`, `plan` → `_plan_face`/`_plan_grid` (→ `_walk_block`, `_grid_plan`), `plan_selection` → `_selection_blocks`, `commit` → `_open_grid`/`_open_face`, `snapshot`/`restore`, `prepare_shrinkwrap`/`_drop_shrinkwrap`, `prepare_data`) → **`Session`** (`pick`, `make_plan`, `apply`, `stamp_selection`, `undo`, `replay`, preview `_build_batches`/`draw`) → operator `OBJECT_OT_topology_patches` (`invoke`/`modal` = tool; `execute` = redo) → `MESH_OT_topology_patches_replace` (Edit Mode: replace the selected faces) → settings, preferences, panel, menu, `register`.

## Data flow

1. `Session.pick` ray-casts every `Target` (BVH on a bmesh copy) → `hover = (target index, (face, half_u, half_v))`.
2. `Target.plan` → dict `{valid, message, mode 'GRID'|'FACE', faces, G, border, world, fills, outline, marker, ...}`; `world` = every patch vertex in world space.
3. `Session.apply` → `snapshot` → `prepare_shrinkwrap?` → `prepare_data` → plan again → `Target.commit` → `_write` (bmesh → mesh).
4. The operator records each stamp as `(point, direction, rot, depth, curve, rigid, flip)` in `stamps` (`replay` also takes the 6-tuple of older records). `execute` = `view_layer.update()` + new Session + `replay`, the last stamp with `turn_in_place(rot, rotation)` and the panel values.
5. Scene state lives only in the meshes, the scene's `topology_patches` settings, and the optional shrinkwrap setup (`Patch Shrinkwrap` modifier, `<name>_patch_ref` hidden copy, `base` group).

## Rules

- **Supported version is Blender 5.3 only:** no fallbacks for other versions. Keep `BLENDER_VERSION` / `BLENDER_SHA256` in both workflows in step with the manifest.
- **Behaviour-preserving changes** must give 0 differences in `compare_snapshots.py` (measured noise: 0). Explain any difference.
- **Every bug fix gets a regression test that fails before the fix** (prove it with `--addon-dir` on a copy without the fix).
- **Panels, preferences, property groups:** `#` comments, no docstrings (they become UI descriptions). The operator docstring is the user tooltip.
- **Tests must work on old and new code:** go through `tests/fixtures.py` helpers (`patch_class`, `error_class`, `new_session`, `session_patch`).
- **The version lives in three places:** manifest, `bl_info`, README (version line + history). Badges are live: never hard-code versions in them. `.github/release-size.json` on `main` is rewritten by CI after each release, so pull before your next change.
- **Never delete** the user's `.blend` files (git-ignored, local).
- **Commits:** small, with a message that says how the change was verified.

## Pitfalls (each one happened here)

- **Redo after Blender's undo:** `matrix_world` is stale until `view_layer.update()`. `execute` must call it first (1.4.1 bug).
- **Regression test geometry:** moving the target *along* the ray hides the stale-matrix bug (the ray hits the same face from behind); move it sideways.
- **`create_uvsphere` face order varies between runs:** key results on face centres, not indices.
- **Background Blender:** no GPU until `gpu.init()`; no 3D Viewport, so `invoke`/`modal` can't be tested; call `execute` with a stand-in `self` (see `TestRedo.run_execute`).
- **Installed preferences are float32:** compare colours with `assertAlmostEqual`.
- **Non-square blocks:** a quarter turn changes the faces; `turn_in_place` uses half turns.
- **Renaming a local to `patch`** clashed with `_open_grid`'s face set (now `block`): check for clashes before renames, and rename by tokens, not text.
- **Manifest:** tagline ≤ 64 characters; `extension build` needs an existing output directory.
- **`git` on Windows:** `.gitattributes` forces LF; files written with CRLF are normalised on commit.

## How changes were verified (cleanup to 1.5.0)

- Baseline: commit `45d7a11` (code of 1.4.1 + new tests), 22/22 tests. Three snapshots of it (1168 cases each) gave 0 differences between them.
- After the rename, docs and packaging: 24/24 tests from source and on the installed package. The snapshot against the baseline gives **0 differences**.
- The redo regression test fails on a copy without the fix and passes with it.

## Release checklist

1. Bump the version in the manifest, `bl_info` and README (version line, history).
2. Tests from source → build → tests on the package.
3. Push to `main`, wait for the `tests` workflow.
4. `git tag -a vX.Y.Z -m "<notes>"`, then `git push origin vX.Y.Z`.
5. `release.yml`: tests → tag == manifest version → fetch the annotated tag → build → `gh release create` ("Topology Patches X.Y.Z", zip, tag message as notes) → bot commit of `.github/release-size.json` on `main`.
6. Verify the release page and the badges.

## Community files

- `.github/ISSUE_TEMPLATE/` (bug report, feature request, `config.yml` with blank issues disabled and contact links), `.github/pull_request_template.md`, `CONTRIBUTING.md`, `SECURITY.md` (private vulnerability reports).

## Git setup

- **Remote:** `origin https://github.com/mttfntn/topology-patches-blender.git` (HTTPS). Default branch `main`.
- **Ignored:** `*.blend*`, `dist/`, `*.zip`, `__pycache__/`, `*.pyc`. `.gitattributes`: LF everywhere, zips / blends / pngs binary.
- **CI:** `tests.yml` on pushes to `main`, pull requests, manual runs, and when called by `release.yml`. No artifacts are stored (the account's artifact quota is shared). The Blender download is cached by version and checksum.
- **Releases start at `v1.5.0`.** Earlier versions (1.0 to 1.4.1) were never released on GitHub.
