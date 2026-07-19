"""Animeka character pose library + BODY_18 OpenPose skeleton renderer.

ADR-2605222000 — animeka v3. Shared semantics with the mangaka v3
character-rig.py (BODY_18 / COCO 18-keypoint skeleton, same joint
naming, same colour palette). 6 poses:

  anxious_at_desk           seated, head down, hands near phone
  standing_facing_camera    front-on standing portrait
  looking_at_phone          standing, looking down at phone
  walking_running           mid-stride action pose
  sleeping_at_desk          collapsed on desk
  talking_animated          standing, arms gesturing

Use this script as a CLI sanity check that the pose functions
produce sane keypoints, and to generate openpose PNG sweeps for
checking against ControlNet output. The same POSE_LIBRARY dict is
mirrored into `comfy_custom_nodes/AnimekaUSDScene/__init__.py` so
ComfyUI nodes load without importing this file.

Run:
    python lg/scripts/usd-scenes/character-rig.py
    # writes /tmp/animeka-pose-{name}.png per pose
"""
from __future__ import annotations
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OUT_DIR = Path("/tmp")

KP_NAMES = ["nose", "neck", "r_shoulder", "r_elbow", "r_wrist",
            "l_shoulder", "l_elbow", "l_wrist", "r_hip", "r_knee", "r_ankle",
            "l_hip", "l_knee", "l_ankle", "r_eye", "l_eye", "r_ear", "l_ear"]
KP_COLORS = [(255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),
             (85,255,0),(0,255,0),(0,255,85),(0,255,170),(0,255,255),
             (0,170,255),(0,85,255),(0,0,255),(85,0,255),(170,0,255),
             (255,0,255),(255,0,170),(255,0,85)]
LIMBS = [(0,1),(1,2),(2,3),(3,4),(1,5),(5,6),(6,7),(1,8),(8,9),
         (9,10),(1,11),(11,12),(12,13),(0,14),(0,15),(14,16),(15,17)]
LIMB_COLORS = [(255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),
               (85,255,0),(0,255,0),(0,255,85),(0,255,170),(0,255,255),
               (0,170,255),(0,85,255),(0,0,255),(85,0,255),(170,0,255),
               (255,0,255),(255,0,170)]

SEGMENTS = {"neck_to_head":0.20,"shoulder_width":0.40,"shoulder_to_elbow":0.30,
            "elbow_to_wrist":0.28,"hip_width":0.30,"hip_to_knee":0.45,
            "knee_to_ankle":0.42,"torso_height":0.60,"head_radius":0.10}


def _deg(d): return math.radians(d)
def _rotx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]])


def _eyes_ears(nose):
    return {
        "r_eye": nose + np.array([-0.04, 0.03, 0.04]),
        "l_eye": nose + np.array([ 0.04, 0.03, 0.04]),
        "r_ear": nose + np.array([-0.08, 0.04, -0.02]),
        "l_ear": nose + np.array([ 0.08, 0.04, -0.02]),
    }


# Mirrored into AnimekaUSDScene/__init__.py — keep both in sync.

def pose_anxious_at_desk(p):
    s = SEGMENTS
    pose = {}
    torso_dir = _rotx(_deg(-5)) @ np.array([0, 1, 0])
    neck = p + torso_dir * s["torso_height"]; pose["neck"] = neck
    head_dir = _rotx(_deg(-15)) @ torso_dir
    pose["nose"] = neck + head_dir * s["neck_to_head"]; pose.update(_eyes_ears(pose["nose"]))
    sh_y = neck[1] + 0.02
    pose["r_shoulder"] = np.array([neck[0] - s["shoulder_width"]/2, sh_y, neck[2]])
    pose["l_shoulder"] = np.array([neck[0] + s["shoulder_width"]/2, sh_y, neck[2]])
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.05,-0.15,0.20])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.05, 0.00,0.30])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.05,-0.15,0.18])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([0.00, 0.00,0.20])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2,0,0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2,0,0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0.02,-0.05,s["hip_to_knee"]])
    pose["l_knee"]  = pose["l_hip"] + np.array([-0.02,-0.05,s["hip_to_knee"]])
    pose["r_ankle"] = pose["r_knee"] + np.array([0,-s["knee_to_ankle"],0.05])
    pose["l_ankle"] = pose["l_knee"] + np.array([0,-s["knee_to_ankle"],0.05])
    return pose


def pose_standing_facing_camera(p):
    s = SEGMENTS
    pose = {}
    neck = p + np.array([0, s["torso_height"], 0]); pose["neck"] = neck
    pose["nose"] = neck + np.array([0, s["neck_to_head"], 0.02]); pose.update(_eyes_ears(pose["nose"]))
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0.02, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0.02, 0])
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.02,-s["shoulder_to_elbow"],0])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0,-s["elbow_to_wrist"],0])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.02,-s["shoulder_to_elbow"],0])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([0,-s["elbow_to_wrist"],0])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0,-s["hip_to_knee"],0])
    pose["l_knee"]  = pose["l_hip"] + np.array([0,-s["hip_to_knee"],0])
    pose["r_ankle"] = pose["r_knee"] + np.array([0,-s["knee_to_ankle"],0])
    pose["l_ankle"] = pose["l_knee"] + np.array([0,-s["knee_to_ankle"],0])
    return pose


def pose_looking_at_phone(p):
    s = SEGMENTS
    pose = {}
    neck = p + np.array([0, s["torso_height"], 0]); pose["neck"] = neck
    head_dir = _rotx(_deg(-25)) @ np.array([0, 1, 0])
    pose["nose"] = neck + head_dir * s["neck_to_head"]; pose.update(_eyes_ears(pose["nose"]))
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0, 0])
    pose["r_elbow"] = pose["r_shoulder"] + np.array([0.02,-0.20,0.20])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.05,-0.05,0.20])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([-0.02,-0.20,0.20])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([-0.05,-0.05,0.20])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0,-s["hip_to_knee"],0])
    pose["l_knee"]  = pose["l_hip"] + np.array([0,-s["hip_to_knee"],0])
    pose["r_ankle"] = pose["r_knee"] + np.array([0,-s["knee_to_ankle"],0])
    pose["l_ankle"] = pose["l_knee"] + np.array([0,-s["knee_to_ankle"],0])
    return pose


def pose_walking_running(p):
    s = SEGMENTS
    pose = {}
    torso_dir = _rotx(_deg(8)) @ np.array([0, 1, 0])
    neck = p + torso_dir * s["torso_height"]; pose["neck"] = neck
    head_dir = _rotx(_deg(5)) @ torso_dir
    pose["nose"] = neck + head_dir * s["neck_to_head"]; pose.update(_eyes_ears(pose["nose"]))
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0, 0])
    pose["r_elbow"] = pose["r_shoulder"] + np.array([0.05, -0.15, 0.20])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.0, -0.10, 0.25])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([-0.05, -0.15, -0.20])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([0.0, -0.10, -0.25])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0, -s["hip_to_knee"]*0.85,  0.25])
    pose["l_knee"]  = pose["l_hip"] + np.array([0, -s["hip_to_knee"]*0.85, -0.20])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"]*0.7,  0.20])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"]*0.7, -0.25])
    return pose


def pose_sleeping_at_desk(p):
    s = SEGMENTS
    pose = {}
    torso_dir = _rotx(_deg(-40)) @ np.array([0, 1, 0])
    neck = p + torso_dir * s["torso_height"]; pose["neck"] = neck
    head_dir = _rotx(_deg(-60)) @ np.array([0, 1, 0])
    pose["nose"] = neck + head_dir * s["neck_to_head"]; pose.update(_eyes_ears(pose["nose"]))
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0, 0.05])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0, 0.05])
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.02, -0.10, 0.30])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([0.05,  0.00, 0.20])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.02, -0.10, 0.30])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([-0.05, 0.00, 0.20])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0, -0.05, s["hip_to_knee"]])
    pose["l_knee"]  = pose["l_hip"] + np.array([0, -0.05, s["hip_to_knee"]])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"], 0.05])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], 0.05])
    return pose


def pose_talking_animated(p):
    s = SEGMENTS
    pose = {}
    neck = p + np.array([0, s["torso_height"], 0]); pose["neck"] = neck
    pose["nose"] = neck + np.array([0, s["neck_to_head"], 0.02]); pose.update(_eyes_ears(pose["nose"]))
    pose["r_shoulder"] = neck + np.array([-s["shoulder_width"]/2, 0.02, 0])
    pose["l_shoulder"] = neck + np.array([ s["shoulder_width"]/2, 0.02, 0])
    pose["r_elbow"] = pose["r_shoulder"] + np.array([-0.10, -0.10, 0.10])
    pose["r_wrist"] = pose["r_elbow"]   + np.array([-0.05,  0.15, 0.10])
    pose["l_elbow"] = pose["l_shoulder"] + np.array([ 0.10, -0.10, 0.10])
    pose["l_wrist"] = pose["l_elbow"]   + np.array([ 0.05,  0.15, 0.10])
    pose["r_hip"] = p + np.array([-s["hip_width"]/2, 0, 0])
    pose["l_hip"] = p + np.array([ s["hip_width"]/2, 0, 0])
    pose["r_knee"]  = pose["r_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["l_knee"]  = pose["l_hip"] + np.array([0, -s["hip_to_knee"], 0])
    pose["r_ankle"] = pose["r_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    pose["l_ankle"] = pose["l_knee"] + np.array([0, -s["knee_to_ankle"], 0])
    return pose


POSE_LIBRARY = {
    "anxious_at_desk":        pose_anxious_at_desk,
    "standing_facing_camera": pose_standing_facing_camera,
    "looking_at_phone":       pose_looking_at_phone,
    "walking_running":        pose_walking_running,
    "sleeping_at_desk":       pose_sleeping_at_desk,
    "talking_animated":       pose_talking_animated,
}


def project_skeleton(kp, camera_origin, camera_target, fov_deg, W, H):
    """Project 3D keypoints to a 2D openpose PNG."""
    o = np.array(camera_origin, dtype=np.float64)
    t = np.array(camera_target, dtype=np.float64)
    forward = t - o; forward /= np.linalg.norm(forward) + 1e-9
    right = np.cross(forward, [0, 1, 0]); right /= np.linalg.norm(right) + 1e-9
    up = np.cross(right, forward)
    fov = math.radians(fov_deg)
    half_h = math.tan(fov / 2)
    half_w = half_h * (W / H)

    pts2d = {}
    for name in KP_NAMES:
        if name not in kp:
            continue
        p3 = kp[name]
        diff = p3 - o
        z = float(diff @ forward)
        if z <= 1e-3:
            continue
        x_cam = float(diff @ right)
        y_cam = float(diff @ up)
        u = (x_cam / z + half_w) / (2 * half_w) * W
        v = (1.0 - (y_cam / z + half_h) / (2 * half_h)) * H
        if 0 <= u < W and 0 <= v < H:
            pts2d[name] = (u, v)

    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    for li, (i, j) in enumerate(LIMBS):
        ni, nj = KP_NAMES[i], KP_NAMES[j]
        if ni in pts2d and nj in pts2d:
            color = LIMB_COLORS[li] if li < len(LIMB_COLORS) else (255, 255, 255)
            draw.line([pts2d[ni], pts2d[nj]], fill=color, width=6)
    for idx, name in enumerate(KP_NAMES):
        if name in pts2d:
            u, v = pts2d[name]
            color = KP_COLORS[idx]
            draw.ellipse([u - 6, v - 6, u + 6, v + 6], fill=color)
    return img


def main():
    """CLI sanity sweep — produce one openpose PNG per pose."""
    pelvis = np.array([2.0, 0.5, 2.0])
    cam_origin = (2.0, 1.4, 4.5)
    cam_target = (2.0, 1.0, 2.0)
    fov = 50.0
    W, H = 768, 1024
    for name, fn in POSE_LIBRARY.items():
        kp = fn(pelvis)
        img = project_skeleton(kp, cam_origin, cam_target, fov, W, H)
        out = OUT_DIR / f"animeka-pose-{name}.png"
        img.save(str(out))
        print(f"[character-rig] wrote {out}")


if __name__ == "__main__":
    main()
