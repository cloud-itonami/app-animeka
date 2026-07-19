/**
 * Animeka 12-actor roster.
 *
 * Mirrors ACTOR_DEFS in ../../src/app.ts — both keep capability + responsibility
 * + stage-ownership in sync with the 12-stage anime production pipeline.
 * UI reads `stageKeys` to colour stage columns and surface the responsible
 * actor chip per Pipeline Board column.
 */

export type ActorSlug =
  | 'director'
  | 'screenwriter'
  | 'storyboarder'
  | 'layout'
  | 'keyAnimator'
  | 'inbetweener'
  | 'colorDesigner'
  | 'finisher'
  | 'bgArtist'
  | 'compositor'
  | 'soundDesigner'
  | 'editor';

export type StageKey =
  | 'script'
  | 'storyboard'
  | 'layout'
  | 'keyAnim'
  | 'inbetween'
  | 'colorDesign'
  | 'finish'
  | 'background'
  | 'composite'
  | 'edit'
  | 'sound'
  | 'delivery';

export interface Actor {
  slug: ActorSlug;
  displayName: string;
  emoji: string;
  color: string;
  role: string;
  capability: string[];
  responsibility: string;
  stageKeys: StageKey[];
}

export const STAGES: { key: StageKey; label: string }[] = [
  { key: 'script',      label: '脚本' },
  { key: 'storyboard',  label: '絵コンテ' },
  { key: 'layout',      label: 'レイアウト' },
  { key: 'keyAnim',     label: '原画' },
  { key: 'inbetween',   label: '動画' },
  { key: 'colorDesign', label: '色指定' },
  { key: 'finish',      label: '仕上げ' },
  { key: 'background',  label: '背景' },
  { key: 'composite',   label: '撮影' },
  { key: 'edit',        label: '編集' },
  { key: 'sound',       label: '音響' },
  { key: 'delivery',    label: '納品' },
];

export const ACTORS: Actor[] = [
  {
    slug: 'director',
    displayName: 'Director',
    emoji: '🎬',
    color: '#e0b860',
    role: '監督',
    capability: ['overall vision', 'pacing', 'retake approval'],
    responsibility: '全工程のレビューと最終承認。retake の方向指示',
    stageKeys: [],
  },
  {
    slug: 'screenwriter',
    displayName: 'Screenwriter',
    emoji: '📝',
    color: '#c48be6',
    role: '脚本',
    capability: ['hakoden breakdown', 'dialogue', 'scene structure'],
    responsibility: 'script → scene 自動分割と台詞生成',
    stageKeys: ['script'],
  },
  {
    slug: 'storyboarder',
    displayName: 'Storyboarder',
    emoji: '✏️',
    color: '#7bb7ff',
    role: '絵コンテ',
    capability: ['3 composition candidates', 'camera note', 'dialogue timing'],
    responsibility: 'cut ごとに 3 候補のコンテを生成',
    stageKeys: ['storyboard'],
  },
  {
    slug: 'layout',
    displayName: 'Layout Artist',
    emoji: '📐',
    color: '#4fd1c5',
    role: 'レイアウト',
    capability: ['char positioning', 'camera frame', 'bg plate'],
    responsibility: '承認済みコンテ → 精密レイアウト + 背景発注',
    stageKeys: ['layout'],
  },
  {
    slug: 'keyAnimator',
    displayName: 'Key Animator',
    emoji: '🎨',
    color: '#ff8a3a',
    role: '原画',
    capability: ['keyframe drawing', 'pose arcs', 'motion pair'],
    responsibility: 'レイアウト → 原画ポーズ案とキーフレーム描画',
    stageKeys: ['keyAnim'],
  },
  {
    slug: 'inbetweener',
    displayName: 'Inbetweener',
    emoji: '🔄',
    color: '#ffc04d',
    role: '動画',
    capability: ['tween frames', 'easing curves', 'interp AI'],
    responsibility: 'keyframe pair → 中割自動生成 (interpolate)',
    stageKeys: ['inbetween'],
  },
  {
    slug: 'colorDesigner',
    displayName: 'Color Designer',
    emoji: '🎨',
    color: '#f06292',
    role: '色指定',
    capability: ['palette', 'lighting-aware color model', 'material map'],
    responsibility: 'キャラ × 光源条件ごとの color model 定義',
    stageKeys: ['colorDesign'],
  },
  {
    slug: 'finisher',
    displayName: 'Finisher',
    emoji: '🖌️',
    color: '#ba68c8',
    role: '仕上げ',
    capability: ['auto color trace', 'flat + shadow layers', 'segmentation'],
    responsibility: 'color model 準拠で線画を自動色トレース',
    stageKeys: ['finish'],
  },
  {
    slug: 'bgArtist',
    displayName: 'BG Artist',
    emoji: '🏞️',
    color: '#81c784',
    role: '美術/背景',
    capability: ['BG painting', 'lighting mood', 'cross-cut reuse'],
    responsibility: 'layout 承認を受けて背景画を制作',
    stageKeys: ['background'],
  },
  {
    slug: 'compositor',
    displayName: 'Compositor',
    emoji: '🎞️',
    color: '#64b5f6',
    role: '撮影',
    capability: ['FX stack', 'camera move', 'grade / blur / flare'],
    responsibility: '色トレス + 背景 → 合成・カメラワーク・FX',
    stageKeys: ['composite'],
  },
  {
    slug: 'soundDesigner',
    displayName: 'Sound Designer',
    emoji: '🔊',
    color: '#ff7043',
    role: '音響',
    capability: ['voice cue', 'SE', 'BGM placement'],
    responsibility: 'cut 承認毎に soundCue slot を生成',
    stageKeys: ['sound'],
  },
  {
    slug: 'editor',
    displayName: 'Editor',
    emoji: '✂️',
    color: '#90a4ae',
    role: '編集',
    capability: ['cut timing', 'pacing', 'master export'],
    responsibility: 'cut 並べ替えと納品マスター書き出し',
    stageKeys: ['edit', 'delivery'],
  },
];

export const ACTOR_BY_SLUG: Record<ActorSlug, Actor> =
  ACTORS.reduce((m, a) => { m[a.slug] = a; return m; }, {} as Record<ActorSlug, Actor>);

/** Stage → owning actor (first actor whose `stageKeys` include the stage). */
export const STAGE_OWNER: Partial<Record<StageKey, Actor>> = (() => {
  const m: Partial<Record<StageKey, Actor>> = {};
  for (const a of ACTORS) for (const k of a.stageKeys) if (!m[k]) m[k] = a;
  return m;
})();
