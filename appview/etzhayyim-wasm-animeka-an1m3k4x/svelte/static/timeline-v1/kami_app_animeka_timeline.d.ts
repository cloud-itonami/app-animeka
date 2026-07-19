/* tslint:disable */
/* eslint-disable */

/**
 * Entry point exported to JS.
 *
 * ```js
 * import init, { run_animeka_timeline } from './kami_app_animeka_timeline.js';
 * await init();
 * await run_animeka_timeline('gc');
 * ```
 */
export function run_animeka_timeline(canvas_id: string): Promise<void>;

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly run_animeka_timeline: (a: number, b: number) => any;
    readonly wasm_bindgen__closure__destroy__h2999ab7c8b76f609: (a: number, b: number) => void;
    readonly wasm_bindgen__closure__destroy__h18833a277fe7211a: (a: number, b: number) => void;
    readonly wasm_bindgen__closure__destroy__h0391569eba8eea3b: (a: number, b: number) => void;
    readonly wasm_bindgen__convert__closures_____invoke__h7fab2cc70c6a6a11: (a: number, b: number, c: any) => [number, number];
    readonly wasm_bindgen__convert__closures_____invoke__h5db5e8dc2faf8fdd: (a: number, b: number, c: any, d: any) => void;
    readonly wasm_bindgen__convert__closures_____invoke__h5a10cba670bf816d: (a: number, b: number, c: any) => void;
    readonly wasm_bindgen__convert__closures_____invoke__h5a10cba670bf816d_3: (a: number, b: number, c: any) => void;
    readonly wasm_bindgen__convert__closures_____invoke__h5a10cba670bf816d_4: (a: number, b: number, c: any) => void;
    readonly wasm_bindgen__convert__closures_____invoke__h5a10cba670bf816d_5: (a: number, b: number, c: any) => void;
    readonly wasm_bindgen__convert__closures_____invoke__h0e07fbe4309edcc8: (a: number, b: number) => void;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
