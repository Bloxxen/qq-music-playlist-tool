# B 站 Toy 平台发布指南（前后端分离版）

## 为什么不能直接把 app.py 传上去

Toy 是**纯静态托管**：只放 HTML/CSS/JS，跑不了 Python。
而这个工具的签名和请求必须由后端完成（浏览器直接请求 QQ 音乐接口会被 CORS 拦死），
所以采用前后端分离：

```
B 站 Toy 静态页（bilibili.com 域名，负责 UI）
        ↓  跨域 fetch（已配好 CORS）
Render 后端（python，负责签名 / 请求 QQ 音乐）
        ↓
QQ 音乐接口
```

Cookie 是**用户手动粘贴的纯文本**传过去的，不涉及浏览器 Cookie，所以跨域没有身份认证障碍。

---

## 一、构建静态页

改完 `app.py`（比如调整界面）后，重新生成一次即可：

```bash
cd 项目目录
python3 build_toy.py --zip
```

产物：

| 文件 | 说明 |
| --- | --- |
| `dist-toy/index.html` | 可直接上传的静态页 |
| `歌单工具箱_Toy静态版.zip` | 打包好的 ZIP，**index.html 在压缩包根目录**（Toy 要求） |

脚本会自动完成三件事：
1. 从 `app.py` 抽出内嵌前端；
2. 把 3 处 `fetch('/api/...')` 改成指向 Render 的绝对地址；
3. 注入后端地址变量、请求超时处理、右上角后端状态灯。

换后端地址：`python3 build_toy.py --api https://你的域名 --zip`

---

## 二、Toy 管理端上传

1. 打开 **Toy 管理端**（B 站创作中心 → Toy / 互动作品入口），需要有 Toy 发布权限的账号。
2. **上传作品**：传 `歌单工具箱_Toy静态版.zip`（不要解压后传外层文件夹，`index.html` 必须在最外层）。
3. **填写信息**：
   - 标题：`QQ 音乐歌单工具箱`
   - 简介：一句话说明用途，例如「把 QQ 音乐歌单导出成文本给 AI 分析，再把 AI 推荐的歌批量导回歌单」。
     建议写上**后端不在 B 站、数据不经 B 站处理**，审核更顺。
   - 封面：可用 `screenshot.png` 或自己截一张。
   - 访问地址（slug）：例如 `qq-music-playlist-tool`。
4. **提交审核**：平台做安全扫描 + 内容审核。
5. 通过后拿到链接：`https://www.bilibili.com/toy/<slug>/index.html`，可放进视频简介 / 动态 / 评论区。

---

## 三、后端侧的跨域配置（已内置）

`app.py` 已加 CORS 支持，默认放行 B 站域名：

```
ALLOWED_ORIGINS = https://www.bilibili.com,https://bilibili.com,http://localhost:8000,http://127.0.0.1:8000
```

- 需要加别的域名：在 Render 的环境变量里设 `ALLOWED_ORIGINS`（逗号分隔）。
- 想图省事全放行：设 `ALLOW_ORIGIN_ALL=1`（**不推荐**，等于开放给别人白嫖接口）。
- 已处理 OPTIONS 预检，返回 204 + 相应 CORS 头。

---

## 四、已知风险（上传前先想清楚）

| 风险 | 说明 | 应对 |
| --- | --- | --- |
| Toy 可能限制外部请求 | 平台说明「纯静态托管无法保证外部 CDN 可访问性」，若它对 `fetch` 做 CSP/沙箱限制，页面将调不通后端 | **先传最小 demo 试水**，确认能连通再投入 |
| 账号权限 | 并非所有账号都有 Toy 发布入口 | 先在创作中心确认是否有入口 |
| Render 冷启动 | 免费实例休眠后首次唤醒要几十秒，用户会以为坏了 | 页面已加状态灯 + 超时提示；也可用外部定时任务保活 |
| 审核 | 涉及第三方平台 Cookie 的工具，审核可能被拒 | 简介里强调「仅本地处理的辅助工具」 |
| 后端被滥用 | 域名公开后接口可被他人直接调用 | 建议加简单限流或校验 Referer |

---

## 五、本地自测方法（改完代码先自测）

```bash
# 1. 起后端（显式放行本地静态服务）
ALLOWED_ORIGINS="https://www.bilibili.com,http://127.0.0.1:8000" PORT=3052 python3 app.py &

# 2. 生成指向本地的静态页
python3 build_toy.py --api http://127.0.0.1:3052

# 3. 起静态服务
cd dist-toy && python3 -m http.server 8000

# 4. 浏览器打开 http://127.0.0.1:8000
#    右上角出现绿点「后端已就绪」即连通成功

# 5. 自测完记得重新生成正式版（指向 Render）
python3 build_toy.py --zip
```

---

## 六、更新流程

| 改了什么 | 要做什么 |
| --- | --- |
| `app.py` 后端逻辑 | 提交 Git → Render 自动重新部署（约 2–3 分钟） |
| 前端界面 | 跑 `build_toy.py --zip` → 在 Toy 管理端**重新上传** ZIP |
| 后端地址换了 | `build_toy.py --api 新地址 --zip` → 重新上传 ZIP |
| 只改 README | 提交 Git 即可，不影响线上工具 |
