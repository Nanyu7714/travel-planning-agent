# Airbnb 城市卡片设计规范

> 适用组件：`frontend/src/components/CityCard.vue` 及复用该组件的城市列表页面。
>
> 来源：`DESIGN.md` 的 Airbnb 设计变量和组件规范，以及已确认的热门城市卡片视觉方案。
>
> 更新时间：2026-09-01

## 1. 使用原则

本规范只覆盖热门城市卡片及其列表布局，不替换项目现有的全局绿色主题。卡片局部使用 Airbnb 的白色画布、深色文字、柔和圆角和唯一 Hover 阴影。

`DESIGN.md` 中 `property-card` 的原始图片比例为 `1:1`；本项目已确认的城市卡片图片比例为 `4:3`，以本项目确认值为准。

## 2. 颜色变量

| 变量 | 值 | 卡片用途 |
| --- | --- | --- |
| `colors.primary` | `#ff385c` | Airbnb 品牌主色，当前卡片不直接使用 |
| `colors.primary-active` | `#e00b41` | 主色激活态，当前卡片不直接使用 |
| `colors.ink` | `#222222` | 城市名称、景点数量标签文字 |
| `colors.body` | `#3f3f3f` | 正文文字备用色 |
| `colors.muted` | `#6a6a6a` | 图片加载失败时的占位文字 |
| `colors.muted-soft` | `#929292` | 弱化文字备用色 |
| `colors.canvas` | `#ffffff` | 卡片背景 |
| `colors.surface-soft` | `#f7f7f7` | 景点数量标签背景、图片占位背景 |
| `colors.hairline` | `#dddddd` | 边界线备用色 |
| `colors.on-primary` | `#ffffff` | 主色背景上的文字备用色 |

## 3. 字体层级

字体栈统一使用：

```css
'Airbnb Cereal VF', Circular, -apple-system, system-ui, Roboto, 'Helvetica Neue', sans-serif
```

| 使用场景 | DESIGN token | 字号 | 字重 | 行高 | 字间距 |
| --- | --- | ---: | ---: | ---: | ---: |
| 城市名称 | `typography.title-md` | `16px` | `600` | `1.25` | `0` |
| 景点数量标签 | `typography.badge` | `11px` | `600` | `1.18` | `0` |
| 图片占位文字 | `typography.badge` 参考 | `11px` | `400` | 默认 | `0` |

## 4. 圆角、间距和阴影

| 设计项 | DESIGN token / 确认值 | 实现要求 |
| --- | --- | --- |
| 卡片圆角 | `rounded.md` = `14px` | 卡片及图片容器使用 `14px`，并裁剪溢出内容 |
| 标签圆角 | `rounded.full` = `9999px` | 景点数量标签使用全圆角 |
| 基础间距 | `spacing.base` = `16px` | 城市列表 Grid 的行间距和列间距均为 `16px` |
| 卡片 Meta 内边距 | `spacing.base` = `16px` | 城市名称和标签区域使用 `16px` 内边距 |
| 默认阴影 | 无 | 卡片静止状态不使用阴影 |
| Hover 阴影 | `rgba(0, 0, 0, 0.02) 0 0 0 1px, rgba(0, 0, 0, 0.04) 0 2px 6px 0, rgba(0, 0, 0, 0.1) 0 4px 8px 0` | 鼠标悬停时使用唯一卡片阴影层级 |
| 鼠标移动 | 最大约 `4deg` | 根据鼠标在卡片内的位置轻微倾斜，离开后回正 |

## 5. 城市卡片结构

| 区域 | 规范 |
| --- | --- |
| 图片 | 大图置于卡片顶部，固定 `aspect-ratio: 4 / 3`，使用 `object-fit: cover` |
| 城市名称 | 加粗显示，使用 `title-md`，允许长名称换行 |
| 景点数量 | 使用 `surface-soft` 背景和 `ink` 文字，内容格式为“`N 个景点`” |
| 卡片链接 | 整张卡片可点击，跳转至 `/cities/:slug` |
| 图片失败 | 显示 `MapPin` 图标和“图片待核验”占位状态 |
| 键盘焦点 | 使用可见的 `focus-visible` 轮廓，不能仅依赖 Hover |
| 动效 | Hover 时向上移动 `4px`，过渡时间 `180ms`；用户偏好减少动画时取消位移和过渡 |

## 6. 城市列表 Grid

列表页文件：`frontend/src/views/CityList.vue`

| 设备范围 | Grid 列数 | CSS |
| --- | ---: | --- |
| 手机端，宽度小于等于 `640px` | 1 列 | `grid-template-columns: 1fr` |
| 平板端，宽度 `641px` 至 `1023px` | 2 列 | `grid-template-columns: repeat(2, minmax(0, 1fr))` |
| 桌面端，宽度大于 `1023px` | 4 列或更多 | `grid-template-columns: repeat(auto-fill, minmax(260px, 1fr))` |

所有断点统一使用：

```css
gap: 16px;
```

桌面 Grid 使用 `minmax(260px, 1fr)` 保证卡片具备可读宽度，平板 Grid 使用 `minmax(0, 1fr)` 防止长城市名称撑开列宽。当前列表页使用 9 条 Mock 城市数据验证布局，不代表这些城市已经接入正式后端数据。

列表首次渲染使用 Vue `TransitionGroup`：卡片从 `opacity: 0`、`translateY(10px)` 过渡到 `opacity: 1`、`translateY(0)`；检测到用户偏好减少动画时取消过渡。

公共交互使用短时、低幅度反馈：按钮按下时缩放至 `0.98`，景点和排行行 Hover 时切换浅灰背景，所有交互控件保留可见焦点轮廓。

## 7. 禁止事项

- 不为城市卡片新增未在本规范或 `DESIGN.md` 中定义的颜色。
- 不把 `gap` 改为 `14px`、`20px` 等其他值；Grid 行列间距必须保持 `16px`。
- 不恢复 `property-card` 的 `1:1` 图片比例；城市卡片必须保持已确认的 `4:3`。
- 不在默认状态增加渐变、厚重阴影或多层阴影。
- `CityCard.vue` 是页面使用的统一入口和视觉实现文件；`PopularCityCard.vue` 作为旧页面兼容组件保留，不新增第二套设计规范。
