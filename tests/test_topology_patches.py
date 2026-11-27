"""Topology Patches test suite (runs inside a background Blender).

Start it with tests/run.py, which launches an isolated Blender:
    python tests/run.py [--blender PATH] [--addon-dir DIR]
    python tests/run.py --installed dist/topology_patches-X.Y.Z.zip

By default the add-on is imported from --addon-dir (the folder that contains the
`topology_patches` package; the repository root) and registered by hand. With
--installed, the built package is installed as an extension in the throw-away
profile and enabled the way Blender does it (TOPOLOGY_PATCHES_MODULE is then the
extension's module name). The user's own Blender and preferences are never used.

The interactive tool needs a 3D Viewport, which a background Blender does not
have, so the tests drive the same code through the scriptable Session class and
call the operator's execute() (the Adjust Last Operation path) directly.
Each test builds its own scene with tests/fixtures.py.
"""

import importlib
import os
import sys
import types
import unittest

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixtures as fx  # noqa: E402

INSTALLED_MODULE = os.environ.get("TOPOLOGY_PATCHES_MODULE")  # bl_ext.user_default.topology_patches
if INSTALLED_MODULE:
    import addon_utils
    tp = addon_utils.enable(INSTALLED_MODULE, default_set=True)
    assert tp is not None, f"could not enable {INSTALLED_MODULE}"
else:
    sys.path.insert(0, os.environ.get("TOPOLOGY_PATCHES_ADDON_DIR")
                    or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tp = importlib.import_module("topology_patches")

Patch = fx.patch_class(tp)
PatchError = fx.error_class(tp)
EQUATOR = fx.direction(1.0, 0.1, 0.12)
CLEAN = (0, 0, 0, 0)          # open, loose, flipped, non-manifold


def setUpModule():
    print(f"TOPOLOGY_PATCHES_UNDER_TEST {tp.__name__} from {tp.__file__}")
    if not INSTALLED_MODULE:
        tp.register()


def tearDownModule():
    if INSTALLED_MODULE:
        addon_utils.disable(INSTALLED_MODULE, default_set=True)
    else:
        tp.unregister()


class Case(unittest.TestCase):
    """Fresh scene per test, with one target sphere."""

    def setUp(self):
        fx.reset_scene()
        self.target = fx.make_target()

    def session(self, patch, targets=None, **kw):
        s = fx.new_session(tp, bpy.context, patch, targets or [self.target], **kw)
        self.addCleanup(s.free)
        return s

    def aim(self, s, d=EQUATOR, target=None):
        c = (target or self.target).matrix_world.translation
        s.pick(c + d * 10.0, -d)
        return s.make_plan()

    def stamp(self, s, d=EQUATOR, target=None):
        plan = self.aim(s, d, target)
        self.assertIsNotNone(plan)
        self.assertTrue(plan["valid"], plan["message"])
        self.assertTrue(s.apply(), s.message)
        return plan

    def assertClean(self, ob):
        self.assertEqual(fx.mesh_stats(ob)[:4], CLEAN)


class TestRegistration(unittest.TestCase):
    def test_operator_panel_settings_and_preferences(self):
        self.assertTrue(hasattr(bpy.types, "OBJECT_OT_topology_patches"))
        self.assertTrue(hasattr(bpy.types, "VIEW3D_PT_topology_patches"))
        opts = bpy.context.scene.topology_patches
        self.assertEqual((opts.use_shrinkwrap, opts.group, opts.use_rigid, opts.rigid_group, opts.uv_source),
                         (False, "base", True, "rigid", 'AUTO'))
        self.assertEqual(bpy.types.OBJECT_OT_topology_patches.bl_options, {'REGISTER', 'UNDO'})
        props = {p.identifier for p in bpy.ops.object.topology_patches.get_rna_type().properties}
        self.assertTrue({"stamps", "rotation", "depth", "curve", "rigid"} <= props)

    def test_preview_colours_default_to_DEFAULTS(self):
        # registered by hand there are no add-on preferences, so DEFAULTS is used;
        # installed, the preferences start at DEFAULTS (stored as 32-bit floats)
        for key in ("wire", "outline", "fill", "marker", "invalid", "wire_width", "outline_width"):
            got, want = tp._pref(key), tp.DEFAULTS[key]
            if isinstance(want, float):
                self.assertAlmostEqual(got, want, places=6, msg=key)
            else:
                self.assertEqual(len(got), len(want), key)
                for g, w in zip(got, want):
                    self.assertAlmostEqual(g, w, places=6, msg=key)


class TestPreview(Case):
    """The viewport preview (needs the GPU module, which a background Blender
    only has after gpu.init(); skipped where that fails, e.g. without OpenGL)."""

    @classmethod
    def setUpClass(cls):
        import gpu
        try:
            gpu.init()
        except Exception as e:  # no GPU backend on this machine
            raise unittest.SkipTest(f"gpu.init() failed: {e}")

    def test_batches_for_valid_invalid_and_missing_plans(self):
        for ob in (fx.frame_patch("F22", 2, 2), fx.round_patch("R8", 8), fx.frame_patch("Huge", 40, 40)):
            s = self.session(ob)
            for d in (EQUATOR, fx.direction(0.0, 0.0, 1.0)):
                self.aim(s, d)
                batches = s._build_batches()
                self.assertGreaterEqual(len(batches), 2, ob.name)
        s.set_hover(None)
        self.assertIsNone(s.make_plan())

    def test_a_failing_preview_draws_nothing_and_reports_once(self):
        if not hasattr(fx.new_session(tp, bpy.context, fx.frame_patch("F", 1, 1), [self.target]),
                       "_draw_error_reported"):
            self.skipTest("this version does not report preview errors")
        s = self.session(fx.frame_patch("F22", 2, 2))
        self.aim(s)
        calls = []

        def broken():
            calls.append(1)
            raise RuntimeError("broken preview")
        s._build_batches = broken
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for _ in range(3):
                s._batches = None
                try:
                    s.draw()
                except SystemError:     # gpu.state needs a viewport: the batches part is what we test
                    pass
        self.assertEqual(len(calls), 3)
        self.assertEqual(s._batches, [])
        self.assertEqual(err.getvalue().count("RuntimeError: broken preview"), 1)


class TestAnalysis(Case):
    def test_labels_and_rotation_steps(self):
        cases = [
            (fx.frame_patch("F11", 1, 1), "1 face, 4 corners", 4),
            (fx.frame_patch("F22", 2, 2), "2 x 2 faces", 4),
            (fx.frame_patch("F24", 2, 4), "2 x 4 faces", 4),
            (fx.round_patch("R8", 8), "round border, 2 x 2 faces", 8),
            (fx.round_patch("R16", 16), "round border, 4 x 4 faces", 16),
            (fx.round_patch("R10", 10), "round border, 2 x 3 faces", 20),
            (fx.face_patch("P5", 5), "1 face, 5 corners", 5),
            (fx.round_patch("R7", 7), "1 face, 7 corners", 7),
        ]
        for ob, label, steps in cases:
            p = Patch(ob, "base", "rigid")
            self.assertEqual((p.label, p.rot_steps), (label, steps), ob.name)

    def test_concave_border_is_accepted(self):
        me = bpy.data.meshes.new("Concave")
        bm = bmesh.new()
        pts = [(0, 0), (2, 0), (2, 2), (1, 0.6), (0, 2)]
        outer = [bm.verts.new((x, y, 0)) for x, y in pts]
        inner = [bm.verts.new((1 + (x - 1) * 0.5, 0.7 + (y - 0.7) * 0.5, -0.3)) for x, y in pts]
        for i in range(5):
            j = (i + 1) % 5
            bm.faces.new((outer[i], outer[j], inner[j], inner[i]))
        bm.faces.new(inner)
        bm.to_mesh(me)
        bm.free()
        p = Patch(fx.link("Concave", me))
        self.assertEqual(p.corner_count, 5)
        self.assertTrue(all(abs(sum(w) - 1.0) < 1e-6 for w in p.weights))

    def test_invalid_patches_are_refused(self):
        closed = fx.make_target("Closed", subsurf=False)
        with self.assertRaises(PatchError):
            Patch(closed)
        me = bpy.data.meshes.new("Empty")
        with self.assertRaises(PatchError):
            Patch(fx.link("Empty", me))

    def test_no_target_is_an_error(self):
        patch = fx.frame_patch("F22", 2, 2)
        self.target.hide_set(True)
        fx.select(patch)
        with self.assertRaises(PatchError):
            fx.new_session(tp, bpy.context, patch, []).free()

    def test_rigid_islands_and_base_weights(self):
        p = Patch(fx.round_patch("R8", 8, rigid=True, base=True), "base", "rigid")
        self.assertEqual(len(p.rigid), 1)
        self.assertEqual(len(p.rigid[0]["verts"]), 16)
        self.assertEqual(sum(w > 0 for w in p.base), 16)
        self.assertEqual(Patch(fx.frame_patch("F", 2, 2), "base", "rigid").rigid, [])


class TestStamping(Case):
    def test_every_kind_of_patch_stamps_watertight(self):
        patches = [fx.frame_patch("F11", 1, 1), fx.frame_patch("F22", 2, 2), fx.frame_patch("F33", 3, 3),
                   fx.frame_patch("F24", 2, 4), fx.round_patch("R8", 8), fx.round_patch("R16", 16),
                   fx.round_patch("R6", 6), fx.round_patch("R10", 10)]
        for ob in patches:
            for curve in (True, False):
                with self.subTest(patch=ob.name, curve=curve):
                    s = self.session(ob)
                    s.curve = curve
                    before = fx.mesh_stats(self.target)
                    self.stamp(s)
                    self.assertClean(self.target)
                    self.assertGreater(fx.mesh_stats(self.target)[4], before[4])
                    self.assertTrue(s.undo())
                    self.assertEqual(fx.mesh_stats(self.target), before)

    def test_single_face_patch_splits_edges_and_stays_closed(self):
        tri = fx.face_patch("Tri", 3)
        me = bpy.data.meshes.new("Tris")
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
        bm.to_mesh(me)
        bm.free()
        ico = fx.link("Ico", me, (5.0, 0.0, 0.0))
        bpy.context.view_layer.update()
        s = self.session(tri, [ico])
        self.stamp(s, target=ico)
        self.assertClean(ico)
        # a 5-corner patch does not fit a triangle
        s2 = self.session(fx.face_patch("P5", 5), [ico])
        plan = self.aim(s2, target=ico)
        self.assertFalse(plan["valid"])
        self.assertIn("corners", plan["message"])

    def test_every_rotation_is_watertight_and_undo_is_exact(self):
        for ob in (fx.round_patch("R8", 8, offset=0.2), fx.frame_patch("F24", 2, 4)):
            s = self.session(ob)
            start = fx.mesh_stats(self.target)
            for step in range(Patch(ob).rot_steps):
                with self.subTest(patch=ob.name, rot=step):
                    s.rot = step
                    self.stamp(s)
                    self.assertClean(self.target)
                    s.undo()
                    self.assertEqual(fx.mesh_stats(self.target), start)

    def test_rotation_in_place_keeps_the_same_faces(self):
        for ob in (fx.frame_patch("F22", 2, 2), fx.frame_patch("F24", 2, 4), fx.frame_patch("F12", 1, 2),
                   fx.round_patch("R8", 8), fx.round_patch("R10", 10), fx.round_patch("R6", 6)):
            s = self.session(ob)
            patch = fx.session_patch(s)
            for d in (EQUATOR, fx.direction(1.0, 0.13, 0.09), fx.direction(1.0, 0.07, 0.15)):
                s.rot = 0
                ref = frozenset(f.index for f in self.aim(s, d)["faces"])
                for k in range(-patch.rot_steps, patch.rot_steps + 1):
                    s.rot = patch.turn_in_place(0, k)
                    plan = self.aim(s, d)
                    with self.subTest(patch=ob.name, k=k):
                        self.assertTrue(plan["valid"], plan["message"])
                        self.assertEqual(frozenset(f.index for f in plan["faces"]), ref)

    def test_two_stamps_side_by_side(self):
        s = self.session(fx.round_patch("R8", 8))
        s.curve = False
        self.stamp(s, fx.direction(1.0, -1.2, 0.1))
        self.stamp(s, fx.direction(1.0, 1.2, 0.1))
        self.assertClean(self.target)
        self.assertFalse(s.undo() and s.undo() and s.undo())

    def test_patch_too_big_or_on_triangles_is_refused(self):
        s = self.session(fx.frame_patch("Huge", 40, 40))
        self.assertFalse(self.aim(s)["valid"])
        s = self.session(fx.frame_patch("F22", 2, 2))
        plan = self.aim(s, fx.direction(0.0, 0.0, 1.0))         # the pole of a UV sphere is triangles
        self.assertFalse(plan["valid"])
        self.assertFalse(s.apply())


class TestRigid(Case):
    def test_rigid_group_keeps_the_hole_round(self):
        target = fx.make_target("Squashed", location=(4.0, 0.0, 0.0), scale=(1.0, 1.0, 1.8))
        ob = fx.round_patch("R16", 16)
        n = 16
        for rigid, want_round in ((False, False), (True, True)):
            s = self.session(ob, [target], rigid=rigid)
            s.rigid = rigid
            plan = self.aim(s, fx.direction(0.5, 0.2, 1.5), target)
            self.assertTrue(plan["valid"], plan["message"])
            r = fx.roundness([plan["world"][i] for i in range(n, 2 * n)])
            if want_round:
                self.assertLess(r, 1.001)
            else:
                self.assertGreater(r, 1.02)

    def test_rigid_shape_follows_a_curved_target(self):
        # rigid keeps the proportions along the surface only: a flat rim at the
        # border's height must lie on a sphere, not stand off it as a flat plate
        from mathutils.bvhtree import BVHTree
        ob = fx.round_patch("R16", 16)
        n = 16
        bm = bmesh.new()
        bm.from_mesh(self.target.data)
        tree = BVHTree.FromBMesh(bm)
        try:
            s = self.session(ob, rigid=True)
            plan = self.aim(s)
            self.assertTrue(plan["valid"], plan["message"])
            rim = [plan["world"][i] for i in range(n, 2 * n)]   # rigid ring at z = 0
            off = [(p - tree.find_nearest(p)[0]).length for p in rim]
            self.assertLess(max(off), 0.005)
            self.assertLess(fx.roundness(rim), 1.01)            # and still round
        finally:
            bm.free()


class TestShrinkwrap(Case):
    def test_setup_order_groups_and_undo_cleanup(self):
        patch = fx.round_patch("R8", 8, rigid=True, base=True)
        n0 = len(self.target.data.vertices)
        name = self.target.name
        for rigid in (True, False):
            with self.subTest(rigid=rigid):
                s = self.session(patch, shrinkwrap=True, group="base", rigid=rigid)
                s.rigid = rigid
                self.stamp(s)
                mods = [m.type for m in self.target.modifiers]
                self.assertEqual(mods, ['SHRINKWRAP', 'SUBSURF'])
                sw = self.target.modifiers[0]
                ref = sw.target
                self.assertTrue(ref.name.startswith(name + "_"))
                self.assertTrue(ref.hide_get())
                self.assertEqual(len(ref.data.vertices), n0)
                self.assertEqual(sw.vertex_group, "base")
                gi = self.target.vertex_groups["base"].index
                inb = sum(any(g.group == gi and g.weight > 0 for g in v.groups) for v in self.target.data.vertices)
                # target's own verts minus the 4 removed by the 2 x 2 block, plus the stamped
                # base verts that are not rigid (8 rim verts when rigid is off)
                self.assertEqual(inb, n0 - 1 + (0 if rigid else 8))
                self.assertTrue(s.undo())
                self.assertEqual([m.type for m in self.target.modifiers], ['SUBSURF'])
                self.assertNotIn("base", self.target.vertex_groups)
                self.assertFalse(any(o.name.startswith(name + "_") for o in bpy.data.objects))
                self.assertEqual(len(self.target.data.vertices), n0)

    def test_existing_setup_from_older_versions_is_reused(self):
        ref = self.target.copy()
        ref.data = self.target.data.copy()
        ref.name = self.target.name + "_sticker_ref"
        bpy.context.scene.collection.objects.link(ref)
        old = self.target.modifiers.new("Sticker Shrinkwrap", 'SHRINKWRAP')
        old.target = ref
        patch = fx.round_patch("R8", 8, base=True)
        n_objects = len(bpy.data.objects)
        s = self.session(patch, shrinkwrap=True)
        self.stamp(s)
        self.assertEqual(len(bpy.data.objects), n_objects)         # no second hidden copy
        self.assertEqual([m.name for m in self.target.modifiers if m.type == 'SHRINKWRAP'], ["Sticker Shrinkwrap"])
        self.assertEqual(old.vertex_group, "base")


class TestCarryOver(Case):
    def stats(self):
        bm = bmesh.new()
        bm.from_mesh(self.target.data)
        uv = bm.loops.layers.uv.active
        crease = bm.edges.layers.float.get("crease_edge")
        mats = [m.name if m else None for m in self.target.data.materials]
        out = {
            "mats": mats,
            "inner faces": sum(mats and mats[f.material_index] == "TP_inner" for f in bm.faces),
            "sharp": sum(not e.smooth for e in bm.edges),
            "creases": sorted({round(e[crease], 2) for e in bm.edges if e[crease] > 0}) if crease else [],
            "patch uv loops": sum(lp[uv].uv.x > 4 for f in bm.faces for lp in f.loops),
            "max uv": max(max(lp[uv].uv) for f in bm.faces for lp in f.loops),
        }
        bm.free()
        return out

    def test_materials_edges_and_uvs(self):
        self.target.data.materials.append(bpy.data.materials.new("TP_outer"))
        patch = fx.decorated_patch()
        expect_uv = {'AUTO': 8, 'PATCH': 66, 'TARGET': 0}
        for mode, n_uv in expect_uv.items():
            with self.subTest(uv=mode):
                s = self.session(patch, uv_source=mode)
                self.stamp(s)
                st = self.stats()
                self.assertEqual(st["mats"], ["TP_outer", "TP_inner"])
                self.assertEqual(st["inner faces"], 1)
                self.assertEqual(st["sharp"], 8)
                self.assertEqual(st["creases"], [0.8])          # the border crease (0.3) is not copied
                self.assertEqual(st["patch uv loops"], n_uv)
                if mode == 'TARGET':
                    self.assertLessEqual(st["max uv"], 1.0 + 1e-6)
                self.assertTrue(s.undo())

    def test_target_without_material_keeps_its_faces_plain(self):
        s = self.session(fx.decorated_patch())
        self.stamp(s)
        self.assertEqual(self.stats()["mats"], [None, "TP_inner"])

    def test_continued_uvs_stay_inside_the_replaced_block(self):
        s = self.session(fx.frame_patch("F22", 2, 2), uv_source='TARGET')
        plan = self.aim(s)
        bm = s.targets[0].bm
        uv = bm.loops.layers.uv.active
        us = [lp[uv].uv.copy() for f in plan["faces"] for lp in f.loops]
        lo = Vector((min(u.x for u in us), min(u.y for u in us)))
        hi = Vector((max(u.x for u in us), max(u.y for u in us)))
        self.assertTrue(s.apply())
        me = self.target.data
        centre = sum(plan["outline"], Vector()) / len(plan["outline"])
        radius = max((p - centre).length for p in plan["outline"]) * 1.001
        mw = self.target.matrix_world
        new = [p for p in me.polygons if all((mw @ me.vertices[i].co - centre).length < radius for i in p.vertices)]
        self.assertGreater(len(new), 0)
        for p in new:
            for li in p.loop_indices:
                u = me.uv_layers.active.data[li].uv
                self.assertTrue(lo.x - 1e-5 <= u.x <= hi.x + 1e-5 and lo.y - 1e-5 <= u.y <= hi.y + 1e-5)


class TestRedo(Case):
    """The Adjust Last Operation panel: execute() replays the recorded stamps."""

    def run_execute(self, patch, stamps, rotation=0, depth=1.0, curve=True, rigid=True, flip=False):
        fx.select(patch, self.target)
        cls = bpy.types.OBJECT_OT_topology_patches
        # `flip` (added in 1.6) is ignored by older versions
        recorded = [types.SimpleNamespace(point=Vector(p), direction=Vector(d), rot=r, depth=dp, curve=c, rigid=rg,
                                          flip=False)
                    for p, d, r, dp, c, rg in stamps]
        op = types.SimpleNamespace(stamps=recorded, rotation=rotation, depth=depth, curve=curve, rigid=rigid,
                                   flip=flip, reports=[])
        op.report = lambda kind, text: op.reports.append((kind, text))
        op._new_session = lambda context: cls._new_session(op, context)
        return cls.execute(op, bpy.context), op.reports

    def record(self, patch, d=EQUATOR, rot=0):
        s = self.session(patch)
        s.rot = rot
        plan = self.aim(s, d)
        self.assertTrue(plan["valid"], plan["message"])
        return (tuple(s.hover_point), tuple(-d), rot, 1.0, True, True), frozenset(
            tuple(round(c, 4) for c in v.co) for f in plan["faces"] for v in f.verts)

    def removed(self, before):
        now = {tuple(round(c, 4) for c in v.co) for v in self.target.data.vertices}
        return before - now

    def test_redo_rotation_keeps_the_same_faces(self):
        for ob in (fx.round_patch("R8", 8, offset=0.2), fx.frame_patch("F24", 2, 4)):
            stamp, block = self.record(ob)
            all_verts = {tuple(round(c, 4) for c in v.co) for v in self.target.data.vertices}
            start = fx.mesh_stats(self.target)
            removed = set()
            for rotation in (0, 1, 2, 3, 4, -1, 7):
                with self.subTest(patch=ob.name, rotation=rotation):
                    res, reports = self.run_execute(ob, [stamp], rotation=rotation)
                    self.assertEqual(res, {'FINISHED'}, reports)
                    self.assertClean(self.target)
                    gone = self.removed(all_verts)          # the inner vertices of the replaced block
                    self.assertTrue(gone and gone <= block)
                    removed.add(frozenset(gone))
                # put the original mesh back for the next redo (what Blender's undo does)
                bm = bmesh.new()
                bm.from_mesh(self.base_mesh)
                bm.to_mesh(self.target.data)
                bm.free()
                self.assertEqual(fx.mesh_stats(self.target), start)
            self.assertEqual(len(removed), 1, "a redo rotation replaced other faces")

    def test_redo_after_the_object_moved_without_an_update(self):
        # Blender's redo undoes first: objects come back without an evaluated
        # world matrix. execute() must refresh it before reading the stamps.
        ob = fx.round_patch("R8", 8)
        # moved across the ray, so a stale matrix makes the ray miss
        self.target.location = (0.0, 3.0, 0.0)
        bpy.context.view_layer.update()
        stamp, block = self.record(ob)
        self.target.location = (0.0, 0.0, 0.0)
        bpy.context.view_layer.update()
        self.target.location = (0.0, 3.0, 0.0)          # matrix_world is now stale
        res, reports = self.run_execute(ob, [stamp])
        self.assertEqual(res, {'FINISHED'}, reports)
        self.assertClean(self.target)

    def test_replay_reproduces_a_run(self):
        ob = fx.round_patch("R8", 8, offset=0.2)
        s = self.session(ob)
        record = []
        for d, rot, depth, curve, rigid in ((fx.direction(1, -1, 0.25), 3, 1.0, True, True),
                                            (fx.direction(1, 0.2, 0.25), 5, 1.3, False, False),
                                            (fx.direction(0.4, 1, 0.25), 1, 0.8, True, True)):
            s.rot, s.depth, s.curve, s.rigid = rot, depth, curve, rigid
            self.aim(s, d)
            record.append((tuple(s.hover_point), tuple(-d), rot, depth, curve, rigid))
            self.assertTrue(s.apply())
        live = sorted(tuple(round(c, 4) for c in v.co) for v in self.target.data.vertices)
        while s.undo():
            pass
        self.assertEqual(s.replay(record), 3)
        self.assertEqual(sorted(tuple(round(c, 4) for c in v.co) for v in self.target.data.vertices), live)

    def test_redo_flip(self):
        ob = fx.frame_patch("F22", 2, 2)
        stamp, _block = self.record(ob)
        volume = signed_volume(self.target)
        res, reports = self.run_execute(ob, [stamp], flip=True)
        self.assertEqual(res, {'FINISHED'}, reports)
        self.assertClean(self.target)
        self.assertGreater(signed_volume(self.target), volume)      # a bump, not a dent

    def setUp(self):
        super().setUp()
        self.base_mesh = self.target.data.copy()


def signed_volume(ob):
    """Volume enclosed by the mesh; it shrinks when faces point inwards."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    vol = 0.0
    for f in bm.faces:
        a = f.verts[0].co
        for i in range(1, len(f.verts) - 1):
            vol += a.dot(f.verts[i].co.cross(f.verts[i + 1].co)) / 6.0
    bm.free()
    return vol


class TestFlip(Case):
    """F in the tool: the patch is mirrored along its normal, normals stay outwards."""

    def pentagon_prism(self):
        me = bpy.data.meshes.new("Pent")
        bm = bmesh.new()
        bmesh.ops.create_circle(bm, cap_ends=True, segments=5, radius=1.0)
        ret = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
        bmesh.ops.translate(bm, vec=(0.0, 0.0, 1.0),
                            verts=[v for v in ret["geom"] if isinstance(v, bmesh.types.BMVert)])
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(me)
        bm.free()
        ob = fx.link("Pent", me, (5.0, 0.0, 0.0))
        bpy.context.view_layer.update()
        return ob

    def test_flip_turns_a_dent_into_a_bump(self):
        start = signed_volume(self.target)
        cases = [(fx.frame_patch("F22", 2, 2), self.target, EQUATOR),
                 (fx.round_patch("R8", 8, offset=0.2), self.target, EQUATOR),
                 (fx.face_patch("P5", 5), self.pentagon_prism(), fx.direction(0.0, 0.0, 1.0))]
        for ob, target, d in cases:
            for curve in (True, False):
                with self.subTest(patch=ob.name, curve=curve):
                    s = self.session(ob, [target])
                    s.curve = curve
                    base = signed_volume(target)
                    self.stamp(s, d, target)
                    dent = signed_volume(target)
                    s.undo()
                    s.toggle_flip()
                    self.stamp(s, d, target)
                    self.assertClean(target)
                    bump = signed_volume(target)
                    s.undo()
                    self.assertLess(dent, base)
                    self.assertGreater(bump, base)
                    # mirrored: the bump adds about what the dent took away
                    self.assertAlmostEqual(bump - base, base - dent, delta=0.5 * (base - dent))
        self.assertAlmostEqual(signed_volume(self.target), start, places=6)

    def test_replay_records_flip(self):
        ob = fx.frame_patch("F22", 2, 2)
        s = self.session(ob)
        s.flip = True
        self.aim(s)
        record = [(tuple(s.hover_point), tuple(-EQUATOR), 0, 1.0, True, True, True)]
        self.assertTrue(s.apply())
        live = sorted(tuple(round(c, 4) for c in v.co) for v in self.target.data.vertices)
        s.undo()
        s.flip = False
        self.assertEqual(s.replay(record), 1)
        self.assertEqual(sorted(tuple(round(c, 4) for c in v.co) for v in self.target.data.vertices), live)


class TestReplaceSelection(Case):
    """Edit Mode: select faces on the target, Ctrl+click the patch, replace the selection."""

    def block(self, patch, d=EQUATOR):
        """Indices of the faces the tool would replace when aimed along `d`."""
        s = self.session(patch)
        plan = self.aim(s, d)
        self.assertTrue(plan["valid"], plan["message"])
        return sorted(f.index for f in plan.get("faces", [plan["face"]]))

    def replace(self, patch, faces, patch_in_edit_mode=True, **props):
        """Select `faces` on the target and run the operator, with the patch
        in Edit Mode as the active object, or only selected (what Ctrl+click
        in the viewport does)."""
        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        me = self.target.data
        wanted = set(faces)
        for p in me.polygons:
            p.select = p.index in wanted
        verts = {v for i in wanted for v in me.polygons[i].vertices}
        for v in me.vertices:
            v.select = v.index in verts
        for e in me.edges:
            e.select = all(v in verts for v in e.vertices)
        if patch_in_edit_mode:
            fx.select(patch, self.target)
            bpy.ops.object.mode_set(mode='EDIT')
        else:
            fx.select(self.target)
            bpy.ops.object.mode_set(mode='EDIT')
            self.target.select_set(False)
            patch.select_set(True)
        try:
            res = bpy.ops.mesh.topology_patches_replace(**props)
        except RuntimeError:          # the operator reported an error
            res = {'CANCELLED'}
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        bpy.ops.object.mode_set(mode='OBJECT')
        return res

    def reset(self):
        bm = bmesh.new()
        bm.from_mesh(self.base_mesh)
        bm.to_mesh(self.target.data)
        bm.free()

    def coords(self):
        return sorted(tuple(round(c, 4) for c in v.co) for v in self.target.data.vertices)

    def setUp(self):
        super().setUp()
        self.base_mesh = self.target.data.copy()

    def test_registered_with_redo(self):
        self.assertEqual(bpy.types.MESH_OT_topology_patches_replace.bl_options, {'REGISTER', 'UNDO'})
        props = {p.identifier for p in bpy.ops.mesh.topology_patches_replace.get_rna_type().properties}
        self.assertTrue({"rotation", "depth", "curve", "rigid", "flip"} <= props)

    def test_same_result_as_the_tool_and_new_faces_selected(self):
        for ob in (fx.frame_patch("F22", 2, 2), fx.frame_patch("F11", 1, 1)):
            with self.subTest(patch=ob.name):
                faces = self.block(ob)
                s = self.session(ob)
                self.stamp(s)
                expected = self.coords()
                s.undo()
                self.assertEqual(self.replace(ob, faces), {'FINISHED'})
                self.assertClean(self.target)
                self.assertEqual(self.coords(), expected)
                selected = [p for p in self.target.data.polygons if p.select]
                self.assertEqual(len(selected), len(ob.data.polygons))
                self.reset()

    def test_single_face_patch_on_one_selected_face(self):
        ob = fx.face_patch("P4", 4)
        faces = self.block(ob)
        self.assertEqual(len(faces), 1)
        before = len(self.target.data.polygons)
        self.assertEqual(self.replace(ob, faces), {'FINISHED'})
        self.assertClean(self.target)
        self.assertEqual(len(self.target.data.polygons), before - 1 + len(ob.data.polygons))

    def test_every_rotation_replaces_only_the_selection(self):
        for ob in (fx.round_patch("R8", 8, offset=0.2), fx.frame_patch("F24", 2, 4)):
            faces = self.block(ob)
            block_verts = {tuple(round(c, 4) for c in self.target.data.vertices[v].co)
                           for i in faces for v in self.target.data.polygons[i].vertices}
            before = set(self.coords())
            results = set()
            steps = Patch(ob).rot_steps
            for rotation in range(steps):
                with self.subTest(patch=ob.name, rotation=rotation):
                    self.assertEqual(self.replace(ob, faces, rotation=rotation), {'FINISHED'})
                    self.assertClean(self.target)
                    self.assertTrue(before - set(self.coords()) <= block_verts)
                    results.add(tuple(self.coords()))
                    self.reset()
            if ob.name == "R8":       # lopsided: every step lands differently
                self.assertEqual(len(results), steps)

    def test_flip(self):
        ob = fx.frame_patch("F22", 2, 2)
        faces = self.block(ob)
        base = signed_volume(self.target)
        self.assertEqual(self.replace(ob, faces), {'FINISHED'})
        dent = signed_volume(self.target)
        self.reset()
        self.assertEqual(self.replace(ob, faces, flip=True), {'FINISHED'})
        self.assertClean(self.target)
        self.assertLess(dent, base)
        self.assertGreater(signed_volume(self.target), base)

    def test_wrong_selection_is_refused_and_changes_nothing(self):
        f24 = fx.frame_patch("F24", 2, 4)
        f22 = fx.frame_patch("F22", 2, 2)
        before = self.coords()
        for ob, faces in ((f24, self.block(f22)),                  # 2 x 2 block for a 2 x 4 patch
                          (f22, self.block(f22)[:3]),              # three faces of the block
                          (f22, [])):                              # nothing selected
            with self.subTest(patch=ob.name, faces=len(faces)):
                self.assertEqual(self.replace(ob, faces), {'CANCELLED'})
                self.assertEqual(self.coords(), before)

    def test_patch_selected_outside_edit_mode(self):
        # Ctrl+click on another object in Edit Mode only selects it: the
        # target stays the only (and active) object in Edit Mode
        ob = fx.frame_patch("F22", 2, 2)
        faces = self.block(ob)
        s = self.session(ob)
        self.stamp(s)
        expected = self.coords()
        s.undo()
        self.assertEqual(self.replace(ob, faces, patch_in_edit_mode=False), {'FINISHED'})
        self.assertEqual(self.coords(), expected)
        self.assertEqual(ob.mode, 'OBJECT')

    def test_sidebar_checks_the_groups_of_the_patch_not_the_target(self):
        ob = fx.round_patch("R8", 8, base=True)
        fx.select(self.target)
        bpy.ops.object.mode_set(mode='EDIT')
        self.target.select_set(False)
        ob.select_set(True)                 # Ctrl+click: selected, not in Edit Mode
        patch, _hint = tp._panel_patch(bpy.context)
        bpy.ops.object.mode_set(mode='OBJECT')
        self.assertIs(patch, ob)
        self.assertIn("base", patch.vertex_groups)

    def test_without_a_patch_it_says_so(self):
        fx.select(self.target)
        bpy.ops.object.mode_set(mode='EDIT')
        self.assertTrue(bpy.ops.mesh.topology_patches_replace.poll())
        with self.assertRaisesRegex(RuntimeError, r"Ctrl\+click the patch"):
            bpy.ops.mesh.topology_patches_replace()
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        bpy.ops.object.mode_set(mode='OBJECT')


if __name__ == "__main__":
    import io
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(stream.getvalue())
    print(f"TOPOLOGY_PATCHES_TESTS ran={result.testsRun} failures={len(result.failures)} errors={len(result.errors)}")
    sys.exit(0 if result.wasSuccessful() else 1)
