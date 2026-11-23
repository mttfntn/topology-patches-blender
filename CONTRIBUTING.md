# Contributing to Topology Patches

Thanks for helping! Bug reports, ideas and pull requests are all welcome.

## Reporting a bug or suggesting a feature

Open an [issue](https://github.com/mttfntn/topology-patches-blender/issues/new/choose) and pick a form:

- **Bug report:** say which Blender version and add-on version you use, and the steps to reproduce. A small `.blend` file with the target and the patch helps most.
- **Feature request:** describe what you're trying to do, not only the solution you have in mind.

First, check whether someone has already opened an issue for the same thing. Also look at the README's [Troubleshooting](README.md#troubleshooting) section: most red previews have a reason listed there.

## Changing the code

[HANDOVER.md](HANDOVER.md) explains how the add-on is organised and the pitfalls already found. Read it before a larger change.

1. **Fork** the repository and create a branch for your change.
2. You need **Blender 5.3** (the only supported version) and Python 3.9 or newer.
3. Run the tests. They start their own background Blender with a throw-away profile, so your Blender setup is never touched:

   ```
   python tests/run.py
   ```

   Expected result: `TOPOLOGY_PATCHES_TESTS ran=24 failures=0 errors=0`. If Blender isn't found, add `--blender "path/to/blender"`.
4. **If you fix a bug,** add a test to `tests/test_topology_patches.py` that fails without your fix.
5. **If your change could alter results,** compare behaviour with `main` using the snapshot tools (HANDOVER.md, [How to make a change](HANDOVER.md#how-to-make-a-change)) and explain any difference in the pull request.
6. **Try it by hand** if you changed the interactive tool, the preview or the panel: the tests can't move a mouse.
7. **Open a pull request.** The template has a short checklist. CI runs the full test suite on Blender 5.3.

### Style

- The add-on is one module, `topology_patches/__init__.py`, divided into sections. Keep new code in the matching section.
- Give new functions a docstring that says what they do.
- **Panels, preferences and property groups:** use `#` comments, not docstrings, because Blender shows them in the interface.
- **The operator's docstring** is its tooltip: write it for users.
- Keep commits small, with messages that explain what changed and how you checked it.

## License

Topology Patches is GPL-3.0-or-later. By contributing, you agree that your contribution is released under the same license.
