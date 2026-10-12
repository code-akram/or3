"""Hero-only suit material detail (Cycles renders of the staged .blend).

Runs after the GLB export (build_character step "suit_hero", between
export_glb and save_blend), so nothing here reaches the game asset; the GLB
keeps the glTF-exportable materials of suit_textures.

    twill   a 2/2 twill detail normal on the wool (jacket, waistcoat,
            trousers): procedural ribs at 45 degrees, period_m apart, with a
            yarn modulation along the warp, as a Bump node over the baked
            seam/fold normal map. Coordinates are metric (atlas UV x the
            atlas side, stored on the material by suit_textures.apply). The
            art direction asks for a Poly Haven CC0 fabric tile; a procedural
            pattern is used instead (own work, no download, no tile seams).
    shirt   a little subsurface scattering (Cycles; the glTF has no
            diffuse transmission), so the shirt reads as thin cotton.

Options: suit.hero in the build config (DEFAULTS below).
"""

import math

DEFAULTS = {
    "enabled": True,
    "twill": {"period_m": 0.0006, "strength": 0.4, "distance_m": 0.0002, "angle_deg": 45.0,
              "yarn": 0.35, "materials": ["suit_wool_a", "suit_wool", "suit_wool_b"]},
    "shirt": {"material": "suit_shirt", "sss": 0.15, "radius": [1.0, 0.85, 0.7], "scale_m": 0.0015},
}


def _bsdf(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


class _Nodes:
    """Small helper for math chains in a node tree."""

    def __init__(self, nt):
        self.nt = nt

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def math(self, op, a, b=None):
        n = self.node("ShaderNodeMath", operation=op)
        for sock, x in zip(n.inputs, (a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                sock.default_value = x
            else:
                self.nt.links.new(x, sock)
        return n.outputs[0]


def twill(mat, T):
    side = mat.get("suit_atlas_side_m")
    bsdf = _bsdf(mat)
    if not side or bsdf is None:
        return False
    nt = mat.node_tree
    N = _Nodes(nt)
    tc = N.node("ShaderNodeTexCoord")
    sep = N.node("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["UV"], sep.inputs[0])
    k = side / T["period_m"]          # rib periods per UV unit
    a = math.radians(T["angle_deg"])
    u, v = sep.outputs["X"], sep.outputs["Y"]
    # rib phase along the twill diagonal, yarn phase along the warp (v)
    s = N.math("ADD", N.math("MULTIPLY", u, k * math.cos(a)), N.math("MULTIPLY", v, k * math.sin(a)))
    rib = N.math("MULTIPLY", N.math("ADD", N.math("SINE", N.math("MULTIPLY", s, 2 * math.pi)), 1.0), 0.5)
    rib = N.math("POWER", rib, 1.5)
    yarn = N.math("MULTIPLY", N.math("ADD", N.math("SINE", N.math("MULTIPLY", v, 4 * math.pi * k)), 1.0),
                  0.5 * T["yarn"])
    h = N.math("MULTIPLY", rib, N.math("SUBTRACT", 1.0, yarn))
    bump = N.node("ShaderNodeBump")
    bump.inputs["Strength"].default_value = T["strength"]
    bump.inputs["Distance"].default_value = T["distance_m"]
    nt.links.new(h, bump.inputs["Height"])
    old = bsdf.inputs["Normal"].links
    if old:
        nt.links.new(old[0].from_socket, bump.inputs["Normal"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return True


def shirt(mat, S):
    bsdf = _bsdf(mat)
    if bsdf is None:
        return False
    bsdf.inputs["Subsurface Weight"].default_value = S["sss"]
    bsdf.inputs["Subsurface Radius"].default_value = tuple(S["radius"])
    bsdf.inputs["Subsurface Scale"].default_value = S["scale_m"]
    return True


def apply(b, o):
    import bpy
    H = o
    out = {"twill": [], "shirt": False}
    if not H.get("enabled", True):
        return out
    for name in H["twill"]["materials"]:
        mat = bpy.data.materials.get(name)
        if mat is not None and twill(mat, H["twill"]):
            out["twill"].append(name)
    mat = bpy.data.materials.get(H["shirt"]["material"])
    if mat is not None:
        out["shirt"] = shirt(mat, H["shirt"])
    return out
