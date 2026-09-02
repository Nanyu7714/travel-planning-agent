# 多城市个性化旅游规划平台

这是一个面向北京、上海和成都的多城市个性化旅游规划平台。系统通过结构化数据、推荐评分和路线约束生成行程；Agent 会调用受控的景点检索、候选筛选和行程校验工具，并保存执行记录。大语言模型只负责理解用户需求和解释已验证结果，不作为景点事实数据源。

## 当前状态

仓库已经包含一个可运行的 MVP 工程骨架：Vue 前端、FastAPI 后端、SQLite 本地数据、邮箱验证与密码找回、Cookie 登录与 7 天自动续期、4 位公开用户 ID、Agent 工具化规则规划与执行追踪、SSE 进度推送、行程管理和管理员概览。生产环境仍按开发文档切换到 PostgreSQL。

## MVP 范围

- 浏览城市、景点和季度热门排行。
- 通过多轮对话收集目的地、天数、预算、兴趣和节奏。
- 生成并校验 2～5 天游，支持修订、保存、历史版本和只读分享。
- 支持收藏、最近浏览、账号设置和用户反馈。
- 注册后分配唯一的 4 位公开用户 ID，支持用户名、邮箱或用户 ID 加密码登录；个人资料页只读展示该 ID，并支持验证密码后注销账号。
- 支持城市、景点、数据导入、排行、反馈和审计后台。

明确不包含酒店、机票、门票预订和支付，不支持复杂跨城市行程，也不提供实时导航。

## 技术方案

- 前端：Vue 3、TypeScript、Vite、Element Plus、ECharts、高德地图 JavaScript API。
- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL、httpx、事务邮件适配器。
- Agent：REST 提交、PostgreSQL 持久化任务、单规划 Worker、SSE 事件流。
- 部署：Alibaba Cloud Linux 3、宝塔 Nginx、Uvicorn、PostgreSQL、Let's Encrypt。

## 本地启动

推荐 Python 3.12（后端代码兼容 Python 3.13），Node.js 使用 LTS 版本。

后端：

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --port 8000
```

前端另开终端：

```powershell
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。本地默认使用 SQLite（数据库文件位于仓库根目录），首次启动会自动创建表和示例数据。

管理员账号由部署人员在服务端初始化和管理，不在前端或项目文档中公开凭据。

## Agent 演示

登录后进入“AI 规划”，输入：

```text
我想去成都玩 4 天，喜欢美食和慢节奏
```

当前 MVP 使用固定景点数据和可复现的规则规划，并通过 SSE 推送规划阶段。普通对话和行程交付说明在配置后端大模型后调用模型；景点选择、时间、价格和约束仍以数据库及规则结果为准。将 `INLINE_WORKER` 设置为 `false` 后，需要额外启动：

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.workers.planning
```

## 环境变量

复制 `backend/.env.example` 为 `backend/.env`。生产环境将 `DATABASE_URL` 改为 PostgreSQL 连接串：

```env
DATABASE_URL=postgresql+psycopg://travel_user:密码@127.0.0.1:5432/travel_platform
```

大模型 Key、数据库密码、JWT 密钥和高德 Web Service Key 只能放在后端环境变量中，`.env` 不能提交到 Git。正式部署前必须修改 `JWT_SECRET`、`CSRF_SECRET` 和管理员密码。

大模型使用兼容 OpenAI Chat Completions 的后端接口。项目不会自动创建或修改 `.env`，请根据所使用的服务填写：

```env
LLM_API_KEY=你的服务端密钥
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_TIMEOUT_SECONDS=30
LLM_MAX_TOKENS=500
```

未配置 `LLM_API_KEY` 时，页面会明确显示“使用本地对话模式”；首次模型请求成功后显示“已连接”，调用失败则自动降级且不会影响城市浏览和规则规划。

认证邮件在开发环境默认使用本地模式，注册、找回密码和修改邮箱后页面会显示一次性的本地测试链接。生产环境应设置 `ENVIRONMENT=production`、`MAIL_DELIVERY_MODE=smtp`、`MAIL_FROM`、`SMTP_HOST`、`SMTP_PORT`、`SMTP_USERNAME`、`SMTP_PASSWORD` 和 `SMTP_STARTTLS`；这些值只允许保存在服务器环境变量中。项目不会自动修改 `.env`。

## 测试和构建

```powershell
cd backend
python -m pytest

cd ..\frontend
npm run build
```

## 生产部署概要

Vue 构建结果放入 `/www/wwwroot/travel-web/`，FastAPI 项目放入 `/www/wwwroot/travel-api/`。生产环境使用一个 Uvicorn Worker 和一个规划 Worker，由 Nginx 转发 `/api/` 到 `127.0.0.1:8000`，SSE 路由关闭代理缓冲，并配置 HTTPS、每日 PostgreSQL 备份和健康检查。

## 项目文档

- [开发文档](旅游规划咨询Agent-开发文档.md)
- [样式设计文档](旅游规划咨询Agent-样式设计文档.md)
- [开发记录](docs/开发记录.md)
- [审查文档](docs/审查文档.md)
- [媒体资源管理](docs/媒体资源管理.md)
- [未实现功能清单](docs/未实现功能.md)

字段、状态、接口和错误码以开发文档为准；布局、交互和组件状态以样式设计文档为准。两份文档冲突时先修订文档，再开始实现。

## 实施顺序

1. 创建 `frontend/`、`backend/`、迁移和测试目录。
2. 完成用户、城市、景点、会话、任务、行程修订和审计数据表。
3. 完成 Cookie 鉴权、CSRF、公开查询与后台 CRUD。
4. 完成 Agent Worker、SSE、推荐评分、路线规划和约束校验。
5. 完成用户端、后台、自动化测试、数据导入与部署演练。

当前已实现城市/景点详情、城市内热度排行、行程工作台编辑与版本、只读分享、收藏/最近浏览、用户主页、邮箱验证、密码找回、账号设备管理和反馈收件箱；真实图片、地图、实时热点和正式 PostgreSQL 迁移仍见 [未实现功能清单](docs/未实现功能.md)。

## 仓库地址

https://github.com/Nanyu7714/travel-planning-agent
