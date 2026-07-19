"""Build a generic anime-teen bedroom as a USD scene.

ADR-2605222000 — animeka v3. Pure Python, no Blender. Mirrors the
mangaka v3 yuto-bedroom pattern (build-yuto-bedroom.py) but with
animeka asset paths and 5 named UsdGeomCamera prims for cut-level
camera selection (`AnimekaUSDCameraPrim`).

Room layout (typical anime teen bedroom):
  Room    4m W × 4m D × 2.5m H
  Floor   y=0
  4 walls
  Window  on north wall (1.2m × 1.5m, sill 0.9m up)
  Bed     south wall, 2m × 1m × 0.4m
  Desk    east wall, 1.4m × 0.6m × 0.75m
  Chair   in front of desk
  Lamp    on desk corner
  Closet  west wall, 1.2m × 0.6m × 2.2m
  Manga shelf  west wall, 0.6m × 0.3m × 1.2m
  Smartphone on desk

Cameras (5 — used for com.etzhayyim.animeka.cut camera selection):
  /Bedroom/Cameras/wide         wide-angle establishing
  /Bedroom/Cameras/character_at_desk    OTS of character at desk
  /Bedroom/Cameras/phone_closeup  tight on smartphone
  /Bedroom/Cameras/overhead     slight high angle
  /Bedroom/Cameras/window_view  from window looking in

Lights (3):
  /Bedroom/Lights/window_rect   UsdLuxRectLight  (dramatic sunset)
  /Bedroom/Lights/desk_lamp     UsdLuxSphereLight (warm desk lamp)
  /Bedroom/Lights/ceiling       UsdLuxDistantLight (fill)

Output: data/animeka/resources/usd/anime-bedroom.usda  (committed to repo)
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import trimesh
from pxr import Usd, UsdGeom, UsdLux, Gf, Sdf

OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "animeka" / "resources" / "usd"
OUT_DIR.mkdir(exist_ok=True, parents=True)
OUT_PATH = OUT_DIR / "anime-bedroom.usda"

ROOM_W, ROOM_D, ROOM_H = 4.0, 4.0, 2.5


def build_meshes() -> list[tuple[str, trimesh.Trimesh]]:
    meshes: list[tuple[str, trimesh.Trimesh]] = []

    floor = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    floor.apply_translation([ROOM_W/2, 0, ROOM_D/2])
    meshes.append(("floor", floor))

    ceil = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    ceil.apply_translation([ROOM_W/2, ROOM_H, ROOM_D/2])
    meshes.append(("ceiling", ceil))

    wn = trimesh.creation.box(extents=[ROOM_W, ROOM_H, 0.1])
    wn.apply_translation([ROOM_W/2, ROOM_H/2, 0])
    meshes.append(("wall_n", wn))
    ws = trimesh.creation.box(extents=[ROOM_W, ROOM_H, 0.1])
    ws.apply_translation([ROOM_W/2, ROOM_H/2, ROOM_D])
    meshes.append(("wall_s", ws))
    we = trimesh.creation.box(extents=[0.1, ROOM_H, ROOM_D])
    we.apply_translation([ROOM_W, ROOM_H/2, ROOM_D/2])
    meshes.append(("wall_e", we))
    ww = trimesh.creation.box(extents=[0.1, ROOM_H, ROOM_D])
    ww.apply_translation([0, ROOM_H/2, ROOM_D/2])
    meshes.append(("wall_w", ww))

    # Window frame on north wall (taller for anime sunset / dawn cuts)
    win = trimesh.creation.box(extents=[1.2, 1.5, 0.05])
    win.apply_translation([ROOM_W/2, 0.9 + 0.75, 0.06])
    meshes.append(("window_frame", win))

    # Bed against south wall
    bed = trimesh.creation.box(extents=[2.0, 0.4, 1.0])
    bed.apply_translation([ROOM_W/2, 0.2, ROOM_D - 0.6])
    meshes.append(("bed", bed))

    # Desk against east wall
    desk_top = trimesh.creation.box(extents=[1.4, 0.05, 0.6])
    desk_top.apply_translation([ROOM_W - 0.35, 0.75, ROOM_D/2])
    meshes.append(("desk_top", desk_top))
    for x_off, z_off in [(-0.6, -0.25), (-0.6, 0.25), (0.6, -0.25), (0.6, 0.25)]:
        leg = trimesh.creation.box(extents=[0.05, 0.75, 0.05])
        leg.apply_translation([ROOM_W - 0.35 + x_off, 0.375, ROOM_D/2 + z_off])
        meshes.append((f"desk_leg_{x_off:+.1f}_{z_off:+.1f}", leg))

    # Chair in front of desk
    seat = trimesh.creation.box(extents=[0.45, 0.05, 0.45])
    seat.apply_translation([ROOM_W - 0.95, 0.45, ROOM_D/2])
    meshes.append(("chair_seat", seat))
    back = trimesh.creation.box(extents=[0.45, 0.50, 0.05])
    back.apply_translation([ROOM_W - 0.95, 0.70, ROOM_D/2 - 0.20])
    meshes.append(("chair_back", back))

    # Desk lamp
    lamp_base = trimesh.creation.cylinder(radius=0.10, height=0.05, sections=24)
    lamp_base.apply_translation([ROOM_W - 0.85, 0.80, ROOM_D/2 + 0.18])
    meshes.append(("lamp_base", lamp_base))
    lamp_arm = trimesh.creation.cylinder(radius=0.02, height=0.40, sections=12)
    lamp_arm.apply_translation([ROOM_W - 0.85, 1.00, ROOM_D/2 + 0.18])
    meshes.append(("lamp_arm", lamp_arm))
    lamp_head = trimesh.creation.box(extents=[0.18, 0.12, 0.18])
    lamp_head.apply_translation([ROOM_W - 0.85, 1.20, ROOM_D/2 + 0.18])
    meshes.append(("lamp_head", lamp_head))

    # Smartphone on desk
    phone = trimesh.creation.box(extents=[0.15, 0.01, 0.07])
    phone.apply_translation([ROOM_W - 0.50, 0.78, ROOM_D/2 + 0.05])
    meshes.append(("phone", phone))

    # Closet against west wall
    closet = trimesh.creation.box(extents=[0.6, 2.2, 1.2])
    closet.apply_translation([0.35, 1.1, ROOM_D - 0.6])
    meshes.append(("closet", closet))

    # Manga shelf against west wall
    shelf = trimesh.creation.box(extents=[0.3, 1.2, 0.6])
    shelf.apply_translation([0.20, 1.5, 1.0])
    meshes.append(("manga_shelf", shelf))

    return meshes


def add_cameras(stage: Usd.Stage):
    cams = stage.DefinePrim("/Bedroom/Cameras", "Xform")
    presets = [
        ("wide",                 (2.0, 1.4, 4.5),  (2.0, 0.7, 2.0),  55.0),
        ("character_at_desk",    (2.6, 1.5, 1.5),  (3.5, 0.8, 2.0),  45.0),
        ("phone_closeup",        (3.4, 1.0, 2.1),  (3.5, 0.78, 2.05), 38.0),
        ("overhead",             (2.0, 2.3, 2.0),  (2.0, 0.5, 2.0),  60.0),
        ("window_view",          (2.0, 1.6, 0.3),  (2.0, 0.8, 3.0),  55.0),
    ]
    for name, origin, target, fov_deg in presets:
        cam_prim = stage.DefinePrim(f"/Bedroom/Cameras/{name}", "Camera")
        cam = UsdGeom.Camera(cam_prim)
        # Position the camera at origin; look at target.
        # USD camera looks down -Z in its local frame, so build a transform.
        o = np.array(origin, dtype=np.float64)
        t = np.array(target, dtype=np.float64)
        forward = t - o
        forward /= np.linalg.norm(forward) + 1e-9
        right = np.cross(forward, [0.0, 1.0, 0.0])
        right /= np.linalg.norm(right) + 1e-9
        up = np.cross(right, forward)
        # Rotation matrix columns = (right, up, -forward)
        mat = Gf.Matrix4d(
            float(right[0]),  float(right[1]),  float(right[2]),  0.0,
            float(up[0]),     float(up[1]),     float(up[2]),     0.0,
            float(-forward[0]), float(-forward[1]), float(-forward[2]), 0.0,
            float(o[0]),      float(o[1]),      float(o[2]),      1.0,
        )
        xf = UsdGeom.Xformable(cam_prim)
        xf.ClearXformOpOrder()
        xop = xf.AddTransformOp()
        xop.Set(mat)
        # Set fov via focal length + aperture (35mm-equiv film back)
        # fov = 2 * atan(aperture / (2 * focal))
        # aperture = 36mm, focal = 36 / (2 * tan(fov/2))
        import math
        focal = 36.0 / (2.0 * math.tan(math.radians(fov_deg) / 2.0))
        cam.GetFocalLengthAttr().Set(float(focal))
        cam.GetHorizontalApertureAttr().Set(36.0)
        cam.GetVerticalApertureAttr().Set(36.0 * 9.0 / 16.0)


def add_lights(stage: Usd.Stage):
    # Window rect light — primary
    rect_prim = stage.DefinePrim("/Bedroom/Lights/window_rect", "RectLight")
    rect = UsdLux.RectLight(rect_prim)
    rect.GetWidthAttr().Set(1.2)
    rect.GetHeightAttr().Set(1.5)
    rect.GetIntensityAttr().Set(3.0)
    xf = UsdGeom.Xformable(rect_prim)
    xop = xf.AddTranslateOp()
    xop.Set(Gf.Vec3d(ROOM_W/2, 0.9 + 0.75, 0.06))

    # Desk lamp — warm secondary
    sph_prim = stage.DefinePrim("/Bedroom/Lights/desk_lamp", "SphereLight")
    sph = UsdLux.SphereLight(sph_prim)
    sph.GetRadiusAttr().Set(0.10)
    sph.GetIntensityAttr().Set(1.2)
    xf = UsdGeom.Xformable(sph_prim)
    xop = xf.AddTranslateOp()
    xop.Set(Gf.Vec3d(ROOM_W - 0.85, 1.20, ROOM_D/2 + 0.18))

    # Ceiling distant fill — tertiary
    dst_prim = stage.DefinePrim("/Bedroom/Lights/ceiling", "DistantLight")
    dst = UsdLux.DistantLight(dst_prim)
    dst.GetIntensityAttr().Set(0.3)
    xf = UsdGeom.Xformable(dst_prim)
    xop = xf.AddTranslateOp()
    xop.Set(Gf.Vec3d(ROOM_W/2, ROOM_H - 0.05, ROOM_D/2))


def main():
    stage = Usd.Stage.CreateNew(str(OUT_PATH))
    stage.SetMetadata("metersPerUnit", 1.0)
    stage.SetMetadata("upAxis", "Y")
    root = UsdGeom.Xform.Define(stage, "/Bedroom")
    stage.SetDefaultPrim(root.GetPrim())

    for name, mesh in build_meshes():
        prim_path = f"/Bedroom/Geometry/{name}"
        u_mesh = UsdGeom.Mesh.Define(stage, prim_path)
        u_mesh.GetPointsAttr().Set([Gf.Vec3f(*v) for v in mesh.vertices])
        u_mesh.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
        u_mesh.GetFaceVertexIndicesAttr().Set([int(i) for i in mesh.faces.flatten()])

    add_cameras(stage)
    add_lights(stage)
    stage.Save()
    print(f"[anime-bedroom] wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
