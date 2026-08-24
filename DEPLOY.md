# 歌单工具箱 · 免费部署指南（Hugging Face Spaces / GitHub 路线）

这是一个 **单文件 Flask 应用**（后端 + 网页一体，无单独前端文件）。它需要后端来调用 QQ 音乐接口——浏览器直连会被跨域（CORS）拦截，且导入需要携带登录 cookie 与接口签名，所以 **纯静态网页（GitHub Pages）跑不了**，必须部署到能跑后端的平台。

两条 0 成本路线任选其一（或都做，互不影响）：

---

## 路线一：Hugging Face Spaces（永久免费 · 约 5 分钟）

### 你要做的（网页上点几下）

1. 注册/登录 [huggingface.co](https://huggingface.co)（免费）。
2. 点右上角头像 → **New Space**：
   - **Space name**：`playlist-toolbox`
   - **SDK**：选 **Docker** → **Blank** 模板
   - **Visibility**：**Public**（否则别人访问不了）
   - 点 **Create Space**
3. 进入 Space 页面 → **Files** 标签 → **Add file → Upload files**，把本项目这 5 个文件拖进去：
   - `app.py`
   - `requirements.txt`
   - `Dockerfile`
   - `README.md`（已带 HF 必需的 YAML 头，勿删文件开头那段 `---` 配置）
   - `.gitignore`（可不上传，不影响）
   > 注意：上传的 `README.md` 会覆盖 Space 自带的，本项目的 README 已包含 HF 需要的 frontmatter（`sdk: docker`、`app_port: 7860`），所以直接覆盖是安全的。
4. 点 **Commit changes to main**，Space 自动开始构建（Building），约 1~3 分钟变 **Running**。
5. 访问 `https://你的用户名-playlist-toolbox.hf.space`（用户名里的下划线会变成连字符），把链接发给任何人即可。

### 说明

- 免费版足够个人使用；长时间无人访问会休眠，再次打开等几秒自动唤醒。
- 构建/运行日志在 Space 的 **Logs** 标签里，报错去那里看。

### 或者：交给 AI 助手自动部署

在 Hugging Face **Settings → Access Tokens → New token** 创建一个 **Fine-grained** token，勾选 **Write access to all/selected Spaces**，把 token 发给 AI 助手，即可全自动创建 Space 并上传文件。

---

## 路线二：GitHub + Render（免费 · 约 10 分钟）

> GitHub 本身只托管代码（GitHub Pages 仅支持静态页，本工具需要后端，跑不了），
> 所以 GitHub 路线 = **代码放 GitHub + Render 从 GitHub 拉取免费部署**，得到 `*.onrender.com` 公网链接。

### 第 1 步：把项目传到 GitHub

1. 登录 [github.com](https://github.com)，点 **New repository**：
   - 名字如 `playlist-toolbox`，**Public**，其他默认，点 **Create repository**
2. 进入空仓库 → **uploading an existing file** 链接（Add file → Upload files），把项目 5 个文件拖进去：
   - `app.py`、`requirements.txt`、`Dockerfile`、`render.yaml`、`README.md`、`.gitignore`
3. 点 **Commit changes**。

（如果你本机装了 git，也可以 `git clone` 空仓库后把文件拷进去再 `git push`。）

### 第 2 步：Render 免费部署

1. 注册/登录 [render.com](https://render.com)（可用 GitHub 账号登录，免费）。
2. 打开仓库页面，点击本文件所在仓库的 **Deploy to Render** 一键部署（或：Render 控制台 → **New** → **Blueprint** → 关联该仓库）。
   - 一键部署链接格式：`https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2F你的用户名%2Fplaylist-toolbox`
3. Render 会读取 `render.yaml` 自动创建服务（Free 套餐、`pip install -r requirements.txt`、`python app.py`）。
4. 等部署完成，得到 `https://playlist-toolbox-xxxx.onrender.com`，发给任何人即可。

### 说明

- 免费版 15 分钟无访问会休眠，下次访问冷启动约 30~60 秒；个人工具完全够用。
- 部署日志在 Render 服务的 **Events / Logs** 里，报错去那里看。
- 更新代码：改完 GitHub 仓库，Render 自动重新部署。

---

## 本地运行（开发 / 自测）

```bash
pip install -r requirements.txt
PORT=3000 python app.py
# 浏览器打开 http://localhost:3000
```

默认监听 `PORT` 环境变量，未设置时回退到 `3000`。

---

## 使用说明要点

- **导出歌单**：填歌单链接（可多个，每行一个），无需登录，调用公开接口读出歌单并导出为 `歌名 - 歌手` 文本，可直接发给 AI 分析口味。
- **导入歌单**：需要你的 QQ 音乐 **登录 cookie**（网页内点开「怎么获取 Cookie？」有 6 步图文）。cookie 仅用于本次导入请求，**不落库、不上传任何第三方**，用完即弃。
- 接口：`POST /api/import`（发起导入）、`GET /api/status/<task_id>`（查进度）、`POST /api/export`（导出歌单）。
