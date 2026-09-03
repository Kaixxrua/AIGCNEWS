/**
 * 环境层 AI 美术加载器（私有 overlay 专属）。
 *
 * 素材 = AI 抽卡原图经离线管线处理（prep_env.py：背景键控只写 alpha、
 * RGB 逐像素保留、内容 bbox 裁切、webp 打包），运行期零加工直接上屏。
 * 镜像 loadCastArt 的模式：模块级 Promise 缓存 + Image.decode +
 * 环境层约定平滑采样（Linear + mipmaps + SRGB；脆像素是精灵层的纪律）。
 */
import * as THREE from 'three'

import grassUrl from '../assets/env/grass.webp?url'
import pathUrl from '../assets/env/path.webp?url'
import hillsUrl from '../assets/env/hills.webp?url'
import treelineUrl from '../assets/env/treeline.webp?url'
import villageUrl from '../assets/env/village.webp?url'
import villageWindowsUrl from '../assets/env/village-windows.webp?url'
import bushUrl from '../assets/env/bush.webp?url'
import rockUrl from '../assets/env/rock.webp?url'
import treeAUrl from '../assets/env/treeA.webp?url'
import treeBUrl from '../assets/env/treeB.webp?url'
import fggrassUrl from '../assets/env/fggrass.webp?url'

export interface EnvArt {
  /** 地面草（不透明，MirroredRepeat 双轴平铺） */
  grass: THREE.Texture
  /** 土径横带（上下缘已羽化，Clamp 单幅拉伸） */
  path: THREE.Texture
  /** 远山（RepeatWrapping 横向平铺防拉伸） */
  hills: THREE.Texture
  /** 树线（RepeatWrapping 横向平铺） */
  treeline: THREE.Texture
  /** 村庄剪影（RepeatWrapping；暖窗层 UV 必须与之同步） */
  village: THREE.Texture
  /** 村庄暖窗加法层（离线提取的亮窗掩码，UV 与村庄一致） */
  villageWindows: THREE.Texture
  /** 中景灌木（Clamp） */
  bush: THREE.Texture
  /** 中景岩石（Clamp） */
  rock: THREE.Texture
  /** 中景树 A：阔叶橡树（Clamp，替换精灵层 DSL 棒棒糖树） */
  treeA: THREE.Texture
  /** 中景树 B：窄冠白杨（Clamp） */
  treeB: THREE.Texture
  /** 前景草（MirroredRepeat 横向平铺） */
  fggrass: THREE.Texture
}

let cache: Promise<EnvArt> | null = null

const decodeTexture = async (
  url: string,
  wrapS: THREE.Wrapping = THREE.ClampToEdgeWrapping,
  wrapT: THREE.Wrapping = THREE.ClampToEdgeWrapping,
): Promise<THREE.Texture> => {
  const image = new Image()
  image.src = url
  await image.decode()
  const texture = new THREE.Texture(image)
  texture.magFilter = THREE.LinearFilter
  texture.minFilter = THREE.LinearMipmapLinearFilter
  texture.generateMipmaps = true
  texture.colorSpace = THREE.SRGBColorSpace
  texture.wrapS = wrapS
  texture.wrapT = wrapT
  texture.needsUpdate = true
  return texture
}

/** 加载全部环境纹理；重复调用共享同一 Promise，失败后缓存清空可重试 */
export const loadEnvArt = (): Promise<EnvArt> => {
  if (!cache) {
    cache = (async (): Promise<EnvArt> => {
      const [grass, path, hills, treeline, village, villageWindows, bush, rock, treeA, treeB, fggrass] =
        await Promise.all([
          decodeTexture(grassUrl, THREE.MirroredRepeatWrapping, THREE.MirroredRepeatWrapping),
          decodeTexture(pathUrl),
          decodeTexture(hillsUrl, THREE.RepeatWrapping),
          decodeTexture(treelineUrl, THREE.RepeatWrapping),
          decodeTexture(villageUrl, THREE.RepeatWrapping),
          decodeTexture(villageWindowsUrl, THREE.RepeatWrapping),
          decodeTexture(bushUrl),
          decodeTexture(rockUrl),
          decodeTexture(treeAUrl),
          decodeTexture(treeBUrl),
          decodeTexture(fggrassUrl, THREE.MirroredRepeatWrapping),
        ])
      return { grass, path, hills, treeline, village, villageWindows, bush, rock, treeA, treeB, fggrass }
    })()
    cache.catch(() => {
      cache = null
    })
  }
  return cache
}
