/**
 * 世界锚点 → 低分美术像素格的投影换算（纯函数 + three 数学类，jsdom 可测）。
 *
 * HD-2D 混合分辨率的精灵层关键：透视相机下世界空间 billboard 的像素尺寸会随
 * 深度变成小数（打出脏像素），所以精灵一律放屏幕空间——每帧把世界锚点
 * （脚底）project 到 NDC → 缓冲像素 → 整数美术格，再以固定美术尺寸摆放。
 * 缓冲像素尺寸恒等于 CSS 尺寸（pixelRatio 钉 1），artX/artY 取自低分精灵
 * 缓冲的整数格（y 自底向上，与精灵层正交相机一致）。
 */
import type { Camera, Vector3 } from 'three'

/** 低分美术格布局：整数倍率 + 居中余量（余量由边缘融合吸收） */
export interface ArtGrid {
  scale: number
  lowW: number
  lowH: number
  cssW: number
  cssH: number
  offsetX: number
  offsetY: number
}

export const makeArtGrid = (cssW: number, cssH: number, scale: number): ArtGrid => {
  const safeScale = Math.max(1, Math.round(scale))
  const lowW = Math.max(2, Math.floor(cssW / safeScale))
  const lowH = Math.max(2, Math.floor(cssH / safeScale))
  return {
    scale: safeScale,
    lowW,
    lowH,
    cssW,
    cssH,
    offsetX: Math.floor((cssW - lowW * safeScale) / 2),
    offsetY: Math.floor((cssH - lowH * safeScale) / 2),
  }
}

export interface ArtPoint {
  /** 美术格坐标（整数，y 自底向上） */
  x: number
  y: number
  /** 是否在低分缓冲范围内（越界精灵可整体跳过） */
  inside: boolean
}

/**
 * 世界坐标锚点 → 美术格（四舍五入取整，像素对齐红线）。
 * world 需为 THREE.Vector3（项目内统一 Vector3.project(camera) 路径）。
 */
export const worldToArt = (
  camera: Camera,
  grid: ArtGrid,
  world: Vector3,
): ArtPoint => {
  const ndc = world.clone().project(camera)
  const bufX = (ndc.x * 0.5 + 0.5) * grid.cssW
  const bufYFromBottom = (ndc.y * 0.5 + 0.5) * grid.cssH
  const x = Math.round((bufX - grid.offsetX) / grid.scale)
  const y = Math.round((bufYFromBottom - grid.offsetY) / grid.scale)
  return { x, y, inside: x >= -64 && x < grid.lowW + 64 && y >= -64 && y < grid.lowH + 64 }
}

/** 美术格 → 缓冲/CSS 像素矩形（左上原点），供命中测试与调试叠层 */
export interface CssRect {
  left: number
  top: number
  width: number
  height: number
}

export const artRectToCss = (
  grid: ArtGrid,
  artX: number,
  artYBottom: number,
  artW: number,
  artH: number,
): CssRect => ({
  left: grid.offsetX + artX * grid.scale,
  top: grid.cssH - grid.offsetY - (artYBottom + artH) * grid.scale,
  width: artW * grid.scale,
  height: artH * grid.scale,
})

/**
 * 透视相机在指定水平距离处的可视半宽（世界单位）。
 * 用于把现行「xRatio 相对布局 / 虚拟像素行走域」映射到世界宽度：
 * 布局比例 × 该深度的可视宽，与视口宽高比解耦。
 */
export const visibleHalfWidthAt = (camera: Camera, horizontalDistance: number): number => {
  const perspective = camera as { fov?: number; aspect?: number; isPerspectiveCamera?: boolean }
  if (!perspective.isPerspectiveCamera || !perspective.fov || !perspective.aspect) {
    // 正交相机：半宽即 right
    return Math.abs((camera as unknown as { right: number }).right ?? 1)
  }
  const vHalf = Math.tan(((perspective.fov / 2) * Math.PI) / 180)
  return vHalf * perspective.aspect * Math.max(0.0001, horizontalDistance)
}

/**
 * 画家算法排序键：屏幕上越靠下（越近）越晚画。
 * 返回 renderOrder 基底（大 artY = 远 = 先画）。
 */
export const painterOrder = (artY: number, layer: number): number => layer * 10000 - artY
