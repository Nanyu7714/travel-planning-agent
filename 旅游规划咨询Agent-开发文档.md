# 多城市个性化旅游规划平台 — Agent 开发文档

| 项 | 内容 |
| :--- | :--- |
| 文档名称 | 多城市个性化旅游规划平台 Agent 开发文档 |
| 文档版本 | V1.3 |
| 适用范围 | 本文档规定 MVP 的产品边界、数据模型、Agent 运行时、接口、前端和部署实现 |
| 目标形态 | 面向浏览器访问的网站 |
| 运行环境 | 宝塔面板、Alibaba Cloud Linux 3、2 核 2 GB 内存 |
| 最近修订 | 2026-08-31：补充用户账号、管理员后台和模块化架构 |
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
| 行程调整 | 支持修改天数、预算、偏好、每日时间、景点顺序，增加、删除、替换景点，查看历史版本并恢复 |
| 行程管理 | 登录用户可以保存、查看和删除自己的行程 |
| 用户功能 | 用户主页维护资料、偏好和排除地点，收藏城市/景点/行程，查看最近浏览，管理登录设备，生成可撤销的只读行程分享链接并提交评分评论 |
| 后台管理 | 查看城市、景点、用户、会话和反馈模块；城市、景点、标签和排行的完整 CRUD 仍在后续实现 |

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

### 2.4 目的地识别与支持边界

- Agent 不得根据热门排行擅自决定用户的目的地。
- 用户明确提供目的地时，以用户目的地为准，并先查询城市支持状态。
- 用户没有提供目的地时，Agent 必须先询问，或展示热门城市供用户主动选择。
- 完整规划只对 `support_level=full` 且 `planning_enabled=true` 的城市开放。
- 已知但暂不支持的城市可以展示基础信息，但不能伪装成完整行程规划。
- 无法识别或存在歧义的目的地必须继续澄清，例如“古城”需要确认具体城市。
- 省份、区域或多城市目的地在 MVP 中需要转换为单一城市，无法转换时明确提示暂不支持。

目的地支持分支：

```text
用户输入目的地
    ↓
名称归一化和别名匹配
    ↓
查询城市支持级别
    ├── full     进入完整行程规划
    ├── basic    提供城市/景点基础信息，不生成完整行程
    ├── disabled 提示暂未开放，并推荐已支持城市
    └── unknown 询问用户确认目的地
```

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
- Agent 消息处理和行程生成由独立的轻量规划 Worker 执行，HTTP 接口持久化消息并创建任务后返回 `202` 和 `job_id`，不得在请求中等待模型或完整规划结果。
- FastAPI 和规划 Worker 通过 PostgreSQL 中的 `planning_jobs`、`chat_messages`、`agent_events` 协作，不引入额外消息队列。
- 单个外部 API 调用超时不超过 30 秒；任务总超时默认 120 秒，超时后写入失败状态并推送错误事件。
- 本项目不部署 Redis、Kafka、Elasticsearch 或独立向量数据库。
- 2 GB 内存服务器只启动一个 Uvicorn worker 和一个规划 Worker；规划 Worker 同时只处理一个任务。
- 复杂的排行榜计算通过宝塔计划任务执行，不阻塞用户请求。

### 3.2 模块化架构与依赖规则

本项目采用模块化单体，不拆分微服务。代码按业务边界划分，遵循高内聚、低耦合：同一业务的路由、数据结构、服务和仓储放在同一模块；模块之间只能通过公开的 Service、DTO 或事件协作，不能直接访问对方的内部 ORM 对象和私有函数。

模块职责：

| 模块 | 负责内容 |
| :--- | :--- |
| `auth` | 注册、登录、邮箱验证、Token、密码和登录会话 |
| `users` | 用户资料、收藏、最近浏览和用户偏好 |
| `catalog` | 城市、景点、开放时间、图片和数据来源 |
| `rankings` | 行为聚合、热度计算和季度排行 |
| `agent` | 意图识别、槽位提取、澄清和工具编排 |
| `planning` | 候选评分、路线排序、预算和约束校验 |
| `itineraries` | 行程、版本、保存、分享和反馈 |
| `imports` | 城市、景点和统计数据的导入校验 |
| `admin` | 管理员权限校验和后台接口编排，不复制业务逻辑 |

依赖方向固定为：

```text
Router → Service → Repository → PostgreSQL
              ↓
       Integration Adapter

Agent → 白名单 Tool → 业务 Service
Admin Router → 权限校验 → 原有业务 Service
```

Router 不直接写 SQL，Agent 不直接访问数据库，管理员模块不重新实现城市、景点或行程逻辑。公共代码只放配置、异常、日志、鉴权和数据库基础能力；禁止建立包含所有业务的巨大 `CommonService`，禁止循环导入。每个模块至少有单元测试，模块之间通过集成测试验证 DTO 和接口契约。

---

## 4. 技术栈

### 4.1 前端

- Vue 3
- TypeScript
- Vite
- Element Plus
- ECharts
- 高德地图 JavaScript API（使用受域名白名单限制的前端 JS Key）
- 浏览器原生 `EventSource`

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
- SMTP 或事务邮件服务适配器
- OR-Tools

### 4.3 部署

- Alibaba Cloud Linux 3
- 宝塔 Nginx
- 宝塔 PostgreSQL 管理器
- 宝塔 Python 项目管理器
- 宝塔计划任务
- Let's Encrypt HTTPS

大模型密钥、高德 Web Service Key、数据库密码和 JWT 密钥只能保存在后端环境变量中，不能写入前端代码或提交到 Git。高德 JavaScript API 的前端 Key 属于浏览器公开配置，必须单独申请、限制允许域名和调用能力，不能与后端 Web Service Key 混用。

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
| 我的行程 | `/me/itineraries` | 保存的行程、修订版本和历史记录 |
| 我的收藏 | `/me/favorites` | 收藏的城市和景点 |
| 最近浏览 | `/me/recent-views` | 最近查看的城市和景点 |
| 个人资料 | `/me/settings/profile` | 查看不可修改的公开用户 ID 和基础资料，注销账号 |
| 账号安全 | `/me/settings/security` | 修改邮箱、密码，管理登录设备和注销账号 |
| 公开分享 | `/share/itineraries/:token` | 通过随机令牌只读查看已分享行程 |
| 登录注册 | `/login`、`/register` | 用户名、邮箱或 4 位公开用户 ID 登录 |
| 验证邮箱 | `/verify-email` | 使用一次性令牌激活邮箱 |
| 找回密码 | `/forgot-password`、`/reset-password` | 申请并完成密码重置 |

#### 5.1.1 访问权限

| 身份 | 允许操作 |
| :--- | :--- |
| 游客 | 浏览首页、城市、景点、排行和有效的公开分享页面 |
| 未验证邮箱用户 | 登录、退出、查看验证提示、重新发送验证邮件 |
| 已验证普通用户 | 使用 Agent、保存行程、收藏、查看历史记录和管理自己的账号 |
| 管理员 | 在普通用户权限基础上访问后台；管理员账号不能通过公开注册获得 |

MVP 不实现匿名 Agent 会话迁移。游客进入 `/planner`、收藏或“我的行程”时跳转登录页，并记录安全的站内 `redirect`；登录完成后返回原页面。`redirect` 只能是本站相对路径，禁止接受完整外部 URL，防止开放重定向。

#### 5.1.2 注册流程

```text
填写邮箱、昵称、密码、确认密码并同意隐私规则
    ↓
前后端校验字段，服务端规范化邮箱
    ↓
创建未验证账号，发送一次性验证邮件
    ↓
用户点击 24 小时内有效的验证链接
    ↓
邮箱验证成功，进入登录页
```

- 当前 MVP 使用唯一用户名和唯一邮箱注册，并为每个正常账号分配唯一的 4 位公开用户 ID。4 位纯数字不能作为用户名，避免和公开用户 ID 混淆。
- 密码长度为 10～128 个字符，允许密码管理器生成的长密码和粘贴操作；不强制特殊字符组合，但拒绝常见弱密码和与邮箱高度相似的密码。
- “确认密码”只在浏览器中校验，不作为接口字段保存或写入日志。
- 注册接口无论邮箱是否已存在，都返回不泄露账号状态的通用提示；已存在账号可以收到安全提醒邮件，但接口不能帮助攻击者枚举用户。
- 验证邮件 60 秒内不能重复发送，每个邮箱和 IP 每小时限制次数。验证令牌只保存哈希，24 小时过期且只能使用一次。

#### 5.1.3 登录与退出流程

登录接收用户名、邮箱或 4 位公开用户 ID，并统一与密码校验。失败时显示“账号或密码错误”，不能分别提示账号存在或密码错误。连续失败按账号和 IP 双维度限流：建议 15 分钟内失败 5 次后暂停登录 15 分钟；成功登录后清除失败计数。重复失败时可以增加验证码，但验证码不是替代限流的安全措施。

登录成功后：

1. 创建新的 `auth_session`，防止会话固定攻击。
2. 设置 15 分钟有效的 Access Token Cookie 和 7 天有效的 Refresh Token Cookie。
3. 生成 CSRF Token，前端只保存在内存或专用非 HttpOnly Cookie，不存入 `localStorage`。
4. 更新最后登录时间和设备摘要，然后跳转到安全校验后的站内 `redirect`。

退出分为两种：

- “退出当前设备”：撤销当前 `auth_session`，清除认证 Cookie 和前端用户状态。
- “退出全部设备”：撤销该用户所有 `auth_sessions`，适用于账号疑似泄露或修改密码后主动操作。

退出接口必须保持幂等。即使 Token 已过期，也应清除 Cookie 并返回成功；退出后使用浏览器后退不能重新看到需要登录的私人数据。

#### 5.1.4 找回密码与账号变更

- 找回密码接口始终返回相同提示。密码重置令牌只保存哈希，15 分钟过期且只能使用一次。
- 重置密码后撤销全部登录会话，并发送安全提醒邮件；新密码不能与当前密码相同。
- 修改密码需要当前密码，成功后撤销其他设备会话，当前设备重新签发 Token。
- 修改邮箱需要当前密码，并向新邮箱发送验证链接；验证完成前继续使用旧邮箱登录。
- 账号注销需要再次输入密码并进行明确确认。服务端立即撤销所有会话和分享链接，随后按数据保留规则删除私人数据、匿名化实验聚合数据。

### 5.2 管理员页面

| 页面 | 路径 | 功能 |
| :--- | :--- | :--- |
| 平台概览 | `/admin` | 统计内容数量、规划任务、数据新鲜度和服务状态 |
| 城市管理 | `/admin/cities` | 城市增删改查、城市封面和季节标签 |
| 景点管理 | `/admin/attractions` | 景点信息、开放时间、门票和位置 |
| 排行管理 | `/admin/rankings` | 导入统计数据、生成季度排行、查看数据时间 |
| 数据导入 | `/admin/imports` | 上传、校验和确认 CSV/JSON 数据 |
| 规划任务 | `/admin/planning-jobs` | 查看规划任务状态、失败原因和安全重试 |
| 用户反馈 | `/admin/feedback` | 查看规划失败和用户评分 |
| 操作日志 | `/admin/audit-logs` | 查看管理员导入、修改、删除和任务操作记录 |
| 用户管理 | `/admin/users` | 查看脱敏账号、禁用账号和撤销登录会话 |

后台模块设计：

- 平台概览只显示真实统计、数据更新时间和服务状态；没有真实用户行为时显示“初始化实验数据”。
- 城市和景点使用停用代替物理删除，避免破坏已有行程和排行快照。景点编辑必须支持常规开放时间、特殊日期、图片来源和许可证。
- 数据导入采用“上传 → 校验 → 预览 → 管理员确认 → 事务导入”流程。字段错误、重复记录和外键错误必须显示行号，导入失败时整体回滚。
- 排行采用“生成草稿 → 查看分项分数 → 发布 → 保留旧版本”的流程，已有成功快照时默认不允许覆盖。
- 规划任务只显示状态、阶段耗时、错误码和请求摘要；管理员只能对可重试错误发起一次重试，不能直接修改用户行程。
- 用户管理只显示脱敏邮箱、验证状态、注册时间和最近登录时间。管理员不能查看密码、Token 或默认读取完整私人对话。
- 普通管理员不能修改自己的管理员角色，也不能删除审计日志。公开注册接口永远只能创建普通用户。

---

## 6. 数据模型

### 6.0 用户与登录会话 `users`、`auth_sessions`

`users` 保存账号、密码哈希和角色，不保存明文密码；`auth_sessions` 保存 Refresh Token 哈希、过期时间和撤销时间，支持退出登录和 Token 轮换。数据库自增主键 `users.id` 是账号和所有私有数据的唯一归属依据；`public_id` 只是面向用户展示和登录的 4 位编号，不能作为外键、权限判断依据或 Token 的用户标识。

```json
{
  "users": {
    "id": "integer, auto increment",
    "public_id": "4 digit string | null",
    "username": "string",
    "email": "string",
    "display_name": "string",
    "password_hash": "string",
    "role": "user | admin",
    "status": "pending_verification | active | locked | disabled | deleted",
    "email_verified_at": "datetime | null",
    "password_changed_at": "datetime",
    "failed_login_count": 0,
    "locked_until": "datetime | null",
    "last_login_at": "datetime | null",
    "created_at": "datetime",
    "updated_at": "datetime",
    "deleted_at": "datetime | null"
  },
  "auth_sessions": {
    "id": "uuid",
    "user_id": "integer",
    "token_family_id": "uuid",
    "refresh_token_hash": "string",
    "csrf_token_hash": "string",
    "device_name": "Chrome on Windows",
    "ip_prefix": "string | null",
    "last_used_at": "datetime",
    "created_at": "datetime",
    "expires_at": "datetime",
    "revoked_at": "datetime | null",
    "revoked_reason": "logout | password_changed | token_reuse | admin | null"
  }
}
```

公开用户 ID 的生命周期规则：

- 正常账号必须持有一个 `0000`～`9999` 范围内的唯一公开 ID，个人资料页只读展示，不允许用户修改。
- 分配时由服务端随机选择起点并检查唯一索引；并发注册发生冲突时重新分配。系统最多同时分配 10,000 个公开 ID，达到上限时停止注册并返回明确错误。
- 用户注销账号时撤销该内部用户主键下的全部认证会话，清除认证 Cookie，将账号标记为不可登录，并把 `public_id` 置空以释放编号。
- 释放后的编号允许分配给新账号，但新账号拥有不同的内部自增主键，因此不能读取原账号的会话、消息、行程或其他私人数据。Access Token 的 `sub` 和 Refresh Token 会话始终绑定内部主键。
- 注销后原业务数据按后台数据保留策略继续保存，后续永久清理或匿名化只能按内部主键执行，不能按可能复用的公开 ID 执行。

邮箱在写入前去除首尾空格并按小写规范化，数据库对规范化邮箱建立唯一索引。首个管理员账号通过一次性部署脚本创建，普通注册接口永远只能创建 `user` 角色；角色变更只能由已有管理员执行并写入审计日志。

邮箱验证、重置密码和修改邮箱使用统一的 `auth_action_tokens`：

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "purpose": "verify_email | reset_password | change_email",
  "token_hash": "string",
  "target_email": "string | null",
  "expires_at": "datetime",
  "used_at": "datetime | null",
  "created_at": "datetime"
}
```

明文操作令牌只出现在发送给用户的邮件链接中，数据库只保存哈希。创建新令牌时使同一用户、同一用途的旧令牌失效。认证安全事件另外记录登录成功/失败、退出、全部设备退出、密码重置、邮箱修改和 Token 重用，只保存必要的时间、结果、设备摘要和 IP 网段，不保存密码、Cookie 或完整令牌。

### 6.1 城市 `cities`

```json
{
  "id": "uuid",
  "slug": "chengdu",
  "name": "成都",
  "description": "string",
  "aliases": ["成都市", "蓉城"],
  "support_level": "full | basic | disabled",
  "planning_enabled": true,
  "best_seasons": ["spring", "autumn"],
  "recommended_days_min": 2,
  "recommended_days_max": 5,
  "budget_level": "medium",
  "cover_image_url": "string",
  "cover_image_source": "string",
  "cover_image_author": "string | null",
  "cover_image_license": "string | null",
  "cover_attribution_url": "string | null",
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
  "opening_hours_summary": "周一至周日 09:00-22:00",
  "visit_duration_min": 120,
  "ticket_price": 0,
  "rating": 4.6,
  "review_count": 10000,
  "season_tags": ["spring", "summer", "autumn"],
  "suitable_for": ["young", "family"],
  "image_url": "string",
  "image_source": "string",
  "image_author": "string | null",
  "image_license": "string | null",
  "attribution_url": "string | null",
  "source": "string",
  "verified_at": "datetime",
  "updated_at": "datetime"
}
```

景点开放时间不得只保存在一个字符串中。`opening_intervals` 保存常规星期时段，允许同一天存在多个区间；`opening_exceptions` 保存节假日、临时闭馆和特殊开放时间。

```json
{
  "opening_intervals": {
    "attraction_id": "uuid",
    "weekday": 1,
    "open_time": "09:00",
    "close_time": "17:00"
  },
  "opening_exceptions": {
    "attraction_id": "uuid",
    "date": "2026-10-01",
    "is_closed": false,
    "open_time": "08:00",
    "close_time": "18:00",
    "source": "景点官网",
    "verified_at": "datetime"
  }
}
```

规划时优先使用特殊日期记录，再使用常规星期时段。没有可验证开放时间时只能标记“开放时间待确认”，不得把未知状态当作正常开放。

### 6.3 季度排行 `ranking_snapshots`

```json
{
  "id": "uuid",
  "period": "2026Q3",
  "ranking_type": "city | attraction",
  "city_id": "uuid | null",
  "attraction_id": "uuid | null",
  "rank": 1,
  "hot_score": 87.5,
  "score_breakdown": {
    "search": 21.0,
    "view": 18.5,
    "favorite": 16.0,
    "add_to_itinerary": 12.0,
    "review": 14.0,
    "season": 18.0
  },
  "data_source": "seed | system_event | imported",
  "updated_at": "datetime"
}
```

`city_id` 和 `attraction_id` 必须且只能填写一个，并与 `ranking_type` 一致。数据库使用 `CHECK` 约束保证二选一，应用层在写入前校验目标存在；删除目标资源时先归档对应快照，不允许留下悬空排行记录。

### 6.3.1 用户行为事件 `user_behavior_events`

排行计算使用原始事件或明确标注的导入数据，不能直接修改最终热度分数冒充系统统计。

```json
{
  "id": "uuid",
  "anonymous_id": "uuid | null",
  "user_id": "uuid | null",
  "event_type": "search | view | favorite | add_to_itinerary",
  "city_id": "uuid | null",
  "attraction_id": "uuid | null",
  "session_id": "uuid | null",
  "occurred_at": "datetime",
  "request_id": "uuid"
}
```

- 同一页面的短时间重复浏览按会话去重，管理员和自动化健康检查不计入排行。
- 每日任务将事件聚合到 `ranking_daily_metrics`，季度任务只读取聚合数据生成快照。
- MVP 不开放用户评论，因此没有可靠评论数据时，将 `review_score` 权重按比例分配给其余指标，不得使用虚构评论数。
- 导入评分时必须保存数据来源、授权情况、导入批次和统计日期。

行为事件同样使用 `CHECK` 约束保证 `city_id` 和 `attraction_id` 恰好填写一个。客户端不能直接指定 `user_id`；服务端从登录会话读取用户身份，并对同一 `request_id` 建立唯一约束以避免网络重试重复计数。

每日聚合表 `ranking_daily_metrics`：

```json
{
  "id": "uuid",
  "metric_date": "date",
  "city_id": "uuid | null",
  "attraction_id": "uuid | null",
  "search_count": 120,
  "view_count": 850,
  "favorite_count": 40,
  "add_to_itinerary_count": 18,
  "data_source": "system_event | imported",
  "import_batch_id": "uuid | null",
  "calculated_at": "datetime"
}
```

聚合表对 `(metric_date, city_id)` 或 `(metric_date, attraction_id)` 唯一。季度排行从聚合表按自然季度汇总；导入数据不得与系统事件重复叠加，同一导入批次重跑时必须使用 upsert 保持幂等。

### 6.3.2 收藏与最近浏览 `favorites`、`recent_views`

```json
{
  "favorites": {
    "id": "uuid",
    "user_id": "uuid",
    "city_id": "uuid | null",
    "attraction_id": "uuid | null",
    "created_at": "datetime"
  },
  "recent_views": {
    "id": "uuid",
    "user_id": "uuid",
    "city_id": "uuid | null",
    "attraction_id": "uuid | null",
    "last_viewed_at": "datetime",
    "view_count": 1
  }
}
```

两张表都要求城市和景点恰好填写一个。收藏对 `(user_id, city_id)` 或 `(user_id, attraction_id)` 唯一；重复收藏保持幂等。最近浏览按用户和目标 upsert，只更新 `last_viewed_at` 和 `view_count`，默认仅保留最近 100 个目标。匿名浏览只进入脱敏行为统计，不出现在“最近浏览”页面。

### 6.3.3 反馈、导入和审计 `itinerary_feedback`、`data_import_batches`、`ranking_generation_jobs`、`admin_audit_logs`

```json
{
  "itinerary_feedback": {
    "id": "uuid",
    "itinerary_id": "uuid",
    "user_id": "uuid",
    "rating": 4,
    "tags": ["节奏合适", "路线清晰"],
    "comment": "string | null",
    "created_at": "datetime"
  },
  "data_import_batches": {
    "id": "uuid",
    "data_type": "city | attraction | behavior_metric",
    "file_name": "string",
    "file_sha256": "string",
    "source": "string",
    "license_note": "string | null",
    "status": "validating | ready | importing | imported | failed | cancelled",
    "row_count": 100,
    "error_summary": "string | null",
    "created_by": "uuid",
    "confirmed_at": "datetime | null",
    "created_at": "datetime"
  },
  "ranking_generation_jobs": {
    "id": "uuid",
    "period": "2026Q3",
    "ranking_type": "city | attraction",
    "status": "queued | running | succeeded | failed | cancelled",
    "idempotency_key": "uuid",
    "created_by": "uuid",
    "error_summary": "string | null",
    "created_at": "datetime",
    "finished_at": "datetime | null"
  },
  "admin_audit_logs": {
    "id": "uuid",
    "admin_user_id": "uuid",
    "action": "create | update | delete | import | generate_ranking | role_change",
    "resource_type": "string",
    "resource_id": "uuid | null",
    "request_id": "uuid",
    "summary": {},
    "created_at": "datetime"
  }
}
```

反馈对 `(itinerary_id, user_id)` 唯一，允许用户更新自己的反馈。导入批次只能按 `validating -> ready -> importing -> imported | failed` 转换，管理员可以在 `ready` 前取消；同一文件哈希、数据类型和来源的成功批次不得重复导入。排行任务对 `(period, ranking_type, idempotency_key)` 唯一。审计日志只保存字段名和必要摘要，不保存密码、Token、完整导入文件或完整对话内容；普通管理员无权删除审计日志。

### 6.4 用户需求 `travel_requests`

```json
{
  "session_id": "uuid",
  "origin_text": "杭州 | null",
  "destination_city_id": "uuid | null",
  "candidate_city_ids": [],
  "selected_city_id": "uuid | null",
  "start_date": "date | null",
  "days": 4,
  "traveler_count": 2,
  "budget_total": 3000,
  "interests": ["美食", "历史文化"],
  "pace": "relaxed | balanced | intensive",
  "transport": "public_transport | car | mixed",
  "must_visit": ["string"],
  "avoid": ["string"],
  "budget_scope": "tickets_local_transport_meals",
  "slots_filled": ["destination_city_id", "days"],
  "slots_pending": ["budget_total"],
  "status": "collecting | comparing | awaiting_selection | confirming | queued | planning | completed | failed | cancelled"
}
```

`origin_text` 用于多个候选城市比较。MVP 不接入机票和火车票实时价格；交通便利度只使用已配置的城市间静态数据或地图 API 可以可靠返回的数据。数据缺失时页面显示“交通项未计算”，并对其余评分项重新归一化，不得由大模型猜测时间或价格。

城市间静态数据保存在 `city_access_estimates`，至少包含 `origin_text`、`destination_city_id`、`transport_mode`、`duration_min`、`cost_min`、`cost_max`、`source` 和 `verified_at`。只有来源明确且仍在有效期内的数据可以参加城市比较。

```json
{
  "id": "uuid",
  "origin_normalized": "hangzhou",
  "origin_display_name": "杭州",
  "destination_city_id": "uuid",
  "transport_mode": "rail | flight | road",
  "duration_min": 180,
  "cost_min": "120.00",
  "cost_max": "380.00",
  "currency": "CNY",
  "source": "string",
  "verified_at": "datetime",
  "expires_at": "datetime"
}
```

同一出发地、目的城市和交通方式只保留一条当前有效记录。`origin_text` 只保存到用户需求，比较时先归一化为 `origin_normalized`；无法归一化时不创建静态估算记录。

### 6.5 行程组与版本 `itinerary_revision_groups`、`itineraries`

`itinerary_revision_groups` 表示用户看到的一条逻辑行程，`itineraries` 保存不可变的内容版本：

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "session_id": "uuid",
  "current_itinerary_id": "uuid | null",
  "status": "active | deleted",
  "created_at": "datetime",
  "updated_at": "datetime",
  "deleted_at": "datetime | null"
}
```

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "session_id": "uuid",
  "revision_group_id": "uuid",
  "parent_itinerary_id": "uuid | null",
  "version_no": 1,
  "lock_version": 1,
  "is_current": true,
  "city_id": "uuid",
  "title": "成都 4 天游",
  "days": 4,
  "total_budget": 2800,
  "budget_breakdown": {
    "tickets": 500,
    "local_transport": 300,
    "meals_estimate": 800,
    "other": 0
  },
  "budget_scope": "tickets_local_transport_meals",
  "pace": "relaxed",
  "status": "draft | saved | archived",
  "algorithm_version": "route-v1",
  "generated_at": "datetime",
  "updated_at": "datetime"
}
```

同一次行程的所有修订共享 `revision_group_id`。首次生成版本的 `parent_itinerary_id=null`、`version_no=1`；重新规划成功后创建新行，指向上一版本，并在同一事务中更新组的 `current_itinerary_id`、把旧版本的 `is_current` 改为 `false`。列表默认只返回活动组的当前版本，详情接口允许显式查询历史版本。`lock_version` 每次原地修改状态或标题时加一，用于防止多标签页覆盖。

### 6.5.1 行程日期 `itinerary_days`

```json
{
  "id": "uuid",
  "itinerary_id": "uuid",
  "day_number": 1,
  "date": "date | null",
  "title": "城市文化体验",
  "estimated_cost": 320,
  "total_visit_min": 360,
  "total_travel_min": 90
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
  "cost_breakdown": {
    "ticket": 0,
    "local_transport": 5,
    "meal_estimate": 0
  },
  "reason": "符合历史文化偏好，且与下一景点距离较近"
}
```

MVP 的行程预算只包含景点门票、市内交通和餐饮额度估算，不包含酒店、往返机票、火车票和购物。餐饮规划只推荐数据库中已核验的美食街区、市场或美食类景点，不承诺具体餐厅的实时营业状态、排队情况和价格。页面必须展示预算范围，不能把上述估算称为旅行总价。

预算单价保存在 `cost_assumptions`，至少包含 `city_id`、`cost_type`、`unit`、`amount`、`source`、`effective_from` 和 `updated_at`。例如餐饮使用“每人每天”额度，市内交通使用“每段”或按路线类型配置的估算；单价缺失时该费用必须标记为“未计入”。

```json
{
  "id": "uuid",
  "city_id": "uuid",
  "cost_type": "meal | local_transport",
  "unit": "person_day | segment | person_segment",
  "amount": "50.00",
  "currency": "CNY",
  "source": "string",
  "effective_from": "date",
  "effective_to": "date | null",
  "updated_at": "datetime"
}
```

MVP 所有金额使用人民币 CNY，数据库使用 `NUMERIC(12,2)`，接口以十进制字符串返回，禁止使用二进制浮点累计金额。预算计算规则：门票按 `单价 × 需购票人数`；餐饮按 `每人每日额度 × 人数 × 天数`；市内交通按路线段的计价单位累加。儿童、老人、免票和团体优惠没有可靠数据时按普通成人价格估算并明确标注。`total_budget` 只汇总状态为“已计入”的分项，缺失分项单独返回 `not_included`，不能以 0 元替代未知费用。

### 6.6.1 行程分享 `itinerary_shares`

```json
{
  "id": "uuid",
  "itinerary_id": "uuid",
  "created_by": "uuid",
  "token_hash": "string",
  "expires_at": "datetime | null",
  "revoked_at": "datetime | null",
  "created_at": "datetime"
}
```

分享令牌至少包含 128 bit 随机性，数据库只保存令牌哈希。创建分享时只能选择当前的 `saved` 版本，链接随后固定指向该版本；后续重新规划不会悄悄改变已分享内容。公开响应不返回用户 ID、会话、私人备注或其他历史版本；用户可以撤销链接，删除行程或账号时所有分享立即失效。公开页面设置 `noindex`，并对令牌查询限流。

### 6.7 会话与事件

`chat_sessions` 保存会话状态，`chat_messages` 保存用户消息和最终交付文本，`agent_events` 保存阶段、工具、确认、结果和错误事件。进度事件不能混入模型上下文。

```json
{
  "chat_sessions": {
    "id": "uuid",
    "user_id": "uuid",
    "title": "string",
    "status": "active | archived | deleted",
    "last_event_id": 123,
    "created_at": "datetime",
    "updated_at": "datetime"
  },
  "chat_messages": {
    "id": "uuid",
    "session_id": "uuid",
    "role": "user | assistant",
    "content": "string",
    "turn_id": "uuid",
    "idempotency_key": "uuid | null",
    "created_at": "datetime"
  },
  "agent_events": {
    "id": "uuid",
    "session_id": "uuid",
    "event_id": 123,
    "turn_id": "uuid",
    "event_type": "stage | tool_call | tool_result | clarify | plan_confirm | job | itinerary | message | error | reset | done",
    "payload": {},
    "created_at": "datetime"
  }
}
```

`event_id` 在每个会话内严格单调递增，由更新 `chat_sessions.last_event_id` 的同一事务分配；事件对 `(session_id, event_id)` 唯一。用户消息对 `(session_id, idempotency_key)` 唯一。工具事件的 `payload` 必须移除密钥、Cookie、完整上游响应和不必要的个人信息后再落库。

`planning_jobs` 保存耗时规划任务，并作为单机 Worker 的持久化任务队列：

```json
{
  "id": "uuid",
  "session_id": "uuid",
  "user_id": "uuid",
  "turn_id": "uuid",
  "job_type": "message | plan | replan",
  "idempotency_key": "uuid",
  "retry_of_job_id": "uuid | null",
  "status": "queued | running | succeeded | failed | cancelled",
  "progress_stage": "retrieving | planning | checking",
  "request_payload": {},
  "result_itinerary_id": "uuid | null",
  "cancel_requested": false,
  "attempt_count": 0,
  "error_code": "string | null",
  "created_at": "datetime",
  "started_at": "datetime | null",
  "finished_at": "datetime | null"
}
```

- Worker 每 1～2 秒轮询一次，使用 `SELECT ... FOR UPDATE SKIP LOCKED` 在事务中领取一个 `queued` 任务，避免重复执行；空队列时不得高频空转。
- 用户重试必须携带幂等键；相同用户、会话和幂等键不得创建重复任务。
- `/stop` 将 `cancel_requested=true`；Worker 在每个规划阶段和外部调用后检查取消状态。
- Worker 重启时，将超过任务总超时的 `running` 任务标记为失败；未超时任务可以重新入队一次。
- 任务、事件和草稿行程均先落库再推送 SSE，确保页面刷新后可以恢复。

同一会话通过部分唯一索引限制最多一个 `queued` 或 `running` 任务。所有状态转换必须使用条件更新，合法转换如下：

```text
queued  -> running | cancelled
running -> succeeded | failed | cancelled
```

终态不能重新进入 `running`。重试会创建带新 `id` 的任务并记录 `retry_of_job_id`，但相同幂等键始终返回原任务。普通消息也作为 `job_type=message` 入队，保证意图识别和澄清过程在进程重启后可以恢复；确认后创建 `plan`，行程调整创建 `replan`。

所有表使用 UUID 主键和 UTC 时间。前端展示时转换为北京时间。

数据库实现必须补充主外键、唯一约束和索引：`cities.slug` 唯一；排行快照分别对 `(period, city_id)`、`(period, attraction_id)` 唯一；事件按 `(session_id, event_id)` 唯一；行程修订对 `(revision_group_id, version_no)` 唯一且每组最多一个 `is_current=true`，组的 `current_itinerary_id` 必须指向同组版本；常用查询字段 `city_id`、`user_id`、`session_id`、`period`、`status` 建立索引。删除用户资源时明确采用级联删除或软删除，不能遗留无主会话和行程。

### 6.8 行程规划数据来源

系统主要通过四类数据为用户规划行程：

| 数据类型 | 主要内容 | 来源 | 主要用途 |
| :--- | :--- | :--- | :--- |
| 景点基础数据 | 名称、简介、标签、位置、开放时间、门票、游玩时长、适合人群 | 文旅部门公开信息、景点官网、经过人工核验的公开资料 | 景点筛选、推荐和事实校验 |
| 用户需求数据 | 目的地、日期、天数、人数、预算、兴趣、节奏、交通方式、排除条件 | 用户与 Agent 的多轮对话、收藏和行程修改 | 生成个性化规划条件 |
| 热门排行数据 | 搜索量、浏览量、收藏量、加入行程次数、评分、增长趋势、季节匹配度 | 平台行为统计、导入数据或明确标注的初始化实验数据 | 城市和景点热度排序 |
| 地图路线数据 | 经纬度、景点间距离、步行/公交/驾车时间 | 高德地图地理编码和路径规划 API | 行程顺序、交通时间和路线约束 |

数据处理流程：

```text
公开资料 / API / 用户行为
    ↓
清洗、归一化和人工核验
    ↓
保存到 PostgreSQL
    ↓
景点过滤与推荐评分
    ↓
路线规划和约束校验
    ↓
大模型生成行程说明
```

大模型不是景点事实数据源。它只能理解用户输入，并根据数据库和 API 返回的结构化结果生成说明。景点名称、价格、开放时间、距离和交通耗时必须来自已保存或已调用的数据。

MVP 使用固定景点数据集保证结果可复现；实时地图路线作为辅助数据。天气数据属于 P1 扩展功能，天气接口失败时不阻塞基础行程规划。

所有数据必须记录 `source` 和 `updated_at`。没有真实用户行为数据时，排行可以使用初始化实验数据，但页面和论文中必须明确标注数据性质，不得伪装成真实平台排行。

### 6.9 图片资源与版权

图片分为真实景点图片和 AI 生成图片两类：

| 类型 | 使用场景 | 规则 |
| :--- | :--- | :--- |
| 真实景点图片 | 城市详情、景点详情、景点卡片、行程景点 | 使用景点官网、文旅部门、明确授权图片库、自有图片或允许展示的 API 数据 |
| AI 生成图片 | 首页季节横幅、专题封面、空状态和装饰性内容 | 不得冒充真实景点，不得用于证明景点外观或真实环境 |

禁止直接复制百度图片、Google 图片、旅游网站或社交平台图片。使用 Wikimedia Commons、Unsplash 等来源时，必须检查单张图片的许可证和署名要求，并保存作者、许可证和原始链接。

景点图片必须保存以下信息：

```json
{
  "image_url": "https://...",
  "image_source": "Wikimedia Commons",
  "image_author": "author name",
  "image_license": "CC BY-SA 4.0",
  "attribution_url": "https://..."
}
```

MVP 可以使用合法的远程图片 URL。图片数量增加后，使用阿里云 OSS 保存获得授权的图片，服务器只保存图片元数据，不保存未经确认版权的图片。图片展示区域需要显示来源或署名入口。

前端必须处理图片加载失败、空地址和链接失效状态，显示统一占位图，不得使用破裂图片。图片地址和外部链接需要进行格式校验。

AI 图片属于管理员离线制作的静态素材，不是 MVP 网站运行时功能。生成后由管理员审核、记录生成工具和日期，再作为普通素材上传；因此运行时不增加图片生成 API、计费、排队或内容审核服务。

---

## 7. 热门排行设计

### 7.1 评分公式

季度排行由宝塔计划任务计算。所有指标先按同一周期归一化，再计算热度：

```text
hot_score =
  0.20 * search_score
  + 0.15 * view_score
  + 0.20 * favorite_score
  + 0.20 * add_to_itinerary_score
  + 0.10 * review_score
  + 0.15 * season_score
```

每个分项先在同一排行类型、同一周期内进行 0～100 的归一化。某个分项没有可靠数据时，不将其记为 0，而是移除该分项并按原比例重新归一化剩余权重。对于已有历史数据，可以加入增长率；没有真实行为数据时只能使用导入数据或明确标记的模拟数据。

### 7.2 排行规则

- 同一 `period` 和 `ranking_type` 下，按 `hot_score` 降序排列。
- 分数相同时按最近增长率，再按评分排序。
- 城市榜和景点榜分开计算。
- 景点榜只能展示当前已启用城市的景点。
- 前端显示分数构成，避免只展示一个无法解释的总分。

### 7.3 计划任务

```text
每天：更新系统浏览、搜索、收藏和加入行程统计
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
compare_destinations 比较两个或三个候选城市
modify_plan       修改已有行程
save_itinerary    保存行程
chat              普通旅游咨询
unsupported       不支持的请求
```

#### 8.3.1 目的地识别与支持分支

目的地识别必须先于行程规划。Agent 按以下顺序处理：

1. 从用户原文提取目的地名称。
2. 使用 `cities.aliases` 将“成都市”“蓉城”等别名归一化为城市记录。
3. 对无法唯一匹配的名称发起澄清，不选择猜测结果。
4. 查询 `support_level` 和 `planning_enabled`。
5. 只有完整支持的城市才进入景点筛选、路线规划和行程生成。

示例：

```text
用户：我想去西安玩四天
系统：识别目的地为西安，但当前没有完整规划数据。当前支持北京、上海和成都的完整行程规划；你可以改选已支持城市，或先查看西安的基础信息。
```

如果用户没有给出目的地：

```text
用户：我想出去玩几天
系统：你更想去哪个城市？目前可以完整规划北京、上海和成都的行程。
```

热门城市和景点排行只能作为发现入口。用户点击某个城市或在对话中明确说出城市后，才将该城市写入 `destination_city_id`。

#### 8.3.2 多候选城市决策

当用户同时提出两个或三个候选城市，但只能选择一个时，Agent 使用 `compare_destinations` 意图，不直接进入单城市行程规划。

候选城市必须能够唯一识别，并且具备可比较的基础数据。只有 `support_level=full` 且 `planning_enabled=true` 的城市可以在选择后继续生成详细行程；其他城市只展示支持状态，不与完整支持城市混合计算综合分。

处理流程：

```text
识别候选城市
    ↓
收集出发地、日期、天数、预算、人数和兴趣等共同条件
    ↓
过滤预算、时间、季节、交通和数据完整性等硬条件
    ↓
计算每个城市的综合匹配分
    ↓
展示城市对比和推荐理由
    ↓
等待用户确认一个城市
    ↓
进入该城市的详细行程规划
```

候选城市保存在 `candidate_city_ids`，用户确认后写入 `selected_city_id`，随后同步写入 `destination_city_id`。热门度只能作为参考，不能代替用户选择。

默认城市评分：

```text
city_score =
  0.35 * interest_match
  + 0.20 * season_match
  + 0.20 * budget_match
  + 0.15 * transport_convenience
  + 0.10 * data_confidence
```

城市对比卡必须展示匹配度、预算、交通、适合原因和主要取舍，并提供“选择此城市并规划”操作。

用户选择城市前，不得生成最终行程；用户拒绝推荐时，应保留候选城市和原始条件，支持重新设置条件或直接选择其他城市。

评分字段缺失时必须在对比卡中标明。`transport_convenience` 仅在存在可追溯交通数据时参与评分；无法计算的分项从公式中移除，并对剩余权重重新归一化。候选城市中只要有一个城市的数据不足以公平比较，系统应提示比较限制，允许用户直接选择，不能给出伪精确的百分比。

### 8.4 必要槽位

规划行程至少需要：

```text
destination_city
days
interests 或 trip_style
pace
```

多候选城市比较还必须收集 `candidate_city_ids`，并优先收集 `origin_text`。预算、日期、人数和交通方式缺失时，Agent 应优先询问；如果用户明确表示“不考虑预算”或“日期未定”，可以使用默认值并在确认卡中标明。

默认值：

```text
days = 3
traveler_count = 1
pace = balanced
transport = public_transport
budget_total = null
```

上述值是确认卡中的建议值，不是静默默认值。`days`、`pace` 等必要槽位缺失时，Agent 必须询问或明确展示建议值，只有用户确认后才能进入规划。日期未定时 `itinerary_days.date=null`，系统不能声称已完成星期和节假日校验；只可使用每天开放规则一致的景点，其他景点标记“出行日期确定后需再次核验”。

### 8.5 确认卡

信息满足规划条件后，Agent 先发送确认卡，不立即生成完整行程：

```json
{
  "type": "plan_confirm",
  "destination": "成都",
  "origin": "杭州",
  "days": 4,
  "budget_total": 3000,
  "budget_scope": "门票、市内交通和餐饮估算",
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
| `city.compare` | 使用相同条件比较两个或三个候选城市 |
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

当 `start_date=null` 时，开放时间约束状态为 `unknown` 而不是 `passed`。用户后续补充日期后必须重新运行开放时间和特殊日期校验；若新日期产生闭馆冲突，创建新行程版本并保留原版本。

目标函数：

```text
route_score =
  attraction_preference_score
  - 0.30 * normalized_travel_time
  - 0.15 * repeated_area_penalty
  - 0.10 * overload_penalty
```

MVP 使用“候选筛选 + 分区聚类 + 最近邻排序”的可解释方案。P1 再引入 OR-Tools 的时间窗口约束进行对照实验。算法失败时使用按区域和评分排序的降级方案，并在结果中记录 `algorithm_version`。

预算约束只针对 `budget_scope=tickets_local_transport_meals` 的估算范围。餐饮额度按人数和天数计算，市内交通按路线类型和已配置单价估算；任何缺失单价必须显示为“未计入”，不能默认为零。酒店、往返大交通和购物不参与该约束。

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
Cookie: access_token=<HttpOnly Cookie，由浏览器自动携带>
Last-Event-ID: <浏览器断线重连时自动携带>
```

生产环境由 Nginx 将页面和 `/api/` 暴露在同一 HTTPS 域名下。登录成功后后端设置 `HttpOnly`、`Secure`、`SameSite=Lax` Cookie，原生 `EventSource` 依靠同源 Cookie 鉴权，不在 URL 中传递 Access Token。服务端校验当前用户是否拥有该会话。

前端断线后由浏览器携带 `Last-Event-ID` 重连，服务端补发更大的事件 ID。关闭浏览器不等于取消规划任务；只有显式调用 `/stop` 才请求取消。

### 10.2 事件公共结构

```json
{
  "event_id": 123,
  "session_id": "uuid",
  "turn_id": "uuid",
  "type": "stage",
  "created_at": "2026-08-31T10:00:00Z",
  "payload": {}
}
```

服务端必须按标准 SSE 帧输出，而不是直接写裸 JSON：

```text
retry: 3000

id: 123
event: stage
data: {"event_id":123,"session_id":"uuid","turn_id":"uuid","type":"stage","created_at":"2026-08-31T10:00:00Z","payload":{"name":"extract","message":"正在整理旅行需求"}}

```

每个事件以两个换行结束，`id:` 必须等于 JSON 中的 `event_id`，这样浏览器重连时才会自动发送 `Last-Event-ID`。连接空闲时服务端每 15 秒发送一次注释心跳 `: heartbeat`，心跳不落库、不增加事件 ID。`retry` 建议为 3000 毫秒，前端同时采用上限 30 秒的指数退避。

会话事件默认保留 180 天。若客户端提交的 `Last-Event-ID` 早于最早保留事件，服务端建立连接后发送不落库的 `reset` 事件并关闭连接；原生 `EventSource` 的错误回调无法可靠读取 HTTP 状态，因此不能只返回 HTTP 409。前端收到 `reset` 后重新获取消息、当前需求、活动任务和当前行程快照，再建立新的 SSE 连接。

### 10.3 服务端事件

| type | payload | 用途 |
| :--- | :--- | :--- |
| `stage` | `{ "name": "extract", "message": "正在整理旅行需求" }` | 阶段状态 |
| `tool_call` | `{ "name": "attraction.search", "arguments": {} }` | 工具开始 |
| `tool_result` | `{ "name": "attraction.search", "ok": true, "data": {} }` | 工具结果 |
| `clarify` | `{ "message": "更偏好美食还是历史景点？" }` | 补充问题 |
| `plan_confirm` | 需求确认卡 JSON | 等待用户确认 |
| `job` | `{ "job_id": "uuid", "status": "queued" }` | 规划任务已创建 |
| `itinerary` | `{ "itinerary_id": "uuid" }` | 行程已生成 |
| `message` | `{ "content": "string" }` | 普通回复或解释 |
| `error` | `{ "code": "TIMEOUT", "message": "路线规划超时" }` | 错误 |
| `reset` | `{ "code": "EVENT_GONE", "message": "历史事件已过期，请重新同步" }` | 游标过期后要求前端重载快照 |
| `done` | `{}` | 本回合结束 |

不新增 `thought`、`token`、`assistant` 等内部推理事件。阶段状态只展示简短摘要，不暴露模型隐藏思维链。

### 10.4 前端提交动作

普通消息：

```http
POST /api/v1/sessions/{session_id}/messages
Content-Type: application/json
X-CSRF-Token: <csrf_token>
Idempotency-Key: <uuid>

{
  "content": "我想去成都玩四天，喜欢美食和休闲，不想安排太满"
}
```

消息保存成功返回 `202 Accepted`，同一个幂等键重复提交时返回原任务：

```json
{
  "message_id": "uuid",
  "turn_id": "uuid",
  "job_id": "uuid",
  "status": "queued"
}
```

确认行程：

```http
POST /api/v1/sessions/{session_id}/plan-confirm
Content-Type: application/json
X-CSRF-Token: <csrf_token>
Idempotency-Key: <uuid>

{
  "confirmed": true,
  "patch": {
    "destination_city_id": 3,
    "days": 4,
    "traveler_count": 2,
    "budget_total": 3000,
    "interests": ["美食", "摄影"],
    "avoid_places": ["过度拥挤"],
    "pace": "relaxed",
    "transport": "public_transport"
  }
}
```

右侧需求清单由 Agent 根据对话填写，用户可以在确认前修改上述字段。服务端必须重新校验城市支持状态和字段范围，不接受前端直接提供的目的地名称作为可信数据。规划完成事件返回准确的 `itinerary_id`，前端在当前窗口打开对应行程详情，不能用列表第一条或上一次行程代替。

固定数据不足以满足每天两个不同景点时，规则规划不得重复或编造景点。系统将现有符合条件的景点均匀分配到各天，把负荷校验标记为 `partial` 并明确保留自由时段；完全没有符合排除条件的景点时才终止规划并要求用户修改条件。

确认成功返回 `202 Accepted`：

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

停止当前回合：

```http
POST /api/v1/sessions/{session_id}/stop
X-CSRF-Token: <csrf_token>
```

`/stop` 取消该会话当前唯一的 `queued` 或 `running` 任务；没有活动任务时保持幂等并返回 `{ "status": "idle", "job_id": null }`。已有任务时返回其 `job_id` 和最终或待取消状态。已经成功生成的草稿不会因随后调用 `/stop` 而被删除。

规划成功后 Worker 先创建 `draft` 行程，再写入 `itinerary` 事件，因此事件中的 `itinerary_id` 一定可以通过详情接口读取。用户点击“保存行程”时只将该草稿状态更新为 `saved`，不得再次创建重复记录。未保存草稿保留 7 天后由计划任务清理；删除和清理前仍需校验用户所有权。

---

## 11. REST API

所有业务接口使用 `/api/v1` 前缀，并按照 RESTful 风格设计。FastAPI Router 只负责 HTTP 层和权限校验，业务逻辑放入 `services`，数据库对象通过 Pydantic schema 转换后再返回。

### 11.1 RESTful 设计原则

- 使用复数名词表示资源：`cities`、`attractions`、`rankings`、`itineraries`。
- 使用 HTTP 方法表达操作：`GET` 查询、`POST` 创建、`PATCH` 局部修改、`DELETE` 删除。
- 不使用 `/getCityList`、`/generateTrip`、`/deleteTrip` 这类动词式资源路径。
- 查询条件使用 Query 参数，例如 `?period=2026Q3&type=city`。
- 资源 ID 使用路径参数，例如 `/cities/{city_id}`。
- 列表接口统一支持 `page`、`page_size`，默认 `page_size=20`，最大不超过 100。
- 分页响应统一返回 `items`、`total`、`page` 和 `page_size`，前端不得根据当前页数量猜测总数。
- 创建成功返回 `201`，异步或耗时操作返回 `202`，删除成功返回 `204`。
- 所有响应字段使用稳定的 JSON 结构，禁止同一字段在不同接口中改变类型。
- 城市、景点、排行和有效分享链接允许匿名读取；会话、任务、行程、收藏、最近浏览和账号接口必须校验资源所有权；后台接口必须校验管理员角色。
- 不直接返回 SQLAlchemy ORM 对象，必须使用 `response_model`。

标准错误结构：

```json
{
  "error": {
    "code": "NOT_FOUND",
    "message": "景点不存在",
    "request_id": "uuid"
  }
}
```

标准状态码：

```text
200  查询或修改成功
201  创建成功
202  请求已接受，任务处理中
204  删除成功，无响应内容
400  请求格式错误
401  未登录或令牌无效
403  无资源权限
404  资源不存在
409  资源状态冲突
422  参数校验失败
429  请求过于频繁
500  服务内部错误
```

FastAPI Router 示例：

```python
from fastapi import APIRouter, Query
from app.schemas.city import CityOut, CityPage

router = APIRouter(prefix="/api/v1/cities", tags=["cities"])


@router.get("", response_model=CityPage)
async def list_cities(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return await city_service.list(
        keyword=keyword,
        page=page,
        page_size=page_size,
    )


@router.get("/{city_id}", response_model=CityOut)
async def get_city(city_id: str):
    return await city_service.get(city_id)
```

`CityPage` 的响应示例：

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "page_size": 20
}
```

Agent 的用户消息仍通过 REST 提交，服务端生成阶段通过 SSE 推送。SSE 是实时事件通道，不替代城市、景点、排行和行程等资源接口。

### 11.2 认证

```text
POST /api/v1/auth/register
POST /api/v1/auth/verify-email
POST /api/v1/auth/resend-verification
POST /api/v1/auth/login
POST /api/v1/auth/refresh
POST /api/v1/auth/logout
POST /api/v1/auth/logout-all
POST /api/v1/auth/forgot-password
POST /api/v1/auth/reset-password
GET  /api/v1/auth/csrf
GET  /api/v1/auth/me
PATCH /api/v1/auth/me
POST /api/v1/auth/change-password
POST /api/v1/auth/change-email
GET  /api/v1/auth/sessions
DELETE /api/v1/auth/sessions/{auth_session_id}
DELETE /api/v1/auth/me
```

`GET /api/v1/auth/me` 返回只读 `public_id`。`DELETE /api/v1/auth/me` 必须再次验证当前密码、校验 CSRF、撤销该用户全部 Token 会话、释放公开 ID 并清除浏览器认证 Cookie；接口不得删除或改绑原内部用户主键下的数据。

密码统一使用 Argon2id 哈希，并在目标服务器上校准参数，使单次验证约为 100～300ms 且不会造成 2 GB 服务器内存压力。已有哈希参数低于当前标准时，在用户下次成功登录后自动重新哈希。密码、重置令牌和 Refresh Token 永远不以明文入库。

Access Token 使用 15 分钟有效的签名 JWT，Refresh Token 使用 7 天有效的高熵随机值并在数据库保存哈希。分别放入 `__Host-access_token` 和 `__Host-refresh_token` Cookie，Cookie 必须设置 `HttpOnly`、`Secure`、`SameSite=Lax`、`Path=/` 且不设置 `Domain`。前端只通过 `/auth/me` 获取用户状态，不读取 Token，也不把 Token 放入 URL、`localStorage` 或 `sessionStorage`。

每次刷新都轮换 Refresh Token，并保持 `token_family_id`。已经轮换的旧 Token 再次出现时视为可能泄露，立即撤销该 Token 家族、清除 Cookie 并记录安全事件。退出登录撤销当前会话；退出全部设备、重置密码和注销账号撤销全部会话。

CSRF 使用双提交 Cookie：登录或刷新成功时设置可被前端读取的 `csrf_token` Cookie，并把同一随机值绑定到当前 `auth_session`。该 Cookie 设置 `Secure`、`SameSite=Lax`、`Path=/`，不设置 `HttpOnly` 和 `Domain`；前端在所有需要登录的 `POST`、`PUT`、`PATCH`、`DELETE` 请求中发送 `X-CSRF-Token`，服务端使用常量时间比较 Cookie、请求头和会话绑定值。`GET /auth/csrf` 用于页面刷新后补取或轮换 Token。注册、登录、验证邮箱、重发验证邮件、找回和重置密码属于未登录公开动作，不要求会话 CSRF，但必须严格校验 `Origin` 并按账号和 IP 限流。退出、改密、删除账号后立即轮换或清除 CSRF Token。

注册、重新发送验证邮件和找回密码接口成功时统一返回 `202 Accepted`，响应文案不说明邮箱是否存在。邮件链接中的一次性令牌由前端读取后立即使用 `history.replaceState` 清除地址栏参数，再通过 POST 请求提交；验证页设置 `Referrer-Policy: no-referrer`，避免令牌随 Referer 泄露。

`GET /auth/sessions` 返回设备名称、首次登录时间、最近活动时间和粗粒度 IP 地区，不返回 Token 或完整 IP。用户不能撤销当前会话时应改用 `/auth/logout`；撤销其他设备会话后，该设备下次请求返回 `401`。

### 11.3 会话

```text
GET  /api/v1/sessions
POST /api/v1/sessions
GET  /api/v1/sessions/{session_id}/messages
GET  /api/v1/sessions/{session_id}/events
POST /api/v1/sessions/{session_id}/messages
POST /api/v1/sessions/{session_id}/plan-confirm
POST /api/v1/sessions/{session_id}/stop
DELETE /api/v1/sessions/{session_id}
GET  /api/v1/planning-jobs/{job_id}
```

任务查询接口只作为 SSE 不可用时的降级方式，返回任务状态、当前阶段、错误码和 `result_itinerary_id`，不返回内部提示词或模型思维过程。

### 11.4 城市、景点和排行

```text
GET /api/v1/cities
GET /api/v1/cities/{city_id}
GET /api/v1/cities/{city_id}/attractions
GET /api/v1/attractions/{attraction_id}
GET /api/v1/rankings?period=2026Q3&type=city
GET /api/v1/rankings?period=2026Q3&type=attraction&city_id=uuid
```

排行接口没有指定历史周期时，默认返回最近一个已生成周期，不得返回实时拼接的假数据。

### 11.5 行程

```text
GET    /api/v1/itineraries
GET    /api/v1/itineraries/{itinerary_id}
PATCH  /api/v1/itineraries/{itinerary_id}
PUT    /api/v1/itineraries/{itinerary_id}
DELETE /api/v1/itineraries/{itinerary_id}
POST   /api/v1/itineraries/{itinerary_id}/replan
GET    /api/v1/itineraries/{itinerary_id}/feedback
PUT    /api/v1/itineraries/{itinerary_id}/feedback
GET    /api/v1/itineraries/{itinerary_id}/revisions
POST   /api/v1/itineraries/{itinerary_id}/revisions/{version_no}/restore
POST   /api/v1/itineraries/{itinerary_id}/shares
DELETE /api/v1/itineraries/{itinerary_id}/shares/{share_id}
GET    /api/v1/shares/{share_token}
```

用户端当前的 `PUT` 编辑接口使用 `expected_version` 做并发版本检查；编辑前自动保存快照，恢复历史版本会再创建一条恢复前快照。自然语言调整接口目前只解析明确的天数、预算、删除和替换景点指令，复杂规划仍需真实 LLM 和路线校验服务。

Agent 生成成功时已经创建 `draft` 行程。保存操作使用 `PATCH /api/v1/itineraries/{itinerary_id}` 将 `status` 从 `draft` 更新为 `saved`；重复提交相同状态应保持幂等。所有原地修改携带 `If-Match: "<lock_version>"`，版本不匹配返回 `409 VERSION_CONFLICT` 和当前版本，不允许静默覆盖。

行程调整统一使用 `replan`，请求必须声明基准版本和操作列表：

```http
POST /api/v1/itineraries/{itinerary_id}/replan
X-CSRF-Token: <csrf_token>
Idempotency-Key: <uuid>
Content-Type: application/json

{
  "base_lock_version": 3,
  "requirement_patch": {
    "pace": "relaxed",
    "budget_total": "3000.00"
  },
  "operations": [
    { "op": "add", "attraction_id": "uuid", "day_number": 2 },
    { "op": "remove", "stop_id": "uuid" },
    { "op": "replace", "stop_id": "uuid", "attraction_id": "uuid" },
    { "op": "reorder", "day_number": 1, "stop_ids": ["uuid", "uuid"] }
  ]
}
```

服务端先校验所有 stop、景点、天数和所有权，再创建 `job_type=replan` 任务并返回 `202`。成功时创建新的行程版本并原子切换 `is_current`；失败或取消时旧版本保持当前版本。拖动排序只提交完整 `stop_ids` 顺序，列表必须与该日当前 stop 集合完全一致。

`restore` 只接受同一行程组内的历史 `saved` 版本，并要求当前版本的 `If-Match` 和幂等键。恢复不会把旧记录重新标记为当前，而是复制为新的 `saved` 版本并增加 `version_no`，保留完整修订链。`DELETE /itineraries/{id}` 删除整个逻辑行程组：软删除所有版本、撤销分享并停止活动任务，不能只删除一个历史版本。7 天草稿清理时，如果组内存在已保存版本，则回退到最新已保存版本；从未保存过的组才整体清理。

“加入行程”有两条明确路径：没有现有行程时跳转规划页并把景点写入 `must_visit`；从某个现有行程操作时使用上述 `add` 操作重新规划。不得直接向时间线插入未经开放时间和路线校验的 stop。

创建分享成功返回 `share_id`、只出现一次的完整 `share_url` 和 `expires_at`；再次读取分享列表只返回令牌尾部摘要，不返回原始令牌。默认有效期 30 天，用户可以选择更短期限或手动撤销。为草稿或历史版本创建分享返回 `409 CONFLICT`。

### 11.6 用户功能

```text
GET    /api/v1/auth/profile
PATCH  /api/v1/auth/profile
GET    /api/v1/auth/sessions
DELETE /api/v1/auth/sessions/{auth_session_id}
POST   /api/v1/auth/logout-all
POST   /api/v1/auth/change-password
PATCH  /api/v1/auth/me/email
GET    /api/v1/favorites
PUT    /api/v1/favorites/{type}/{target_id}
DELETE /api/v1/favorites/{type}/{target_id}
GET    /api/v1/recent-views
POST   /api/v1/recent-views
DELETE /api/v1/recent-views
```

收藏写入和删除均保持幂等。城市和景点详情页使用登录用户的最近浏览记录；用户可以一键清空，单条历史不提供永久保存承诺。当前邮箱接口只完成密码保护下的直接更新，邮箱验证和找回密码待邮件服务接入后实现。

### 11.7 后台管理

```text
GET    /api/v1/admin/overview
GET    /api/v1/admin/cities
POST   /api/v1/admin/cities
GET    /api/v1/admin/cities/{city_id}
PATCH  /api/v1/admin/cities/{city_id}
DELETE /api/v1/admin/cities/{city_id}
GET    /api/v1/admin/attractions
POST   /api/v1/admin/attractions
GET    /api/v1/admin/attractions/{attraction_id}
PATCH  /api/v1/admin/attractions/{attraction_id}
DELETE /api/v1/admin/attractions/{attraction_id}
POST   /api/v1/admin/import-batches
GET    /api/v1/admin/import-batches
GET    /api/v1/admin/import-batches/{batch_id}
POST   /api/v1/admin/import-batches/{batch_id}/confirm
POST   /api/v1/admin/ranking-jobs
GET    /api/v1/admin/ranking-jobs/{job_id}
POST   /api/v1/admin/ranking-jobs/{job_id}/publish
GET    /api/v1/admin/planning-jobs
POST   /api/v1/admin/planning-jobs/{job_id}/retry
GET    /api/v1/admin/feedback
GET    /api/v1/admin/failures
GET    /api/v1/admin/audit-logs
GET    /api/v1/admin/users
PATCH  /api/v1/admin/users/{user_id}/status
POST   /api/v1/admin/users/{user_id}/revoke-sessions
PATCH  /api/v1/admin/users/{user_id}/role
```

后台列表全部分页。导入接口先创建 `validating` 批次，完成格式、重复项、外键、来源和许可证检查后才允许管理员确认导入；排行生成按周期和类型使用幂等键，已有成功快照时默认拒绝覆盖。所有写操作记录操作者、请求 ID、目标资源和字段级摘要。

### 11.8 统一错误码

```text
UNAUTHORIZED       未登录或令牌无效
FORBIDDEN          无资源权限
VALIDATION         请求参数或槽位不合法
NOT_FOUND          城市、景点或行程不存在
CONFLICT           当前会话状态冲突
VERSION_CONFLICT   行程已被其他页面或任务更新
EVENT_GONE         SSE 请求的历史事件已超过保留期
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

多候选城市必须使用单独结构，不能把第一个候选城市误写为 `destination_city`：

```json
{
  "intent": "compare_destinations",
  "slots": {
    "origin_text": "杭州",
    "candidate_cities": ["成都", "上海"],
    "days": 4,
    "budget_total": "3000.00",
    "interests": ["美食", "休闲"],
    "pace": "relaxed",
    "transport": "public_transport"
  },
  "missing_required": [],
  "next_action": "compare"
}
```

模型只提取用户原文中的城市名称，后端负责别名归一化并转换为 `candidate_city_ids`。比较完成后的 `next_action` 只能是 `clarify | compare | await_selection | confirm`；选择城市必须来自用户点击或明确文本，不允许模型自行把最高分城市写入 `selected_city_id`。

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

地图服务使用两套隔离配置：前端 JavaScript API Key 只负责底图和标记点展示，并限制生产域名；后端 Web Service Key 只负责地理编码和路线服务，不返回前端。两个 Key 不能复用。

后端保存必要的距离、耗时、查询时间和数据来源，优先读取缓存，避免重复消耗配额。路线请求失败且无有效缓存时，行程必须标记交通数据缺失，不能由直线距离伪装成真实通勤时间。

```text
route_cache:
  origin_attraction_id
  destination_attraction_id
  transport
  distance_m
  duration_min
  source
  queried_at
  expires_at
```

前端构建变量仅允许包含受域名限制的 `VITE_AMAP_JS_KEY`；后端使用 `AMAP_WEB_SERVICE_KEY`。前端 Key 会被浏览器看到，因此安全依赖域名白名单、配额限制和监控，不能把它当作后端秘密。

### 13.3 天气 API

天气作为 P1 功能。天气请求失败不应阻塞固定景点规划，前端显示“天气信息暂不可用”。

### 13.4 事务邮件

邮箱验证、重置密码、修改邮箱和安全提醒通过统一邮件适配器发送。生产环境使用经过域名验证的 SMTP 或事务邮件服务，配置 SPF、DKIM 和 DMARC；开发环境使用本地邮件捕获服务，不向真实用户发送。

- 发送超时不超过 10 秒，最多自动重试 2 次；接口仍返回防枚举的通用响应，服务器记录不含邮箱全文和令牌的失败类型。
- 邮件模板只使用服务端固定模板和受控变量，链接必须以 `APP_BASE_URL` 开头，禁止把用户输入拼接为任意 URL。
- 原始验证或重置令牌只存在于当前发送调用和邮件链接中，不写日志、不进入分析事件；发送失败后用户可以重新申请，新申请会使旧令牌失效。
- 邮件服务不可用时不影响游客浏览、登录已有已验证账号和查看已保存行程；注册验证、找回密码和修改邮箱显示“邮件暂未送达，可稍后重试”。

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
queued         已进入规划队列
planning       正在安排路线
checking       正在检查行程
waiting_confirm 等待确认
completed      行程已生成
cancelled      已取消
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
- Cookie 鉴权接口启用 CSRF 防护，登录、刷新和修改密码配置频率限制。
- Access Token 短期有效，Refresh Token 每次刷新后轮换；退出和改密后撤销旧 Token。
- 所有输入限制长度，用户消息建议不超过 4000 字符。
- Markdown 输出必须进行 XSS 清洗。
- 图片地址、外部链接和地图参数进行白名单或格式校验。
- API Key 只从环境变量读取。
- PostgreSQL 只允许本机或内网访问，不开放公网 `5432`。
- Nginx 只开放 `80`、`443`，SSH 端口限制来源 IP。
- 数据库每日备份到独立位置，不只保存在当前服务器。
- 未保存草稿默认保留 7 天，Agent 会话和消息默认保留 180 天；用户可以主动删除自己的会话、行程和账户。
- 删除账户时，认证信息和私人内容删除；用于论文统计的数据只能保留不可逆匿名化聚合结果。
- 日志保留 30 天并轮转，不记录 Cookie、Token、完整对话、密码或外部 API Key。

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

服务器应配置约 2 GB Swap 作为突发内存保护，但 Swap 不能替代内存扩容。若持续发生 Swap 占用或 OOM，应减少进程并发、排查内存使用或升级服务器配置。

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

规划 Worker 作为第二个 Python 项目或受管进程启动：

```text
工作目录：/www/wwwroot/travel-api
启动命令：python -m app.workers.planning
进程数：1
并发任务数：1
异常退出：自动重启
```

Web 服务和 Worker 使用同一份应用代码与环境变量，但运行日志分开保存。部署新版本时先停止 Worker 领取新任务，等待当前任务结束或安全取消，再执行数据库迁移和重启服务。

### 16.4 Nginx 网站配置

```nginx
location / {
    try_files $uri $uri/ /index.html;
}

location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location ~ ^/api/v1/sessions/[0-9a-fA-F-]+/events$ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
    add_header X-Accel-Buffering no;
}
```

SSE 路由必须放在通用 `/api/` 路由之前或确保 Nginx 正确匹配。域名配置完成后使用宝塔申请 HTTPS 证书，并将 HTTP 重定向到 HTTPS。前端、REST 和 SSE 使用同一域名，避免 Cookie 和 CORS 配置分裂。

### 16.5 环境变量与数据库

```env
DATABASE_URL=postgresql+psycopg://travel_user:密码@127.0.0.1:5432/travel_platform
LLM_API_KEY=服务端密钥
AMAP_WEB_SERVICE_KEY=后端地图服务密钥
JWT_SECRET=随机长字符串
CSRF_SECRET=随机长字符串
APP_BASE_URL=https://travel.example.com
MAIL_PROVIDER=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=465
SMTP_USERNAME=服务账号
SMTP_PASSWORD=服务密钥
MAIL_FROM=no-reply@example.com
```

`.env` 文件不提交到 Git。生产环境数据库使用独立用户，不使用 PostgreSQL 超级用户连接应用。

SQLAlchemy 连接池在 2 GB 服务器上从小配置开始，例如 `pool_size=5`、`max_overflow=2`、`pool_pre_ping=true`；数据库连接和慢查询必须设置超时，不能让异常请求长期占用全部连接。

宝塔计划任务每天执行 PostgreSQL 逻辑备份并复制到独立位置，每月至少执行一次恢复演练。应用提供 `/api/v1/health/live` 和 `/api/v1/health/ready`，部署后检查 Web、数据库、Worker 和 SSE；日志按天轮转并限制总保留天数。

---

## 17. 目录结构

```text
travel-platform/
├── frontend/
│   ├── src/
│   │   ├── core/
│   │   ├── layouts/
│   │   ├── features/
│   │   │   ├── auth/
│   │   │   ├── catalog/
│   │   │   ├── rankings/
│   │   │   ├── planner/
│   │   │   ├── itineraries/
│   │   │   ├── account/
│   │   │   └── admin/
│   │   ├── components/common/
│   │   └── styles/
│   └── package.json
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── core/
│   │   │   ├── errors.py
│   │   │   ├── logging.py
│   │   │   └── security.py
│   │   ├── db/
│   │   ├── modules/
│   │   │   ├── auth/
│   │   │   ├── users/
│   │   │   ├── catalog/
│   │   │   ├── rankings/
│   │   │   ├── agent/
│   │   │   ├── planning/
│   │   │   ├── itineraries/
│   │   │   ├── imports/
│   │   │   └── admin/
│   │   ├── integrations/
│   │   │   ├── llm.py
│   │   │   ├── amap.py
│   │   │   ├── weather.py
│   │   │   └── email.py
│   │   ├── workers/
│   │   │   └── planning.py
│   ├── migrations/
│   ├── scripts/
│   │   ├── build_rankings.py
│   │   ├── cleanup_drafts.py
│   │   └── import_seed_data.py
│   ├── tests/
│   └── requirements.txt
├── data/
│   ├── cities.json
│   └── attractions.json
└── README.md
```

每个业务模块内部保持一致的 `router.py`、`schemas.py`、`service.py`、`repository.py` 和 `models.py` 结构，简单模块可以合并文件但不能跨模块随意引用。Agent 只能通过 `modules/agent/tools.py` 暴露的白名单工具访问业务服务，不能在提示词中直接拼接 SQL 或调用任意 HTTP 地址。

---

## 18. 开发里程碑

### M0：工程骨架

- [ ] 创建前后端项目。
- [ ] 建立按业务划分的模块目录和依赖规则。
- [ ] 配置 PostgreSQL 和 Alembic。
- [ ] 完成用户、城市、景点、会话、任务和审计基础表及约束。
- [ ] 完成 Cookie 鉴权、CSRF、退出和 Token 刷新。
- [ ] 完成邮箱验证、密码重置和事务邮件适配器。
- [ ] 配置本地环境变量和日志。

### M1：旅游内容平台

- [ ] 导入北京、上海、成都景点数据。
- [ ] 完成首页、城市详情和景点详情。
- [ ] 完成热门城市和热门景点排行。
- [ ] 完成行为事件、每日聚合和排行快照任务。
- [ ] 完成收藏、最近浏览和账号设置。
- [ ] 完成后台城市、景点、导入批次、排行和反馈管理。

### M2：Agent 对话闭环

- [ ] 完成会话和消息接口。
- [ ] 完成 SSE 事件推送和断线恢复。
- [ ] 完成 `planning_jobs`、规划 Worker、幂等重试和任务取消。
- [ ] 完成意图识别和槽位提取。
- [ ] 完成澄清问题和需求确认卡。
- [ ] 完成工具白名单和错误处理。

### M3：行程规划

- [ ] 完成景点硬条件过滤。
- [ ] 完成景点推荐评分。
- [ ] 完成每日景点顺序规划。
- [ ] 完成开放时间、交通时间和预算校验。
- [ ] 完成多候选城市比较和用户选择闭环。
- [ ] 完成行程结果展示。

### M4：行程管理和优化

- [ ] 完成保存、修改和删除行程。
- [ ] 完成行程修订链、并发版本校验和历史版本读取。
- [ ] 支持自然语言修改行程。
- [ ] 完成只读分享链接的创建、读取和撤销。
- [ ] 增加地图路线展示。
- [ ] 增加用户反馈和规划失败记录。

### M5：部署和测试

- [ ] 部署到宝塔服务器。
- [ ] 配置 Nginx、HTTPS 和 SSE。
- [ ] 配置数据库备份和计划任务。
- [ ] 完成备份恢复演练、健康检查和日志轮转。
- [ ] 完成接口、算法、Agent 和端到端测试。
- [ ] 完成答辩演示数据和操作脚本。

---

## 19. 测试与验收

### 19.1 功能验收

- [ ] 用户可以浏览 3 个城市。
- [ ] 用户可以查看指定季度的城市和景点排行。
- [ ] 排行明确展示统计周期、数据来源以及真实或初始化实验数据标识。
- [ ] 用户输入模糊需求时，Agent 会继续询问，而不是直接编造行程。
- [ ] 用户输入两个或三个候选城市时，可以在相同条件下比较并自主选择一个城市。
- [ ] 不支持或有歧义的城市不会被系统自动替换为热门城市。
- [ ] 用户确认需求后，系统生成 2～5 天游。
- [ ] 行程中的景点均属于目标城市。
- [ ] 行程不包含已知闭馆时间。
- [ ] 每日时间不重叠，交通时间有来源。
- [ ] 修改“轻松一点”“减少美食”等要求后，行程发生可解释变化。
- [ ] 用户可以保存并重新打开行程。
- [ ] 用户可以收藏和取消收藏城市或景点，并查看、清空最近浏览。
- [ ] 用户可以创建和撤销只读分享链接，匿名访问看不到用户私有信息。
- [ ] 行程调整失败或取消时旧版本保持可用，成功后可以查看历史版本。
- [ ] 两个页面同时编辑同一行程时，旧 `lock_version` 返回 `VERSION_CONFLICT`。
- [ ] 管理员可以完成城市和景点 CRUD、数据导入、排行生成、反馈查看和审计查询；普通用户访问后台接口返回 403。
- [ ] 邮箱验证、重发验证、找回密码和修改邮箱在邮件成功、超时、令牌过期和重复使用场景下行为一致且不泄露账号状态。
- [ ] 页面明确说明预算只覆盖门票、市内交通和餐饮估算。

### 19.2 Agent 验收

- [ ] Agent 只能调用白名单工具。
- [ ] 工具失败时显示真实错误或降级说明。
- [ ] 大模型输出 JSON 失败时最多重试一次。
- [ ] 不存在的城市或景点不会被写入行程。
- [ ] 没有满足约束的方案时返回 `NO_FEASIBLE_PLAN`。
- [ ] 刷新页面后可以恢复已落库的消息和事件。
- [ ] SSE 重连不会重复显示事件。
- [ ] SSE 响应包含标准 `id`、`event`、`data` 帧和心跳，过期事件游标发送 `reset/EVENT_GONE` 并恢复快照。
- [ ] `/stop` 可以停止当前未完成的 Agent 回合。
- [ ] 重复确认和网络重试不会生成重复任务或重复行程。
- [ ] Worker 重启后，超时任务会失败，允许恢复的任务最多重新执行一次。
- [ ] 缺失、错误或已轮换的 CSRF Token 无法执行写操作；同源正常请求可以完成登录、刷新和退出。
- [ ] 删除账号后 Refresh Token、会话、私人行程和分享链接失效，只保留不可逆匿名聚合数据。

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

实验数据与标注规范：

1. 准备不少于 180 条用户表达，覆盖全部意图、目的地别名、槽位缺失、否定条件和多候选城市；其中 30 条用于开发调试，至少 150 条作为最终固定测试集。
2. 准备不少于 60 个行程场景，北京、上海、成都各不少于 20 个，覆盖 2～5 天、三档节奏、不同预算和兴趣组合。
3. 每条测试样本由两名标注者独立标注意图和槽位，冲突由第三方或共同复核解决，并报告一致率或 Cohen's Kappa。
4. 基线和本系统使用相同景点数据、地图缓存、模型版本与输入条件；固定 Prompt 版本、算法版本和随机种子，模型不支持固定种子时记录重复运行次数。
5. 专家行程评分至少由两名评审按可执行性、兴趣匹配、节奏合理性、预算合理性和解释可信度进行 1～5 分盲评。
6. 保存测试集版本、运行时间、模型名称、参数、失败样本和原始结果，论文中的表格必须能从实验脚本重新生成。

MVP 目标阈值：

```text
slot_f1 >= 0.85
constraint_satisfaction_rate >= 0.95
recommendation_reason_grounded_rate >= 0.95
expert_itinerary_score >= 4.0 / 5.0
任务成功率 >= 0.90
规划任务 P95 完成时间 <= 120 秒
```

阈值是项目验收目标，不得删除未达到目标的失败样本。论文同时报告平均值、样本量和失败类型，避免只展示最佳案例。

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

---

## 21. 修订记录

| 版本 | 日期 | 修订内容 |
| :--- | :--- | :--- |
| V1.2 | 2026-08-31 | 补齐收藏、最近浏览、分享、后台接口、行程修订、关键表结构、SSE 帧、CSRF 和并发控制 |
| V1.1 | 2026-08-31 | 完善任务 Worker、预算、开放时间、鉴权、部署和实验规范 |
| V1.0 | 2026-08-31 | 建立初版产品、架构、Agent、接口和部署规范 |
