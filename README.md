# sooc-vs-edited

直出还是修图？—— 把相机直出 JPEG 和 RAW 修图导出摆在一起，逐张对比、逐张挑选，最后把选中的**原图**导出到一个文件夹。

修图几乎总会顺手改构图（裁切、转正、偶尔拉一下透视），两张图不再像素对齐，叠加对比就没意义了。所以本工具先用 SIFT + RANSAC 估计单应矩阵，把直出图**变形到修图版的取景框里**，剩下的差异才是纯粹的调色。

## 特性

- **三种对比模式**：滑块（拖动分隔线，左直出右修图）、A/B 闪切（同位置盲切，最适合判断"哪个更好"）、并排。
- **几何自动对齐**：裁切 / 旋转 / 透视一次性抵消，并在顶栏标出每张的裁切倍率、旋转角、透视残差（px）。
- **全屏单图 + 键盘操作**：`←/→` 翻页，`空格` 闪切，`A` 选直出，`D` 选调色，`X` 取消，`⌘/Ctrl+E` 导出。
- **选择持久化**：存在 localStorage，关掉浏览器也不丢。
- **导出的是原图**：页面里看的是 1600px 预览，导出时由本地服务复制真正的全画幅原图，附带 `manifest.csv`；可选连 RAW 一起导。镜像模式让导出目录始终等于当前选择。
- **选直出 = 只要相机的颜色，不是相机的构图**：导出直出时会把对齐用的单应矩阵放大到全分辨率，重新渲染成修图版的画幅，裁切/转正/透视都保留（EXIF 一并保留）。修图版没动构图的帧则原样复制，不做二次编码。用 `--keep-sooc-crop` 或取消页面上的开关可以关掉。

## 安装 / 运行

依赖 numpy、Pillow、opencv-python-headless。用 [uv](https://docs.astral.sh/uv/) 免安装直接跑：

```bash
uv tool run --from git+https://github.com/t0saki/sooc-vs-edited svse build \
  --sooc  "/path/to/camera/jpg" \
  --edited "/path/to/lightroom/export"
```

或者克隆下来：

```bash
git clone https://github.com/t0saki/sooc-vs-edited && cd sooc-vs-edited
uv run svse build --sooc <直出目录> --edited <修图目录>
```

`build` 默认在生成后直接起本地服务并打开浏览器。

## 用法

```
svse build  --sooc DIR --edited DIR [--out DIR] [--export-to DIR]
            [--title T] [--width 1600] [--no-align] [--jobs 8]
            [--port 8787] [--no-serve] [--no-open] [--recursive]
svse serve  OUT_DIR [--port 8787]          # 为已生成的目录起服务
svse export OUT_DIR choices.json [--raw]   # 页面没连上服务时的兜底导出
svse pair   --sooc DIR --edited DIR        # 只看配对结果
```

默认输出到 `<修图目录> 对比`，导出到 `<输出目录> 精选`。

### 文件配对

按帧号配对，正则默认 `^([A-Za-z]*[_-]?\d+)`，取文件名第一个 `.` 之前的部分匹配。所以下面这些都会归到同一帧：

```
P1035532.JPG   P1035532.jpg   P1035699.RW22.jpg   DSC_0123-Edit.jpg   IMG_4821_1.jpg
```

不合适就用 `--key-regex` 换一个。一个帧号对应多个文件时取排序后的第一个，并在输出里提示。

### 对齐指标

顶栏徽章来自单应矩阵的分解（在预览尺度上计算）：

| 徽章 | 含义 | 说明 |
|---|---|---|
| 裁 1.24× | 缩放 | 修图时裁进去了多少 |
| 旋 -1.6° | 旋转 | 转正的角度 |
| 透视 34px | 非仿射残差 | 用最优仿射拟合四角后的最大残差，大于 ~5px 说明真的做了透视/keystone 校正 |
| 未对齐 | 失败 | 特征点太少或内点不足，回退到未对齐的直出预览 |

## 工作原理

1. **配对** — 两个目录按帧号取交集。
2. **预览** — Pillow 生成 1600px 预览（含 EXIF 方向校正）和 260px 缩略图。
3. **对齐** — 对预览做 SIFT（6000 特征点）→ BFMatcher knnMatch → Lowe ratio 0.75 → `findHomography(RANSAC, 4px)` → `warpPerspective` 到修图版画幅。对齐在预览尺度做，全分辨率不会更准，只会更慢。
4. **页面** — 帧列表和对齐指标直接注入 HTML，无外部依赖，整个目录可以拷走。
5. **导出** — 页面 POST `/export`，本地服务按选择复制原始文件。

## License

MIT
