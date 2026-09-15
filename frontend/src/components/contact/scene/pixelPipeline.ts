/**
 * 像素管线共用件：整数倍率计算 + 收尾边缘融合 shader。
 *
 * `computePixelScale`：容器高 ÷ 目标低分高，四舍五入钳制 [2,6]——
 * 1 美术像素恒等于整数个屏幕像素（pixel-art 红线：任何小数倍拉伸都会打出
 * 2,3,2,3 的脏像素）。整数对齐本身由 replicaPipeline 的 CompositeShader
 * floor 取格保证，本模块不再持有 composer 构建器（HD-2D 双层管线重写后无调用方）。
 *
 * EdgeBlendShader 位于 OutputPass 之前（线性空间）；uPaper 经 THREE.Color
 * 自动转线性，编码后边缘像素 = CSS token 精确值。
 */
import * as THREE from 'three'

export const PIXEL_SCALE_MIN = 2
export const PIXEL_SCALE_MAX = 6
/** 低分缓冲目标高度（美术像素） */
export const PIXEL_TARGET_HEIGHT = 230
/** 边缘融合宽度（占短边比例） */
export const EDGE_BLEND_RATIO = 0.06

/** 整数倍率：容器高 ÷ 目标低分高，四舍五入后钳制到 [2, 6] */
export const computePixelScale = (rawHeight: number): number => {
  if (!Number.isFinite(rawHeight) || rawHeight <= 0) return PIXEL_SCALE_MIN
  return Math.min(
    PIXEL_SCALE_MAX,
    Math.max(PIXEL_SCALE_MIN, Math.round(rawHeight / PIXEL_TARGET_HEIGHT)),
  )
}

/**
 * 收尾边缘融合：最外 ~6% 边缘向 uPaper 混合，1px 有序抖动边界防色带。
 */
export const EdgeBlendShader = {
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    uPaper: { value: new THREE.Color('#fffefa') },
    uEdge: { value: EDGE_BLEND_RATIO },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform vec3 uPaper;
    uniform float uEdge;
    varying vec2 vUv;

    // GLSL1 可用的有序抖动（无位运算）：2x2 → 4x4 递归
    float bayer2(vec2 a) {
      a = floor(a);
      return fract(a.x / 2.0 + a.y * a.y * 0.75);
    }
    float bayer4(vec2 a) {
      return bayer2(0.5 * a) * 0.25 + bayer2(a);
    }

    void main() {
      vec4 color = texture2D(tDiffuse, vUv);
      vec2 edgeDist = min(vUv, 1.0 - vUv);
      float d = min(edgeDist.x, edgeDist.y);
      float dither = (bayer4(gl_FragCoord.xy) - 0.5) * (1.0 / 32.0);
      float t = smoothstep(0.0, uEdge, d + dither * uEdge);
      gl_FragColor = vec4(mix(uPaper, color.rgb, t), color.a);
    }
  `,
}
