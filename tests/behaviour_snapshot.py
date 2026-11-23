"""Record what Topology Patches produces for a broad set of inputs (runs inside Blender).

    python tests/run.py --script tests/behaviour_snapshot.py [--addon-dir DIR] -- OUT.json

For eight kinds of patch (grid, non-square grid, round, lopsided round with a
rigid group, single face, a patch with materials / UVs / creases) it records:
  * the planned vertex positions for every rotation step, curve on/off, rigid
    on/off and two depths, at three spots on a squashed target;
  * the mesh after stamping, for every UV mode, with and without the
    shrinkwrap setup, and after undo: counts, coordinate moments, materials,
    UV sums, edge flags, vertex-group weights, modifiers and helper objects.
Comparing the JSON of two versions (tests/compare_snapshots.py) shows whether a
change altered behaviour.
"""

import importlib
import json
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixtures as fx  # noqa: E402

sys.path.insert(0, os.environ["TOPOLOGY_PATCHES_ADDON_DIR"])
tp = importlib.import_module("topology_patches")
Patch = fx.patch_class(tp)

OUT = sys.argv[sys.argv.index("--") + 1]
SPOTS = [fx.direction(1.0, 0.1, 0.12), fx.direction(0.5, 0.2, 1.5), fx.direction(-0.3, -1.0, 0.4)]


def r(x, n=5):
    return round(float(x), n)


def vec(v, n=5):
    return [r(c, n) for c in v]


def make_patches():
    return {
        "frame 1x1": fx.frame_patch("F11", 1, 1),
        "frame 2x2": fx.frame_patch("F22", 2, 2),
        "frame 2x4": fx.frame_patch("F24", 2, 4),
        "round 8 lopsided rigid": fx.round_patch("R8", 8, rigid=True, base=True, offset=0.2),
        "round 16 rigid": fx.round_patch("R16", 16, rigid=True),
        "round 10": fx.round_patch("R10", 10, rigid=False),
        "face 4 (2x2 border on one face)": fx.face_patch("P4", 4),
        "decorated": fx.decorated_patch(),
    }


def mesh_state(ob):
    """Everything a stamp can change on the target, summed so the order of
    vertices and faces does not matter."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    uv = bm.loops.layers.uv.active
    crease = bm.edges.layers.float.get("crease_edge")
    deform = bm.verts.layers.deform.active
    mats = [m.name if m else None for m in ob.data.materials]
    out = {
        "stats": list(fx.mesh_stats(ob)),
        "sum": vec([sum(v.co[i] for v in bm.verts) for i in range(3)], 3),
        "sum2": r(sum(v.co.length_squared for v in bm.verts), 3),
        "materials": mats,
        "faces per material": sorted([mats[f.material_index] if mats else None for f in bm.faces].count(m)
                                     for m in set(mats or [None])),
        "smooth faces": sum(f.smooth for f in bm.faces),
        "sharp edges": sum(not e.smooth for e in bm.edges),
        "seams": sum(e.seam for e in bm.edges),
        "crease sum": r(sum(e[crease] for e in bm.edges), 3) if crease else None,
        "uv sum": vec([sum(lp[uv].uv[i] for f in bm.faces for lp in f.loops) for i in range(2)], 2) if uv else None,
        "group weight sum": r(sum(sum(v[deform].values()) for v in bm.verts), 3) if deform else None,
        "groups": [g.name for g in ob.vertex_groups],
        "modifiers": [(m.type, getattr(m, "vertex_group", ""), getattr(getattr(m, "target", None), "hide_render", None))
                      for m in ob.modifiers],
        "hidden copies": sorted(len(o.data.vertices) for o in bpy.data.objects
                                if o.name.startswith(ob.name + "_") and o.type == 'MESH'),
    }
    bm.free()
    return out


def plans(patch_ob, target):
    s = fx.new_session(tp, bpy.context, patch_ob, [target])
    p = fx.session_patch(s)
    out = {"label": p.label, "steps": p.rot_steps}
    c = target.matrix_world.translation
    for si, d in enumerate(SPOTS):
        for curve in (True, False):
            for rigid in (False, True):
                for depth in (1.0, 1.5):
                    for rot in range(min(p.rot_steps, 8)):
                        s.rot, s.curve, s.rigid, s.depth = rot, curve, rigid, depth
                        s.pick(c + d * 10.0, -d)
                        plan = s.make_plan()
                        key = f"spot{si} curve={curve} rigid={rigid} depth={depth} rot={rot}"
                        if plan is None:
                            out[key] = None
                        elif not plan["valid"]:
                            out[key] = {"invalid": plan["message"]}
                        else:
                            w = plan["world"]
                            out[key] = {"n": len(w), "sum": vec(sum(w, w[0] * 0), 4),
                                        "sum2": r(sum(v.length_squared for v in w), 4),
                                        "first": vec(w[0], 4), "last": vec(w[-1], 4),
                                        # face centres, not indices: create_uvsphere does not
                                        # number its faces the same way on every run
                                        "faces": sorted(vec(f.calc_center_median(), 4)
                                                        for f in plan.get("faces", [plan["face"]]))}
    s.free()
    return out


def stamps(patch_ob, target):
    out = {}
    d = SPOTS[0]
    c = target.matrix_world.translation
    for uv_source in ('AUTO', 'PATCH', 'TARGET'):
        for shrinkwrap in (False, True):
            for rot in (0, 1):
                key = f"uv={uv_source} shrinkwrap={shrinkwrap} rot={rot}"
                s = fx.new_session(tp, bpy.context, patch_ob, [target], shrinkwrap=shrinkwrap, uv_source=uv_source)
                s.rot = rot
                s.pick(c + d * 10.0, -d)
                ok = s.apply()
                case = {"applied": ok, "message": s.message, "after": mesh_state(target)}
                # a second stamp next to the first one
                d2 = fx.direction(0.2, 1.0, 0.12)
                s.pick(c + d2 * 10.0, -d2)
                case["second applied"] = s.apply()
                case["after second"] = mesh_state(target)
                while s.undo():
                    pass
                case["after undo"] = mesh_state(target)
                s.free()
                out[key] = case
    return out


def main():
    tp.register()
    results = {}
    fx.reset_scene()
    names = list(make_patches())
    for name in names:
        fx.reset_scene()
        target = fx.make_target("Target", scale=(1.0, 1.0, 1.4))
        target.data.materials.append(bpy.data.materials.new("TP_outer"))
        patch_ob = make_patches()[name]
        bpy.context.view_layer.update()
        try:
            results[name + " / plans"] = plans(patch_ob, target)
            results[name + " / stamps"] = stamps(patch_ob, target)
        except Exception as e:  # an error is behaviour too: record it, keep going
            results[name] = {"error": f"{type(e).__name__}: {e}"}
    tp.unregister()
    with open(OUT, "w") as f:
        json.dump(results, f, indent=1, sort_keys=True)
    n = sum(len(v) for v in results.values())
    print(f"SNAPSHOT groups={len(results)} cases={n} -> {OUT}")


main()
