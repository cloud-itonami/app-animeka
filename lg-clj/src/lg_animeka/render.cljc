(ns lg-animeka.render
  "Injectable image/video/social boundary seams — clj port of the native-only
  edges the animeka graphs reach for (ADR-2606280030):

    - ComfyUI render  (`kotodama.primitives.shinshi_image/_comfy_render_png`)
    - PDS blob upload (`…/_upload_blob_to_pds`)
    - PDS createRecord social post
    - ffmpeg concat   (assemble_episode)

  None of these have a bb host (ComfyUI/ffmpeg are native services; PDS is a
  remote atproto server). Following the actor-swap pattern, each is a dynamic
  seam whose default is `not configured`, swappable to a babashka.process /
  babashka.http-client implementation (or a kotoba-backed one) without touching
  any graph. Tests rebind these to deterministic stubs.

  The single piece of pure, host-independent content — the autopilot ComfyUI
  workflow JSON builder — is ported faithfully here and unit-tested."
  (:require [clojure.string :as str]))

(def ckpt "animagine-xl-4.0.safetensors")

(def neg-char
  (str "lowres, worst quality, low quality, bad anatomy, bad hands, missing fingers, "
       "extra digit, fewer digits, cropped, text, signature, watermark, username, blurry, "
       "jpeg artifacts, ugly, duplicate, mutated, deformed, monochrome, nsfw"))

(def neg-bg
  (str "lowres, worst quality, low quality, blurry, jpeg artifacts, watermark, signature, "
       "people, characters, person, human, nsfw"))

(defn quality-workflow
  "Faithful port of autopilot `_build_quality_workflow`: animagine-xl-4.0 /
  Illustrious ComfyUI graph with CLIP skip=2 (CLIPSetLastLayer -2) and tunable
  cfg/sampler/scheduler. Pure data — host-independent and unit-tested."
  [{:keys [prompt negative ckpt w h steps cfg sampler scheduler seed]
    :or {negative neg-char ckpt ckpt cfg 7.0 sampler "dpmpp_2m" scheduler "karras"}}]
  {"1" {:class_type "CLIPSetLastLayer" :inputs {:clip ["4" 1] :stop_at_clip_layer -2}}
   "3" {:class_type "KSampler"
        :inputs {:seed (or seed 0) :steps steps :cfg cfg
                 :sampler_name sampler :scheduler scheduler :denoise 1.0
                 :model ["4" 0] :positive ["6" 0] :negative ["7" 0]
                 :latent_image ["5" 0]}}
   "4" {:class_type "CheckpointLoaderSimple" :inputs {:ckpt_name ckpt}}
   "5" {:class_type "EmptyLatentImage" :inputs {:width w :height h :batch_size 1}}
   "6" {:class_type "CLIPTextEncode" :inputs {:text prompt :clip ["1" 0]}}
   "7" {:class_type "CLIPTextEncode" :inputs {:text negative :clip ["1" 0]}}
   "8" {:class_type "VAEDecode" :inputs {:samples ["3" 0] :vae ["4" 2]}}
   "9" {:class_type "SaveImage" :inputs {:images ["8" 0] :filename_prefix "animeka"}}})

(defn- not-configured-render [& _]
  {:error "comfy render: not configured (inject render/*render-png*)"})

;; ── seams ────────────────────────────────────────────────────────────────────

;; (prompt {:w :h :steps :cfg :sampler :scheduler :negative}) →
;;   {:cid <blob-cid>} | {:error <str>}
;; Default = not configured. A real impl builds a ComfyUI workflow, renders a
;; PNG, and uploads it to PDS, returning the blob CID.
(def ^:dynamic *render-png* not-configured-render)

;; (cut-rkey kf-cid bg-cid fps duration-sec) → {:output-cid <cid>} | {:error <str>}
(def ^:dynamic *composite* (fn [& _] {:error "compositor: not configured"}))

;; (record-map) → {:uri <at-uri>} | {:error <str>} | {:skipped true}
(def ^:dynamic *pds-post* (fn [_record] {:error "pds: not configured"}))

;; (cids out-path fps) → {:cid <cid> :duration-sec <n>} | {:error <str>}
(def ^:dynamic *ffmpeg-concat* (fn [& _] {:error "ffmpeg: not configured"}))

(defn render-png
  "Render+upload via the injected seam. opts merged with defaults."
  [prompt opts]
  (*render-png* prompt (merge {:w 1024 :h 1024 :steps 28 :cfg 7.0
                               :sampler "dpmpp_2m" :scheduler "karras"
                               :negative neg-char} opts)))
