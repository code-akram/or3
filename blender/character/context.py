"""Shared build state passed to every stage, plus MPFB service access."""

import importlib
import os
import time

import addon_utils
import bpy


class Mpfb:
    """MPFB services, resolved from the installed extension's module name."""

    SERVICES = ("HumanService", "AssetService", "ExportService", "ObjectService",
                "TargetService", "LocationService")

    def __init__(self, system_root, suit_root):
        self.pkg = next((m.__name__ for m in addon_utils.modules()
                         if m.__name__.endswith(".mpfb") or m.__name__ == "mpfb"), None)
        if self.pkg is None:
            raise RuntimeError("MPFB extension not installed; run blender/install_mpfb.sh")
        addon_utils.enable(self.pkg, default_set=True, persistent=False)
        prefs = bpy.context.preferences.addons[self.pkg].preferences
        # Two packs, two roots: second_root + mh_user_data are both plain data
        # roots in MPFB's asset search (AssetService.get_available_data_roots).
        prefs.mpfb_second_root = os.path.abspath(system_root)
        prefs.mh_user_data = os.path.abspath(suit_root)
        for name in self.SERVICES:
            mod = importlib.import_module(f"{self.pkg}.services.{name.lower()}")
            setattr(self, name, getattr(mod, name))
        self.LocationService.update_second_root()
        self.LocationService.update_mh_data()

    def find(self, fname, subdir):
        path = self.AssetService.find_asset_absolute_path(fname, asset_subdir=subdir)
        if path is None:
            raise RuntimeError(f"asset {subdir}/{fname} not found in MPFB data roots")
        return path

    def add_mhclo(self, basemesh, subdir, fname, asset_type):
        return self.HumanService.add_mhclo_asset(
            self.find(fname, subdir), basemesh, asset_type=asset_type,
            subdiv_levels=0, material_type="GAMEENGINE")


class Build:
    """Everything a stage may read or write."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.mpfb = None
        self.basemesh = None      # live MPFB human (pre-staging)
        self.export_root = None   # staged armature (post-staging)
        self.export_objs = []     # staged armature + children
        self.cutouts = []         # name fragments whose materials export as MASK
        self.notes = {}           # per-stage facts for stats.json
        self.timings = {}
        self.t0 = time.perf_counter()

    def meshes(self, name_part=None):
        return [o for o in self.export_objs if o.type == "MESH"
                and (name_part is None or name_part in o.name)]

    def armature(self):
        return next(o for o in self.export_objs if o.type == "ARMATURE")

    def step(self, name, fn, *args):
        t = time.perf_counter()
        print(f"[build] {name} ...", flush=True)
        out = fn(self, *args)
        dt = time.perf_counter() - t
        self.timings[name] = round(dt, 3)
        print(f"[build] {name}: {dt:.2f} s", flush=True)
        return out
