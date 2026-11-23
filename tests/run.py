"""Run the Topology Patches tests in an isolated background Blender.

    python tests/run.py [--blender PATH] [--addon-dir DIR] [--script FILE] [-- extra args]
    python tests/run.py --installed dist/topology_patches-X.Y.Z.zip

* --blender    Blender executable (default: $BLENDER, then the usual install paths)
* --addon-dir  folder that contains the `topology_patches` package (default: repo root)
* --installed  test the built package instead: install it as an extension in the
               throw-away profile and let Blender enable it
* --script     what to run inside Blender (default: tests/test_topology_patches.py)

Blender is started with --factory-startup and a throw-away user profile
(BLENDER_USER_RESOURCES), so the installed add-on and your settings are never
touched. The exit code is Blender's (non-zero when a test fails).
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def find_blender():
    """$BLENDER, else a Blender 5.3 in the usual install locations, else `blender` on PATH."""
    if os.environ.get("BLENDER"):
        return os.environ["BLENDER"]
    candidates = sorted(glob.glob(r"C:\Program Files\Blender Foundation\Blender 5.3*\blender.exe"), reverse=True)
    candidates += ["/Applications/Blender.app/Contents/MacOS/Blender", shutil.which("blender") or ""]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("Blender not found: pass --blender or set $BLENDER")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blender", default=None)
    ap.add_argument("--addon-dir", default=REPO)
    ap.add_argument("--installed", default=None, metavar="ZIP")
    ap.add_argument("--script", default=os.path.join(HERE, "test_topology_patches.py"))
    args, extra = ap.parse_known_args()
    blender = args.blender or find_blender()
    profile = tempfile.mkdtemp(prefix="topology-patches-profile-")
    env = dict(os.environ, BLENDER_USER_RESOURCES=profile,
               TOPOLOGY_PATCHES_ADDON_DIR=os.path.abspath(args.addon_dir))
    env.pop("TOPOLOGY_PATCHES_MODULE", None)
    if args.installed:
        install = [blender, "-b", "--factory-startup", "--command", "extension", "install-file",
                   "--repo", "user_default", os.path.abspath(args.installed)]
        print("installing:", " ".join(install), flush=True)
        if subprocess.call(install, env=env) != 0:
            shutil.rmtree(profile, ignore_errors=True)
            return 1
        env["TOPOLOGY_PATCHES_MODULE"] = "bl_ext.user_default.topology_patches"
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", args.script]
    if extra:
        cmd += ["--"] + [a for a in extra if a != "--"]
    print("running:", " ".join(cmd), flush=True)
    try:
        return subprocess.call(cmd, env=env)
    finally:
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
