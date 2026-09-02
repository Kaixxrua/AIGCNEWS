<script setup lang="ts">
/**
 * 联系页 Hero 视觉层：Three.js + WebGL2 全屏 shader 像素风 HD-2D 港湾，实时渲染。
 * 纯装饰（aria-hidden），生命周期自包含：
 * - 仅探测 webgl2 上下文；不可用 / 上下文丢失 / three 加载失败 → 露出底层静态 CSS 渐变兜底
 * - 昼/夜双场景绑定站点主题（亮=白昼，暗=夜晚）；主题切换时 uDay 指数趋近，
 *   天体沿弧线交替、经黄昏带、灯火星星渐隐渐现（八方旅人式时间切换）；
 *   reduced-motion / 离屏 / 首帧直接跳变，不播动画
 * - 主题色经 getComputedStyle 读 token 注入 uniform；uLight/uDark 由 --ink/--paper-raised
 *   按亮度比较得出，规避 token 随主题反转的语义
 * - DPR 上限、离屏（IntersectionObserver）暂停、卸载全量 dispose
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import type { ShaderMaterial, WebGLRenderer } from 'three'

const rootRef = ref<HTMLDivElement | null>(null)
const canvasRef = ref<HTMLCanvasElement | null>(null)
/** 首帧已上屏后才淡入 canvas，盖住静态兜底 */
const live = ref(false)

let cleanup: (() => void) | null = null
let alive = true

const VERTEX_SHADER = /* glsl */ `
void main() {
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`

/* 像素风 HD-2D 港湾：场景几何像素化（ARTP 艺术像素网格），光照/辉光用平滑坐标 ——
 * 即八方旅人"像素场景 + 现代光影"的签名质感。昼夜同一几何、两套光照：
 * 夜 = 青月 + 灯笼光池 + 村落窗火 + 萤火 + 星空；昼 = 酸绿太阳 + 亮青天空 + 波光 + 光尘。
 * 主题切换经 uDay 渐变播放时间过渡：天体沿头顶弧线交替，中点进入黄昏（天压暗、
 * 地平线泛酸绿霞光、灯火半亮）。所有颜色由 token uniform 经 mix 派生，不写死色值。
 * GLSL1 语法跑在 WebGL2 上下文上（three r163+ 只创建 WebGL2 context）；
 * 结尾 colorspace_fragment 把线性结果编码回 sRGB（linearToOutputTexel 由 three 的
 * program prefix 自动定义，不能再 include pars chunk，否则黑屏）。 */
const FRAGMENT_SHADER = /* glsl */ `
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uPointer;
uniform float uDay;
uniform vec3 uBg;
uniform vec3 uAcid;
uniform vec3 uTech;
uniform vec3 uLight;
uniform vec3 uDark;

float hash21(vec2 p) {
  p = fract(p * vec2(234.34, 435.345));
  p += dot(p, p + 34.23);
  return fract(p.x * p.y);
}

float noise2(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash21(i), hash21(i + vec2(1.0, 0.0)), u.x),
    mix(hash21(i + vec2(0.0, 1.0)), hash21(i + vec2(1.0, 1.0)), u.x),
    u.y
  );
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 3; i++) {
    v += a * noise2(p);
    p = p * 2.03 + vec2(11.7, -7.3);
    a *= 0.5;
  }
  return v;
}

float bayer2(vec2 a) {
  a = floor(a);
  return fract(a.x / 2.0 + a.y * a.y * 0.75);
}
float bayer4(vec2 a) {
  return bayer2(0.5 * a) * 0.25 + bayer2(a);
}

const float ARTP = 160.0;
const float HOR = 0.02;

/* 天体位置：夜=月在右，昼=日在左，切换时沿头顶弧线交替（八方旅人式时间过渡） */
vec2 bodyPos(float day, float halfAsp) {
  float phi = mix(0.20 * 3.14159, 0.80 * 3.14159, day);
  return vec2(cos(phi) * 0.62 * halfAsp, HOR + sin(phi) * 0.36);
}

vec3 sceneAbove(vec2 p, vec2 par, float t, float halfAsp, float day, float dusk, float lightAmt) {
  // 天空：Bayer 有序抖动渐变（像素画色带肌理），黄昏带压暗顶部、地平线泛霞
  float skyT = clamp((p.y - HOR) / (0.52 - HOR), 0.0, 1.0);
  float dith = (bayer4(p * ARTP) - 0.5) * 0.10;
  vec3 skyTop = mix(mix(uBg, uTech, 0.08), mix(uLight, uTech, 0.55), day);
  vec3 skyHor = mix(mix(uBg, uTech, 0.20), mix(uLight, uTech, 0.22), day);
  skyHor = mix(skyHor, mix(uAcid, uLight, 0.25), dusk * 0.45);
  skyTop = mix(skyTop, mix(uBg, uTech, 0.22), dusk * 0.40);
  vec3 col = mix(skyHor, skyTop, clamp(skyT * 1.10 + dith, 0.0, 1.0));

  // 星星（夜场，昼场渐隐；大星更亮并带闪烁）
  vec2 sp = p + par * 0.004;
  vec2 cell = floor(sp * ARTP * 0.5);
  float sh = hash21(cell);
  if (sh > 0.988 && sp.y > 0.12) {
    float tw = 0.45 + 0.55 * sin(t * (1.0 + 2.0 * fract(sh * 77.0)) + sh * 61.0);
    float big = step(0.996, sh);
    col += mix(uTech, uLight, 0.5) * tw * (0.10 + 0.22 * big) * (1.0 - day);
  }

  // 云带：慢速漂移，昼场更亮更实
  vec2 cp = p + par * 0.006;
  float cl = fbm(vec2(cp.x * 1.4 + t * 0.008, cp.y * 5.0 + 2.0));
  float cmask = smoothstep(0.14, 0.24, p.y) * smoothstep(0.48, 0.34, p.y);
  vec3 cloudCol = mix(mix(uBg, uTech, 0.50), uLight, day);
  col += cloudCol * smoothstep(0.55, 0.8, cl) * cmask * mix(0.07, 0.18, day);

  // 日/月盘：硬边圆 + 盘面噪点；昼盘更平更亮，夜盘带环形山
  vec2 mp = (p + par * 0.004) - bodyPos(day, halfAsp);
  float md = length(mp);
  float bodyR = mix(0.036, 0.046, day);
  if (md < bodyR) {
    float tex = 0.82 + 0.18 * noise2(mp * 90.0 + 4.0);
    vec3 bodyCol = mix(mix(uTech, uLight, 0.60), mix(uAcid, uLight, 0.30), day);
    col = bodyCol * mix(tex, 1.0, day * 0.6);
  }

  // 远山（画家算法：远层先画，近层覆盖）；昼场挂雾气
  vec2 rp = p + par * 0.012;
  float ridge = 0.05 + 0.10 * noise2(vec2(rp.x * 1.8 + 3.7, 4.2)) + 0.045 * noise2(vec2(rp.x * 4.9 + 1.3, 9.1));
  if (p.y < ridge) {
    float haze = clamp((ridge - p.y) * 2.0, 0.0, 1.0);
    vec3 farHi = mix(mix(uBg, uTech, 0.13), mix(uLight, uTech, 0.55), day);
    vec3 farLo = mix(mix(uBg, uTech, 0.05), mix(uLight, uTech, 0.36), day);
    col = mix(farHi, farLo, haze);
  }
  float ridge2 = (0.02 + 0.05 * noise2(vec2(rp.x * 3.1 + 11.7, 6.6))) * smoothstep(0.2 * halfAsp, -0.5 * halfAsp, rp.x);
  if (p.y < ridge2) {
    col = mix(mix(uBg, uTech, 0.045), mix(uLight, uTech, 0.28), day);
  }

  // 岸线
  if (p.y < HOR + 0.010) {
    col = mix(mix(uBg, uLight, 0.05), mix(uLight, uTech, 0.22), day);
  }

  // 右岸村落：台阶屋顶 + 窗火（夜/黄昏点亮，昼熄灭成深色玻璃）
  vec2 vp = p + par * 0.020;
  for (int i = 0; i < 5; i++) {
    float fi = float(i);
    float h1 = hash21(vec2(fi * 7.1, 2.3));
    float h2 = hash21(vec2(fi * 3.7, 8.9));
    float cx = halfAsp * (0.10 + 0.17 * fi) + (h1 - 0.5) * 0.02;
    float bw = halfAsp * (0.10 + 0.05 * h2);
    float bh = 0.045 + 0.055 * h1;
    if (fi == 2.0) bh += 0.05;
    float y0 = HOR + 0.008;
    float lx = vp.x - cx;
    if (abs(lx) < bw * 0.5 && p.y > y0 && p.y < y0 + bh) {
      col = mix(mix(uBg, uLight, 0.06 + 0.02 * h2), mix(uLight, uTech, 0.24 + 0.08 * h2), day);
      vec2 wp = vec2(lx + bw * 0.5, p.y - y0);
      vec2 wc = floor(wp * ARTP / vec2(3.0, 4.0));
      vec2 wf = fract(wp * ARTP / vec2(3.0, 4.0));
      float lit = step(0.42, hash21(wc + fi * 13.7));
      if (wf.x > 0.25 && wf.x < 0.75 && wf.y > 0.30 && wf.y < 0.75 && lit > 0.5 && bh * ARTP > 8.0) {
        float fl = 0.75 + 0.25 * sin(t * (1.5 + h1 * 2.0) + h2 * 40.0);
        col = mix(mix(uDark, uTech, 0.30), mix(uAcid, uLight, 0.18) * fl, lightAmt);
      }
    }
    float rh = 0.028 + 0.012 * h2;
    float rt = (p.y - y0 - bh) / rh;
    if (rt > 0.0 && rt < 1.0 && abs(lx) < bw * 0.68 * (1.0 - rt)) {
      col = mix(mix(uBg, uTech, 0.12 + 0.03 * h1), mix(uDark, uTech, 0.35), day);
    }
  }

  // 左岸挑灯（灯还亮着 = 联系页隐喻）；昼场灯灭，只留灯架剪影
  vec2 lp = p + par * 0.030;
  float lantX = -0.58 * halfAsp;
  if (p.y > 0.115 && p.y < 0.128 && lp.x > lantX - 0.004 && lp.x < lantX + 0.052) {
    col = mix(uDark, uTech, 0.06 + 0.10 * day);
  }
  if (abs(lp.x - (lantX + 0.040)) < 0.003 && p.y > 0.094 && p.y < 0.115) {
    col = mix(uDark, uTech, 0.05 + 0.10 * day);
  }
  vec2 lb = abs(lp - vec2(lantX + 0.040, 0.070));
  if (lb.x < 0.016 && lb.y < 0.024) {
    if (lb.x < 0.011 && lb.y < 0.018) {
      float lf = 0.85 + 0.15 * noise2(vec2(t * 2.3, 5.0));
      col = mix(mix(uDark, uLight, 0.12), mix(uAcid, uLight, 0.30) * lf, lightAmt);
    } else {
      col = mix(uDark, uTech, 0.08);
    }
  }
  return col;
}

void main() {
  vec2 uv = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
  float t = uTime;
  float halfAsp = 0.5 * uRes.x / uRes.y;
  float day = clamp(uDay, 0.0, 1.0);
  float dusk = 1.0 - abs(day * 2.0 - 1.0);
  float lightAmt = clamp(1.25 - day * 1.5, 0.0, 1.0);
  vec2 px = (floor(uv * ARTP) + 0.5) / ARTP;
  float lantX = -0.58 * halfAsp;

  vec3 col;
  if (px.y >= HOR) {
    col = sceneAbove(px, uPointer, t, halfAsp, day, dusk, lightAmt);
  } else {
    // 水面：镜像倒影 + 波纹扰动 + 细 shimmer
    vec2 rp = vec2(
      px.x + 0.004 * sin(px.y * 90.0 + t * 1.6) + 0.002 * sin(px.y * 233.0 - t * 2.3),
      2.0 * HOR - px.y
    );
    rp = (floor(rp * ARTP) + 0.5) / ARTP;
    vec3 rcol = sceneAbove(rp, vec2(0.0), t, halfAsp, day, dusk, lightAmt);
    float depth = clamp((HOR - px.y) / (HOR + 0.5), 0.0, 1.0);
    vec3 waterTint = mix(mix(uBg, uTech, 0.10), mix(uLight, uTech, 0.45), day);
    col = mix(rcol, waterTint, 0.50 + 0.28 * depth);
    col *= 0.93 + 0.07 * sin(px.y * ARTP * 3.14159 + t * 1.1);
    // 日/月波光路（跟随天体 x 位置）
    vec2 bp = bodyPos(day, halfAsp);
    float glint = exp(-abs(px.x - bp.x) * mix(22.0, 14.0, day)) * exp(-depth * 3.2);
    vec3 glintCol = mix(uTech, mix(uLight, uAcid, 0.45), day);
    col += glintCol * glint * (0.16 + 0.06 * sin(t * 2.0 + px.y * 60.0)) * mix(1.0, 1.5, day);
    // 灯笼与村落的倒影光带（随灯火明灭）
    float lstreak = exp(-abs(px.x - (lantX + 0.040)) * 16.0) * exp(-depth * 2.6);
    col += uAcid * lstreak * (0.20 + 0.05 * sin(t * 2.6 + px.y * 47.0)) * lightAmt;
    float vstreak = exp(-abs(px.x - 0.45 * halfAsp) * 5.0) * exp(-depth * 4.0);
    col += uAcid * vstreak * 0.06 * lightAmt;
  }

  // 近景灯柱（立在水面前，不入倒影）
  vec2 np = px + uPointer * 0.030;
  if (abs(np.x - lantX) < 0.007 && px.y < 0.118) {
    col = mix(uDark, uTech, 0.06 + 0.10 * day);
  }

  // 近景苇草剪影
  float reed = -0.435 + 0.030 * noise2(vec2(np.x * 7.0 + 2.0, 3.3));
  if (px.y < reed) {
    col = mix(uDark, uTech, 0.04 + 0.12 * day);
    float bx = floor(np.x * ARTP);
    float bh2 = hash21(vec2(bx, 5.5));
    if (bh2 > 0.80 && px.y < reed + 0.02 + 0.05 * fract(bh2 * 57.0) && fract(np.x * ARTP) < 0.45) {
      col = mix(uDark, uTech, 0.02 + 0.08 * day);
    }
  }

  // ── HD-2D 现代光影层（平滑坐标，不像素化）──
  vec2 bp2 = bodyPos(day, halfAsp);
  float bd = length(uv - bp2);
  vec3 glowCol = mix(uTech, mix(uAcid, uLight, 0.35), day);
  col += glowCol * exp(-bd * 7.0) * mix(0.18, 0.24, day);
  float lgd = length(uv - vec2(lantX + 0.040, 0.070));
  float lflick = 0.85 + 0.15 * noise2(vec2(t * 2.3, 5.0));
  col += uAcid * (exp(-lgd * 14.0) * 0.55 + exp(-lgd * 4.5) * 0.16) * lflick * lightAmt;
  float vgd = length((uv - vec2(0.45 * halfAsp, HOR + 0.03)) * vec2(1.0, 2.2));
  col += uAcid * exp(-vgd * 5.0) * 0.10 * lightAmt;

  // 漂浮粒子：夜 = 萤火，昼 = 飘散光尘（同一批粒子跨昼夜变色变弱）
  for (int i = 0; i < 16; i++) {
    float fi = float(i);
    float a1 = hash21(vec2(fi * 3.17, 1.71));
    float a2 = hash21(vec2(fi * 7.77, 4.13));
    float a3 = hash21(vec2(fi * 5.51, 9.31));
    float cyc = fract(t * (0.018 + 0.02 * a1) + a2);
    vec2 fpos;
    fpos.x = (a1 - 0.5) * 1.7 * halfAsp + 0.10 * sin(t * (0.25 + 0.35 * a2) + a3 * 6.2831);
    fpos.y = -0.46 + cyc * 0.95;
    fpos = (floor(fpos * ARTP) + 0.5) / ARTP;
    float fade = sin(3.14159 * cyc);
    float tw2 = 0.55 + 0.45 * sin(t * (2.0 + 3.0 * a3) + a1 * 40.0);
    float fd = length(uv - fpos);
    vec3 pcol = mix(uAcid, mix(uLight, uTech, 0.30), day);
    col += pcol * (exp(-fd * fd / 0.000008) * 0.9 + exp(-fd * 30.0) * 0.10) * fade * tw2 * mix(0.85, 0.45, day);
  }

  // 暗角（昼场收敛）+ 细颗粒
  float vig = smoothstep(1.35, 0.30, length(uv * vec2(0.82, 1.15)));
  col *= mix(mix(0.62, 1.0, vig), mix(0.85, 1.0, vig), day);
  col += (hash21(gl_FragCoord.xy + vec2(fract(t) * 91.7, fract(t * 0.7) * 57.3)) - 0.5) * 0.026;

  gl_FragColor = vec4(col, 1.0);
  #include <colorspace_fragment>
}
`

const boot = async () => {
  const root = rootRef.value
  const canvas = canvasRef.value
  if (!root || !canvas) return
  // jsdom 等环境没有 WebGL2，直接留在静态兜底层
  if (typeof window === 'undefined' || typeof window.WebGL2RenderingContext !== 'function') return
  let probe: WebGL2RenderingContext | null = null
  try {
    probe = canvas.getContext('webgl2', { antialias: false, alpha: false })
  } catch {
    probe = null
  }
  if (!probe) return

  try {
    const THREE = await import('three')
    if (!alive) return

    const renderer: WebGLRenderer = new THREE.WebGLRenderer({
      canvas,
      context: probe,
      antialias: false,
      alpha: false,
      depth: false,
      stencil: false,
      powerPreference: 'low-power',
    })

    const uniforms = {
      uRes: { value: new THREE.Vector2(1, 1) },
      uTime: { value: 0 },
      uPointer: { value: new THREE.Vector2(0, 0) },
      uDay: { value: 0 },
      uBg: { value: new THREE.Color('#151512') },
      uAcid: { value: new THREE.Color('#d8f14b') },
      uTech: { value: new THREE.Color('#06b6d4') },
      uLight: { value: new THREE.Color('#f2f0e4') },
      uDark: { value: new THREE.Color('#151512') },
    }
    const material: ShaderMaterial = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      depthTest: false,
      depthWrite: false,
    })
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material)
    const scene = new THREE.Scene()
    scene.add(mesh)
    const camera = new THREE.Camera()

    let rafId = 0
    let running = false
    let onScreen = true
    let contextLost = false
    let last = 0
    let elapsed = 0
    const pointerTarget = { x: 0, y: 0 }
    /** 昼=1 夜=0 的目标值；RAF 内指数趋近实现八方旅人式时间切换 */
    let targetDay = 0

    const renderFrame = () => {
      renderer.render(scene, camera)
    }

    const frame = (now: number) => {
      rafId = window.requestAnimationFrame(frame)
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      elapsed += dt
      uniforms.uTime.value = elapsed * 0.55
      const pointer = uniforms.uPointer.value
      pointer.x += (pointerTarget.x - pointer.x) * 0.06
      pointer.y += (pointerTarget.y - pointer.y) * 0.06
      const ud = uniforms.uDay.value
      // 恒速 1.8s 扫过昼夜（天体角速度恒定，黄昏带有停留感），比指数趋近更像时间流逝
      const step = dt / 1.8
      const diff = targetDay - ud
      uniforms.uDay.value = Math.abs(diff) <= step ? targetDay : ud + Math.sign(diff) * step
      renderFrame()
    }

    const stop = () => {
      if (rafId) window.cancelAnimationFrame(rafId)
      rafId = 0
      running = false
    }
    const maybeStart = () => {
      if (running || contextLost || !onScreen || motionQuery.matches) return
      running = true
      last = performance.now()
      rafId = window.requestAnimationFrame(frame)
    }

    const readToken = (name: string, target: InstanceType<typeof THREE.Color>) => {
      const raw = getComputedStyle(root).getPropertyValue(name).trim()
      if (!raw) return
      try {
        target.set(raw)
      } catch {
        // token 解析失败时保留上一值，不中断渲染
      }
    }
    const readTokenColor = (name: string) => {
      const raw = getComputedStyle(root).getPropertyValue(name).trim()
      if (!raw) return null
      try {
        return new THREE.Color(raw)
      } catch {
        return null
      }
    }
    const luminance = (c: InstanceType<typeof THREE.Color>) =>
      0.2126 * c.r + 0.7152 * c.g + 0.0722 * c.b
    const syncTheme = () => {
      readToken('--contact-hero-bg', uniforms.uBg.value)
      readToken('--acid', uniforms.uAcid.value)
      readToken('--tech-primary', uniforms.uTech.value)
      // --ink/--paper-raised 随主题反转；按亮度分出"浅色漆/深色漆"，语义与主题无关
      const ink = readTokenColor('--ink')
      const paper = readTokenColor('--paper-raised')
      if (ink && paper) {
        if (luminance(ink) > luminance(paper)) {
          uniforms.uLight.value.copy(ink)
          uniforms.uDark.value.copy(paper)
        } else {
          uniforms.uLight.value.copy(paper)
          uniforms.uDark.value.copy(ink)
        }
      }
      targetDay = document.documentElement.dataset.theme === 'dark' ? 0 : 1
      // 循环停止时（reduced-motion / 离屏 / 首帧前）直接跳变，保证静帧也是正确场景
      if (!running) {
        uniforms.uDay.value = targetDay
        renderFrame()
      }
    }

    const resize = () => {
      const width = root.clientWidth || 1
      const height = root.clientHeight || 1
      const dpr = Math.min(window.devicePixelRatio || 1, width < 640 ? 1.4 : 1.75)
      renderer.setPixelRatio(dpr)
      renderer.setSize(width, height, false)
      uniforms.uRes.value.set(width * dpr, height * dpr)
      if (!running) renderFrame()
    }

    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    const applyMotionPref = () => {
      if (motionQuery.matches) stop()
      else maybeStart()
    }

    syncTheme()
    resize()
    live.value = true
    applyMotionPref()

    const resizeObserver =
      typeof ResizeObserver === 'function' ? new ResizeObserver(resize) : null
    resizeObserver?.observe(root)

    const intersectionObserver =
      typeof IntersectionObserver === 'function'
        ? new IntersectionObserver(
            (entries) => {
              onScreen = entries[0]?.isIntersecting ?? true
              if (onScreen) maybeStart()
              else stop()
            },
            { threshold: 0.02 },
          )
        : null
    intersectionObserver?.observe(root)

    const themeObserver = new MutationObserver(syncTheme)
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })

    const hero = root.closest('.contact-hero') ?? root
    const onPointerMove = (event: Event) => {
      const pointerEvent = event as PointerEvent
      const rect = root.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      pointerTarget.x = ((pointerEvent.clientX - rect.left) / rect.width - 0.5) * 2
      pointerTarget.y = -(((pointerEvent.clientY - rect.top) / rect.height - 0.5) * 2)
    }
    hero.addEventListener('pointermove', onPointerMove, { passive: true })

    const onContextLost = (event: Event) => {
      event.preventDefault()
      contextLost = true
      stop()
      live.value = false
    }
    const onContextRestored = () => {
      contextLost = false
      syncTheme()
      resize()
      live.value = true
      applyMotionPref()
    }
    canvas.addEventListener('webglcontextlost', onContextLost)
    canvas.addEventListener('webglcontextrestored', onContextRestored)
    motionQuery.addEventListener('change', applyMotionPref)

    cleanup = () => {
      stop()
      resizeObserver?.disconnect()
      intersectionObserver?.disconnect()
      themeObserver.disconnect()
      motionQuery.removeEventListener('change', applyMotionPref)
      hero.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('webglcontextlost', onContextLost)
      canvas.removeEventListener('webglcontextrestored', onContextRestored)
      mesh.geometry.dispose()
      material.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
    }
  } catch {
    // three 加载或渲染器创建失败：静默回退，静态兜底层仍在
  }
}

onMounted(() => {
  alive = true
  void boot()
})
onBeforeUnmount(() => {
  alive = false
  cleanup?.()
  cleanup = null
})
</script>

<template>
  <div ref="rootRef" class="hero-visual" :class="{ 'hero-visual--live': live }" aria-hidden="true">
    <div class="hero-fallback" />
    <canvas ref="canvasRef" class="hero-canvas" />
  </div>
</template>

<style scoped>
.hero-visual {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}
/* 静态兜底与场景同语义：昼 = 亮天空渐变，夜 = 暗场酸绿/青光晕 */
.hero-fallback {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(110% 80% at 30% 14%, color-mix(in srgb, var(--acid) 22%, transparent), transparent 58%),
    linear-gradient(180deg, color-mix(in srgb, var(--tech-primary) 18%, var(--contact-hero-bg)), var(--contact-hero-bg) 82%);
}
:global(:root[data-theme='dark']) .hero-fallback {
  background:
    radial-gradient(120% 90% at 78% 18%, color-mix(in srgb, var(--acid) 16%, transparent), transparent 60%),
    radial-gradient(90% 70% at 18% 82%, color-mix(in srgb, var(--tech-primary) 14%, transparent), transparent 65%),
    var(--contact-hero-bg);
}
.hero-canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  opacity: 0;
  transition: opacity 0.6s ease;
}
.hero-visual--live .hero-canvas {
  opacity: 1;
}
@media (prefers-reduced-motion: reduce) {
  .hero-canvas {
    transition: none;
  }
}
</style>
