# etzhayyim-project-animeka — animeka.etzhayyim.com

**Team-based anime creation appview** — KAMI Engine canvas + X-sheet timeline で、原作 → 脚本 → 絵コンテ → レイアウト → 原画 → 動画 → 色指定 → 仕上げ(色トレス) → 背景 → 撮影 → 編集 → 音響 の 12 工程を 1 project で並走させる。`mangaka` (manga) の anime 版 — atom は `page/panel` ではなく **`cut` (ショット)**。

## Architecture

| 項目 | 値 |
|---|---|
| Domain | `animeka.etzhayyim.com` |
| Runtime | **Single Worker** (TS Native) |
| nanoid | `an1m3k4x` |
| performerType | `service` (default sensitivity: `public`) |
| uiType | `appview` (KAMI Engine canvas + X-sheet timeline) |
| Engine | `40-engine/kami-engine/kami-app-animeka-timeline` (planned) |

## Multi-DID Architecture `[DESIGN]`

Project Actor Composition (1 project = 1 convoId + N member DIDs, `60-apps/CLAUDE.md` §Project Actor Composition)。

| DID | 用途 |
|---|---|
| `did:web:animeka.etzhayyim.com` | Controller (app 本体) |
| `did:web:animeka.etzhayyim.com:work:{nanoid}` | 作品 (シリーズ単位) |
| `did:web:animeka.etzhayyim.com:episode:{nanoid}` | 話 (= project 単位, convoId = roomId) |
| `did:web:animeka.etzhayyim.com:cut:{nanoid}` | カット (ショット単位) |
| `did:web:animeka.etzhayyim.com:character:{nanoid}` | キャラクターデザイン/色モデル |
| `did:web:animeka.etzhayyim.com:actor:director` | 監督 AI |
| `did:web:animeka.etzhayyim.com:actor:screenwriter` | 脚本 AI |
| `did:web:animeka.etzhayyim.com:actor:storyboarder` | 絵コンテ AI |
| `did:web:animeka.etzhayyim.com:actor:layout` | レイアウト AI |
| `did:web:animeka.etzhayyim.com:actor:keyAnimator` | 原画 AI (genga) |
| `did:web:animeka.etzhayyim.com:actor:inbetweener` | 動画 AI (douga, interp) |
| `did:web:animeka.etzhayyim.com:actor:colorDesigner` | 色彩設計 AI |
| `did:web:animeka.etzhayyim.com:actor:finisher` | 仕上げ/色トレス AI |
| `did:web:animeka.etzhayyim.com:actor:bgArtist` | 美術/背景 AI |
| `did:web:animeka.etzhayyim.com:actor:compositor` | 撮影 AI (FX + camera) |
| `did:web:animeka.etzhayyim.com:actor:soundDesigner` | 音響 AI |
| `did:web:animeka.etzhayyim.com:actor:editor` | 編集 AI |

全 12 actor DID は起動時に `ensureActorDids(sdk)` で一括登録 (`sdk.hostImports.comAtprotoIdentityCreate`)。AI 成果物の author DID として `actor:inbetweener` / `actor:finisher` / `actor:compositor` が record.author に設定される (`src/app.ts`)。

人間参加者は自己 DID (`did:web:alice.etzhayyim.com` 等) で member 参加。

## Design E 3-Tier Write

| Tier | 用途 | 関数 | Collection NSID |
|---|---|---|---|
| **1 Social** | 作品/話/PV 告知, 納品アナウンス | `AppBskyFeedPost(did, text, {embed})` | `app.bsky.feed.post` |
| **2 Domain** | work/episode/cut/layer/retake 等 | `ComAtprotoRepoCreateRecord(kind, payload)` | `com.etzhayyim.animeka.*` |
| **3 State** | viewer 設定・ペンプリセット・通知 | `Preferences()` | server-side |

PII (スタッフ本名/連絡先), retake の人物評価コメントは Tier 3。retake が人事評価に及ぶ場合は `signal:v1:` field encrypt。

## Domain Record Types (Tier 2, camelCase)

| Kind | NSID | 内容 |
|---|---|---|
| `work` | `com.etzhayyim.animeka.work` | シリーズ (title, genre, episodeCount, coverCid) |
| `episode` | `com.etzhayyim.animeka.episode` | 話 (workRef, episodeNum, titleJP, duration, fps) |
| `script` | `com.etzhayyim.animeka.script` | 脚本 (episodeRef, sceneCount, bodyCid) |
| `scene` | `com.etzhayyim.animeka.scene` | シーン (episodeRef, sceneNum, location, timeOfDay) |
| `cut` | `com.etzhayyim.animeka.cut` | カット (sceneRef, cutNum, durationFrames, fps, camera) |
| `storyboard` | `com.etzhayyim.animeka.storyboard` | 絵コンテ (cutRef, thumbCid, dialogue, action, cameraNote) |
| `layout` | `com.etzhayyim.animeka.layout` | レイアウト (cutRef, layoutCid, charPositions[], bgRef) |
| `keyframe` | `com.etzhayyim.animeka.keyframe` | 原画 (cutRef, frameNum, imageCid) |
| `inbetween` | `com.etzhayyim.animeka.inbetween` | 動画 (cutRef, frameNum, imageCid, prevKey, nextKey) |
| `colorModel` | `com.etzhayyim.animeka.colorModel` | キャラ色指定 (characterRef, palette[], materialMap) |
| `colorTrace` | `com.etzhayyim.animeka.colorTrace` | 仕上げ (frameRef, colorLayersCid) |
| `background` | `com.etzhayyim.animeka.background` | 背景 (layoutRef, bgCid, lightingMood) |
| `composite` | `com.etzhayyim.animeka.composite` | 撮影 (cutRef, outputCid, fxStack[], cameraMove) |
| `soundCue` | `com.etzhayyim.animeka.soundCue` | 音響 (cutRef, trackType, assetCid, inFrame, outFrame) |
| `retake` | `com.etzhayyim.animeka.retake` | リテイク (targetUri, timecode, comment, status) |
| `character` | `com.etzhayyim.animeka.character` | キャラ設定 (name, refSheetCid, colorModelRef) |
| `asset` | `com.etzhayyim.animeka.asset` | 汎用素材 (effect, ref sheet, LUT) |
| `project` | `com.etzhayyim.animeka.project` | project index (B2 index + graph) |
| `chatMessage` | `com.etzhayyim.animeka.chatMessage` | project 内 LLM 対話 |

## Reactive Pipeline (ComAtprotoSyncSubscribeRepos) `[DESIGN]`

Write-Only Derived Architecture (handler は write のみ、social / cross-actor invoke は `kotodama.jsonld` `derive` rule)。

| 入力 commit | derive rule | 出力 |
|---|---|---|
| `work` create + status=published | social post | AppBskyFeedPost |
| `episode` create + status=published | social post (thread root) | AppBskyFeedPost |
| `script` create | scene 分割 → `scene` auto-create | screenwriter actor invoke |
| `scene` create (status=ready) | カット割案 3 候補 | storyboarder actor invoke |
| `storyboard` approve | レイアウト案 | layout actor invoke |
| `layout` approve | 原画アサイン + ポーズ案 | keyAnimator actor invoke |
| `keyframe` pair commit | 中割自動生成 | inbetweener actor invoke |
| `colorModel` ready | 色トレス自動 | finisher actor invoke |
| `layout` approve | 背景発注 | bgArtist actor invoke |
| `colorTrace` + `background` ready | 撮影(合成+FX) | compositor actor invoke |
| `cut` status=approved | soundCue slot 生成 | soundDesigner actor invoke |
| `episode` publish | PV 告知 social post | AppBskyFeedPost |

全 actor invoke は `com.etzhayyim.signal` lxm-scoped auth gate 経由。

## KAMI Engine Integration `[SCAFFOLDED]`

**Crate**: `40-engine/kami-engine/kami-app-animeka-timeline/` (per-game WASM pattern 準拠、`kami-web` monolith 追加禁止)。`cargo check` passes on host (aarch64) + `wasm32-unknown-unknown`.

- `src/lib.rs` — `run_animeka_timeline(canvas_id)` wasm entry: `KamiApp::new_web` + `CameraMode::Ortho2D` + `InputMode::None` + 2 pipelines
- `src/xsheet.rs` — `XSheetPipeline` draws 6-column × N-row grid with 1-second (fps) accent rows + alternating row bands + column dividers + outer border (WGSL shader inline, Nintendo cream bg)
- `src/onion_skin.rs` — `OnionSkinPipeline` alpha-blended 3-quad stack (prev blue α=0.30 / next red α=0.30 / current opaque) in a square preview column at world x=-6.8

**Phase 2 follow-up**: stylus input via `kami-input` + per-frame `wgpu::Texture` upload from blob CIDs + text atlas (`kami-text`) for frame numbers + playback scrubber.

Build + deploy:
```bash
cd 40-engine/kami-engine
wasm-pack build kami-app-animeka-timeline --target web --release
APP=60-apps/etzhayyim-project-animeka/appview/etzhayyim-wasm-animeka-an1m3k4x
mkdir -p $APP/svelte/static/timeline-v1
cp kami-app-animeka-timeline/pkg/* $APP/svelte/static/timeline-v1/
```

| 機能 | KAMI Component | 用途 |
|---|---|---|
| Canvas rendering | wgpu renderer (`kami_render`) | frame 描画 (WebGPU + WebGL2 fallback) |
| Pen/Brush input | `kami-input` | 筆圧・傾き対応 stylus input |
| X-sheet grid + onion skin | `kami-ui-gpu` + `kami-render` layer compositor | タイムシート + 前後コマ透過表示 |
| Color fill / segmentation | `kami-pipelines::ColorTraceAdapter` (NEW) | 線画 flood-fill + AI segmentation |
| Background 3D layout | `kami-terrain` (streaming) + `SkyAdapter` | 美術 3D compositing |
| Camera move (TU/PAN/TB) | `kami-app` Camera keyframe track | カメラワーク制御 |
| Composite FX | `kami-postfx` | グロー / ブラー / レンズフレア / カメラブレ |
| Timeline preview player | `kami-app-animeka-timeline` (NEW crate) | cut の frame accurate 再生 |

## UI Surface — 5 primary views

### (A) Series Dashboard `/works/{workId}`
- 左: 作品カード (cover / synopsis / ep roster / team DID chips)
- 中央: **Episode Gantt** — 全話 × 12 工程の進捗ヒートマップ
- 右: 社会 feed (AppBskyFeedPost derive)

### (B) Pipeline Board `/episodes/{episodeId}` ★主画面
12 列 × cut 行のカンバン。タイルクリック → (C) Cut Detail drawer。担当 actor DID avatar、retake drag-reassign、time strip。

### (C) Cut Detail `/at/.../cut/{rkey}` ★作業画面
3 連結タブ:
1. **Storyboard + Layout** — KAMI canvas (絵コンテサムネ + レイアウトペーパー重ね描き) + AI 3 候補生成
2. **Animation** — X-sheet + onion-skin 付き frame drawing + `inbetweener.interpolate(keyA, keyB, n)` 中割自動
3. **Color & Comp** — キャラ color model + `finisher.autoTrace` 色トレス + BG slot + FX node editor + preview player (with soundCue)

下部: **Retake panel** (`retake` record 一覧、timecode ピン付き、"retake" ボタンで status=open)

### (D) Script & Storyboard View `/episodes/{episodeId}/script`
脚本表 (scene 単位) + 絵コンテ縦スクロール。脚本行 drag → scene/cut 自動生成。

### (E) Review Room `/episodes/{episodeId}/review`
試写。frame accurate スクラブ、retake タイムラインマーカー、参加者 DID + convo チャット。`publishEpisode` で Tier 1 social post + 納品 B2 push。

## AT URI Deep-Link

```
https://animeka.etzhayyim.com/at/an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.cut/cut-ep01-003
  ↔ at://an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.cut/cut-ep01-003
```

| Collection | Deep-link 例 |
|---|---|
| episode | `animeka.etzhayyim.com/at/an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.episode/ep-s01e01` |
| cut | `animeka.etzhayyim.com/at/an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.cut/cut-ep01-003` |
| retake | `animeka.etzhayyim.com/at/an1m3k4x.etzhayyim.com/com.etzhayyim.animeka.retake/rt-ep01-003-a#t=120f` |

retake comment は `#t={frame}f` fragment で frame pin。

## Document Persistence (Graph Primary, P10v2 GraphAr)

| Layer | Storage | 用途 |
|---|---|---|
| **Graph (primary)** | `vertex_animeka` (typed columns) | 全 18 domain record kinds (migration `20260420140000_vertex_animeka.ts`) |
| **Flat read view** | `view_animeka_record_flat` | props JSON overflow を typed columns にマージした読み取り view |
| **Graph edge** | `edge_contains` / `edge_membership` (shared) + app-specific edges TBD | relationship |
| **PDS blob** | `blobs/anonymous/{sha256}` | frame images, PV mp4 (content-addressed) |
| **MV** | `mv_vertex_animeka_count` / `mv_animeka_cut_progress` / `mv_animeka_open_retake_by_cut` / `mv_animeka_children_by_parent` | pipeline rollup (< 100ms freshness) |

## File Structure `[PLANNED]`

```
60-apps/etzhayyim-project-animeka/
├── CLAUDE.md
├── appview/
│   └── etzhayyim-wasm-animeka-an1m3k4x/
│       ├── kotodama.jsonld          # triggers + derive rules + profile
│       ├── wrangler.jsonc
│       ├── package.json
│       ├── src/app.ts               # TS Native — Design E reactive pipeline
│       └── svelte/                  # CSR UI (Pipeline Board + Cut Detail + Review Room)
└── scripts/
```

Lexicon JSON: `00-contracts/lexicons/com/etzhayyim/apps/animeka/*.json`

## Cinematic Pipeline (kami-cine)

animeka uses the **撮影 (compositor) ↔ kami-cine pipeline** bridge. Genga / douga / iro-shitei (stages 5-8 of the 12-step anime workflow) hand off to the 8-stage neural pipeline (`etzhayyim:kami-cine@1.0.0`, `40-engine/kami-engine/wit/cine/package.wit`) — shared with mangaka and dogaka — to deliver 3DCG cuts, full-CG episodes, and final composite-quality EXR/mp4.

| Anime 工程 | kami-cine bridge | Stages |
|---|---|---|
| Layout (レイアウト) | usdScene compose from storyboard | 1 → 2 |
| Background (美術) | usdScene + neuralGeom for matte paintings | 1 → 3 |
| Key / Inbetween (原画/動画) | temporalField over 2D-rigged characters or 3D | 1 → 4 |
| Compositing (撮影) | neuralRender + diffusionPass + exrSeq | 1 → 7 |
| Final delivery (納品) | encode (ProRes for master, h265 for streaming) | 1 → 8 |

The shared `com.etzhayyim.apps.cine.*` records carry `subjectKind = "animeka.cut"` or `"animeka.episode"` + `subjectRef` strongRef. Each cut take = one `pipelineRunId`. The `actor:compositor` DID owns stages 5-8 records; the `actor:keyAnimator` / `actor:inbetweener` DIDs own stages 1-4. Subscribe to `com.etzhayyim.apps.cine.encode` to auto-emit episode-delivery announcements.

## Differences from mangaka (設計上の "anime らしさ")

1. **Atom = cut (時間軸)**、page (空間軸) ではない → Kanban 軸は scene×cut、時間軸は X-sheet
2. **工程が直列でない** → Board の列並列進行 (background/color/keyAnim 同時走行)
3. **リテイク文化** 一級市民 → `retake` record + review room が独立 view
4. **音** が必須 layer → soundCue は timeline 独立トラック
5. **12/24 fps 選択** を cut 単位で持つ (リミテッド / フル)
6. **In-between AI** と **color trace AI** が mangaka にない二大機能
