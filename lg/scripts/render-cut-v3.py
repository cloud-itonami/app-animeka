"""render-cut-v3 — single-cut renderer using AnimekaUSDScene + ControlNet stack.

ADR-2605222000 — animeka v3. Mirrors mangaka v3's render-arc01-page-v3.py.

Builds and submits a ComfyUI workflow JSON for ONE animeka cut. The
workflow chains:

  AnimekaUSDLoader → AnimekaUSDLight + AnimekaUSDMaterial + AnimekaUSDInspect
                  → AnimekaShotComposition (pose-driven) OR
                    AnimekaUSDCameraPrim (named camera) OR
                    AnimekaCameraKeyframe (hand-authored, time-stamped)
                  → AnimekaCameraViewFromParams (depth + canny + camera)
                  → AnimekaPoseFromLibrary → AnimekaProjectPose (openpose)
                  → AnimekaCharacterEmotion → AnimekaPromptConcat
                  → CLIPTextEncode + 3× ControlNetApply + LoRA
                  → KSampler → VAEDecode → SaveImage

For camera-move cuts (TU/PAN/TB/TILT/ZOOM), pair an
AnimekaCameraMovePreset on top of either a shot composition or a
hand-authored keyframe; the output (start, end) is fed into
AnimekaInterpolateCameras per frame in the cut's duration.

Usage (against a running host ComfyUI):
    python render-cut-v3.py \
      --host 192.168.50.21:8188 \
      --scene anime-bedroom \
      --shot MS --angle low --rule thirds_R \
      --pose anxious_at_desk --emotion determined \
      --pelvis-x 3.0 --pelvis-y 0.5 --pelvis-z 2.0 \
      --frame-num 1 \
      --lora character-yuto-v1.safetensors --lora-strength 0.55 \
      --checkpoint animagine-xl-4.0.safetensors \
      --out /tmp/test-animeka-cut-v3.png

For camera-move sweep (e.g. ZOOM_IN over 12 frames):
    python render-cut-v3.py ... --move ZOOM_IN --move-distance 12 \
      --duration-frames 12 --sweep-frames 1,6,12

Outputs:
  - One PNG per --sweep-frames entry under --out
  - The full workflow JSON saved next to it as {out}.workflow.json
    (drag-drop into ComfyUI editor to restore the parametric state)
"""
from __future__ import annotations
import argparse
import copy
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any


ANIME_STYLE = (
    "anime production cel art, full color illustration, vibrant cel shading, "
    "detailed shading and highlights, character on-model, expressive face, "
    "detailed eyes with catchlights, perfect anatomy, sharp focus, "
    "masterpiece, best quality, very aesthetic, absurdres, highres, newest, "
    "1girl or 1boy, solo, looking at viewer"
)
NEGATIVE = (
    "lowres, worst quality, low quality, bad anatomy, bad hands, missing fingers, "
    "extra digit, fewer digits, cropped, text, signature, watermark, username, blurry, "
    "jpeg artifacts, ugly, duplicate, mutated, deformed, normal quality, monochrome, "
    "gray background, placeholder, solid color background, sketch, lineart only, "
    "unfinished, rough sketch, wireframe"
)


def build_workflow(args: argparse.Namespace, frame_num: int) -> dict[str, Any]:
    """Construct a ComfyUI workflow dict for a single keyframe.

    Returns a {prompt: {nodes...}} POST body for /prompt.
    """
    nodes: dict[str, dict[str, Any]] = {}

    # 1. USD Loader
    nodes["10"] = {"class_type": "AnimekaUSDLoader",
                    "inputs": {"scene_name": args.scene}}

    # 2. Light + Material + Inspect (auxiliary prompt hints)
    nodes["11"] = {"class_type": "AnimekaUSDLight",
                    "inputs": {"scene": ["10", 0]}}
    nodes["12"] = {"class_type": "AnimekaUSDMaterial",
                    "inputs": {"scene": ["10", 0]}}

    # 3. Pose from library
    nodes["20"] = {"class_type": "AnimekaPoseFromLibrary",
                    "inputs": {"pose_name": args.pose,
                                "pelvis_x": args.pelvis_x, "pelvis_y": args.pelvis_y,
                                "pelvis_z": args.pelvis_z, "scale": 1.0}}

    # 4. Camera params — three modes
    if args.camera_path:
        # Mode A: named UsdGeomCamera prim from the scene
        nodes["30"] = {"class_type": "AnimekaUSDCameraPrim",
                        "inputs": {"scene": ["10", 0],
                                    "camera_path": args.camera_path,
                                    "width": args.width, "height": args.height,
                                    "frame_num": frame_num}}
        cam_params_ref = ["30", 0]
    elif args.shot:
        # Mode B: pose-driven shot composition
        nodes["30"] = {"class_type": "AnimekaShotComposition",
                        "inputs": {"subject_pose": ["20", 0],
                                    "shot_type": args.shot, "angle": args.angle,
                                    "rule": args.rule,
                                    "subject_yaw_deg": args.subject_yaw_deg,
                                    "width": args.width, "height": args.height,
                                    "frame_num": frame_num}}
        cam_params_ref = ["30", 0]
    else:
        # Mode C: hand-authored time-stamped keyframe
        nodes["30"] = {"class_type": "AnimekaCameraKeyframe",
                        "inputs": {"origin_x": args.origin_x or 0.0,
                                    "origin_y": args.origin_y or 1.5,
                                    "origin_z": args.origin_z or 0.0,
                                    "target_x": args.target_x or 2.0,
                                    "target_y": args.target_y or 1.0,
                                    "target_z": args.target_z or 2.0,
                                    "fov_deg":  args.fov_deg,
                                    "width": args.width, "height": args.height,
                                    "frame_num": frame_num}}
        cam_params_ref = ["30", 0]

    # 4b. Camera move — wrap the start_camera into a move preset and
    #     pick the per-frame interp via AnimekaInterpolateCameras.
    if args.move:
        nodes["31"] = {"class_type": "AnimekaCameraMovePreset",
                        "inputs": {"start_camera": cam_params_ref,
                                    "move": args.move,
                                    "distance": args.move_distance,
                                    "duration_frames": args.duration_frames}}
        # t = (frame_num - 1) / (duration_frames - 1), clamped to [0,1]
        if args.duration_frames > 1:
            t = max(0.0, min(1.0, (frame_num - 1) / (args.duration_frames - 1)))
        else:
            t = 0.0
        nodes["32"] = {"class_type": "AnimekaInterpolateCameras",
                        "inputs": {"start": ["31", 0],
                                    "end":   ["31", 1],
                                    "t":     t}}
        cam_params_ref = ["32", 0]

    # 5. Camera view from params → depth + canny + ANIMEKA_CAMERA
    nodes["40"] = {"class_type": "AnimekaCameraViewFromParams",
                    "inputs": {"scene": ["10", 0],
                                "camera_params": cam_params_ref,
                                "render_resolution": args.render_resolution}}

    # 6. Project pose onto camera → openpose image
    nodes["50"] = {"class_type": "AnimekaProjectPose",
                    "inputs": {"pose": ["20", 0], "camera": ["40", 2]}}

    # 7. Emotion + prompt concat
    nodes["60"] = {"class_type": "AnimekaCharacterEmotion",
                    "inputs": {"emotion": args.emotion,
                                "intensity": args.emotion_intensity}}
    nodes["61"] = {"class_type": "AnimekaPromptConcat",
                    "inputs": {"base": args.base_prompt or "",
                                "face_emotion": ["60", 0],
                                "body_modifier": ["60", 1],
                                "extra_suffix": ANIME_STYLE}}

    # 8. Checkpoint + LoRA + CLIP encode
    nodes["70"] = {"class_type": "CheckpointLoaderSimple",
                    "inputs": {"ckpt_name": args.checkpoint}}
    if args.lora:
        nodes["71"] = {"class_type": "LoraLoaderModelOnly",
                        "inputs": {"model": ["70", 0],
                                    "lora_name": args.lora,
                                    "strength_model": args.lora_strength}}
        model_ref = ["71", 0]
    else:
        model_ref = ["70", 0]
    nodes["72"] = {"class_type": "CLIPTextEncode",
                    "inputs": {"text": ["61", 0], "clip": ["70", 1]}}
    nodes["73"] = {"class_type": "CLIPTextEncode",
                    "inputs": {"text": NEGATIVE, "clip": ["70", 1]}}

    # 9. ControlNet stack — canny + depth + openpose
    nodes["80"] = {"class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": args.canny_cn}}
    nodes["81"] = {"class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": args.depth_cn}}
    nodes["82"] = {"class_type": "ControlNetLoader",
                    "inputs": {"control_net_name": args.openpose_cn}}
    nodes["83"] = {"class_type": "ControlNetApply",
                    "inputs": {"conditioning": ["72", 0],
                                "control_net": ["80", 0],
                                "image": ["40", 1],
                                "strength": args.canny_strength}}
    nodes["84"] = {"class_type": "ControlNetApply",
                    "inputs": {"conditioning": ["83", 0],
                                "control_net": ["81", 0],
                                "image": ["40", 0],
                                "strength": args.depth_strength}}
    nodes["85"] = {"class_type": "ControlNetApply",
                    "inputs": {"conditioning": ["84", 0],
                                "control_net": ["82", 0],
                                "image": ["50", 0],
                                "strength": args.openpose_strength}}

    # 10. Sampler + decode + save
    nodes["90"] = {"class_type": "EmptyLatentImage",
                    "inputs": {"width": args.width, "height": args.height, "batch_size": 1}}
    nodes["91"] = {"class_type": "KSampler",
                    "inputs": {"seed": args.seed + frame_num,
                                "steps": args.steps,
                                "cfg": args.cfg,
                                "sampler_name": args.sampler,
                                "scheduler": args.scheduler,
                                "denoise": 1.0,
                                "model": model_ref,
                                "positive": ["85", 0],
                                "negative": ["73", 0],
                                "latent_image": ["90", 0]}}
    nodes["92"] = {"class_type": "VAEDecode",
                    "inputs": {"samples": ["91", 0], "vae": ["70", 2]}}
    nodes["93"] = {"class_type": "SaveImage",
                    "inputs": {"images": ["92", 0],
                                "filename_prefix": f"animeka-v3-{args.scene}-f{frame_num:04d}"}}

    return {"prompt": nodes}


def submit_and_wait(host: str, workflow: dict[str, Any], timeout: float = 600.0) -> str:
    """POST workflow to ComfyUI host, poll history for completion, return filename."""
    base = f"http://{host}"
    data = json.dumps(workflow).encode("utf-8")
    req = urllib.request.Request(f"{base}/prompt", data=data,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
    prompt_id = body.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"no prompt_id in response: {body}")

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(3.0)
        try:
            with urllib.request.urlopen(f"{base}/history/{prompt_id}", timeout=5) as resp:
                hist = json.loads(resp.read())
        except Exception as e:
            print(f"  history poll error: {e}", file=sys.stderr)
            continue
        run = hist.get(prompt_id)
        if not run:
            continue
        for output in run.get("outputs", {}).values():
            for img in output.get("images", []):
                fn = img.get("filename")
                if fn:
                    return fn
    raise TimeoutError(f"timed out waiting for prompt {prompt_id}")


def fetch_image(host: str, filename: str, out_path: Path) -> None:
    base = f"http://{host}"
    params = urllib.parse.urlencode({"filename": filename, "type": "output"})
    with urllib.request.urlopen(f"{base}/view?{params}", timeout=30) as resp:
        out_path.write_bytes(resp.read())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost:8188", help="ComfyUI host:port")
    ap.add_argument("--scene", required=True, help="USD scene_name in animeka-assets/usd/")
    # camera mode (mutually exclusive but enforced loosely)
    ap.add_argument("--shot", help="ECU|CU|MS|MLS|LS|ELS|POV|OTS|TWO|INSERT")
    ap.add_argument("--angle", default="eye_level",
                    help="eye_level|high|low|overhead|worm|dutch_L|dutch_R")
    ap.add_argument("--rule", default="thirds_R",
                    help="center|thirds_L|thirds_R|thirds_top_L|thirds_top_R|...")
    ap.add_argument("--subject-yaw-deg", type=float, default=0.0)
    ap.add_argument("--camera-path", help="UsdGeomCamera prim path (alt to --shot)")
    ap.add_argument("--origin-x", type=float)
    ap.add_argument("--origin-y", type=float)
    ap.add_argument("--origin-z", type=float)
    ap.add_argument("--target-x", type=float)
    ap.add_argument("--target-y", type=float)
    ap.add_argument("--target-z", type=float)
    ap.add_argument("--fov-deg", type=float, default=45.0)
    ap.add_argument("--width", type=int, default=1024)
    ap.add_argument("--height", type=int, default=1024)
    ap.add_argument("--render-resolution", type=int, default=608)
    # pose
    ap.add_argument("--pose", default="standing_facing_camera")
    ap.add_argument("--pelvis-x", type=float, default=3.0)
    ap.add_argument("--pelvis-y", type=float, default=0.5)
    ap.add_argument("--pelvis-z", type=float, default=2.0)
    # emotion
    ap.add_argument("--emotion", default="determined")
    ap.add_argument("--emotion-intensity", type=float, default=1.0)
    ap.add_argument("--base-prompt", default="")
    # camera move
    ap.add_argument("--move", help="TU|TB|PAN_L|PAN_R|TILT_UP|TILT_DOWN|ZOOM_IN|ZOOM_OUT")
    ap.add_argument("--move-distance", type=float, default=1.0)
    ap.add_argument("--duration-frames", type=int, default=12)
    ap.add_argument("--sweep-frames", default="1",
                    help="comma-separated frame_num values to render (e.g. 1,6,12)")
    ap.add_argument("--frame-num", type=int, default=1,
                    help="single frame_num if --sweep-frames is left default")
    # model + lora
    ap.add_argument("--checkpoint", default="animagine-xl-4.0.safetensors")
    ap.add_argument("--lora")
    ap.add_argument("--lora-strength", type=float, default=0.55)
    # sampler
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--steps", type=int, default=35)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--sampler", default="dpmpp_2m_sde")
    ap.add_argument("--scheduler", default="karras")
    # controlnet
    ap.add_argument("--canny-cn", default="control_v11p_sd15_canny.pth")
    ap.add_argument("--depth-cn", default="control_v11f1p_sd15_depth.pth")
    ap.add_argument("--openpose-cn", default="control_v11p_sd15_openpose.pth")
    ap.add_argument("--canny-strength", type=float, default=0.35)
    ap.add_argument("--depth-strength", type=float, default=0.25)
    ap.add_argument("--openpose-strength", type=float, default=0.65)
    # output
    ap.add_argument("--out", default="/tmp/animeka-cut-v3.png")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    frames = [int(f.strip()) for f in args.sweep_frames.split(",") if f.strip()]
    if not frames:
        frames = [args.frame_num]

    out_root = Path(args.out)
    for i, frame_num in enumerate(frames):
        wf = build_workflow(args, frame_num)
        wf_path = out_root.with_suffix(f".f{frame_num:04d}.workflow.json")
        wf_path.write_text(json.dumps(wf, indent=2))
        if not args.host:
            print(f"[dry-run] wrote {wf_path}")
            continue
        print(f"[render-cut-v3] frame_num={frame_num} → submitting to {args.host}")
        try:
            fn = submit_and_wait(args.host, wf)
        except Exception as e:
            print(f"  submit failed: {e}", file=sys.stderr)
            continue
        out_path = (out_root.with_suffix(f".f{frame_num:04d}.png")
                     if len(frames) > 1 else out_root)
        fetch_image(args.host, fn, out_path)
        print(f"  wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
