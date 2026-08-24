---
title: 歌单工具箱
emoji: 🎵
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

<!-- 上面这段 YAML 是 Hugging Face Spaces 的必需配置（sdk: docker + app_port: 7860），
     在 GitHub 上保留它没有任何副作用。 -->

# QQ 音乐歌单工具箱 · 部署说明

一个零代码网页工具：把「歌名 - 歌手」列表批量导入 QQ 音乐歌单，也支持把歌单导出成 txt 发给 AI 分析。

> 🚀 **想免费部署成在线链接？** 看 [DEPLOY.md](DEPLOY.md) —— 支持 Hugging Face Spaces（永久免费）和 GitHub + Render 两条 0 成本路线，都有逐步操作说明。

## 文件清单

| 文件 | 作用 |
|---|---|
| `app.py` | 后端（Flask）+ 前端界面（HTML/CSS/JS 内嵌），单文件 |
| `requirements.txt` | 依赖声明（flask、requests） |

## 如何重新部署

### 方式一：本地运行

```bash
pip install -r requirements.txt
python app.py
```

默认监听 `PORT` 环境变量，未设置时用 3000。浏览器打开 `http://localhost:3000` 即可。

### 方式二：发布到在线平台

这是标准 Flask 应用，可部署到任何支持 Python 的平台（如 Heroku、Vercel、Railway、腾讯云等），只需：

1. 指定启动命令为 `python app.py`；
2. 设置 `PORT` 环境变量；
3. 平台自动 `pip install -r requirements.txt`。

### 方式三：交给 AI 助手重新发布

把本目录（尤其 `app.py`）交给 AI 助手，说明"这是个 Flask 应用，帮我发布成在线链接"，它通常能自动完成。

## 关键说明

- 前端界面**内嵌在 `app.py` 的 `HTML = r"""..."""` 里**，没有单独的前端文件；改界面就改这一段。
- 后端接口：`POST /api/import`（发起导入）、`GET /api/status/<task_id>`（查进度）、`POST /api/export`（导出歌单）。
- 导入功能依赖用户的 QQ 音乐 cookie（从浏览器获取，工具支持粘贴 cURL 命令自动提取）。
- **发布平台网关会拦截含多行 cURL 命令的请求（返回 403）**，前端已在浏览器本地把 cURL 提取成纯 cookie 再上传，规避了这个问题。
- 界面里的示例歌单数字已脱敏（`0000000000` 等假数字）。
