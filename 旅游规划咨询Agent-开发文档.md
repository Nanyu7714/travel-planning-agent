# 多城市个性化旅游规划平台 — Agent 开发文档

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | 多城市个性化旅游规划平台 Agent 开发文档 |
| 文档版本 | V1.0 |
| 适用范围 | 本文档规定 MVP 的产品边界、数据模型、Agent 运行时、接口、前端和部署实现 |
| 目标形态 | 面向浏览器访问的网站 |
| 运行环境 | 宝塔面板、Alibaba Cloud Linux 3、2 核 2 GB 内存 |
| 最近修订 | 2026-08-31：初版 |
| 实现原则 | 先完成固定城市和可复现数据，再扩展实时数据与更多城市 |

本文是本项目的开发依据。产品需求、接口字段、事件名称和状态值以本文为准。实现中不应为了展示效果伪造实时数据、路线结果或用户行为数据。没有真实数据的功能必须标注为“示例数据”或“未启用”。

---

## 1. 项目目标

本项目建设一个“旅游发现 + 热门排行 + AI 行程规划”平台，帮助用户发现适合当前季节的城市和景点，并根据目的地、日期、预算、兴趣和出行节奏生成可执行的多日行程。

平台的核心不是让大模型自由生成攻略，而是：

1. 把用户自然语言需求转换成结构化旅行条件。
2. 从城市和景点数据中筛选候选对象。
3. 根据热度、季节、偏好和预算计算推荐结果。
4. 根据开放时间、游玩时长和交通时间规划顺序。
5. 只让大模型解释已经计算出的结果，避免编造景点信息。

本项目第一版固定支持北京、上海、成都三个城市。城市数量通过数据配置扩展，不为每个城市单独编写一套 Agent 逻辑。

---

## 2. 产品边界

### 2.1 MVP 必须完成

| 模块 | MVP 要求 |
| :--- | :--- |
| 城市发现 | 展示 3 个城市、城市简介、推荐季节、预算和建议天数 |
| 热门排行 | 支持季度热门城市排行和热门景点排行 |
| 景点浏览 | 展示景点详情、标签、开放时间、门票、游玩时长和位置 |
| AI 咨询 | 多轮采集目的地、天数、预算、兴趣和节奏 |
| 行程规划 | 生成 2～5 天游，安排景点顺序和每日时间 |
| 约束校验 | 校验开放时间、游玩时长、交通时间和预算 |
| 行程调整 | 支持增加、删除、替换景点和调整节奏 |
| 行程管理 | 登录用户可以保存、查看和删除自己的行程 |
| 后台管理 | 管理城市、景点、标签和排行数据 |

### 2.2 明确不做

- 酒店、机票、门票在线预订和支付。
- 复杂的跨城市路线优化。
- 用户社区、评论发布和私信。
- 全网实时爬虫。
- 代替地图导航的实时定位服务。
- 签证、保险和医疗等专业咨询。
- 本地运行大语言模型。
- 任意代码执行、外部 MCP 和通用工作流引擎。

### 2.3 数据原则

- 固定数据集是 MVP 的主要数据源，保证演示和实验可复现。
- 每条景点、价格、开放时间和排行数据必须包含 `source` 和 `updated_at`。
- 实时地图路线可以调用高德 API；调用失败时使用已缓存路线，不得编造距离。
- 未验证的天气、营业状态和价格信息必须显示数据更新时间。

---

## 3. 总体架构

```text
浏览器
  ├── Vue 前端页面
  ├── 城市 / 景点 / 排行浏览
  └── Agent 对话与行程展示
          │ REST + SSE
          ▼
Nginx（宝塔管理）
          │
          ▼
FastAPI 应用
  ├── 认证与用户模块
  ├── 城市和景点模块
  ├── 热门排行模块
  ├── Agent Harness
  ├── 推荐评分模块
  ├── 行程规划模块
  └── 外部 API 适配器
          │
          ├── PostgreSQL
          ├── 高德地图 API
          └── 云端大模型 API
```

### 3.1 运行时约束

- 对话使用 REST 提交消息，SSE 推送服务端事件。
- 单次 Agent 回合最多调用 4 次大模型，最多执行 8 次短工具。
- 行程生成不得在 HTTP 请求中无限等待；超过 30 秒返回超时错误。
- 本项目不部署 Redis、Kafka、Elasticsearch 或独立向量数据库。
- 2 GB 内存服务器只启动一个 Uvicorn worker。
- 复杂的排行榜计算通过宝塔计划任务执行，不阻塞用户请求。

---

## 4. 技术栈

### 4.1 前端

- Vue 3
- TypeScript
- Vite
- Element Plus
- ECharts
- 高德地图 JavaScript API
- 原生 `EventSource` 或轻量 SSE 客户端

### 4.2 后端

- Python 3.11 或 3.12
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- Uvicorn
- PyJWT 或同类 JWT 库
- `psycopg[binary]`
- httpx
- OR-Tools

### 4.3 部署

- Alibaba Cloud Linux 3
- 宝塔 Nginx
- 宝塔 PostgreSQL 管理器
- 宝塔 Python 项目管理器
- 宝塔计划任务
- Let's Encrypt HTTPS

大模型密钥、高德密钥和数据库密码只能保存在后端环境变量中，不能写入前端代码或提交到 Git。

---

## 5. 用户角色与页面

### 5.1 普通用户页面

| 页面 | 路径 | 功能 |
| :--- | :--- | :--- |
| 首页 | `/` | 季节推荐、热门城市、热门景点和入口 |
| 热门排行 | `/rankings` | 季度城市榜、景点榜和趋势 |
| 城市详情 | `/cities/:slug` | 城市概览、景点、预算和推荐季节 |
| 景点详情 | `/attractions/:id` | 景点信息、标签、开放时间和地图 |
| AI 规划 | `/planner` | 多轮对话和行程生成 |
| 行程详情 | `/itineraries/:id` | 每日行程、地图、预算和调整 |
| 我的行程 | `/me/itineraries` | 保存的行程和历史记录 |
| 登录注册 | `/login`、`/register` | 用户认证 |

### 5.2 管理员页面

| 页面 | 功能 |
| :--- | :--- |
| 城市管理 | 城市增删改查、城市封面和季节标签 |
| 景点管理 | 景点信息、开放时间、门票和位置 |
| 排行管理 | 导入统计数据、生成季度排行、查看数据时间 |
| 用户反馈 | 查看规划失败和用户评分 |

---

## 6. 数据模型

### 6.1 城市 `cities`

```json
{
  "id": "uuid",
  "slug": "chengdu",
  "name": "成都",
  "description": "string",
  "best_seasons": ["spring", "autumn"],
  "recommended_days_min": 2,
  "recommended_days_max": 5,
  "budget_level": "medium",
  "cover_image_url": "string",
  "latitude": 30.5728,
  "longitude": 104.0668,
  "source": "string",
  "updated_at": "datetime"
}
```

### 6.2 景点 `attractions`

```json
{
  "id": "uuid",
  "city_id": "uuid",
  "name": "宽窄巷子",
  "description": "string",
  "category": "culture",
  "tags": ["历史文化", "美食", "拍照"],
  "address": "string",
  "latitude": 30.6574,
  "longitude": 104.0617,
  "opening_hours": [
    { "weekday": 1, "open": "09:00", "close": "22:00" }
  ],
  "visit_duration_min": 120,
  "ticket_price": 0,
  "rating": 4.6,
  "review_count": 10000,
  "season_tags": ["spring", "summer", "autumn"],
  "suitable_for": ["young", "family"],
  "image_url": "string",
  "source": "string",
  "updated_at": "datetime"
}
```

### 6.3 季度排行 `ranking_snapshots`

```json
{
  "id": "uuid",
  "period": "2026Q3",
  "ranking_type": "city | attraction",
  "target_id": "uuid",
  "rank": 1,
  "hot_score": 87.5,
  "score_breakdown": {
    "search": 21.0,
    "view": 18.5,
    "favorite": 16.0,
    "review": 14.0,
    "season": 18.0
  },
  "data_source": "seed | system_event | imported",
  "updated_at": "datetime"
}
```

### 6.4 用户需求 `travel_requests`

```json
{
  "session_id": "uuid",
  "destination_city_id": "uuid | null",
  "start_date": "date | null",
  "days": 4,
  "traveler_count": 2,
  "budget_total": 3000,
  "interests": ["美食", "历史文化"],
  "pace": "relaxed | balanced | intensive",
  "transport": "public_transport | car | mixed",
  "must_visit": ["string"],
  "avoid": ["string"],
  "slots_filled": ["destination_city_id", "days"],
  "slots_pending": ["budget_total"],
  "status": "collecting | confirming | planning | completed | failed"
}
```

### 6.5 行程 `itineraries`

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "session_id": "uuid",
  "city_id": "uuid",
  "title": "成都 4 天游",
  "days": 4,
  "total_budget": 2800,
  "pace": "relaxed",
  "status": "draft | saved | archived",
  "algorithm_version": "route-v1",
  "generated_at": "datetime",
  "updated_at": "datetime"
}
```

### 6.6 每日行程 `itinerary_stops`

```json
{
  "id": "uuid",
  "itinerary_day_id": "uuid",
  "attraction_id": "uuid",
  "sequence": 1,
  "arrival_time": "10:00",
  "departure_time": "12:00",
  "visit_duration_min": 120,
  "travel_from_previous_min": 25,
  "estimated_cost": 0,
  "reason": "符合历史文化偏好，且与下一景点距离较近"
}
```

### 6.7 会话与事件

`chat_sessions` 保存会话状态，`chat_messages` 保存用户消息和最终交付文本，`agent_events` 保存阶段、工具、确认、结果和错误事件。进度事件不能混入模型上下文。

所有表使用 UUID 主键和 UTC 时间。前端展示时转换为北京时间。

---

## 7. 热门排行设计

### 7.1 评分公式

季度排行由宝塔计划任务计算。所有指标先按同一周期归一化，再计算热度：

```text
hot_score =
  0.25 * search_score
  + 0.20 * view_score
  + 0.20 * favorite_score
  + 0.15 * review_score
  + 0.20 * season_score
```

对于已有历史数据，可以加入增长率；没有真实行为数据时只能使用导入数据或明确标记的模拟数据。

### 7.2 排行规则

- 同一 `period` 和 `ranking_type` 下，按 `hot_score` 降序排列。
- 分数相同时按最近增长率，再按评分排序。
- 城市榜和景点榜分开计算。
- 景点榜只能展示当前已启用城市的景点。
- 前端显示分数构成，避免只展示一个无法解释的总分。

### 7.3 计划任务

```text
每天：更新系统浏览、搜索、收藏统计
每周：刷新趋势数据
每季度：生成 ranking_snapshots
```

计划任务失败时保留上一期榜单，并在后台显示失败原因，不生成空榜单。

---

## 8. Agent 运行时

### 8.1 Agent 职责边界

Agent 负责理解需求、调用允许的短工具和生成解释。推荐结果、路线顺序、时间和费用由后端规则或算法计算。Agent 不得凭记忆编造景点、价格、开放时间或交通距离。

不向用户展示模型的隐藏思维链，只展示简短的阶段状态，例如“正在整理需求”“正在查询景点”“正在检查时间安排”。

### 8.2 处理流程

```text
用户消息
    ↓
INTENT：识别意图
    ↓
EXTRACT：提取旅行槽位
    ↓
CLARIFY：补齐必要信息
    ↓
RETRIEVE：调用城市、景点、排行和路线工具
    ↓
PLAN：推荐评分与路线规划
    ↓
CHECK：规则校验与事实校验
    ↓
DELIVER：交付确认卡、行程或澄清问题
```

### 8.3 意图类型

```text
browse_city       查看城市信息
ranking           查看热门排行
attraction_info   查询景点信息
plan_trip         规划旅游行程
modify_plan       修改已有行程
save_itinerary    保存行程
chat              普通旅游咨询
unsupported       不支持的请求
```

### 8.4 必要槽位

规划行程至少需要：

```text
destination_city
days
interests 或 trip_style
pace
```

预算、日期、人数和交通方式缺失时，Agent 应优先询问，但如果用户明确表示“不考虑预算”或“日期未定”，可以使用默认值并在确认卡中标明。

默认值：

```text
days = 3
traveler_count = 1
pace = balanced
transport = public_transport
budget_total = null
```

### 8.5 确认卡

信息满足规划条件后，Agent 先发送确认卡，不立即生成完整行程：

```json
{
  "type": "plan_confirm",
  "destination": "成都",
  "days": 4,
  "budget_total": 3000,
  "interests": ["美食", "休闲"],
  "pace": "relaxed",
  "transport": "public_transport",
  "missing_optional": ["start_date"],
  "editable": true
}
```

用户确认后才进入路线规划。用户拒绝确认时，保留原槽位并接受修改；不应清空整个会话。

### 8.6 Agent 短工具白名单

| 工具名 | 作用 |
| :--- | :--- |
| `city.list` | 查询支持的城市 |
| `city.get` | 查询城市详情 |
| `ranking.get` | 查询季度热门榜单 |
| `attraction.search` | 按城市、标签、预算和季节筛选景点 |
| `attraction.get` | 查询景点完整信息 |
| `route.matrix` | 查询景点之间的交通时间和距离 |
| `weather.get` | 可选的天气查询，失败时不影响固定数据规划 |
| `itinerary.get` | 查询当前或历史行程 |
| `itinerary.save` | 用户确认后保存行程 |
| `feedback.create` | 保存用户对行程的评分或反馈 |

禁止工具：

```text
任意 URL 请求
任意代码执行
任意数据库 SQL
任意文件读取
未登记的地图或模型工具
```

### 8.7 工具调用规则

- 工具调用必须串行，便于事件回放和错误定位。
- 每个工具必须返回结构化 JSON。
- 工具返回为空时，进入澄清或降级流程，不允许模型补造 ID。
- 同一回合最多调用 8 次工具。
- `route.matrix` 优先读取缓存，未命中时才调用高德 API。
- 工具超时统一转换为 `UPSTREAM` 或 `TIMEOUT`。

---

## 9. 推荐与路线规划

### 9.1 景点候选筛选

先进行硬条件过滤：

1. 景点属于目标城市。
2. 景点当前处于启用状态。
3. 适合用户日期或季节。
4. 不在用户明确排除列表中。
5. 门票和预算条件允许。
6. 开放时间数据完整或已标记为未知。

再对候选景点评分：

```text
attraction_score =
  0.35 * interest_match
  + 0.20 * season_match
  + 0.15 * popularity
  + 0.15 * rating
  + 0.15 * budget_match
```

用户明确表达的条件优先级高于默认权重。例如用户说“不想去太拥挤的地方”，则热门度不能简单地提高推荐分。

### 9.2 路线规划

每日行程的硬约束：

- 不安排闭馆时间内无法游览的景点。
- 景点游玩时间必须大于等于数据中的最小游玩时长。
- 每日游玩和交通总时长不超过 10 小时。
- 每日安排 2～5 个主要景点。
- 预算存在时，不超过用户预算；超出时明确提示。
- 相邻景点之间必须有路线时间或距离数据。

目标函数：

```text
route_score =
  attraction_preference_score
  - 0.30 * normalized_travel_time
  - 0.15 * repeated_area_penalty
  - 0.10 * overload_penalty
```

MVP 使用“候选筛选 + 分区聚类 + 最近邻排序”的可解释方案。P1 再引入 OR-Tools 的时间窗口约束进行对照实验。算法失败时使用按区域和评分排序的降级方案，并在结果中记录 `algorithm_version`。

### 9.3 结果事实校验

行程生成后必须执行：

- 景点 ID 是否存在。
- 所有推荐景点是否属于目标城市。
- 时间是否落在开放时间内。
- 每日时间段是否重叠。
- 交通时间是否为数据库或地图 API 返回值。
- 预算是否重新计算。
- 推荐理由引用的字段是否真实存在。

校验失败不得直接交付，先重新规划或给出无法满足约束的说明。

---

## 10. SSE 事件协议

### 10.1 连接方式

```text
GET /api/v1/sessions/{session_id}/events
Authorization: Bearer <access_token>
Last-Event-ID: <last_event_id>
```

服务端使用 SSE 推送事件。前端断线后携带 `Last-Event-ID` 重连，服务端补发更大的事件 ID。关闭浏览器不等于取消已完成的路线计算。

### 10.2 事件公共结构

```json
{
  "event_id": 123,
  "session_id": "uuid",
  "type": "stage",
  "created_at": "2026-08-31T10:00:00Z",
  "payload": {}
}
```

### 10.3 服务端事件

| type | payload | 用途 |
| :--- | :--- | :--- |
| `stage` | `{ "name": "extract", "message": "正在整理旅行需求" }` | 阶段状态 |
| `tool_call` | `{ "name": "attraction.search", "arguments": {} }` | 工具开始 |
| `tool_result` | `{ "name": "attraction.search", "ok": true, "data": {} }` | 工具结果 |
| `clarify` | `{ "message": "更偏好美食还是历史景点？" }` | 补充问题 |
| `plan_confirm` | 需求确认卡 JSON | 等待用户确认 |
| `itinerary` | `{ "itinerary_id": "uuid" }` | 行程已生成 |
| `message` | `{ "content": "string" }` | 普通回复或解释 |
| `error` | `{ "code": "TIMEOUT", "message": "路线规划超时" }` | 错误 |
| `done` | `{}` | 本回合结束 |

不新增 `thought`、`token`、`assistant` 等内部推理事件。阶段状态只展示简短摘要，不暴露模型隐藏思维链。

### 10.4 前端提交动作

普通消息：

```http
POST /api/v1/sessions/{session_id}/messages
Content-Type: application/json

{
  "content": "我想去成都玩四天，喜欢美食和休闲，不想安排太满"
}
```

确认行程：

```http
POST /api/v1/sessions/{session_id}/plan-confirm
Content-Type: application/json

{
  "confirmed": true,
  "patch": {
    "budget_total": 3000
  }
}
```

停止当前回合：

```http
POST /api/v1/sessions/{session_id}/stop
```

已生成的行程需要通过单独接口保存，不因生成完成自动写入用户收藏。

---

## 11. REST API

### 11.1 认证

```text
POST /api/v1/auth/register
POST /api/v1/auth/login
GET  /api/v1/auth/me
```

密码使用 Argon2 或 bcrypt 哈希。Access Token 不放在 URL 参数中。

### 11.2 会话

```text
GET  /api/v1/sessions
POST /api/v1/sessions
GET  /api/v1/sessions/{session_id}/messages
GET  /api/v1/sessions/{session_id}/events
POST /api/v1/sessions/{session_id}/messages
POST /api/v1/sessions/{session_id}/plan-confirm
POST /api/v1/sessions/{session_id}/stop
```

### 11.3 城市、景点和排行

```text
GET /api/v1/cities
GET /api/v1/cities/{city_id}
GET /api/v1/cities/{city_id}/attractions
GET /api/v1/attractions/{attraction_id}
GET /api/v1/rankings?period=2026Q3&type=city
GET /api/v1/rankings?period=2026Q3&type=attraction&city_id=uuid
```

排行接口没有指定历史周期时，默认返回最近一个已生成周期，不得返回实时拼接的假数据。

### 11.4 行程

```text
POST   /api/v1/itineraries
GET    /api/v1/itineraries
GET    /api/v1/itineraries/{itinerary_id}
PATCH  /api/v1/itineraries/{itinerary_id}
DELETE /api/v1/itineraries/{itinerary_id}
POST   /api/v1/itineraries/{itinerary_id}/replan
POST   /api/v1/itineraries/{itinerary_id}/feedback
```

### 11.5 统一错误码

```text
UNAUTHORIZED       未登录或令牌无效
FORBIDDEN          无资源权限
VALIDATION         请求参数或槽位不合法
NOT_FOUND          城市、景点或行程不存在
CONFLICT           当前会话状态冲突
UPSTREAM           大模型、地图或天气服务失败
TIMEOUT            调用超时
NO_FEASIBLE_PLAN   没有满足约束的行程
RATE_LIMITED       请求过于频繁
INTERNAL           服务内部错误
```

内部堆栈只写服务器日志，不返回给浏览器。日志中不得打印 API Key、密码和完整用户隐私信息。

---

## 12. Prompt 与模型调用

### 12.1 系统提示词原则

Agent 人设固定在服务端代码中：

```text
你是旅游规划咨询助手。
先理解并确认用户需求，再推荐景点和生成行程。
只能使用工具返回的城市、景点、价格、开放时间和路线信息。
不编造不存在的景点、价格、营业时间或交通距离。
不能满足约束时，明确说明冲突并提出调整建议。
推荐理由必须引用结构化数据中的真实字段。
```

### 12.2 结构化输出

需求提取模型只能输出以下结构：

```json
{
  "intent": "plan_trip",
  "slots": {
    "destination_city": "成都",
    "days": 4,
    "budget_total": 3000,
    "interests": ["美食", "休闲"],
    "pace": "relaxed",
    "transport": "public_transport"
  },
  "missing_required": [],
  "next_action": "confirm"
}
```

JSON 解析失败时最多重试一次；仍失败则使用规则解析预算、天数和城市名称，并进入规则校验。规则解析失败时只返回澄清问题，不生成行程。

### 12.3 行程文案生成

大模型只能接收：

- 已通过校验的行程 JSON。
- 景点真实字段。
- 路线时间和预算计算结果。

模型输出后，后端不接受新的景点 ID、价格或时间字段。所有事实字段以数据库和规划算法结果为准。

---

## 13. 外部服务与缓存

### 13.1 大模型 API

- 只在后端调用。
- 配置请求超时和最大输出长度。
- 每个用户限制单位时间调用次数。
- 模型不可用时，浏览、排行和景点详情仍应正常使用。
- 模型失败不得返回“已成功生成行程”。

### 13.2 高德地图 API

后端调用地理编码和路线服务，保存必要的距离、耗时和查询时间。优先读取缓存，避免重复消耗配额。

```text
route_cache:
  origin_attraction_id
  destination_attraction_id
  transport
  distance_m
  duration_min
  source
  expires_at
```

### 13.3 天气 API

天气作为 P1 功能。天气请求失败不应阻塞固定景点规划，前端显示“天气信息暂不可用”。

---

## 14. 前端交互约定

### 14.1 Agent 页面

页面组成：


- 左侧会话列表。
- 中间对话区域。
- 右侧可折叠的需求摘要或行程预览。
- 底部输入框和发送按钮。
- 生成时展示阶段状态。

确认卡直接出现在对话流中，不使用无法回放的弹窗。行程结果使用每日行程卡、地图和预算摘要展示。

### 14.2 状态显示

```text
extracting     正在整理需求
clarifying     等待补充信息
retrieving     正在查询景点
planning       正在安排路线
checking       正在检查行程
waiting_confirm 等待确认
completed      行程已生成
failed         生成失败
```

前端状态必须来自服务端事件或接口结果，不允许本地自行把请求标记为成功。

### 14.3 断线恢复

- 页面刷新后读取 messages 和 events。
- SSE 重连携带 `Last-Event-ID`。
- 同一个事件按 `event_id` 去重。
- 用户关闭页面不自动删除已生成行程。
- 未完成的当前回合可以在刷新后显示“本轮已中断”，不得伪造结果。

---

## 15. 安全与异常处理

- 所有用户资源查询必须校验 `user_id` 所有权。
- 管理员接口必须校验角色。
- 所有输入限制长度，用户消息建议不超过 4000 字符。
- Markdown 输出必须进行 XSS 清洗。
- 图片地址、外部链接和地图参数进行白名单或格式校验。
- API Key 只从环境变量读取。
- PostgreSQL 只允许本机或内网访问，不开放公网 `5432`。
- Nginx 只开放 `80`、`443`，SSH 端口限制来源 IP。
- 数据库每日备份到独立位置，不只保存在当前服务器。

统一异常结构：

```python
try:
    result = await service.execute()
except AppError:
    raise
except TimeoutError as exc:
    logger.warning("upstream timeout type=%s", type(exc).__name__)
    raise AppError("TIMEOUT", "服务响应超时") from exc
except Exception as exc:
    logger.exception("unexpected internal error")
    raise AppError("INTERNAL", "系统暂时无法完成操作") from exc
```

---

## 16. 宝塔部署方案

### 16.1 宝塔软件

保留和安装：

```text
Nginx
PostgreSQL 管理器
Python 项目管理器
Node.js 版本管理器（可选）
```

Redis、PHP 和 phpMyAdmin 不属于本项目必需服务。确认没有其他网站依赖后可以停止或卸载。

### 16.2 目录规划

```text
/www/wwwroot/travel-web/       Vue dist 静态文件
/www/wwwroot/travel-api/       FastAPI 项目
/www/wwwroot/travel-api/.venv/ Python 虚拟环境
/www/backup/travel/            数据库和配置备份
```

### 16.3 FastAPI 启动

```text
工作目录：/www/wwwroot/travel-api
启动文件：app.main:app
监听地址：127.0.0.1
监听端口：8000
进程数：1
```

2 GB 内存服务器不要启动多个 worker，也不要在服务器上运行前端开发服务器。

### 16.4 Nginx 网站配置

```text
/              → Vue dist 静态文件
/api/          → http://127.0.0.1:8000
/api/v1/sessions/{session_id}/events → FastAPI SSE
```

SSE 代理需要关闭缓冲并延长读取超时。域名配置完成后使用宝塔申请 HTTPS 证书。

### 16.5 数据库连接

```env
DATABASE_URL=postgresql+psycopg://travel_user:密码@127.0.0.1:5432/travel_platform
LLM_API_KEY=服务端密钥
AMAP_KEY=服务端地图密钥
JWT_SECRET=随机长字符串
```

`.env` 文件不提交到 Git。生产环境数据库使用独立用户，不使用 PostgreSQL 超级用户连接应用。

---

## 17. 目录结构

```text
travel-platform/
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   ├── components/
│   │   ├── stores/
│   │   ├── api/
│   │   └── types/
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── routers/
│   │   ├── services/
│   │   ├── agent/
│   │   │   ├── harness.py
│   │   │   ├── intents.py
│   │   │   ├── prompts.py
│   │   │   ├── tools.py
│   │   │   └── validators.py
│   │   ├── planning/
│   │   │   ├── scoring.py
│   │   │   ├── route.py
│   │   │   └── constraints.py
│   │   └── integrations/
│   │       ├── llm.py
│   │       ├── amap.py
│   │       └── weather.py
│   ├── migrations/
│   ├── scripts/
│   │   └── build_rankings.py
│   ├── tests/
│   └── requirements.txt
├── data/
│   ├── cities.json
│   └── attractions.json
└── README.md
```

Agent 只能通过 `agent/tools.py` 暴露的白名单工具访问业务服务，不能在提示词中直接拼接 SQL 或调用任意 HTTP 地址。

---

## 18. 开发里程碑

### M0：工程骨架

- [ ] 创建前后端项目。
- [ ] 配置 PostgreSQL 和 Alembic。
- [ ] 完成用户、城市、景点基础表。
- [ ] 配置本地环境变量和日志。

### M1：旅游内容平台

- [ ] 导入北京、上海、成都景点数据。
- [ ] 完成首页、城市详情和景点详情。
- [ ] 完成热门城市和热门景点排行。
- [ ] 完成后台景点数据管理。

### M2：Agent 对话闭环

- [ ] 完成会话和消息接口。
- [ ] 完成 SSE 事件推送和断线恢复。
- [ ] 完成意图识别和槽位提取。
- [ ] 完成澄清问题和需求确认卡。
- [ ] 完成工具白名单和错误处理。

### M3：行程规划

- [ ] 完成景点硬条件过滤。
- [ ] 完成景点推荐评分。
- [ ] 完成每日景点顺序规划。
- [ ] 完成开放时间、交通时间和预算校验。
- [ ] 完成行程结果展示。

### M4：行程管理和优化

- [ ] 完成保存、修改和删除行程。
- [ ] 支持自然语言修改行程。
- [ ] 增加地图路线展示。
- [ ] 增加用户反馈和规划失败记录。

### M5：部署和测试

- [ ] 部署到宝塔服务器。
- [ ] 配置 Nginx、HTTPS 和 SSE。
- [ ] 配置数据库备份和计划任务。
- [ ] 完成接口、算法、Agent 和端到端测试。
- [ ] 完成答辩演示数据和操作脚本。

---

## 19. 测试与验收

### 19.1 功能验收

- [ ] 用户可以浏览 3 个城市。
- [ ] 用户可以查看指定季度的城市和景点排行。
- [ ] 用户输入模糊需求时，Agent 会继续询问，而不是直接编造行程。
- [ ] 用户确认需求后，系统生成 2～5 天游。
- [ ] 行程中的景点均属于目标城市。
- [ ] 行程不包含已知闭馆时间。
- [ ] 每日时间不重叠，交通时间有来源。
- [ ] 修改“轻松一点”“减少美食”等要求后，行程发生可解释变化。
- [ ] 用户可以保存并重新打开行程。

### 19.2 Agent 验收

- [ ] Agent 只能调用白名单工具。
- [ ] 工具失败时显示真实错误或降级说明。
- [ ] 大模型输出 JSON 失败时最多重试一次。
- [ ] 不存在的城市或景点不会被写入行程。
- [ ] 没有满足约束的方案时返回 `NO_FEASIBLE_PLAN`。
- [ ] 刷新页面后可以恢复已落库的消息和事件。
- [ ] SSE 重连不会重复显示事件。
- [ ] `/stop` 可以停止当前未完成的 Agent 回合。

### 19.3 论文实验

至少准备以下对比：

1. 规则槽位提取与大模型槽位提取的准确率比较。
2. 纯大模型直接生成行程与“推荐评分 + 路线规划 + 大模型解释”的对比。
3. 不同热度权重对热门排行的影响。
4. 使用路线优化前后的总距离、总耗时和约束满足率。
5. 统计推荐理由与景点真实字段的一致性。

建议指标：

```text
slot_precision / slot_recall / slot_f1
constraint_satisfaction_rate
average_route_distance
average_route_duration
budget_error
expert_itinerary_score
recommendation_reason_grounded_rate
average_response_time
```

---

## 20. 实现规范

- 所有 API 使用 `/api/v1` 前缀。
- 请求和响应使用 Pydantic schema，禁止直接返回 ORM 对象。
- 所有数据库迁移使用 Alembic，禁止手动修改生产表结构后不记录迁移。
- 所有时间使用 UTC 存储，显示层转换为北京时间。
- 所有排序、规划和约束计算必须有单元测试。
- 业务错误使用统一 `AppError`，禁止把 Python 堆栈返回前端。
- 日志只记录请求 ID、用户 ID 摘要、耗时和错误类型，不记录密钥和完整隐私内容。
- 数据源、更新时间和算法版本必须随结果返回或可在详情页查看。
- 前端不自行计算热度、预算和路线，展示值以服务端结果为准。
- 没有完成的功能显示“未启用”，禁止使用假成功数据冒充完成。

本项目的最终交付物包括：源代码、数据库初始化脚本、景点数据集、接口文档、部署说明、测试报告、实验结果和用户操作说明。
