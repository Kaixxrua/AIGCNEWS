import type { InjectionKey, Ref } from 'vue'

/** 报眉中间那一栏的挂载点（LayoutView）：各页把本版工具传送进来。 */
export const FOLIO_TOOLS_TARGET_ID = 'masthead-page-tools'

/** LayoutView 提供：此刻有没有报眉（桌面内页才有）；没有时本版工具留在页面里。 */
export const FOLIO_TOOLS_AVAILABLE: InjectionKey<Readonly<Ref<boolean>>> = Symbol('folio-tools-available')

/**
 * 本版工具在报眉里的几档样子，挂在盒子的 data-folio 上，各页按它写报眉里的尺寸：
 * full 是完整的一组；compact 由页面自己决定收掉什么（比如按钮只留图标），full 放不下时再试。
 * trim 是两者之间的一档（先收一部分），tight 是 compact 之后再收的一档（比如把长名字换成短名字），
 * 都只有把它写进 FolioTools levels 的页面才试。
 */
export type FolioToolsLevel = 'full' | 'trim' | 'compact' | 'tight'
export const FOLIO_TOOLS_LEVELS: readonly FolioToolsLevel[] = ['full', 'compact']
