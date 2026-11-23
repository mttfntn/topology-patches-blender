# SPDX-FileCopyrightText: 2026 Matteo Fontana
# SPDX-License-Identifier: GPL-3.0-or-later

"""Topology Patches
================

Replace part of a mesh with another mesh (the "patch"), stretching the
patch so that its open border lands exactly on existing vertices of the
target and welding everything together.

Usage (Object Mode)
-------------------
1. Select the mesh(es) you want to stamp onto, then select the patch LAST so
   that it is the active object.  (If only the patch is selected, every
   visible mesh is a target.)
2. Run  Object > Topology Patches  (also in the sidebar, "Patches" tab).
3. Hover the target: the faces that will be replaced are highlighted and the
   stretched patch is previewed.

   LMB ................. stamp (the tool keeps running)
   Left / Right arrow .. rotate the patch by 90 deg
   Ctrl + Wheel ........ same as the arrows
   Up / Down arrow ..... depth multiplier
   C ................... curve the patch onto the original surface on/off
   R ................... keep the "rigid" vertex group undistorted on/off
   Ctrl + Z ............ undo the last stamp (while the tool is running)
   Esc / RMB / Enter ... finish

After the tool is finished, a single Ctrl + Z in Blender takes back every
stamp made in that run, and the "Adjust Last Operation" panel (bottom left
of the viewport, or F9) lets you change the rotation, depth, curve and rigid
setting of the last stamp.  Rotating there never moves the stamp to other
faces (a patch that is not square turns by half turns).

The patch
---------
Any mesh with exactly ONE open border loop.

* Border with 4 corners and the same number of edges on opposite sides
  (A edges on two sides, B on the other two): the patch replaces an A x B
  block of quads and every border vertex is welded to an existing vertex of
  the target.  A plain square border (1 x 1) replaces a single face; a border
  with 2 edges per side replaces 2 x 2 faces, and so on.
* Round border (more than 4 corners, e.g. an octagon or a circle, with an
  even number N of vertices): the N border vertices are spread over the
  outline of an A x B block of quads with 2 * (A + B) = N, so 8 vertices
  take a 2 x 2 block and 16 a 4 x 4 block.  Rotating moves the patch one
  border vertex at a time.  On a face that has exactly N corners it replaces
  that single face instead.
* Any other border (triangle, pentagon, uneven sides, concave ...): the
  patch replaces a single face with the same number of corners; extra
  border vertices split the edges of that face.

Keep Rigid Shapes (sidebar option, R in the tool)
-------------------------------------------------
Stretching the patch to fit the block distorts it: a circle turns into an
oval or an eye shape when the block is not a flat square.  Paint a vertex
group (default name "rigid") on the PATCH over the vertices that must keep
their proportions.  Each connected island of that group is placed as one
piece - moved, rotated and uniformly scaled, never sheared or bent.  Weights
between 0 and 1 blend between rigid and stretched, which is how you make a
smooth transition from the round part to the border.  Border vertices always
weld to the target and ignore the group.

Shrinkwrap to Original (sidebar option)
---------------------------------------
Paint a vertex group (default name "base") on the PATCH over the vertices
that must stay on the target's surface.  With the option on, the first stamp
on a target hides a copy of it ("<name>_patch_ref") and adds a Shrinkwrap
modifier onto that copy, limited to the same vertex group on the target.
The modifier is placed before the first Subdivision modifier.  Vertices that
are kept rigid (see above) are left out of the group, so they stay rigid.
The target's own vertices are put in the group, stamped vertices inherit the
patch's weights, so everything outside the group keeps the patch's shape.

What the patch brings along
-----------------------------
* Materials: a patch face that has a material keeps it (the material is
  added to the target if needed); faces without one take the material of
  the face they replace.
* UVs (sidebar option): "Auto" keeps the patch's own UVs on faces that
  have their own material and continues the target's UVs through all other
  faces; "Patch" / "Target" force one or the other.
* Sharp edges, seams, edge creases, edge bevel weights and vertex creases of
  the patch's inner edges.  The border edges keep what the target had.
* Smooth / flat shading of the patch faces, unless the whole patch is
  flat: then the faces are shaded like the face they replace.

Preferences
-----------
Edit > Preferences > Add-ons > Topology Patches: colours and line widths of
the preview.

Curve (C)
---------
On:  every patch vertex is laid onto the original surface of the block it
     replaces and its depth is pushed along the interpolated vertex normals,
     so the patch bends with the mesh.
Off: only the border follows the mesh; the inside is a smooth membrane
     stretched between the border vertices with a single depth direction.

How the code fits together (Blender 5.3 extension, single module)
-----------------------------------------------------------------
Sections, in order:

  geometry helpers   corner detection, Newell normal, Wachspress / mean value
                     coordinates, grid parameters
  Patch              analyses the patch mesh once: its border loop, corners,
                     sides, the A x B grid (or round border), every vertex as
                     weights over the border corners + a height, rigid islands,
                     and the data a stamp carries over (materials, UVs, edges)
  Target             a bmesh copy of one target object plus a BVH for ray
                     casts.  plan() describes a stamp without touching the mesh
                     (which faces, where every patch vertex lands); commit()
                     opens the hole, welds the border and builds the faces;
                     snapshot() / restore() are the in-tool undo; the
                     shrinkwrap setup lives here too
  Session            everything the tool does, without any UI: hover, rotate,
                     depth, curve, rigid, apply, undo, replay, and the GPU
                     preview.  Tests and scripts drive the add-on through it
  operator           OBJECT_OT_topology_patches: the modal tool (mouse and
                     keys) around a Session; it records every stamp so that
                     execute() can replay them for Adjust Last Operation
  UI / registration  scene settings, add-on preferences (preview colours),
                     sidebar panel, Object menu entry

Data flow of one stamp: Session.pick (ray cast) -> Target.plan (Patch.map_grid
or Patch.map_points) -> preview batches -> Session.apply -> Target.snapshot ->
prepare_shrinkwrap / prepare_data -> Target.commit -> mesh written back.

Names kept for files made with earlier versions: a "Sticker Shrinkwrap"
modifier and "<name>_sticker_ref" copies are still recognised and reused.
"""

# Only used if the add-on is installed the legacy way; extensions read blender_manifest.toml.
bl_info = {
    "name": "Topology Patches",
    "author": "Matteo Fontana",
    "version": (1, 5, 0),
    "blender": (5, 3, 0),
    "location": "View3D > Object > Topology Patches  |  Sidebar > Patches",
    "description": "Replace faces with the active mesh, stretched to fit and welded",
    "category": "Mesh",
}

import math

import bmesh
import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector
from mathutils.bvhtree import BVHTree

CORNER_ANGLE = math.radians(1.0)   # border turns sharper than this are corners
PARAM_TOL = 1e-4                   # two border params closer than this are the same vertex
SHRINKWRAP_NAME = "Patch Shrinkwrap"           # modifier added by the shrinkwrap option
REF_SUFFIX = "_patch_ref"                       # hidden copy of the original target
OLD_SHRINKWRAP_NAME = "Sticker Shrinkwrap"     # made by versions before 1.4: still recognised
OLD_REF_SUFFIX = "_sticker_ref"
ADDON_ID = __package__ or __name__             # key of the add-on preferences

# preview colours / widths; the add-on preferences override them
DEFAULTS = {
    "wire": (0.2, 0.9, 1.0, 0.9),
    "outline": (1.0, 0.7, 0.2, 1.0),
    "fill": (1.0, 0.55, 0.1, 0.35),
    "marker": (1.0, 0.1, 0.6, 1.0),
    "invalid": (1.0, 0.2, 0.2, 1.0),
    "wire_width": 1.5,
    "outline_width": 3.0,
}


def _pref(name):
    """A preview colour or width from the add-on preferences (DEFAULTS when
    the preferences are not available, e.g. in tests)."""
    addon = bpy.context.preferences.addons.get(ADDON_ID)
    prefs = addon.preferences if addon else None
    value = getattr(prefs, name, None) if prefs else None
    if value is None:
        return DEFAULTS[name]
    return value if isinstance(value, float) else tuple(value)


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------

def _corner_indices(points):
    """Indices of the points of a closed polygon where the outline turns."""
    n = len(points)
    out = []
    for i in range(n):
        d_in = points[i] - points[i - 1]
        d_out = points[(i + 1) % n] - points[i]
        if d_in.length_squared == 0.0 or d_out.length_squared == 0.0:
            continue
        if d_in.angle(d_out) > CORNER_ANGLE:
            out.append(i)
    return out if len(out) >= 3 else list(range(n))


def _newell(points):
    """Area-weighted normal of a (possibly non planar) polygon. |n| = 2 * area."""
    n = Vector((0.0, 0.0, 0.0))
    for i, p in enumerate(points):
        n += p.cross(points[(i + 1) % len(points)])
    return n


def _tri_area_2d(a, b, c):
    """Signed area of a 2D triangle (positive when a, b, c turn counter-clockwise)."""
    return 0.5 * ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _wachspress(p, poly):
    """Wachspress coordinates of 2D point p in a convex CCW polygon.
    Equal to barycentric coords for a triangle and bilinear coords for a
    rectangle, which is exactly the "stretch" we want."""
    k = len(poly)
    scale = max(abs(_tri_area_2d(poly[i - 1], poly[i], poly[(i + 1) % k])) for i in range(k))
    eps = scale * 1e-10 + 1e-30
    a = [max(_tri_area_2d(p, poly[i], poly[(i + 1) % k]), eps) for i in range(k)]
    w = []
    for i in range(k):
        c = _tri_area_2d(poly[i - 1], poly[i], poly[(i + 1) % k])
        w.append(c / (a[i - 1] * a[i]))
    total = sum(w)
    if abs(total) < 1e-30:
        return [1.0 / k] * k
    return [x / total for x in w]


def _mean_value(p, poly):
    """Mean value coordinates of 2D point p in any simple polygon (concave ok)."""
    k = len(poly)
    s = [(q[0] - p[0], q[1] - p[1]) for q in poly]
    r = [math.hypot(x, y) for x, y in s]
    size = max(r) or 1.0
    for i in range(k):
        if r[i] < size * 1e-9:
            w = [0.0] * k
            w[i] = 1.0
            return w
    t = []
    for i in range(k):
        j = (i + 1) % k
        cross = s[i][0] * s[j][1] - s[i][1] * s[j][0]
        dot = s[i][0] * s[j][0] + s[i][1] * s[j][1]
        if abs(cross) < size * size * 1e-12:
            if dot < 0.0:                     # p lies on edge i -> j
                w = [0.0] * k
                w[i] = r[j] / (r[i] + r[j])
                w[j] = r[i] / (r[i] + r[j])
                return w
            t.append(0.0)
        else:
            t.append((r[i] * r[j] - dot) / cross)
    w = [(t[i - 1] + t[i]) / r[i] for i in range(k)]
    total = sum(w)
    if abs(total) < 1e-30:
        return [1.0 / k] * k
    return [x / total for x in w]


def _to_grid(u, ts):
    """Map u in [0, 1] to a grid coordinate, ts[i] being the param of grid line i."""
    u = min(max(u, 0.0), 1.0)
    for i in range(len(ts) - 1):
        if u <= ts[i + 1] or i == len(ts) - 2:
            span = ts[i + 1] - ts[i]
            return i + ((u - ts[i]) / span if span > 1e-12 else 0.0)
    return float(len(ts) - 1)


# --------------------------------------------------------------------------
# patch (source mesh) analysis
# --------------------------------------------------------------------------

class PatchError(Exception):
    """A patch that cannot be used, or a tool that cannot start; the message is shown to the user."""


class Patch:
    """Pre-computed description of the patch mesh, independent of any target.

    Every vertex is stored as weights over the K border corners plus a signed
    height above the border plane.  When the border is a regular A x B frame,
    `grid` is (A, B) and every vertex also has a coordinate in that grid.
    """

    def __init__(self, obj, group="", rigid_group=""):
        self.name = obj.name
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        try:
            self._analyse(bm, obj.matrix_world)
            layer = bm.verts.layers.deform.active

            def read(name):
                """Per vertex weight in a vertex group (None: no such group)."""
                vg = obj.vertex_groups.get(name) if name else None
                if vg is None:
                    return None
                out = [0.0] * len(bm.verts)
                if layer is not None:
                    for v in bm.verts:
                        out[v.index] = v[layer].get(vg.index, 0.0)
                return out

            self.base = read(group)
            self.rigid = self._rigid_islands(read(rigid_group))
            self.rigid_weight = {v: min(w, 1.0) for isl in self.rigid for v, w in isl["verts"]}
            self._read_data(bm, obj)
        finally:
            bm.free()

    def _read_data(self, bm, obj):
        """Everything besides the shape that a stamp carries over."""
        slots = [slot.material.name if slot.material else None for slot in obj.material_slots]
        self.face_material = [slots[f.material_index] if f.material_index < len(slots) else None
                              for f in bm.faces]
        self.face_smooth = [f.smooth for f in bm.faces]
        self.any_smooth = any(self.face_smooth)
        self.uv = {layer.name: [[lp[layer].uv.copy() for lp in f.loops] for f in bm.faces]
                   for layer in bm.loops.layers.uv.values()}
        active = bm.loops.layers.uv.active
        self.uv_active = active.name if active else None
        crease = bm.edges.layers.float.get("crease_edge")
        bevel = bm.edges.layers.float.get("bevel_weight_edge")
        self.edge_data = {}      # (v0, v1) -> (sharp, seam, crease, bevel weight), inner edges only
        for e in bm.edges:
            if e.is_boundary:
                continue
            data = (not e.smooth, e.seam, e[crease] if crease else 0.0, e[bevel] if bevel else 0.0)
            if any(data):
                self.edge_data[(e.verts[0].index, e.verts[1].index)] = data
        vcrease = bm.verts.layers.float.get("crease_vert")
        self.vert_crease = {}
        if vcrease:
            self.vert_crease = {v.index: v[vcrease] for v in bm.verts
                                if v[vcrease] > 0.0 and v.index not in self.border_set}

    def _rigid_islands(self, weights):
        """Group the vertices of the "rigid" vertex group into connected
        islands; each island is later placed as one undistorted piece."""
        if weights is None:
            return []
        w = [0.0 if i in self.border_set else x for i, x in enumerate(weights)]
        links = {}
        for a, b in self.edges:
            if w[a] > 0.0 and w[b] > 0.0:
                links.setdefault(a, []).append(b)
                links.setdefault(b, []).append(a)
        seen = set()
        islands = []
        for start in range(len(w)):
            if w[start] <= 0.0 or start in seen:
                continue
            seen.add(start)
            todo = [start]
            verts = []
            while todo:
                v = todo.pop()
                verts.append(v)
                for o in links.get(v, ()):
                    if o not in seen:
                        seen.add(o)
                        todo.append(o)
            total = sum(w[v] for v in verts)
            cx = sum(w[v] * self.xy[v][0] for v in verts) / total
            cy = sum(w[v] * self.xy[v][1] for v in verts) / total
            rms = math.sqrt(sum(w[v] * ((self.xy[v][0] - cx) ** 2 + (self.xy[v][1] - cy) ** 2)
                                for v in verts) / total)
            islands.append({"verts": [(v, w[v]) for v in verts], "center": (cx, cy),
                            "delta": max(0.5 * rms, 1e-3 * math.sqrt(self.area))})
        return islands

    def _apply_rigid(self, out, foot, depth):
        """Blend the rigid islands back to their original proportions.
        `foot(x, y)` is the stretched position of a point of the patch's
        border plane; around each island's centre it is replaced by its best
        similarity (move + rotate + uniform scale), so circles stay circles."""
        for isl in self.rigid:
            cx, cy = isl["center"]
            d = isl["delta"]
            anchor = foot(cx, cy)
            tu = (foot(cx + d, cy) - foot(cx - d, cy)) / (2.0 * d)
            tv = (foot(cx, cy + d) - foot(cx, cy - d)) / (2.0 * d)
            n = tu.cross(tv)
            if n.length < 1e-12 or tu.length < 1e-12 or tv.length < 1e-12:
                continue
            scale = math.sqrt(n.length)
            n.normalize()
            # orthonormal frame that splits the shear evenly between both axes
            eu = (tu - n * tu.dot(n)).normalized()
            ev = (tv - n * tv.dot(n)).normalized()
            bis = (eu + ev).normalized()
            side = n.cross(bis)
            axis_u = (bis - side).normalized()
            axis_v = (bis + side).normalized()
            for vi, w in isl["verts"]:
                x, y = self.xy[vi]
                rp = (anchor + (axis_u * (x - cx) + axis_v * (y - cy)) * scale
                      + n * (self.heights[vi] * scale * depth))
                out[vi] = out[vi].lerp(rp, min(w, 1.0))

    def _analyse(self, bm, mw):
        """Find the border loop, its corners and sides, and express every vertex
        as border-corner weights + height; detect an A x B grid or a round border."""
        if not bm.faces:
            raise PatchError("The patch has no faces")
        if any(not e.is_manifold and not e.is_boundary and not e.is_wire for e in bm.edges):
            raise PatchError("The patch has non-manifold edges")

        # --- border loop, ordered along the winding of the patch faces
        nxt = {}
        n_boundary = 0
        for e in bm.edges:
            if not e.is_boundary:
                continue
            n_boundary += 1
            loop = e.link_loops[0]
            a, b = loop.vert.index, loop.link_loop_next.vert.index
            if a in nxt:
                raise PatchError("The patch border touches itself")
            nxt[a] = b
        if not nxt:
            raise PatchError("The patch is closed: it needs one open border")
        start = next(iter(nxt))
        order = [start]
        while True:
            v = nxt.get(order[-1])
            if v is None:
                raise PatchError("The patch border is not a closed loop (flipped normals?)")
            if v == start:
                break
            order.append(v)
            if len(order) > n_boundary:
                raise PatchError("The patch border is not a simple loop")
        if len(order) != n_boundary:
            raise PatchError("The patch must have exactly one open border loop")

        co = [mw @ v.co for v in bm.verts]
        border = [co[i] for i in order]
        corners = _corner_indices(border)
        k = len(corners)
        self.corner_count = k

        # rotate so that the loop starts on a corner
        first = corners[0]
        order = order[first:] + order[:first]
        border = border[first:] + border[:first]
        corners = [c - first for c in corners]

        corner_pts = [border[c] for c in corners]
        normal = _newell(corner_pts)
        self.area = normal.length * 0.5
        if self.area < 1e-12:
            raise PatchError("The patch border has no area")
        normal.normalize()
        origin = sum(corner_pts, Vector((0.0, 0.0, 0.0))) / k
        axis_u = corner_pts[1] - corner_pts[0]
        axis_u -= normal * axis_u.dot(normal)
        axis_u.normalize()
        axis_v = normal.cross(axis_u)

        def to_2d(p):
            d = p - origin
            return (d.dot(axis_u), d.dot(axis_v))

        poly = [to_2d(p) for p in corner_pts]
        # Wachspress gives the cleanest stretch but only exists for convex
        # outlines; mean value coordinates take over for concave borders.
        convex = all(_tri_area_2d(poly[i - 1], poly[i], poly[(i + 1) % k]) > 0.0
                     for i in range(k))
        coords = _wachspress if convex else _mean_value

        # --- per vertex mapping data
        self.weights = [None] * len(co)
        self.heights = [0.0] * len(co)
        self.corner_verts = [order[c] for c in corners]
        self.sides = []            # sides[i] = [(vert index, t)] strictly between corner i and i+1
        n = len(order)
        self._frames = {}
        for i in range(k):
            c0 = corners[i]
            c1 = corners[(i + 1) % k] if i + 1 < k else n
            chain = list(range(c0, c1 + 1))
            lengths = [0.0]
            for j in range(1, len(chain)):
                lengths.append(lengths[-1] + (border[chain[j] % n] - border[chain[j - 1] % n]).length)
            w = [0.0] * k
            w[i] = 1.0
            self.weights[order[c0]] = w
            side = []
            for j in range(1, len(chain) - 1):
                t = lengths[j] / lengths[-1]
                w = [0.0] * k
                w[i] = 1.0 - t
                w[(i + 1) % k] = t
                self.weights[order[chain[j]]] = w
                side.append((order[chain[j]], t))
            self.sides.append(side)

        for i, p in enumerate(co):
            if self.weights[i] is None:
                self.weights[i] = coords(to_2d(p), poly)
                self.heights[i] = (p - origin).dot(normal)

        self.xy = [to_2d(p) for p in co]      # every vertex in the border plane
        self._poly = poly
        self._coords = coords
        self.faces = [[v.index for v in f.verts] for f in bm.faces]
        self.edges = [(e.verts[0].index, e.verts[1].index) for e in bm.edges]
        self.border_set = set(order)

        # --- regular A x B frame?
        self.grid = None
        s = self.sides
        if (k == 4 and len(s[0]) == len(s[2]) and len(s[1]) == len(s[3])
                and (s[0] or s[1])):
            a, b = len(s[0]) + 1, len(s[1]) + 1
            self.grid = (a, b)
            cv = self.corner_verts
            gb = {cv[0]: (0, 0), cv[1]: (a, 0), cv[2]: (a, b), cv[3]: (0, b)}
            for q, (vi, _t) in enumerate(s[0]):
                gb[vi] = (q + 1, 0)
            for q, (vi, _t) in enumerate(s[1]):
                gb[vi] = (a, q + 1)
            for q, (vi, _t) in enumerate(s[2]):
                gb[vi] = (a - 1 - q, b)
            for q, (vi, _t) in enumerate(s[3]):
                gb[vi] = (0, b - 1 - q)
            # params of the grid lines, averaged over the two opposite sides
            tu0 = [0.0] + [t for _v, t in s[0]] + [1.0]
            tu1 = [0.0] + [1.0 - t for _v, t in reversed(s[2])] + [1.0]
            tv0 = [0.0] + [t for _v, t in s[1]] + [1.0]
            tv1 = [0.0] + [1.0 - t for _v, t in reversed(s[3])] + [1.0]
            tu = [(x + y) * 0.5 for x, y in zip(tu0, tu1)]
            tv = [(x + y) * 0.5 for x, y in zip(tv0, tv1)]

            def grid_of(x, y):
                w = coords((x, y), poly)
                return (_to_grid(w[1] + w[2], tu), _to_grid(w[2] + w[3], tv))

            grid_uv = {}
            for i, w in enumerate(self.weights):
                if i not in gb:
                    grid_uv[i] = (_to_grid(w[1] + w[2], tu), _to_grid(w[2] + w[3], tv))
            self._frames = {0: (gb, grid_uv, grid_of)}

        # --- round border (no 4 clear corners): its N vertices are spread
        # over the outline of an A x B patch, 2 * (A + B) = N
        self.round = None
        if self.grid is None and k > 4 and n % 2 == 0:
            a = n // 4
            b = n // 2 - a
            self.grid = (a, b)
            ring = ([(q, 0) for q in range(a)] + [(a, q) for q in range(b)]
                    + [(a - q, b) for q in range(a)] + [(0, b - q) for q in range(b)])
            rpoly = [self.xy[v] for v in order]
            strict = all(_tri_area_2d(rpoly[i - 1], rpoly[i], rpoly[(i + 1) % n]) > 1e-12 * self.area
                         for i in range(n))
            # start with the border vertices that make the biggest quad on the patch corners
            best, start = -1.0, 0
            for shift in range(n):
                q = [rpoly[(c - shift) % n] for c in (0, a, a + b, 2 * a + b)]
                area = abs(_tri_area_2d(q[0], q[1], q[2]) + _tri_area_2d(q[0], q[2], q[3]))
                if area > best * (1.0 + 1e-6):
                    best, start = area, shift
            self.round = {"order": order, "ring": ring, "poly": rpoly, "start": start,
                          "coords": _wachspress if strict else _mean_value}
            self._frames = {}

    @property
    def rot_steps(self):
        """Number of rotation steps in a full turn."""
        if self.round:
            a, b = self.grid
            return len(self.round["order"]) * (1 if a == b else 2)
        return self.corner_count

    def turn_in_place(self, rot, steps):
        """Rotation `rot` turned by `steps` without changing which faces of
        the target are replaced.  A patch that is not square can only do
        half turns in place; a round border slides along its outline."""
        if self.round:
            n = len(self.round["order"])
            a, b = self.grid
            if a != b:
                rot %= 2 * n
                return (rot // n) * n + (rot + steps) % n
            return (rot + steps) % n
        if self.grid and self.grid[0] != self.grid[1]:
            return (rot + 2 * steps) % 4
        return (rot + steps) % self.corner_count

    def frame(self, shift=0):
        """-> (border vertex -> grid point, inner vertex -> grid coordinate,
        function (x, y) -> grid coordinate).  For a round border, `shift`
        slides the border vertices along the outline of the patch."""
        if not self.round:
            return self._frames[0]
        r = self.round
        n = len(r["order"])
        shift = (shift + r["start"]) % n
        if shift not in self._frames:
            a, b = self.grid
            ring = [r["ring"][(i + shift) % n] for i in range(n)]
            gb = {v: ring[i] for i, v in enumerate(r["order"])}
            rpoly, coords = r["poly"], r["coords"]

            def grid_of(x, y):
                w = coords((x, y), rpoly)
                return (min(max(sum(wi * g[0] for wi, g in zip(w, ring)), 0.0), float(a)),
                        min(max(sum(wi * g[1] for wi, g in zip(w, ring)), 0.0), float(b)))

            grid_uv = {i: grid_of(*xy) for i, xy in enumerate(self.xy) if i not in gb}
            self._frames[shift] = (gb, grid_uv, grid_of)
        return self._frames[shift]

    @property
    def label(self):
        """Short description shown in the tool's header, e.g. "2 x 2 faces"."""
        if self.round:
            return "round border, %d x %d faces" % self.grid
        if self.grid:
            return "%d x %d faces" % self.grid
        return "1 face, %d corners" % self.corner_count

    # -- single face mapping -------------------------------------------------

    def map_points(self, corners, normals, rot, depth, rigid=False):
        """World position of every patch vertex for a target face whose K
        corner positions / normals are given.  Patch corner i lands on
        target corner (i + rot) % K."""
        k = self.corner_count
        pts = [corners[(i + rot) % k] for i in range(k)]
        nrm = [normals[(i + rot) % k] for i in range(k)]
        scale = math.sqrt(_newell(corners).length * 0.5 / self.area) * depth

        def blend(w, vecs):
            p = Vector((0.0, 0.0, 0.0))
            for wi, pi in zip(w, vecs):
                if wi:
                    p += pi * wi
            return p

        out = []
        for w, h in zip(self.weights, self.heights):
            p = blend(w, pts)
            if h:
                d = blend(w, nrm)
                if d.length_squared > 1e-20:
                    p += d.normalized() * (h * scale)
            out.append(p)
        if rigid and self.rigid:
            self._apply_rigid(out, lambda x, y: blend(self._coords((x, y), self._poly), pts),
                              depth)
        return out

    # -- A x B patch mapping -------------------------------------------------

    def map_grid(self, P, N, depth, curve, rigid=False, shift=0):
        """World position of every patch vertex for a block whose
        (A+1) x (B+1) vertex positions P[i][j] and normals N[i][j] are given."""
        a, b = self.grid
        grid_border, grid_uv, grid_of = self.frame(shift)
        outline = ([P[i][0] for i in range(a)] + [P[a][j] for j in range(b)]
                   + [P[i][b] for i in range(a, 0, -1)] + [P[0][j] for j in range(b, 0, -1)])
        area_n = _newell(outline)
        scale = math.sqrt(area_n.length * 0.5 / self.area) * depth
        flat_n = area_n.normalized()

        def surface(gu, gv):
            """-> (position, depth direction) at grid coordinate (gu, gv)"""
            i = min(int(gu), a - 1)
            j = min(int(gv), b - 1)
            fu, fv = gu - i, gv - j
            if curve:
                # lie on the original surface of the cell
                p = ((P[i][j] * (1 - fu) + P[i + 1][j] * fu) * (1 - fv)
                     + (P[i][j + 1] * (1 - fu) + P[i + 1][j + 1] * fu) * fv)
                d = ((N[i][j] * (1 - fu) + N[i + 1][j] * fu) * (1 - fv)
                     + (N[i][j + 1] * (1 - fu) + N[i + 1][j + 1] * fu) * fv)
                return p, (d.normalized() if d.length_squared > 1e-20 else flat_n)
            # Coons patch: a membrane stretched between the four border polylines
            U, V = gu / a, gv / b
            bottom = P[i][0].lerp(P[i + 1][0], fu)
            top = P[i][b].lerp(P[i + 1][b], fu)
            left = P[0][j].lerp(P[0][j + 1], fv)
            right = P[a][j].lerp(P[a][j + 1], fv)
            p = (bottom * (1 - V) + top * V + left * (1 - U) + right * U
                 - (P[0][0] * (1 - U) * (1 - V) + P[a][0] * U * (1 - V)
                    + P[a][b] * U * V + P[0][b] * (1 - U) * V))
            return p, flat_n

        out = []
        for vi, h in enumerate(self.heights):
            ij = grid_border.get(vi)
            if ij is not None:
                out.append(P[ij[0]][ij[1]].copy())
                continue
            p, d = surface(*grid_uv[vi])
            out.append(p + d * (h * scale))

        if rigid and self.rigid:
            self._apply_rigid(out, lambda x, y: surface(*grid_of(x, y))[0], depth)
        return out


# --------------------------------------------------------------------------
# target mesh
# --------------------------------------------------------------------------

def _grid_step(loop, direction):
    """Walk from a quad to its neighbour. `loop` is the 'bottom' loop of the
    quad (its edge runs along +u); the returned loop is the neighbour's."""
    if direction == '+u':
        e = loop.link_loop_next
    elif direction == '+v':
        e = loop.link_loop_next.link_loop_next
    elif direction == '-u':
        e = loop.link_loop_prev
    else:
        e = loop
    r = e.link_loop_radial_next
    if r is e or len(e.edge.link_faces) != 2:
        raise PatchError("the patch runs off the mesh")
    if len(r.face.loops) != 4:
        raise PatchError("the patch needs quads only")
    if r.vert is e.vert:
        raise PatchError("inconsistent normals")
    if direction == '+u':
        return r.link_loop_next
    if direction == '+v':
        return r
    if direction == '-u':
        return r.link_loop_prev
    return r.link_loop_next.link_loop_next


class Target:
    """One target object while the tool runs: a bmesh copy of its mesh, a BVH
    for ray casts, and the snapshots for the in-tool undo.  Every change is
    made on the bmesh and written back to the object at once (_write)."""

    def __init__(self, obj):
        self.name = obj.name
        self.bm = bmesh.new()
        self.bm.from_mesh(obj.data)
        self.mw = obj.matrix_world.copy()
        self.inv = self.mw.inverted_safe()
        self.nmat = self.inv.transposed().to_3x3()
        self.group_index = None      # index of the "base" group once shrinkwrap is set up
        self.shrink_level = None     # history length from which the shrinkwrap setup exists
        self.shrink_made = None      # (modifier, copy, vertex group) names this session created
        self.mat_index = {}          # patch material name -> slot on this target
        self.history = []            # mesh snapshots, one per stamp, for Ctrl+Z in the tool
        self.refresh()

    def refresh(self):
        """Rebuild normals, lookup tables and the BVH after the bmesh changed."""
        self.bm.normal_update()
        self.bm.verts.ensure_lookup_table()
        self.bm.edges.ensure_lookup_table()
        self.bm.faces.ensure_lookup_table()
        self.bm.verts.index_update()
        self.bm.faces.index_update()
        self.bvh = BVHTree.FromBMesh(self.bm) if self.bm.faces else None

    def free(self):
        for snap in self.history:
            snap.free()
        self.history = []
        self.bm.free()

    def snapshot(self):
        """Keep a copy of the mesh before a stamp (in-tool undo)."""
        self.history.append(self.bm.copy())

    def restore(self):
        """Go back to the last snapshot. Returns False when there is none."""
        if not self.history:
            return False
        self.bm.free()
        self.bm = self.history.pop()
        self.refresh()
        self._write()
        if self.shrink_level is not None and len(self.history) < self.shrink_level:
            self._drop_shrinkwrap()
        return True

    def _drop_shrinkwrap(self):
        """The stamp that set the shrinkwrap up was undone: take the hidden
        copy, the modifier and the vertex group away again (only what this
        session made itself)."""
        obj = bpy.data.objects[self.name]
        mod_name, ref_name, group_name = self.shrink_made or (None, None, None)
        self.group_index = self.shrink_level = self.shrink_made = None
        mod = obj.modifiers.get(mod_name) if mod_name else None
        if mod is not None:
            obj.modifiers.remove(mod)
        ref = bpy.data.objects.get(ref_name) if ref_name else None
        if ref is not None:
            mesh = ref.data
            bpy.data.objects.remove(ref)
            if mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        vg = obj.vertex_groups.get(group_name) if group_name else None
        if vg is not None:
            obj.vertex_groups.remove(vg)

    def _write(self):
        """Write the bmesh back to the object's mesh."""
        obj = bpy.data.objects[self.name]
        self.bm.to_mesh(obj.data)
        obj.data.update()

    def ray_cast(self, origin, direction):
        """-> (world distance, (face index, half_u, half_v)) or None.
        half_u / half_v tell in which half of a quad the hit is, relative to
        the face's first loop; used to centre even sized patches."""
        if self.bvh is None:
            return None
        o = self.inv @ origin
        d = (self.inv.to_3x3() @ direction).normalized()
        loc, _nor, index, _dist = self.bvh.ray_cast(o, d)
        if loc is None:
            return None
        hu = hv = 0
        vs = [v.co for v in self.bm.faces[index].verts]
        if len(vs) == 4:
            mid = [(vs[i] + vs[(i + 1) % 4]) * 0.5 for i in range(4)]   # bottom,right,top,left
            hu = int((loc - mid[1]).length < (loc - mid[3]).length)
            hv = int((loc - mid[2]).length < (loc - mid[0]).length)
        return ((self.mw @ loc) - origin).length, (index, hu, hv)

    def prepare_shrinkwrap(self, group):
        """Keep the original shape around: hide a copy of the object and
        shrinkwrap this one onto it, limited to the vertex group `group`.
        Existing vertices join the group (when it is new) so that only the
        patch vertices outside the group are free to leave the surface."""
        if self.group_index is not None:
            return
        obj = bpy.data.objects[self.name]
        mod = next((m for m in obj.modifiers
                    if m.type == 'SHRINKWRAP'
                    and m.name.startswith((SHRINKWRAP_NAME, OLD_SHRINKWRAP_NAME))
                    and m.target is not None), None)
        made_mod = made_ref = None
        if mod is None:
            ref = obj.copy()
            ref.data = obj.data.copy()
            ref.name = obj.name + REF_SUFFIX
            for coll in obj.users_collection:
                coll.objects.link(ref)
            ref.hide_render = True
            try:
                ref.select_set(False)
                ref.hide_set(True)
            except RuntimeError:
                ref.hide_viewport = True
            mod = obj.modifiers.new(SHRINKWRAP_NAME, 'SHRINKWRAP')
            mod.target = ref
            mod.wrap_method = 'NEAREST_SURFACEPOINT'
            mod.show_expanded = False
            made_mod, made_ref = mod.name, ref.name
            # the subdivision has to smooth the wrapped cage, not the other way round
            mods = list(obj.modifiers)
            first = next((i for i, m in enumerate(mods) if m.type in {'SUBSURF', 'MULTIRES'}), None)
            if first is not None and first < len(mods) - 1:
                obj.modifiers.move(len(mods) - 1, first)
        vg = obj.vertex_groups.get(group)
        fresh = vg is None
        if fresh:
            vg = obj.vertex_groups.new(name=group)
        mod.vertex_group = vg.name
        layer = self.bm.verts.layers.deform.verify()
        if fresh:
            for v in self.bm.verts:
                v[layer][vg.index] = 1.0
        self.group_index = vg.index
        self.shrink_level = len(self.history)
        self.shrink_made = (made_mod, made_ref, vg.name if fresh else None)
        self.refresh()

    def prepare_data(self, patch, uv_source):
        """Make room on the target for what the patch brings: attribute
        layers, UV maps and material slots."""
        bm = self.bm
        if any(d[2] for d in patch.edge_data.values()) and not bm.edges.layers.float.get("crease_edge"):
            bm.edges.layers.float.new("crease_edge")
        if any(d[3] for d in patch.edge_data.values()) and not bm.edges.layers.float.get("bevel_weight_edge"):
            bm.edges.layers.float.new("bevel_weight_edge")
        if patch.vert_crease and not bm.verts.layers.float.get("crease_vert"):
            bm.verts.layers.float.new("crease_vert")
        if patch.uv and uv_source != 'TARGET' and not bm.loops.layers.uv:
            for name in patch.uv:
                bm.loops.layers.uv.new(name)
        mats = bpy.data.objects[self.name].data.materials
        self.mat_index = {}
        for name in set(patch.face_material):
            mat = bpy.data.materials.get(name) if name else None
            if mat is None:
                continue
            index = next((i for i, m in enumerate(mats) if m == mat), None)
            if index is None:
                if len(mats) == 0:
                    mats.append(None)      # the faces already there keep "no material"
                mats.append(mat)
                index = len(mats) - 1
            self.mat_index[name] = index
        self.refresh()

    def _world_normal(self, n):
        """Local normal -> unit world normal."""
        return (self.nmat @ n).normalized()

    # -- planning: what would a stamp here do? -------------------------------

    def plan(self, patch, hover, rot, depth, curve, rigid=False):
        """Describe the stamp at `hover` without touching the mesh.
        -> dict(valid, message, fills, outline, marker, world, + commit data)"""
        face = self.bm.faces[hover[0]]
        plan = self._plan(patch, face, hover, rot, depth, curve, rigid)
        plan["rigid"] = bool(rigid and patch.rigid)
        return plan

    def _plan(self, patch, face, hover, rot, depth, curve, rigid):
        """Pick the stamping mode for this face: single face (FACE) or A x B block (GRID)."""
        if patch.round:
            # a face with as many corners as the border takes the patch directly
            outline = [self.mw @ v.co for v in face.verts]
            if len(_corner_indices(outline)) == patch.corner_count:
                return self._plan_face(patch, face, rot, depth, curve, rigid)
        if patch.grid:
            try:
                return self._plan_grid(patch, face, hover[1], hover[2], rot, depth, curve,
                                       rigid)
            except PatchError as ex:
                outline = [self.mw @ v.co for v in face.verts]
                return {"valid": False, "message": str(ex),
                        "fills": [outline], "outline": outline}
        return self._plan_face(patch, face, rot, depth, curve, rigid)

    def _plan_face(self, patch, face, rot, depth, curve, rigid):
        """FACE mode: the patch replaces this one face, its corners on the face's corners."""
        verts = list(face.verts)
        outline = [self.mw @ v.co for v in verts]
        corners = _corner_indices(outline)
        k = patch.corner_count
        plan = {"valid": False, "message": "", "fills": [outline], "outline": outline}
        if len(corners) != k:
            plan["message"] = "face has %d corners, patch border has %d" % (len(corners), k)
            return plan
        points = [outline[c] for c in corners]
        if curve:
            normals = [self._world_normal(verts[c].normal) for c in corners]
        else:
            normals = [self._world_normal(face.normal)] * k
        plan.update(valid=True, mode='FACE', face=face, verts=verts, corners=corners,
                    world=patch.map_points(points, normals, rot, depth, rigid),
                    marker=[points[rot % k], points[(rot + 1) % k]])
        return plan

    def _plan_grid(self, patch, face, hu, hv, rot, depth, curve, rigid):
        """GRID mode: walk the quads around `face` to collect the A x B block
        (centred on the cursor) and its (A+1) x (B+1) vertices."""
        a, b = patch.grid
        if len(face.loops) != 4:
            raise PatchError("the patch needs quads only")
        shift = 0
        if patch.round:
            # one step = one border vertex further along the outline of the patch
            n = len(patch.round["order"])
            shift, rot = rot % n, (rot // n if a != b else 0)
        rot %= 4
        for _ in range(rot):
            hu, hv = hv, 1 - hu
        # which cell of the patch is the hovered face (keeps the patch centred on the cursor)
        iu = (a - 1) // 2 if a % 2 else (a // 2 - 1 if hu else a // 2)
        iv = (b - 1) // 2 if b % 2 else (b // 2 - 1 if hv else b // 2)
        loop = face.loops[rot]
        for _ in range(iu):
            loop = _grid_step(loop, '-u')
        for _ in range(iv):
            loop = _grid_step(loop, '-v')

        G = [[None] * (b + 1) for _ in range(a + 1)]

        def put(i, j, v):
            if G[i][j] is None:
                G[i][j] = v
            elif G[i][j] is not v:
                raise PatchError("the faces here do not form a regular %d x %d grid" % (a, b))

        faces = []
        cells = [[None] * b for _ in range(a)]     # the 'bottom' loop of every patch face
        column = loop
        for i in range(a):
            cell = column
            for j in range(b):
                faces.append(cell.face)
                cells[i][j] = cell
                nx = cell.link_loop_next
                put(i, j, cell.vert)
                put(i + 1, j, nx.vert)
                put(i + 1, j + 1, nx.link_loop_next.vert)
                put(i, j + 1, cell.link_loop_prev.vert)
                if j < b - 1:
                    cell = _grid_step(cell, '+v')
            if i < a - 1:
                column = _grid_step(column, '+u')
        flat = [v for col in G for v in col]
        if len(set(flat)) != len(flat) or len(set(faces)) != len(faces):
            raise PatchError("the mesh is too small for a %d x %d patch" % (a, b))

        P = [[self.mw @ v.co for v in col] for col in G]
        N = [[self._world_normal(v.normal) for v in col] for col in G]
        outline = ([P[i][0] for i in range(a)] + [P[a][j] for j in range(b)]
                   + [P[i][b] for i in range(a, 0, -1)] + [P[0][j] for j in range(b, 0, -1)])
        border = patch.frame(shift)[0]
        marker = []
        if patch.round:
            ij0, ij1 = (border[v] for v in patch.round["order"][:2])
            marker = [P[ij0[0]][ij0[1]], P[ij1[0]][ij1[1]]]
        else:
            for i in range(a):
                marker += [P[i][0], P[i + 1][0]]
        return {"valid": True, "message": "", "mode": 'GRID', "face": face,
                "faces": faces, "G": G, "border": border, "cells": cells, "shift": shift,
                "fills": [[self.mw @ v.co for v in f.verts] for f in faces],
                "outline": outline, "marker": marker,
                "world": patch.map_grid(P, N, depth, curve, rigid, shift)}

    # -- committing ----------------------------------------------------------

    def _uv_sampler(self, patch, plan, rot, uv_layers):
        """-> function (layer number, patch face, corner of that face) giving
        the UV the replaced faces had at that spot.  Has to be built before
        the faces are removed."""
        if plan["mode"] == 'GRID':
            a, b = patch.grid
            cells = plan["cells"]
            data = [[[[lp[layer].uv.copy() for lp in (c, c.link_loop_next,
                                                      c.link_loop_next.link_loop_next,
                                                      c.link_loop_prev)]
                      for c in column] for column in cells] for layer in uv_layers]
            border, inner, _grid_of = patch.frame(plan["shift"])
            centres = {}

            def sample(li, fi, ci):
                pts = [border[v] if v in border else inner[v] for v in patch.faces[fi]]
                if fi not in centres:
                    centres[fi] = (sum(q[0] for q in pts) / len(pts), sum(q[1] for q in pts) / len(pts))
                cu, cv = centres[fi]
                gu, gv = pts[ci]
                # a vertex on a grid line belongs to the cell its face lies in
                # (matters where the patch crosses a UV seam)
                i = min(max(int(gu + (cu - gu) * 1e-3), 0), a - 1)
                j = min(max(int(gv + (cv - gv) * 1e-3), 0), b - 1)
                fu, fv = min(max(gu - i, 0.0), 1.0), min(max(gv - j, 0.0), 1.0)
                q = data[li][i][j]
                return (q[0] * (1 - fu) + q[1] * fu) * (1 - fv) + (q[3] * (1 - fu) + q[2] * fu) * fv
            return sample

        k = patch.corner_count
        loops = list(plan["face"].loops)
        data = [[loops[c][layer].uv.copy() for c in plan["corners"]] for layer in uv_layers]

        def sample(li, fi, ci):
            uv = Vector((0.0, 0.0))
            for i, w in enumerate(patch.weights[patch.faces[fi][ci]]):
                if w:
                    uv += data[li][(i + rot) % k] * w
            return uv
        return sample

    def commit(self, patch, plan, rot, uv_source='AUTO'):
        """Apply a valid plan to the mesh. Returns the number of new faces."""
        bm = self.bm
        material, smooth = plan["face"].material_index, plan["face"].smooth
        uv_layers = list(bm.loops.layers.uv.values())
        uv_active = bm.loops.layers.uv.active.name if uv_layers else None
        sample = self._uv_sampler(patch, plan, rot, uv_layers) if uv_layers else None
        if plan["mode"] == 'GRID':
            vmap = self._open_grid(patch, plan)
        else:
            vmap = self._open_face(patch, plan, rot)

        world = plan["world"]
        layer = bm.verts.layers.deform.verify() if self.group_index is not None else None
        vcrease = bm.verts.layers.float.get("crease_vert")
        count = 0
        for fi, fverts in enumerate(patch.faces):
            fv = []
            for vi in fverts:
                bv = vmap.get(vi)
                if bv is None:
                    bv = vmap[vi] = bm.verts.new(self.inv @ world[vi])
                    if layer is not None and patch.base:
                        weight = patch.base[vi]
                        if plan.get("rigid"):      # a rigid vertex must not be pulled back
                            weight *= 1.0 - patch.rigid_weight.get(vi, 0.0)
                        if weight > 0.0:
                            bv[layer][self.group_index] = weight
                    if vcrease is not None and vi in patch.vert_crease:
                        bv[vcrease] = patch.vert_crease[vi]
                fv.append(bv)
            try:
                nf = bm.faces.new(fv)
            except ValueError:        # face already exists / degenerate
                continue
            own = patch.face_material[fi] in self.mat_index
            nf.material_index = self.mat_index[patch.face_material[fi]] if own else material
            nf.smooth = patch.face_smooth[fi] if patch.any_smooth else smooth
            from_patch = uv_source == 'PATCH' or (uv_source == 'AUTO' and own)
            for li, uvl in enumerate(uv_layers):
                src = None
                if from_patch:
                    src = patch.uv.get(uvl.name)
                    if src is None and uvl.name == uv_active and patch.uv_active:
                        src = patch.uv[patch.uv_active]
                for ci, lp in enumerate(nf.loops):
                    lp[uvl].uv = src[fi][ci] if src else sample(li, fi, ci)
            count += 1

        crease = bm.edges.layers.float.get("crease_edge")
        bevel = bm.edges.layers.float.get("bevel_weight_edge")
        for (va, vb), (sharp, seam, cr, bw) in patch.edge_data.items():
            if va not in vmap or vb not in vmap:
                continue
            e = bm.edges.get((vmap[va], vmap[vb]))
            if e is None:
                continue
            if sharp:
                e.smooth = False
            if seam:
                e.seam = True
            if crease is not None and cr:
                e[crease] = cr
            if bevel is not None and bw:
                e[bevel] = bw

        self.refresh()
        self._write()
        return count

    def _open_grid(self, patch, plan):
        """Remove the A x B block; border vertices of the patch map onto the
        existing vertices around the hole."""
        bm = self.bm
        a, b = patch.grid
        G = plan["G"]
        block = set(plan["faces"])
        inner_edges = {e for f in block for e in f.edges
                       if len(e.link_faces) == 2 and all(lf in block for lf in e.link_faces)}
        inner_verts = [G[i][j] for i in range(1, a) for j in range(1, b)]
        bmesh.ops.delete(bm, geom=list(block), context='FACES_ONLY')
        if inner_edges:
            bmesh.ops.delete(bm, geom=list(inner_edges), context='EDGES')
        inner_verts = [v for v in inner_verts if v.is_valid]   # some die with their edges
        if inner_verts:
            bmesh.ops.delete(bm, geom=inner_verts, context='VERTS')
        return {vi: G[i][j] for vi, (i, j) in plan["border"].items()}

    def _open_face(self, patch, plan, rot):
        """Remove one face; patch corners map onto its corners, extra border
        vertices split its edges (or reuse vertices already sitting there)."""
        bm = self.bm
        k = patch.corner_count
        verts, corners = plan["verts"], plan["corners"]
        bmesh.ops.delete(bm, geom=[plan["face"]], context='FACES_ONLY')
        vmap = {}
        n = len(verts)
        for i in range(k):
            ti = (i + rot) % k
            c0 = corners[ti]
            c1 = corners[(ti + 1) % k]
            span = (c1 - c0) % n or n
            chain = [verts[(c0 + j) % n] for j in range(span + 1)]
            vmap[patch.corner_verts[i]] = chain[0]
            side = patch.sides[i]
            if not side:
                continue
            params = [0.0]
            for j in range(1, len(chain)):
                params.append(params[-1] + (chain[j].co - chain[j - 1].co).length)
            params = [p / params[-1] for p in params]
            for sv, t in side:
                j = min(range(len(params)), key=lambda q: abs(params[q] - t))
                if abs(params[j] - t) < PARAM_TOL:
                    vmap[sv] = chain[j]
                    continue
                j = max(q for q in range(len(params) - 1) if params[q] < t)
                va, vb = chain[j], chain[j + 1]
                fac = (t - params[j]) / (params[j + 1] - params[j])
                edge = bm.edges.get((va, vb))
                if edge is None:
                    edge = bm.edges.new((va, vb))
                target_co = va.co.lerp(vb.co, fac)
                _new_edge, new_vert = bmesh.utils.edge_split(edge, va, fac)
                new_vert.co = target_co
                chain.insert(j + 1, new_vert)
                params.insert(j + 1, t)
                vmap[sv] = new_vert
        return vmap


# --------------------------------------------------------------------------
# interactive session (kept separate from the operator so it can be scripted)
# --------------------------------------------------------------------------

class Session:
    """The tool without its UI: one patch, its targets, the current rotation /
    depth / curve / rigid state and the undo stack.  The modal operator, the
    redo (execute) and the tests all work through this class."""

    def __init__(self, context, shrinkwrap=False, group="base",
                 patch_name=None, target_names=None, rigid=True, rigid_group="rigid",
                 uv_source='AUTO'):
        self.shrinkwrap = shrinkwrap
        self.uv_source = uv_source
        self.group = group
        self.rigid = rigid
        self.rigid_group = rigid_group
        self.patch_name = patch_name or context.view_layer.objects.active.name
        self.target_names = target_names or [
            o.name for o in context.selected_objects
            if o.type == 'MESH' and o.name != self.patch_name]
        if not self.target_names:
            self.target_names = [o.name for o in context.visible_objects
                                 if o.type == 'MESH' and o.name != self.patch_name
                                 and not o.name.endswith((REF_SUFFIX, OLD_REF_SUFFIX))]
        if not self.target_names:
            raise PatchError("No target mesh: select the meshes to stamp, then the patch last")
        self.rot = 0
        self.depth = 1.0
        self.curve = True
        self.hover = None          # (target index, (face index, half_u, half_v))
        self.hover_point = None    # world position under the cursor
        self.message = ""
        self.targets = []
        self._batches = None
        self._draw_error_reported = False
        self.patch = None
        self.undo_stack = []       # target index of every stamp, oldest first
        self.dirty = False         # did this session change the scene at all?
        self.reload()

    def reload(self):
        """(Re)read every mesh from the scene, e.g. after an undo."""
        for t in self.targets:
            t.free()
        self.patch = Patch(bpy.data.objects[self.patch_name], self.group,
                               self.rigid_group)
        self.targets = [Target(bpy.data.objects[n]) for n in self.target_names
                        if n in bpy.data.objects]
        self.hover = None
        self._batches = None

    def free(self):
        """Free every target's bmesh and snapshots."""
        for t in self.targets:
            t.free()
        self.targets = []

    # -- state changes -----------------------------------------------------

    def set_hover(self, hover):
        """Change the hovered spot; the preview is rebuilt only when it changes."""
        if hover != self.hover:
            self.hover = hover
            self._batches = None
            if hover is None:
                self.message = ""

    def pick(self, origin, direction):
        """Ray cast every target; hover the nearest hit (or nothing)."""
        best = None
        for ti, t in enumerate(self.targets):
            hit = t.ray_cast(origin, direction)
            if hit and (best is None or hit[0] < best[0]):
                best = (hit[0], ti, hit[1])
        self.set_hover((best[1], best[2]) if best else None)
        self.hover_point = origin + direction.normalized() * best[0] if best else None

    def rotate(self, step):
        """Rotate by `step` steps (90 deg, or one border vertex for a round patch)."""
        self.rot = (self.rot + step) % self.patch.rot_steps
        self._batches = None

    def scale_depth(self, factor):
        """Multiply the depth of the patch, kept between 0.01 and 100."""
        self.depth = min(max(self.depth * factor, 0.01), 100.0)
        self._batches = None

    def toggle_curve(self):
        """C in the tool."""
        self.curve = not self.curve
        self._batches = None

    def toggle_rigid(self):
        """R in the tool."""
        self.rigid = not self.rigid
        self._batches = None

    def make_plan(self):
        """Plan of a stamp at the hovered spot with the current settings (None: nothing hovered)."""
        if self.hover is None:
            return None
        ti, hov = self.hover
        return self.targets[ti].plan(self.patch, hov, self.rot, self.depth, self.curve,
                                     self.rigid)

    def apply(self):
        """Stamp at the hovered location. Returns True on success."""
        plan = self.make_plan()
        if plan is None:
            return False
        self.message = plan["message"]
        if not plan["valid"]:
            return False
        target = self.targets[self.hover[0]]
        target.snapshot()
        self.undo_stack.append(self.hover[0])
        self.dirty = True
        if self.shrinkwrap and target.group_index is None:
            target.prepare_shrinkwrap(self.group)
        target.prepare_data(self.patch, self.uv_source)
        plan = self.make_plan()              # the mesh layers changed: plan again
        target.commit(self.patch, plan, self.rot, self.uv_source)
        self.hover = None
        self._batches = None
        return True

    def replay(self, stamps):
        """Stamp again from a record: (point, direction, rot, depth, curve,
        rigid) for every stamp, in order.  Returns how many succeeded."""
        done = 0
        for point, direction, rot, depth, curve, rigid in stamps:
            point = Vector(point)
            direction = Vector(direction).normalized()
            self.rot = rot % self.patch.rot_steps
            self.depth, self.curve, self.rigid = depth, curve, rigid
            # look at the recorded spot from just above the surface
            self.pick(point - direction * (1e-4 * max(1.0, point.length)), direction)
            done += bool(self.apply())
        return done

    def undo(self):
        """Take back the last stamp of this session. Returns True if there was one."""
        if not self.undo_stack:
            self.message = "nothing to undo"
            return False
        self.targets[self.undo_stack.pop()].restore()
        self.hover = None
        self._batches = None
        self.message = "stamp undone (%d left)" % len(self.undo_stack)
        return True

    # -- drawing -----------------------------------------------------------

    def _build_batches(self):
        """GPU batches of the preview for the current plan."""
        plan = self.make_plan()
        self.message = plan["message"]
        valid = plan["valid"]

        tri_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')

        tris = []
        for poly in plan["fills"]:
            for i in range(1, len(poly) - 1):
                tris += [poly[0], poly[i], poly[i + 1]]
        outline = plan["outline"]
        loop = []
        for i, p in enumerate(outline):
            loop += [p, outline[(i + 1) % len(outline)]]

        fill, edge = _pref("fill"), _pref("outline")
        if not valid:
            edge = _pref("invalid")
            fill = edge[:3] + (edge[3] * 0.35,)
        width = _pref("outline_width")
        batches = [
            (tri_shader, batch_for_shader(tri_shader, 'TRIS', {"pos": tris}), fill, None),
            (line_shader, batch_for_shader(line_shader, 'LINES', {"pos": loop}), edge, width),
        ]
        if valid:
            st = self.patch
            world = plan["world"]
            wires = []
            for a, b in st.edges:
                if a in st.border_set and b in st.border_set:
                    continue
                wires += [world[a], world[b]]
            if wires:
                batches.append((line_shader, batch_for_shader(line_shader, 'LINES', {"pos": wires}),
                                _pref("wire"), _pref("wire_width")))
            # orientation marker: first side of the patch border
            batches.append((line_shader,
                            batch_for_shader(line_shader, 'LINES', {"pos": plan["marker"]}),
                            _pref("marker"), width + 2.0))
        return batches

    def draw(self):
        """Viewport draw callback: highlight of the faces to replace, outline,
        stretched patch edges and the rotation marker."""
        if self.hover is None:
            return
        if self._batches is None:
            try:
                self._batches = self._build_batches()
            except Exception:
                # A draw callback that raises would print on every redraw: draw
                # nothing instead, but report the first error so it is not lost.
                self._batches = []
                if not self._draw_error_reported:
                    self._draw_error_reported = True
                    import traceback
                    traceback.print_exc()
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        viewport = gpu.state.viewport_get()[2:]
        for shader, batch, color, width in self._batches:
            shader.bind()
            if width is not None:
                shader.uniform_float("viewportSize", viewport)
                shader.uniform_float("lineWidth", width)
            shader.uniform_float("color", color)
            batch.draw(shader)
        gpu.state.blend_set('NONE')


# --------------------------------------------------------------------------
# operator
# --------------------------------------------------------------------------

_NAV_EVENTS = {
    'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'WHEELINMOUSE', 'WHEELOUTMOUSE',
    'TRACKPADPAN', 'TRACKPADZOOM', 'MOUSEROTATE', 'MOUSESMARTZOOM',
    'NDOF_MOTION', 'NUMPAD_0', 'NUMPAD_1', 'NUMPAD_2', 'NUMPAD_3', 'NUMPAD_4',
    'NUMPAD_5', 'NUMPAD_6', 'NUMPAD_7', 'NUMPAD_8', 'NUMPAD_9', 'NUMPAD_PERIOD',
    'NUMPAD_PLUS', 'NUMPAD_MINUS', 'NUMPAD_SLASH', 'ACCENT_GRAVE', 'HOME',
}


# One stamp of a tool run, recorded so that execute() can replay it (redo).
class TopologyPatchesStamp(bpy.types.PropertyGroup):
    point: bpy.props.FloatVectorProperty(size=3)
    direction: bpy.props.FloatVectorProperty(size=3)
    rot: bpy.props.IntProperty()
    depth: bpy.props.FloatProperty(default=1.0)
    curve: bpy.props.BoolProperty(default=True)
    rigid: bpy.props.BoolProperty(default=True)


class OBJECT_OT_topology_patches(bpy.types.Operator):
    """Replace hovered faces of the selected meshes with the active mesh, stretched to fit"""
    bl_idname = "object.topology_patches"
    bl_label = "Topology Patches"
    bl_options = {'REGISTER', 'UNDO'}

    # what "Adjust Last Operation" shows: the settings of the last stamp
    stamps: bpy.props.CollectionProperty(type=TopologyPatchesStamp, options={'HIDDEN', 'SKIP_SAVE'})
    rotation: bpy.props.IntProperty(
        name="Rotation", description="Turn the last stamp in place: it keeps replacing the "
                                     "same faces. A patch that is not square turns by half turns",
        soft_min=-16, soft_max=16, default=0, options={'SKIP_SAVE'})
    depth: bpy.props.FloatProperty(
        name="Depth", description="Depth multiplier of the last stamp",
        min=0.01, max=100.0, default=1.0, options={'SKIP_SAVE'})
    curve: bpy.props.BoolProperty(
        name="Curve", description="Curve the last stamp onto the original surface",
        default=True, options={'SKIP_SAVE'})
    rigid: bpy.props.BoolProperty(
        name="Keep Rigid Shapes", description="Keep the rigid vertex group of the last stamp "
                                              "undistorted",
        default=True, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        obj = context.view_layer.objects.active
        return (context.mode == 'OBJECT' and context.area is not None
                and context.area.type == 'VIEW_3D'
                and obj is not None and obj.type == 'MESH')

    def _new_session(self, context):
        """A Session with the sidebar options of this scene."""
        opts = context.scene.topology_patches
        return Session(context, opts.use_shrinkwrap, opts.group.strip() or "base",
                       rigid=opts.use_rigid, rigid_group=opts.rigid_group.strip() or "rigid",
                       uv_source=opts.uv_source)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        if len(self.stamps) > 1:
            layout.label(text="Last of %d stamps" % len(self.stamps))
        layout.prop(self, "rotation")
        layout.prop(self, "depth")
        layout.prop(self, "curve")
        layout.prop(self, "rigid")

    def execute(self, context):
        """Redo: stamp everything again from the record, the last stamp with
        the values of the panel."""
        if not self.stamps:
            return {'CANCELLED'}
        # Blender has just undone the previous result: until the scene is
        # evaluated again the objects still lack their world transform, and
        # the recorded world positions would land on the wrong faces
        context.view_layer.update()
        try:
            session = self._new_session(context)
        except PatchError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        items = [(tuple(st.point), tuple(st.direction), st.rot, st.depth, st.curve, st.rigid)
                 for st in self.stamps]
        rot = session.patch.turn_in_place(self.stamps[-1].rot, self.rotation)
        items[-1] = items[-1][:2] + (rot, self.depth, self.curve, self.rigid)
        try:
            done = session.replay(items)
        finally:
            session.free()
        if done < len(items):
            self.report({'WARNING'}, "%d of %d stamps could not be redone" % (len(items) - done,
                                                                              len(items)))
        return {'FINISHED'} if done else {'CANCELLED'}

    def invoke(self, context, event):
        self.stamps.clear()
        self._direction = None
        try:
            self.session = self._new_session(context)
        except PatchError as ex:
            self.report({'ERROR'}, str(ex))
            return {'CANCELLED'}
        self.area = context.area
        self.region = context.region
        self.rv3d = context.region_data
        self.handle = bpy.types.SpaceView3D.draw_handler_add(
            self.session.draw, (), 'WINDOW', 'POST_VIEW')
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('CROSSHAIR')
        self._update_hover(event)
        self._update_ui(context)
        return {'RUNNING_MODAL'}

    # -- helpers -----------------------------------------------------------

    def _inside(self, event):
        """Is the mouse inside the viewport region the tool was started in?"""
        r = self.region
        return (0 <= event.mouse_x - r.x < r.width) and (0 <= event.mouse_y - r.y < r.height)

    def _update_hover(self, event):
        """Ray from the mouse position into the scene."""
        if not self._inside(event):
            self.session.set_hover(None)
            return
        coord = (event.mouse_x - self.region.x, event.mouse_y - self.region.y)
        direction = view3d_utils.region_2d_to_vector_3d(self.region, self.rv3d, coord)
        self._direction = direction.copy()
        origin = view3d_utils.region_2d_to_origin_3d(self.region, self.rv3d, coord)
        if not self.rv3d.is_perspective:
            origin = origin - direction * 10000.0
        self.session.pick(origin, direction)

    def _update_ui(self, context):
        """Header text with the keys and the current settings."""
        s = self.session
        k = len(s.patch.round["order"]) if s.patch.round else s.patch.corner_count
        text = ("Topology Patches (%s)  |  LMB: stamp   ←/→: rotate (%d°)   "
                "↑/↓: depth x%.2f   C: curve %s   R: rigid %s   Ctrl+Z: undo   "
                "Esc/RMB/Enter: finish"
                % (s.patch.label, round(360.0 * (s.rot % k) / k), s.depth,
                   "ON" if s.curve else "OFF",
                   ("ON" if s.rigid else "OFF") if s.patch.rigid else "(no group)"))
        if s.shrinkwrap:
            text += "   [shrinkwrap: %s]" % s.group
        if s.message:
            text += "   — " + s.message
        self.area.header_text_set(text)
        self.area.tag_redraw()

    def _finish(self, context):
        """Remove the preview and the header text, free the session."""
        bpy.types.SpaceView3D.draw_handler_remove(self.handle, 'WINDOW')
        context.window.cursor_modal_restore()
        self.area.header_text_set(None)
        self.area.tag_redraw()
        self.session.free()

    # -- modal -------------------------------------------------------------

    def modal(self, context, event):
        s = self.session
        et, press = event.type, event.value == 'PRESS'

        if et in {'ESC', 'RIGHTMOUSE', 'RET', 'NUMPAD_ENTER'}:
            if press:
                changed = s.dirty
                if len(self.stamps):
                    last = self.stamps[-1]
                    self.rotation, self.depth = 0, last.depth
                    self.curve, self.rigid = last.curve, last.rigid
                self._finish(context)
                # FINISHED registers one undo step for everything stamped in this run
                return {'FINISHED'} if changed else {'CANCELLED'}
            return {'RUNNING_MODAL'}

        if et == 'MOUSEMOVE':
            self._update_hover(event)
            self._update_ui(context)
            return {'PASS_THROUGH'}

        if not self._inside(event):
            return {'PASS_THROUGH'}        # let the rest of the UI work

        if event.ctrl and et in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            s.rotate(1 if et == 'WHEELUPMOUSE' else -1)
        elif et in _NAV_EVENTS:
            return {'PASS_THROUGH'}
        elif not press:
            return {'RUNNING_MODAL'}
        elif et == 'LEFTMOUSE':
            point, direction = s.hover_point, self._direction
            state = (s.rot, s.depth, s.curve, s.rigid)
            if s.apply():
                st = self.stamps.add()
                st.point, st.direction = point, direction
                st.rot, st.depth, st.curve, st.rigid = state
                self._update_hover(event)
        elif et == 'RIGHT_ARROW':
            s.rotate(1)
        elif et == 'LEFT_ARROW':
            s.rotate(-1)
        elif et == 'UP_ARROW':
            s.scale_depth(1.1)
        elif et == 'DOWN_ARROW':
            s.scale_depth(1.0 / 1.1)
        elif et == 'C':
            s.toggle_curve()
        elif et == 'R':
            s.toggle_rigid()
        elif et == 'Z' and event.ctrl:
            if s.undo() and len(self.stamps):
                self.stamps.remove(len(self.stamps) - 1)
            keep = s.message
            self._update_hover(event)
            s.message = keep

        self._update_ui(context)
        return {'RUNNING_MODAL'}


# --------------------------------------------------------------------------
# UI / registration
# --------------------------------------------------------------------------

# Sidebar options, stored per scene (scene.topology_patches).
class TopologyPatchesSettings(bpy.types.PropertyGroup):
    use_shrinkwrap: bpy.props.BoolProperty(
        name="Shrinkwrap to Original",
        description="Before the first stamp, hide a copy of the target and shrinkwrap the "
                    "target onto it. Only vertices in the vertex group are held on the "
                    "original surface; patch vertices outside it keep their shape",
        default=False)
    group: bpy.props.StringProperty(
        name="Vertex Group",
        description="Vertex group of the patch marking the vertices that must stay on "
                    "the original surface. The same group is created on the target",
        default="base")
    use_rigid: bpy.props.BoolProperty(
        name="Keep Rigid Shapes",
        description="Patch vertices in the rigid vertex group are not stretched: each "
                    "connected island is only moved, rotated and uniformly scaled, so "
                    "circles stay circles. Weights below 1 blend towards the stretched shape",
        default=True)
    rigid_group: bpy.props.StringProperty(
        name="Vertex Group",
        description="Vertex group of the patch marking the vertices that keep their "
                    "original proportions",
        default="rigid")
    uv_source: bpy.props.EnumProperty(
        name="UVs",
        description="Where the UVs of the stamped faces come from",
        items=(('AUTO', "Auto", "Patch faces with their own material keep the patch's "
                                "UVs, all other faces continue the UVs of the target"),
               ('PATCH', "Patch", "Always copy the UVs of the patch"),
               ('TARGET', "Target", "Always continue the UVs of the faces that are replaced")),
        default='AUTO')


def _color_prop(key, name, description):
    """RGBA colour property for the preferences, defaulting to DEFAULTS[key]."""
    return bpy.props.FloatVectorProperty(
        name=name, description=description, subtype='COLOR_GAMMA', size=4,
        min=0.0, max=1.0, default=DEFAULTS[key])


# Edit > Preferences > Add-ons > Topology Patches: preview colours and widths.
class TopologyPatchesPreferences(bpy.types.AddonPreferences):
    bl_idname = ADDON_ID

    wire: _color_prop("wire", "Patch Edges", "Edges of the previewed patch")
    outline: _color_prop("outline", "Target Outline", "Outline of the faces that will be replaced")
    fill: _color_prop("fill", "Target Fill", "Highlight of the faces that will be replaced")
    marker: _color_prop("marker", "Rotation Marker",
                        "Marks where the first border edge of the patch lands")
    invalid: _color_prop("invalid", "Cannot Stamp", "Outline and highlight where the patch "
                                                    "does not fit")
    wire_width: bpy.props.FloatProperty(
        name="Patch Edge Width", min=0.5, max=10.0, default=DEFAULTS["wire_width"])
    outline_width: bpy.props.FloatProperty(
        name="Outline Width", min=0.5, max=10.0, default=DEFAULTS["outline_width"])

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        col = layout.column(heading="Preview Colours")
        for name in ("wire", "outline", "fill", "marker", "invalid"):
            col.prop(self, name)
        col = layout.column()
        col.prop(self, "wire_width")
        col.prop(self, "outline_width")


# Sidebar (N) > Patches tab, Object Mode.
class VIEW3D_PT_topology_patches(bpy.types.Panel):
    bl_label = "Topology Patches"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Patches"
    bl_context = "objectmode"

    def draw(self, context):
        col = self.layout.column()
        obj = context.view_layer.objects.active
        col.label(text="Patch: %s" % (obj.name if obj else "-"), icon='MESH_GRID')
        col.label(text="Select targets, then the patch last")
        opts = context.scene.topology_patches
        box = col.box()
        box.prop(opts, "use_shrinkwrap")
        sub = box.column()
        sub.active = opts.use_shrinkwrap
        sub.prop(opts, "group", icon='GROUP_VERTEX')
        if (opts.use_shrinkwrap and obj is not None and obj.type == 'MESH'
                and opts.group not in obj.vertex_groups):
            sub.label(text="Patch has no '%s' group" % opts.group, icon='ERROR')
        box = col.box()
        box.prop(opts, "use_rigid")
        sub = box.column()
        sub.active = opts.use_rigid
        sub.prop(opts, "rigid_group", icon='GROUP_VERTEX')
        if (opts.use_rigid and obj is not None and obj.type == 'MESH'
                and opts.rigid_group not in obj.vertex_groups):
            sub.label(text="Patch has no '%s' group" % opts.rigid_group, icon='INFO')
        col.prop(opts, "uv_source")
        col.operator(OBJECT_OT_topology_patches.bl_idname, icon='MOD_BOOLEAN')


def _menu(self, context):
    """Object menu entry."""
    self.layout.separator()
    self.layout.operator(OBJECT_OT_topology_patches.bl_idname, icon='MOD_BOOLEAN')


_classes = (TopologyPatchesSettings, TopologyPatchesPreferences, TopologyPatchesStamp,
            OBJECT_OT_topology_patches,
            VIEW3D_PT_topology_patches)


def register():
    """Blender calls this when the add-on is enabled."""
    for c in _classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.topology_patches = bpy.props.PointerProperty(type=TopologyPatchesSettings)
    bpy.types.VIEW3D_MT_object.append(_menu)


def unregister():
    """Blender calls this when the add-on is disabled."""
    bpy.types.VIEW3D_MT_object.remove(_menu)
    del bpy.types.Scene.topology_patches
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
