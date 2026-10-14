# 联系页静态截图（contact-poster）

联系页默认只显示 `camp-scene/contact-poster-{960,1600,2400}.webp`，访客点「选择画质 → 开启」
后才内嵌 Godot 场景。截图随私有发布包走（写进 `cn-current-godot-release-source-manifest.json`），
组件用 `?v=` 版本号（`GodotContactScene.vue` 的 `POSTER_VERSION`）绕开浏览器旧缓存，换图时一起改。

## 重新截图

本机无 GPU，只能用 SwiftShader 软渲染，一帧 10–30 秒。`capture.mjs` 在场景 iframe 里注入帧时钟
（每渲染一帧 `performance.now` 前进 17.5ms，性能调速器看到的是 ~57 FPS，不会降渲染比例），
并把 ≥20s 的 `setTimeout` 放大 20 倍，避免出场伙伴 30s 看门狗被软渲染拖到误报 `error`。

```bash
mkdir -p root && cp host.html root/index.html
ln -s <发布目录>/cn-current-godot-release/camp-scene root/camp-scene
node serve.mjs "$PWD/root" 4191 &
# 宽 高 画质 输出 就绪后再等的帧数；2400×1101 与桌面联系卡片同比例，约 15–20 分钟
node capture.mjs 2400 1101 original poster-2400.png 40
for w in 960 1600 2400; do
  ffmpeg -loglevel error -y -i poster-2400.png -vf "scale=$w:-2:flags=lanczos" \
    -c:v libwebp -quality 82 -compression_level 6 -preset picture contact-poster-$w.webp
done
```

截图会隐藏 iframe 内的控件与载入层，游戏内的 BOSS 血条、伤害数字与喊话属于场景画面，保留。

## 组装发布包

`build_release.py <poster 目录>` 从上一版发布目录硬链接 `camp-scene`（不原地改任何继承文件），
加入三张截图，复制四个受保护源码，按原格式重写清单与描述文件并打印新的描述文件 SHA-256。
脚本里的新旧发布目录、release ID 与源码目录按需修改。之后更新
`~/.config/aigcnews/local-delivery.json` 的 `private_root` / `private_release_id` /
`private_descriptor_sha256`，下一次 main 发布即带上新版联系页。
