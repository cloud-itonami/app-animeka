"""Build a generic anime classroom as a USD scene.

ADR-2605222000 — animeka v3. Pure Python, no Blender. Mirrors the
mangaka v3 classroom pattern (build-classroom.py) for animeka cuts.

Classroom layout:
  Room    8m W × 9m D × 3m H
  Floor / 4 walls
  6 columns × 4 rows of desks (24 desks total), each 0.65m × 0.45m × 0.75m
  Teacher's podium at front
  Blackboard on front wall, 4m × 1.2m
  3 windows on east wall, each 1.0m × 1.5m
  Door on west wall, 0.9m × 2.0m

Cameras (5):
  /Classroom/Cameras/wide            establishing wide
  /Classroom/Cameras/teacher_pov     teacher looking at students
  /Classroom/Cameras/student_pov     student looking at blackboard
  /Classroom/Cameras/back_corner     dramatic back-corner low angle
  /Classroom/Cameras/window_side     looking from window side

Lights (3):
  /Classroom/Lights/windows_rect    UsdLuxRectLight (daylight from windows)
  /Classroom/Lights/ceiling_fill    UsdLuxDistantLight (fluorescent fill)
  /Classroom/Lights/blackboard_spot UsdLuxSphereLight (slight rim on chalk)

Output: data/animeka/resources/usd/anime-classroom.usda
"""
from __future__ import annotations
import math
from pathlib import Path

import numpy as np
import trimesh
from pxr import Usd, UsdGeom, UsdLux, Gf

OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "animeka" / "resources" / "usd"
OUT_DIR.mkdir(exist_ok=True, parents=True)
OUT_PATH = OUT_DIR / "anime-classroom.usda"

ROOM_W, ROOM_D, ROOM_H = 8.0, 9.0, 3.0
N_COLS, N_ROWS = 6, 4
DESK_W, DESK_D, DESK_H = 0.65, 0.45, 0.75


def build_meshes() -> list[tuple[str, trimesh.Trimesh]]:
    meshes: list[tuple[str, trimesh.Trimesh]] = []

    # Shell
    floor = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    floor.apply_translation([ROOM_W/2, 0, ROOM_D/2])
    meshes.append(("floor", floor))
    ceil = trimesh.creation.box(extents=[ROOM_W, 0.01, ROOM_D])
    ceil.apply_translation([ROOM_W/2, ROOM_H, ROOM_D/2])
    meshes.append(("ceiling", ceil))

    for name, ext, pos in [
        ("wall_n", [ROOM_W, ROOM_H, 0.1], [ROOM_W/2, ROOM_H/2, 0]),
        ("wall_s", [ROOM_W, ROOM_H, 0.1], [ROOM_W/2, ROOM_H/2, ROOM_D]),
        ("wall_e", [0.1, ROOM_H, ROOM_D], [ROOM_W, ROOM_H/2, ROOM_D/2]),
        ("wall_w", [0.1, ROOM_H, ROOM_D], [0, ROOM_H/2, ROOM_D/2]),
    ]:
        w = trimesh.creation.box(extents=ext)
        w.apply_translation(pos)
        meshes.append((name, w))

    # 24 desks — 6 cols × 4 rows
    margin_front = 2.0   # space in front of front row
    margin_back = 1.5    # space behind last row
    margin_sides = 0.8
    available_w = ROOM_W - 2 * margin_sides
    available_d = ROOM_D - margin_front - margin_back
    col_step = available_w / (N_COLS - 1)
    row_step = available_d / (N_ROWS - 1)
    for ri in range(N_ROWS):
        for ci in range(N_COLS):
            x = margin_sides + ci * col_step
            z = margin_front + ri * row_step
            top = trimesh.creation.box(extents=[DESK_W, 0.04, DESK_D])
            top.apply_translation([x, DESK_H, z])
            meshes.append((f"desk_{ri}_{ci}_top", top))
            # 4 legs
            for x_off, z_off in [(-DESK_W/2 + 0.04, -DESK_D/2 + 0.04),
                                 (-DESK_W/2 + 0.04,  DESK_D/2 - 0.04),
                                 ( DESK_W/2 - 0.04, -DESK_D/2 + 0.04),
                                 ( DESK_W/2 - 0.04,  DESK_D/2 - 0.04)]:
                leg = trimesh.creation.box(extents=[0.04, DESK_H, 0.04])
                leg.apply_translation([x + x_off, DESK_H/2, z + z_off])
                meshes.append((f"desk_{ri}_{ci}_leg_{x_off:+.2f}_{z_off:+.2f}", leg))
            # Chair behind desk
            chair_seat = trimesh.creation.box(extents=[0.40, 0.04, 0.40])
            chair_seat.apply_translation([x, 0.45, z + DESK_D/2 + 0.20])
            meshes.append((f"chair_{ri}_{ci}_seat", chair_seat))
            chair_back = trimesh.creation.box(extents=[0.40, 0.45, 0.04])
            chair_back.apply_translation([x, 0.70, z + DESK_D/2 + 0.40])
            meshes.append((f"chair_{ri}_{ci}_back", chair_back))

    # Teacher's podium at front
    podium = trimesh.creation.box(extents=[1.2, 1.0, 0.6])
    podium.apply_translation([ROOM_W/2, 0.5, 0.8])
    meshes.append(("podium", podium))

    # Blackboard on front wall (north wall)
    board = trimesh.creation.box(extents=[4.0, 1.2, 0.06])
    board.apply_translation([ROOM_W/2, 1.7, 0.08])
    meshes.append(("blackboard", board))

    # 3 windows on east wall — placed as window-frame boxes
    for i, z_pos in enumerate([2.0, 4.5, 7.0]):
        win = trimesh.creation.box(extents=[0.05, 1.5, 1.0])
        win.apply_translation([ROOM_W - 0.05, 1.5, z_pos])
        meshes.append((f"window_{i}", win))

    # Door on west wall
    door = trimesh.creation.box(extents=[0.05, 2.0, 0.9])
    door.apply_translation([0.05, 1.0, ROOM_D - 1.0])
    meshes.append(("door", door))

    return meshes


def _camera_matrix(origin, target):
    o = np.array(origin, dtype=np.float64)
    t = np.array(target, dtype=np.float64)
    forward = t - o
    forward /= np.linalg.norm(forward) + 1e-9
    right = np.cross(forward, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right) + 1e-9
    up = np.cross(right, forward)
    return Gf.Matrix4d(
        float(right[0]),  float(right[1]),  float(right[2]),  0.0,
        float(up[0]),     float(up[1]),     float(up[2]),     0.0,
        float(-forward[0]), float(-forward[1]), float(-forward[2]), 0.0,
        float(o[0]),      float(o[1]),      float(o[2]),      1.0,
    )


def add_cameras(stage: Usd.Stage):
    presets = [
        ("wide",         (4.0, 1.9, 8.0),    (4.0, 1.0, 4.0),   55.0),
        ("teacher_pov",  (4.0, 1.7, 1.0),    (4.0, 1.0, 6.0),   60.0),
        ("student_pov",  (4.0, 1.0, 6.0),    (4.0, 1.6, 0.5),   45.0),
        ("back_corner",  (0.8, 1.0, 8.0),    (4.0, 1.6, 0.8),   60.0),
        ("window_side",  (7.0, 1.5, 4.5),    (3.0, 1.0, 4.5),   55.0),
    ]
    for name, origin, target, fov_deg in presets:
        cam_prim = stage.DefinePrim(f"/Classroom/Cameras/{name}", "Camera")
        cam = UsdGeom.Camera(cam_prim)
        xf = UsdGeom.Xformable(cam_prim)
        xf.ClearXformOpOrder()
        xop = xf.AddTransformOp()
        xop.Set(_camera_matrix(origin, target))
        focal = 36.0 / (2.0 * math.tan(math.radians(fov_deg) / 2.0))
        cam.GetFocalLengthAttr().Set(float(focal))
        cam.GetHorizontalApertureAttr().Set(36.0)
        cam.GetVerticalApertureAttr().Set(36.0 * 9.0 / 16.0)


def add_lights(stage: Usd.Stage):
    # 3 rect lights for the windows
    for i, z_pos in enumerate([2.0, 4.5, 7.0]):
        prim = stage.DefinePrim(f"/Classroom/Lights/window_{i}_rect", "RectLight")
        rect = UsdLux.RectLight(prim)
        rect.GetWidthAttr().Set(1.0)
        rect.GetHeightAttr().Set(1.5)
        rect.GetIntensityAttr().Set(4.0)
        xf = UsdGeom.Xformable(prim)
        xop = xf.AddTranslateOp()
        xop.Set(Gf.Vec3d(ROOM_W - 0.05, 1.5, z_pos))

    # Ceiling distant — fluorescent fill
    prim = stage.DefinePrim("/Classroom/Lights/ceiling_fill", "DistantLight")
    dst = UsdLux.DistantLight(prim)
    dst.GetIntensityAttr().Set(0.6)
    xf = UsdGeom.Xformable(prim)
    xop = xf.AddTranslateOp()
    xop.Set(Gf.Vec3d(ROOM_W/2, ROOM_H - 0.05, ROOM_D/2))

    # Blackboard spot (chalk highlight)
    prim = stage.DefinePrim("/Classroom/Lights/blackboard_spot", "SphereLight")
    sph = UsdLux.SphereLight(prim)
    sph.GetRadiusAttr().Set(0.20)
    sph.GetIntensityAttr().Set(0.8)
    xf = UsdGeom.Xformable(prim)
    xop = xf.AddTranslateOp()
    xop.Set(Gf.Vec3d(ROOM_W/2, ROOM_H - 0.4, 1.2))


def main():
    stage = Usd.Stage.CreateNew(str(OUT_PATH))
    stage.SetMetadata("metersPerUnit", 1.0)
    stage.SetMetadata("upAxis", "Y")
    root = UsdGeom.Xform.Define(stage, "/Classroom")
    stage.SetDefaultPrim(root.GetPrim())

    for name, mesh in build_meshes():
        prim_path = f"/Classroom/Geometry/{name}"
        u_mesh = UsdGeom.Mesh.Define(stage, prim_path)
        u_mesh.GetPointsAttr().Set([Gf.Vec3f(*v) for v in mesh.vertices])
        u_mesh.GetFaceVertexCountsAttr().Set([3] * len(mesh.faces))
        u_mesh.GetFaceVertexIndicesAttr().Set([int(i) for i in mesh.faces.flatten()])

    add_cameras(stage)
    add_lights(stage)
    stage.Save()
    print(f"[anime-classroom] wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
