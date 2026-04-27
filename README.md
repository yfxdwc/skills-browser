# Skills Browser

Hermes Skills 的轻量级 Web 查看器 — 三个面板布局：

- **左侧** — Agent → Skill 树形列表
- **中间** — Skill 内容渲染（Markdown → HTML）
- **右侧** — Agent 对话（通过 `hermes --profile <agent> chat -q` SSE 实时流）

![Skills Browser](https://img.shields.io/badge/status-stable-green)
![Python](https://img.shields.io/badge/python-3.12+-blue)

---

## 🎨 项目设计规范（Design Spec）

### 视觉风格：NotebookLM Inspired

整体风格参考 Google NotebookLM 的轻亮界面：**大量留白、柔和灰蓝调、克制用色**，拒绝过度装饰。

### 配色体系（CSS Variables）

| 变量 | 值 | 用途 |
|------|----|------|
| `--bg` | `#ffffff` | 主背景 |
| `--bg0` | `#F8F9FB` | 面板背景 |
| `--bg1` | `#EEF1F6` | 悬停背景 |
| `--bg2` | `#E4E8F0` | 次级元素 |
| `--border` | `#E2E6F0` | 边框 |
| `--text` | `#1A1D27` | 主文字 |
| `--text2` | `#4B5268` | 次文字 |
| `--text3` | `#8892A8` | 弱文字 |
| `--accent` | `#0B6BF2` | 主强调色（Feishu 蓝） |
| `--accent-light` | `#EBF2FF` | 强调色浅底 |
| `--accent-glow` | `rgba(11,107,242,.10)` | 强调色光晕 |

### Agent 头像（Agent Icon）

**默认态**：浅灰底 `--bg2`，深灰文字 `--text3`，1px 细边框 `--border`。

**选中态**：ecosystem 对应弱色背景 `--eco-bg`（Hermes: `#FFFBF0` / OpenClaw: `#FFF5F5`），细边框和文字使用 ecosystem 弱强调色（H: `#D4961C` / O: `#C81E1E`），opacity 0.9。

### Ecosystem 区块

分为 **Hermes**（🔥）和 **OpenClaw**（🦞）两个区块：

- **顶部边线** 2px，ecosystem 弱强调色，opacity 0.88
- **标签文字** 65% 透明度，ecosystem 弱强调色
- **区块整体** opacity 0.88，自然融入背景

### Ecosystem 官方配色

| Ecosystem | 官方品牌色 | 用于 |
|----------|-----------|------|
| Hermes | `#F5C542`（金色） | agent 选中态 icon 边框/文字（opacity 0.65 淡化） |
| OpenClaw | `#E81B25`（红色） | 同上 |
| Feishu Accent | `#0B6BF2`（蓝） | 全局交互强调色 |

### 字体

- **UI**：Inter / -apple-system / BlinkMacSystemFont / Segoe UI，15px
- **代码**：JetBrains Mono / Fira Code / Consolas

### 共享 Badge

淡灰色 `--bg2` 背景，`--text3` 文字，1px `--border` 边框，融入整体不抢眼。

### Agent 选中态

不使用加粗色块，使用 ecosystem **弱色淡底 + 细边框**（1px），配合 0.9 opacity，头像随区块色调，整体保持轻亮感。

---

## 架构

```
skills-browser/
├── server.py     # Python HTTP 服务器（无依赖）
└── index.html    # 单文件前端（~8KB gzip）
```

**服务端** (`server.py`)：
- 递归发现 `~/.hermes/profiles/<agent>/skills/**/SKILL.md`
- Markdown → HTML 转换（最小化实现，支持代码块、列表、加粗等）
- Hermes CLI 代理：`hermes --profile <agent> chat -q <msg>` SSE 流式输出
- gzip 压缩（35KB → 8KB）

**前端** (`index.html`)：
- 纯原生 JS，无框架、无 CDN 依赖
- `skillPathMap` JS Map 存储路径，避免 DOM `data-path` 特殊字符问题
- 独立的 per-agent 对话历史
- Resize 面板拖拽

## 部署

```bash
# 启动
python3 server.py

# 或 systemd 服务
systemctl --user start skills-browser
# 访问 http://localhost:8383
```

配合 Cloudflare Tunnel 公网访问：

```yaml
# ~/.cloudflared/config.yml
tunnel: <your-tunnel-id>
credentials-file: ~/.cloudflared/credentials.json
ingress:
  - hostname: skills.tooyang.top
    service: http://localhost:8383
```

## API

| 端点 | 说明 |
|------|------|
| `GET /` | Web UI |
| `GET /api/agents` | 所有 Agent 列表 |
| `GET /api/agents/<agent>` | Agent 所有 Skills（含 path、depth） |
| `GET /api/agents/<agent>/content?path=<path>` | 读取 Skill 内容（Markdown → HTML） |
| `POST /api/chat/stream` | SSE 流式对话（`{agent, message, skill_context}`） |

## 开发

```bash
cd skills-browser
python3 server.py
# 编辑 index.html / server.py 后直接刷新浏览器即可
```
