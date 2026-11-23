"""Scene fixtures for the Topology Patches tests (runs inside Blender).

Everything is built procedurally, so the tests need no .blend file:
  * make_target: a quad UV sphere, optionally scaled, with UVs and a Subdivision
    modifier;
  * frame_patch: an A x B frame border with a sunken centre (the classic grid patch);
  * round_patch: an N-gon border with a round hole (rim + bottom ring), optional
    `rigid` and `base` vertex groups;
  * face_patch: a single-face patch with K corners (triangle, pentagon...).
All patches are modelled flat with their border at Z = 0 and detail below it.

The module also wraps the small differences between add-on versions (class and
argument names) so the same tests and snapshots run on old and new code.
"""

import inspect
import math

import bmesh
import bpy
from mathutils import Vector


def reset_scene():
    """Empty scene with default settings (the add-on's scene settings included)."""
    bpy.ops.wm.read_homefile(use_empty=True)


def link(name, me, location=(0.0, 0.0, 0.0)):
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = location
    return ob


def make_target(name="Target", location=(0.0, 0.0, 0.0), scale=(1.0, 1.0, 1.0), segments=32, rings=16,
                subsurf=True, uvs=True):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    if uvs:
        bm.loops.layers.uv.new("UVMap")
    bmesh.ops.create_uvsphere(bm, u_segments=segments, v_segments=rings, radius=1.0, calc_uvs=uvs)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    ob = link(name, me, location)
    ob.scale = scale
    if subsurf:
        ob.modifiers.new("Subdivision", 'SUBSURF').levels = 1
    bpy.context.view_layer.update()
    return ob


def frame_patch(name, a, b, depth=0.3):
    """A x B frame: 2*(A+B) border vertices around a sunken centre face."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    pts = ([(i, 0) for i in range(a)] + [(a, j) for j in range(b)]
           + [(a - i, b) for i in range(a)] + [(0, b - j) for j in range(b)])
    outer = [bm.verts.new((x, y, 0.0)) for x, y in pts]
    cx, cy = a / 2.0, b / 2.0
    inner = [bm.verts.new((cx + (x - cx) * 0.5, cy + (y - cy) * 0.5, -depth)) for x, y in pts]
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((outer[i], outer[j], inner[j], inner[i]))
    bm.faces.new(inner)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    return link(name, me, (0.0, -6.0, 0.0))


def round_patch(name, n=8, rigid=True, base=False, offset=0.0):
    """N-gon border (radius 1), rim ring (0.6) and a bottom ring (0.5, z=-0.5)
    closed by one N-gon. `offset` shifts the hole sideways (a lopsided patch,
    so every rotation gives a different result)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()

    def circle(r, z, dx=0.0):
        return [bm.verts.new((dx + r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), z))
                for i in range(n)]

    r0, r1, r2 = circle(1.0, 0.0), circle(0.6 - offset, 0.0, offset), circle(0.5 - offset, -0.5, offset)
    for ra, rb in ((r0, r1), (r1, r2)):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((ra[i], ra[j], rb[j], rb[i]))
    bm.faces.new(r2)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    ob = link(name, me, (0.0, -6.0, 0.0))
    if rigid:
        ob.vertex_groups.new(name="rigid").add(list(range(n, 3 * n)), 1.0, 'REPLACE')
    if base:
        ob.vertex_groups.new(name="base").add(list(range(0, 2 * n)), 1.0, 'REPLACE')
    return ob


def face_patch(name, k=5, depth=0.3):
    """Single-face patch: K-corner border, a smaller K-gon sunk below it."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    outer = [bm.verts.new((math.cos(2 * math.pi * i / k), math.sin(2 * math.pi * i / k), 0.0)) for i in range(k)]
    inner = [bm.verts.new((0.5 * math.cos(2 * math.pi * i / k), 0.5 * math.sin(2 * math.pi * i / k), -depth))
             for i in range(k)]
    for i in range(k):
        j = (i + 1) % k
        bm.faces.new((outer[i], outer[j], inner[j], inner[i]))
    bm.faces.new(inner)
    bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    return link(name, me, (0.0, -6.0, 0.0))


def decorated_patch(name="Decorated"):
    """2 x 2 frame with an 8-ring hole: a second material on the bottom face,
    its own UVs (all > 4, easy to recognise), creases and sharp edges inside,
    a crease on the border (must not be carried over), `base` and `rigid` groups."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    pts = [(-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0)]

    def ring(scale, z):
        return [bm.verts.new((x * scale, y * scale, z)) for x, y in pts]

    r0, r1, r2 = ring(1.0, 0.0), ring(0.6, 0.0), ring(0.5, -0.6)
    for ra, rb in ((r0, r1), (r1, r2)):
        for i in range(8):
            j = (i + 1) % 8
            bm.faces.new((ra[i], ra[j], rb[j], rb[i]))
    bottom = bm.faces.new(r2)
    bottom.material_index = 1
    uv = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for lp in f.loops:
            lp[uv].uv = (5.0 + lp.vert.co.x, 5.0 + lp.vert.co.y)
    cr = bm.edges.layers.float.new("crease_edge")
    for i in range(8):
        j = (i + 1) % 8
        bm.edges.get((r1[i], r1[j]))[cr] = 0.8
        bm.edges.get((r2[i], r2[j])).smooth = False
        bm.edges.get((r0[i], r0[j]))[cr] = 0.3
    bm.to_mesh(me)
    bm.free()
    ob = link(name, me, (0.0, -6.0, 0.0))
    me.materials.append(None)
    me.materials.append(bpy.data.materials.get("TP_inner") or bpy.data.materials.new("TP_inner"))
    ob.vertex_groups.new(name="base").add(list(range(0, 16)), 1.0, 'REPLACE')
    ob.vertex_groups.new(name="rigid").add(list(range(8, 24)), 1.0, 'REPLACE')
    return ob


def select(active, *others):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in (active,) + others:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active


def direction(x, y, z):
    return Vector((x, y, z)).normalized()


def mesh_stats(ob):
    """(open edges, loose verts, flipped edges, non-manifold edges, verts, faces)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    out = (sum(e.is_boundary for e in bm.edges),
           sum(not v.link_faces for v in bm.verts),
           sum(len(e.link_loops) == 2 and e.link_loops[0].vert == e.link_loops[1].vert for e in bm.edges),
           sum(not e.is_manifold for e in bm.edges),
           len(bm.verts), len(bm.faces))
    bm.free()
    return out


def roundness(points):
    """max / min distance of a ring of points from its centre (1.0 = circle)."""
    c = sum(points, Vector()) / len(points)
    r = [(p - c).length for p in points]
    return max(r) / min(r)


# -- differences between add-on versions ------------------------------------

def patch_class(tp):
    return getattr(tp, "Patch", None) or tp.Sticker


def error_class(tp):
    return getattr(tp, "PatchError", None) or tp.StickerError


def new_session(tp, context, patch, targets, **kw):
    """Session(...) whatever the patch argument is called in this version."""
    params = inspect.signature(tp.Session.__init__).parameters
    key = "patch_name" if "patch_name" in params else "sticker_name"
    kw[key] = patch.name
    kw["target_names"] = [t.name for t in targets]
    # "UVs from the patch" was called 'STICKER' before 1.5
    if kw.get("uv_source") == 'PATCH' and not hasattr(tp, "Patch"):
        kw["uv_source"] = 'STICKER'
    return tp.Session(context, **kw)


def session_patch(session):
    """The analysed patch of a session (`patch` or, in old versions, `sticker`)."""
    return getattr(session, "patch", None) or session.sticker


def scene_settings(scene):
    return scene.topology_patches
