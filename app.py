# -*- coding: utf-8 -*-
"""
QQ 音乐歌单批量导入 - 在线版
用户粘贴：目标歌单链接 + 自己的登录 cookie + 歌单内容（"歌名 - 歌手"）
后端自动解析歌单 dirId、搜索匹配、去重、批量加歌。
"""
import os, re, json, time, base64, threading, uuid
from hashlib import sha1
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# ---------------- 签名 / g_tk ----------------
def hash33(s, h=5381):
    for c in s:
        h = (h << 5) + h + ord(c)
    return 2147483647 & h

P1 = [23, 14, 6, 36, 16, 7, 19]
P2 = [16, 1, 32, 12, 19, 27, 8, 5]
SC = [89, 39, 179, 150, 218, 82, 58, 252, 177, 52, 186, 123, 120, 64, 242, 133, 143, 161, 121, 179]

def zzc(p):
    h = sha1(p.encode()).hexdigest().upper()
    p1 = "".join(h[i] for i in P1)
    p2 = "".join(h[i] for i in P2)
    p3 = bytearray(20)
    for i, v in enumerate(SC):
        p3[i] = v ^ int(h[i * 2:i * 2 + 2], 16)
    return f"zzc{p1}{re.sub(rb'[/+=]', b'', base64.b64encode(p3)).decode()}{p2}".lower()


# ---------------- 解析输入 ----------------
def normalize_cookie_input(text):
    """支持粘贴纯 cookie 字符串，或整段 cURL 命令（自动提取其中的 cookie）"""
    t = (text or "").strip()
    if not t:
        return t
    if t.lower().startswith('curl') or '--url' in t or '-b ' in t or '-b"' in t or '-b^' in t:
        m = re.search(r'(?:-b|--cookie)\s+\^?"([^"]*?)\^?"', t, re.DOTALL)
        if m and '=' in m.group(1):
            return m.group(1).strip()
        m = re.search(r'(?:-H|--header)\s+\^?"?cookie:\s*([^"\n]+?)\^?"?', t, re.I | re.DOTALL)
        if m and '=' in m.group(1):
            return m.group(1).strip()
    return t

def parse_cookie(cookie_str):
    """把 cookie 字符串解析成 dict（按分号切分，值里允许含 = ）"""
    ck = {}
    for p in re.split(r';\s*', cookie_str.strip()):
        p = p.strip()
        if '=' in p:
            k, v = p.split('=', 1)
            ck[k.strip()] = v.strip()
    return ck

def extract_uin(cookie_str):
    m = re.search(r'(?:^|[;\s])uin=(\d+)', cookie_str)
    if m:
        return m.group(1)
    return None

def extract_disstid(playlist_url):
    """从歌单链接提取 disstid，也支持直接贴纯数字"""
    s = playlist_url.strip()
    if s.isdigit():
        return s
    m = re.search(r'playlist/(\d+)', s)
    if m:
        return m.group(1)
    m = re.search(r'(\d{6,})', s)
    if m:
        return m.group(1)
    return None


# ---------------- QQ 音乐接口 ----------------
def get_playlist_info(disstid):
    """公开接口读歌单详情：拿 dirid + 歌单名 + 现有歌曲 songmid 集合（去重用）"""
    url = (f"https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?"
           f"type=1&utf8=1&disstid={disstid}&format=json&inCharset=utf-8&outCharset=utf-8"
           f"&notice=0&platform=yqq.json&needNewCode=0&song_begin=0&song_num=5000")
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://y.qq.com/"}, timeout=30)
    t = r.text.strip()
    d = json.loads(t[t.index('(') + 1:t.rindex(')')] if t.startswith('(') else t)
    cd = (d.get("cdlist") or [{}])[0]
    if not cd or not cd.get("dirid"):
        raise ValueError("无法读取该歌单信息，请检查歌单链接是否正确")
    dirid = cd["dirid"]
    name = cd.get("dissname", "未知歌单")
    existing = set()
    for x in cd.get("songlist", []):
        if x.get("songmid"):
            existing.add(x["songmid"])
    return dirid, name, existing

def export_playlist(disstid):
    """公开接口读歌单，返回 (歌单名, 歌曲行列表)，无需登录"""
    url = (f"https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?"
           f"type=1&utf8=1&disstid={disstid}&format=json&inCharset=utf-8&outCharset=utf-8"
           f"&notice=0&platform=yqq.json&needNewCode=0&song_begin=0&song_num=5000")
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://y.qq.com/"}, timeout=30)
    t = r.text.strip()
    d = json.loads(t[t.index('(') + 1:t.rindex(')')] if t.startswith('(') else t)
    cd = (d.get("cdlist") or [{}])[0]
    if not cd or not cd.get("dissname"):
        raise ValueError("无法读取该歌单，请确认链接正确（私密歌单请先「分享」拿到带数字的链接）")
    name = cd.get("dissname", "未知歌单")
    lines = []
    for x in cd.get("songlist", []):
        songname = (x.get("songname") or "").strip()
        if not songname:
            continue
        singers = [s.get("name", "").strip() for s in x.get("singer", []) if s.get("name")]
        singer = "/".join(singers)
        lines.append(f"{songname} - {singer}" if singer else songname)
    if not lines:
        raise ValueError("该歌单没有歌曲")
    return name, lines

def search_song(ck, kw):
    url = ("https://c.y.qq.com/soso/fcgi-bin/client_search_cp?"
           f"w={requests.utils.quote(kw)}&format=json&n=5&p=1&cr=1&t=0&new_format=1"
           "&platform=yqq.json&needNewCode=0&g_tk=0")
    r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://y.qq.com/"}, cookies=ck, timeout=15)
    t = r.text.strip()
    d = json.loads(t[t.index('(') + 1:t.rindex(')')] if t.startswith('(') else t)
    for s in d.get("data", {}).get("song", {}).get("list", []):
        if s.get("songmid") and s.get("songid"):
            return {"songmid": s["songmid"], "songid": s["songid"],
                    "name": s.get("songname"), "singer": "/".join(x.get("name", "") for x in s.get("singer", []))}
    return None

def add_songs(ck, uin, dirid, songids):
    gtk = hash33(ck.get('qm_keyst') or ck.get('qqmusic_key', ''))
    comm = {"ct": 24, "cv": 4747474, "platform": "yqq.json", "chid": "0", "uin": uin,
            "g_tk": gtk, "g_tk_new_20200303": gtk, "format": "json", "inCharset": "utf-8",
            "outCharset": "utf-8", "notice": 0, "need_new_code": 1}
    req0 = {"module": "music.musicasset.PlaylistDetailWrite", "method": "AddSonglist",
            "param": {"dirId": int(dirid), "tid": 0, "bFmtUtf8": True,
                      "v_songInfo": [{"songId": int(sid), "songType": 0} for sid in songids]}}
    body = json.dumps({"comm": comm, "req_0": req0}, ensure_ascii=False, separators=(",", ":"))
    sign = zzc(body)
    url = f"https://u.y.qq.com/cgi-bin/musics.fcg?_={int(time.time()*1000)}&sign={sign}"
    r = requests.post(url, data=body.encode(),
                      headers={"User-Agent": UA, "Content-Type": "application/json", "Referer": "https://y.qq.com/"},
                      cookies=ck, timeout=30)
    return r.json()


# ---------------- 任务管理 ----------------
TASKS = {}
_lock = threading.Lock()

def set_task(tid, **kw):
    with _lock:
        TASKS[tid].update(kw)

def get_task(tid):
    with _lock:
        return dict(TASKS.get(tid, {}))

def parse_songs(text):
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        # 剥离行首序号，如 "1." "1、" "1)" "1：" 等
        ln = re.sub(r'^\s*\d+\s*[.、)）:：\]】>]\s*', '', ln)
        for sep in [" - ", " -", "- ", "—", "–"]:
            if sep in ln:
                a, b = ln.split(sep, 1)
                out.append((a.strip(), b.strip()))
                break
        else:
            out.append((ln, ""))
    return out


def run_import(tid, data):
    try:
        playlist_url = (data.get("playlist_url") or "").strip()
        cookie_str = normalize_cookie_input(data.get("cookie") or "")
        songs_text = (data.get("songs") or "").strip()

        if not playlist_url:
            raise ValueError("请填写目标歌单链接")
        if not cookie_str:
            raise ValueError("请粘贴你的登录 cookie")
        if not songs_text:
            raise ValueError("请粘贴要导入的歌单内容")

        disstid = extract_disstid(playlist_url)
        if not disstid:
            raise ValueError("无法从链接中识别歌单 ID，请粘贴形如 https://y.qq.com/n/ryqq_v2/playlist/xxxx 的链接")

        uin = extract_uin(cookie_str)
        if not uin:
            raise ValueError("cookie 中缺少 uin 字段，请确认是从浏览器请求头复制的完整 cookie")

        ck = parse_cookie(cookie_str)
        if not (ck.get('qm_keyst') or ck.get('qqmusic_key')):
            raise ValueError("cookie 中缺少 qm_keyst / qqmusic_key，请确认是从浏览器请求头复制的完整 cookie")

        # 1) 读目标歌单
        set_task(tid, progress=5, message="正在读取目标歌单信息…")
        dirid, plname, existing = get_playlist_info(disstid)
        set_task(tid, progress=10, message=f"目标歌单「{plname}」，已有 {len(existing)} 首")

        # 2) 解析歌单
        wanted = parse_songs(songs_text)
        if not wanted:
            raise ValueError("歌单内容为空，请按「歌名 - 歌手」每行一首填写")
        set_task(tid, progress=15, message=f"共解析到 {len(wanted)} 首待导入")

        # 3) 逐首搜索匹配 + 去重
        to_add, skipped = [], []
        for i, (name, singer) in enumerate(wanted):
            kw = f"{name} {singer}".strip() if singer else name
            hit = search_song(ck, kw)
            if not hit:
                skipped.append({"name": name, "singer": singer, "reason": "未匹配到"})
            elif hit["songmid"] in existing:
                skipped.append({"name": name, "singer": singer, "reason": "已在歌单中"})
            else:
                to_add.append({"songid": hit["songid"], "name": name, "singer": singer,
                               "matched": f"{hit['name']} - {hit['singer']}"})
                existing.add(hit["songmid"])
            pct = 15 + int((i + 1) / len(wanted) * 55)
            set_task(tid, progress=pct, message=f"匹配中 {i+1}/{len(wanted)}…")
            time.sleep(0.08)

        if not to_add:
            set_task(tid, status="done", progress=100,
                     message=f"匹配完成，{len(skipped)} 首被跳过（可能已存在或未匹配），无需新增",
                     result={"added": 0, "skipped": len(skipped), "failed": 0, "skipped_detail": skipped})
            return

        # 4) 批量加歌（每批 20 首）
        ok, fail = 0, 0
        fail_detail = []
        total_batches = (len(to_add) + 19) // 20
        for bi in range(0, len(to_add), 20):
            batch = to_add[bi:bi + 20]
            j = add_songs(ck, uin, dirid, [b["songid"] for b in batch])
            code = (j.get("req_0") or {}).get("code")
            if code == 0:
                ok += len(batch)
            else:
                fail += len(batch)
                fail_detail.append({"code": code, "count": len(batch), "raw": json.dumps(j, ensure_ascii=False)[:200]})
            pct = 70 + int((bi // 20 + 1) / total_batches * 30)
            set_task(tid, progress=pct, message=f"加歌中 第 {bi//20+1}/{total_batches} 批…")
            time.sleep(1.0)

        set_task(tid, status="done", progress=100,
                 message=f"完成：成功 {ok} 首，跳过 {len(skipped)} 首，失败 {fail} 首",
                 result={"added": ok, "skipped": len(skipped), "failed": fail,
                         "playlist": plname, "skipped_detail": skipped, "fail_detail": fail_detail})

    except Exception as e:
        set_task(tid, status="error", message=str(e))


# ---------------- 路由 ----------------
@app.route("/")
def index():
    return HTML

@app.route("/api/import", methods=["POST"])
def api_import():
    data = request.get_json(force=True, silent=True) or {}
    tid = uuid.uuid4().hex
    with _lock:
        TASKS[tid] = {"status": "running", "progress": 0, "message": "准备中…", "result": None}
    threading.Thread(target=run_import, args=(tid, data), daemon=True).start()
    return jsonify({"task_id": tid})

@app.route("/api/status/<tid>")
def api_status(tid):
    return jsonify(get_task(tid))


@app.route("/api/export", methods=["POST"])
def api_export():
    data = request.get_json(force=True, silent=True) or {}
    raw = data.get("playlist_url") or data.get("playlist_urls") or ""
    urls = [l.strip() for l in str(raw).splitlines() if l.strip()]
    if not urls:
        return jsonify({"error": "请填写至少一个歌单链接"}), 400

    parts, details = [], []
    total = 0
    for url in urls:
        disstid = extract_disstid(url)
        if not disstid:
            parts.append(f"【无法识别的链接】{url}")
            details.append({"url": url, "error": "无法识别链接"})
            continue
        try:
            name, lines = export_playlist(disstid)
            parts.append(f"【{name}】共 {len(lines)} 首")
            parts.extend(lines)
            parts.append("")
            total += len(lines)
            details.append({"url": url, "name": name, "count": len(lines)})
        except Exception as e:
            parts.append(f"【{url}】导出失败：{e}")
            details.append({"url": url, "error": str(e)})

    text = "\n".join(parts).rstrip()
    return jsonify({"name": "多歌单合并", "count": total,
                    "playlist_count": len(details), "text": text, "details": details})


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>歌单工具箱 — 深色科技风</title>
<style>
:root {
  --bg: #0D1117;
  --bg-card: rgba(22, 27, 34, 0.85);
  --bg-card-solid: #161B22;
  --bg-input: #0D1117;
  --border: rgba(48, 54, 61, 0.8);
  --border-hover: #30363D;
  --brand: #39D353;
  --brand-dark: #2EA043;
  --brand-glow: rgba(57, 211, 83, 0.15);
  --brand-gradient: linear-gradient(135deg, #39D353, #2EA043);
  --cyan: #58A6FF;
  --cyan-glow: rgba(88, 166, 255, 0.12);
  --warning: #D29922;
  --danger: #F85149;
  --text-primary: #E6EDF3;
  --text-secondary: #8B949E;
  --text-tertiary: #6E7681;
  --font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  --font-mono: "SF Mono", "Fira Code", Consolas, monospace;
  --radius: 12px;
  --radius-sm: 8px;
  --radius-full: 999px;
  --shadow: 0 8px 32px rgba(0,0,0,0.4);
  --shadow-glow: 0 0 24px rgba(57, 211, 83, 0.08);
  --ease: cubic-bezier(0.4, 0, 0.2, 1);
  --dur: 0.25s;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: var(--font-sans); background: var(--bg); color: var(--text-primary); line-height: 1.6; min-height: 100vh;
  background-image: radial-gradient(circle at 20% 0%, rgba(57,211,83,0.06) 0%, transparent 50%),
                    radial-gradient(circle at 80% 100%, rgba(88,166,255,0.05) 0%, transparent 50%);
}
button, input, textarea { font-family: inherit; font-size: inherit; }
button { cursor: pointer; border: none; background: none; }

.app { min-height: 100vh; display: flex; flex-direction: column; align-items: center; }

.topbar { width: 100%; background: rgba(13, 17, 23, 0.8); backdrop-filter: blur(20px); border-bottom: 1px solid var(--border); position: sticky; top: 0; z-index: 100; }
.topbar-inner { max-width: 680px; margin: 0 auto; padding: 16px 24px 8px; }

.brand { display: flex; align-items: center; gap: 10px; justify-content: center; margin-bottom: 14px; }
.brand::after { content: ''; width: 34px; flex-shrink: 0; }
.brand-icon { width: 34px; height: 34px; background: var(--brand-gradient); border-radius: var(--radius-sm); display: flex; align-items: center; justify-content: center; box-shadow: 0 0 16px rgba(57,211,83,0.4); }
.brand-icon svg { width: 18px; height: 18px; stroke: white; fill: none; stroke-width: 2.5; }
.brand-text h1 { font-size: 24px; font-weight: 700; letter-spacing: 0.02em; line-height: 1.3; }

.tabs { display: flex; gap: 4px; background: var(--bg-card-solid); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 4px; max-width: 320px; margin: 0 auto; }
.tab-btn { flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 12px; border-radius: 6px; font-size: 13px; font-weight: 500; color: var(--text-secondary); transition: all var(--dur) var(--ease); }
.tab-btn svg { width: 15px; height: 15px; stroke: currentColor; fill: none; stroke-width: 2; }
.tab-btn:hover:not(.active) { color: var(--text-primary); background: rgba(255,255,255,0.04); }
.tab-btn.active { background: var(--brand-gradient); color: white; font-weight: 600; box-shadow: 0 2px 8px rgba(57,211,83,0.3); }

.safety-bar { display: flex; align-items: center; justify-content: center; gap: 5px; font-size: 11px; color: var(--text-tertiary); padding: 8px 0 4px; font-family: var(--font-mono); }
.safety-bar svg { width: 12px; height: 12px; stroke: var(--brand); fill: none; stroke-width: 2; }

.main { width: 100%; max-width: 680px; padding: 24px 24px 48px; }
.page-header { margin-bottom: 20px; text-align: center; }
.page-header h2 { font-size: 20px; font-weight: 700; }
.page-header p { font-size: 13px; color: var(--text-secondary); margin-top: 3px; }

.form-card { background: var(--bg-card); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 12px; transition: all var(--dur) var(--ease); }
.form-card:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-glow); }
.form-label { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; }
.form-label .step-badge { width: 20px; height: 20px; background: var(--brand-glow); color: var(--brand); border-radius: var(--radius-full); display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; }
.form-label .badge-tag { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: var(--radius-full); background: var(--brand-glow); color: var(--brand); }
.form-label .badge-tag.detected { background: var(--brand); color: #0D1117; }
.form-hint { font-size: 12px; color: var(--text-tertiary); margin-bottom: 8px; }

.input-wrap { position: relative; }
.input-wrap .input-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; stroke: var(--text-tertiary); fill: none; stroke-width: 2; pointer-events: none; transition: stroke var(--dur); }
.input-wrap:focus-within .input-icon { stroke: var(--brand); }
input.field, textarea.field { width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm); font-size: 13px; color: var(--text-primary); background: var(--bg-input); transition: all var(--dur) var(--ease); line-height: 1.5; }
input.field.with-icon { padding-left: 36px; }
textarea.field { resize: vertical; min-height: 90px; line-height: 1.6; }
textarea.field.code { min-height: 110px; font-family: var(--font-mono); font-size: 12px; }
textarea.field.songs { min-height: 140px; }
input.field:focus, textarea.field:focus { outline: none; border-color: var(--brand); box-shadow: 0 0 0 3px var(--brand-glow); }
input.field::placeholder, textarea.field::placeholder { color: var(--text-tertiary); }

.guide-toggle { display: flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 500; color: var(--cyan); cursor: pointer; margin-bottom: 8px; user-select: none; }
.guide-toggle svg { width: 12px; height: 12px; stroke: currentColor; fill: none; stroke-width: 2.5; transition: transform var(--dur) var(--ease); }
.guide-toggle.open svg { transform: rotate(90deg); }
.guide-body { max-height: 0; overflow: hidden; transition: max-height 0.4s var(--ease); }
.guide-body.open { max-height: 500px; }
.guide-steps { background: rgba(88,166,255,0.05); border: 1px solid rgba(88,166,255,0.15); border-radius: var(--radius-sm); padding: 12px 14px; font-size: 12px; color: var(--text-secondary); line-height: 1.8; }
.guide-steps ol { padding-left: 18px; }
.guide-steps b { color: var(--text-primary); }
.guide-steps code { background: var(--bg-input); border: 1px solid var(--border); padding: 1px 5px; border-radius: 4px; font-family: var(--font-mono); font-size: 11px; color: var(--cyan); }

.btn { display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 11px 24px; border-radius: var(--radius-sm); font-size: 14px; font-weight: 600; transition: all var(--dur) var(--ease); white-space: nowrap; }
.btn svg { width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 2; }
.btn-primary { background: var(--brand-gradient); color: white; box-shadow: 0 4px 16px rgba(57,211,83,0.25); }
.btn-primary:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 6px 24px rgba(57,211,83,0.4); }
.btn-primary:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-secondary { background: var(--bg-card-solid); color: var(--text-primary); border: 1px solid var(--border); }
.btn-secondary:hover { border-color: var(--border-hover); }
.btn-lg { padding: 13px 32px; font-size: 15px; }
.btn-center { display: flex; justify-content: center; margin-top: 14px; }
.btn-center .btn { min-width: 180px; }

.progress-section { background: var(--bg-card); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; margin-bottom: 12px; display: none; }
.progress-section.show { display: block; animation: slideIn var(--dur) var(--ease); }
@keyframes slideIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

.progress-stages { display: flex; margin-bottom: 16px; }
.progress-stage { flex: 1; text-align: center; position: relative; }
.progress-stage:not(:last-child)::after { content: ''; position: absolute; top: 14px; left: 50%; right: -50%; height: 2px; background: var(--border); transition: background var(--dur) var(--ease); z-index: 0; }
.progress-stage.done:not(:last-child)::after { background: var(--brand); }
.progress-stage-dot { width: 28px; height: 28px; border-radius: 50%; background: var(--bg); border: 2px solid var(--border-hover); display: flex; align-items: center; justify-content: center; margin: 0 auto 6px; position: relative; z-index: 1; transition: all var(--dur) var(--ease); font-size: 12px; font-weight: 600; color: var(--text-tertiary); }
.progress-stage.active .progress-stage-dot { border-color: var(--brand); color: var(--brand); box-shadow: 0 0 0 3px var(--brand-glow); }
.progress-stage.active .progress-stage-dot::after { content: ''; position: absolute; inset: -5px; border-radius: 50%; border: 2px solid var(--brand); opacity: 0.3; animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%,100% { transform: scale(1); opacity: 0.3; } 50% { transform: scale(1.2); opacity: 0; } }
.progress-stage.done .progress-stage-dot { background: var(--brand); border-color: var(--brand); }
.progress-stage.done .progress-stage-dot svg { width: 14px; height: 14px; stroke: white; fill: none; stroke-width: 3; }
.progress-stage-label { font-size: 11px; color: var(--text-tertiary); }
.progress-stage.active .progress-stage-label { color: var(--brand); }
.progress-stage.done .progress-stage-label { color: var(--text-primary); }

.progress-bar-wrap { height: 6px; background: var(--bg); border-radius: var(--radius-full); overflow: hidden; margin-bottom: 8px; }
.progress-bar-fill { height: 100%; width: 0; background: var(--brand-gradient); border-radius: var(--radius-full); transition: width var(--dur) var(--ease); position: relative; }
.progress-bar-fill::after { content: ''; position: absolute; inset: 0; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent); animation: shimmer 1.5s infinite; }
@keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
.progress-text { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-secondary); }
.progress-text .pct { font-weight: 600; color: var(--brand); font-family: var(--font-mono); }

.log-stream { margin-top: 12px; background: #010409; border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 10px 12px; max-height: 140px; overflow-y: auto; font-family: var(--font-mono); font-size: 11px; line-height: 1.7; display: none; }
.log-stream.show { display: block; }
.log-line { color: var(--text-tertiary); }
.log-line .time { color: #484F58; margin-right: 6px; }
.log-line.ok { color: var(--brand); }
.log-line.warn { color: var(--warning); }
.log-line.err { color: var(--danger); }

.result-section { display: none; }
.result-section.show { display: block; animation: slideIn var(--dur) var(--ease); }
.result-summary { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 12px; }
.stat-card { background: var(--bg-card); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: var(--radius); padding: 18px 12px; text-align: center; position: relative; overflow: hidden; }
.stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: var(--border); }
.stat-card.success::before { background: var(--brand); box-shadow: 0 0 12px var(--brand); }
.stat-card.skip::before { background: var(--warning); }
.stat-card.fail::before { background: var(--danger); }
.stat-num { font-size: 32px; font-weight: 800; line-height: 1; margin-bottom: 4px; font-variant-numeric: tabular-nums; }
.stat-card.success .stat-num { color: var(--brand); }
.stat-card.skip .stat-num { color: var(--warning); }
.stat-card.fail .stat-num { color: var(--danger); }
.stat-label { font-size: 12px; color: var(--text-secondary); }

.result-detail { background: var(--bg-card); backdrop-filter: blur(12px); border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
.detail-header { display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; cursor: pointer; border-bottom: 1px solid transparent; transition: background var(--dur); }
.detail-header:hover { background: rgba(255,255,255,0.03); }
.detail-header .left { display: flex; align-items: center; gap: 7px; font-size: 13px; font-weight: 600; }
.detail-header .left svg { width: 15px; height: 15px; stroke: currentColor; fill: none; stroke-width: 2; }
.detail-header .count { font-size: 11px; color: var(--text-tertiary); font-family: var(--font-mono); }
.detail-header .chevron { width: 16px; height: 16px; stroke: var(--text-tertiary); fill: none; stroke-width: 2; transition: transform var(--dur) var(--ease); }
.detail-header.open .chevron { transform: rotate(180deg); }
.detail-header.open { border-bottom-color: var(--border); }
.detail-body { max-height: 0; overflow: hidden; transition: max-height 0.4s var(--ease); }
.detail-body.open { max-height: 400px; overflow-y: auto; }
.skip-item { display: flex; align-items: center; justify-content: space-between; padding: 9px 16px; border-bottom: 1px solid rgba(48,54,61,0.5); font-size: 12px; }
.skip-item:last-child { border-bottom: none; }
.skip-item .song-name { color: var(--text-primary); }
.skip-item .song-reason { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: var(--radius-full); white-space: nowrap; }
.skip-item .song-reason.exists { background: rgba(210,153,34,0.15); color: var(--warning); }
.skip-item .song-reason.nomatch { background: rgba(248,81,73,0.15); color: var(--danger); }

.export-output { width: 100%; min-height: 240px; background: var(--bg-input); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 12px; font-family: var(--font-mono); font-size: 12px; line-height: 1.7; color: var(--text-primary); resize: vertical; }
.export-meta { display: flex; gap: 10px; margin-bottom: 12px; }
.meta-pill { display: flex; align-items: center; gap: 5px; background: var(--brand-glow); color: var(--brand); padding: 5px 12px; border-radius: var(--radius-full); font-size: 12px; font-weight: 600; }
.meta-pill svg { width: 13px; height: 13px; stroke: currentColor; fill: none; stroke-width: 2; }

.toast-container { position: fixed; top: 20px; right: 20px; z-index: 9999; display: flex; flex-direction: column; gap: 8px; }
.toast { display: flex; align-items: center; gap: 9px; background: var(--bg-card-solid); border: 1px solid var(--border); border-radius: var(--radius-sm); padding: 11px 14px; box-shadow: var(--shadow); font-size: 13px; font-weight: 500; min-width: 260px; animation: toastIn var(--dur) var(--ease); border-left: 3px solid var(--text-tertiary); }
@keyframes toastIn { from { opacity: 0; transform: translateX(100%); } to { opacity: 1; transform: translateX(0); } }
.toast.success { border-left-color: var(--brand); }
.toast.error { border-left-color: var(--danger); }
.toast.info { border-left-color: var(--cyan); }
.toast svg { width: 16px; height: 16px; flex-shrink: 0; }
.toast.success svg { stroke: var(--brand); fill: none; stroke-width: 2; }
.toast.error svg { stroke: var(--danger); fill: none; stroke-width: 2; }
.toast.info svg { stroke: var(--cyan); fill: none; stroke-width: 2; }

@media (max-width: 900px) { .main { padding: 16px 16px 40px; } .result-summary { grid-template-columns: 1fr; } }
@media (max-width: 480px) { .main { padding: 12px; } .form-card { padding: 16px; } .progress-stage-label { font-size: 10px; } .stat-num { font-size: 26px; } .topbar-inner { padding: 12px 16px 6px; } .tabs { max-width: 100%; } .export-meta { flex-direction: column; } }
</style>
</head>
<body>
<div class="app">
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand">
        <div class="brand-icon"><svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13M9 9l12-2M6 18a3 3 0 1 1-3-3 3 3 0 0 1 3 3zM18 16a3 3 0 1 1-3-3 3 3 0 0 1 3 3z"/></svg></div>
        <div class="brand-text"><h1>歌单工具箱</h1></div>
      </div>
      <div class="tabs">
        <button class="tab-btn active" id="tab-import-btn" onclick="switchTab('import')">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span>导入歌单</span>
        </button>
        <button class="tab-btn" id="tab-export-btn" onclick="switchTab('export')">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
          <span>导出歌单</span>
        </button>
      </div>
      <div class="safety-bar">
        <svg viewBox="0 0 24 24"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        <span>cookie 仅本次使用 · 不持久化 · 不上传第三方</span>
      </div>
    </div>
  </header>
  <main class="main">
    <div id="tab-import">
      <div class="page-header"><h2>导入歌单</h2><p>粘贴歌单内容，批量搜索匹配并加入你的 QQ 音乐歌单</p></div>
      <div class="form-card">
        <div class="form-label"><span class="step-badge">1</span>目标歌单链接</div>
        <div class="form-hint">打开你要导入进去的歌单，复制浏览器地址栏链接</div>
        <div class="input-wrap">
          <svg class="input-icon" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
          <input type="text" class="field with-icon" id="playlist_url" placeholder="https://y.qq.com/n/ryqq_v2/playlist/0000000000">
        </div>
      </div>
      <div class="form-card">
        <div class="form-label"><span class="step-badge">2</span>登录 Cookie<span class="badge-tag" id="cookieBadge" style="display:none;"></span></div>
        <div class="form-hint">用于以你的身份操作歌单，仅本次导入使用，不会保存</div>
        <div class="guide-toggle" id="guideToggle" onclick="toggleGuide()">
          <svg viewBox="0 0 24 24"><polyline points="9 18 15 12 9 6"/></svg><span>怎么获取 Cookie？（点击展开）</span>
        </div>
        <div class="guide-body" id="guideBody">
          <div class="guide-steps"><ol>
            <li>浏览器登录 <b>y.qq.com</b>，进入你的<b>歌单页面</b></li>
            <li>按 <b>F12</b> → <b>Network</b> 标签</li>
            <li>点歌单页面 <b>「编辑歌单」</b> 按钮触发请求</li>
            <li>找到 <code>musics.fcg</code> 请求</li>
            <li>右键 → <b>复制为 cURL (cmd)</b></li>
            <li>整段粘贴到下面输入框（自动提取 cookie）</li>
          </ol></div>
        </div>
        <div class="input-wrap" style="margin-top:8px;">
          <textarea class="field code" id="cookie" placeholder="粘贴 cURL 命令或 cookie 字符串…" oninput="checkCookieInput()"></textarea>
        </div>
      </div>
      <div class="form-card">
        <div class="form-label"><span class="step-badge">3</span>要导入的歌单<span class="badge-tag" id="songCount" style="display:none; background:rgba(88,166,255,0.12); color:var(--cyan);"></span></div>
        <div class="form-hint">每行一首，格式「歌名 - 歌手」</div>
        <textarea class="field songs" id="songs" placeholder="孤勇者 - 陈奕迅&#10;亲密关系 - 郑秀文&#10;Blinding Lights - The Weeknd" oninput="updateSongCount()"></textarea>
      </div>
      <div class="btn-center">
        <button class="btn btn-primary btn-lg" id="btnImport" onclick="startImport()">
          <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          <span id="btnImportText">开始导入</span>
        </button>
      </div>
      <div class="progress-section" id="progressSection">
        <div class="progress-stages">
          <div class="progress-stage" id="stage-0"><div class="progress-stage-dot">1</div><div class="progress-stage-label">读取歌单</div></div>
          <div class="progress-stage" id="stage-1"><div class="progress-stage-dot">2</div><div class="progress-stage-label">解析内容</div></div>
          <div class="progress-stage" id="stage-2"><div class="progress-stage-dot">3</div><div class="progress-stage-label">搜索匹配</div></div>
          <div class="progress-stage" id="stage-3"><div class="progress-stage-dot">4</div><div class="progress-stage-label">批量加歌</div></div>
        </div>
        <div class="progress-bar-wrap"><div class="progress-bar-fill" id="barFill"></div></div>
        <div class="progress-text"><span id="statusText">准备中…</span><span class="pct" id="pctText">0%</span></div>
        <div class="log-stream" id="logStream"></div>
      </div>
      <div class="result-section" id="resultSection"></div>
    </div>
    <div id="tab-export" style="display:none;">
      <div class="page-header"><h2>导出歌单</h2><p>输入歌单链接，导出为文本格式，方便发给 AI 分析口味</p></div>
      <div class="form-card">
        <div class="form-label">要导出的歌单链接（可多个）</div>
        <div class="form-hint">每行一个歌单链接，会按顺序合并导出</div>
        <textarea class="field" id="export_url" style="min-height:90px;" placeholder="https://y.qq.com/n/ryqq_v2/playlist/0000000000&#10;https://y.qq.com/n/ryqq_v2/playlist/1111111111"></textarea>
        <div class="btn-center">
          <button class="btn btn-primary" id="btnExport" onclick="doExport()">
            <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            <span id="btnExportText">导出歌单</span>
          </button>
        </div>
      </div>
      <div class="result-section" id="exportResultSection" style="display:none;">
        <div class="export-meta" id="exportMeta"></div>
        <textarea class="export-output" id="export_output" readonly></textarea>
        <div class="btn-center" style="gap:10px;">
          <button class="btn btn-primary" onclick="copyExport()"><svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>一键复制</button>
          <button class="btn btn-secondary" onclick="downloadTxt()"><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>下载 txt</button>
        </div>
      </div>
    </div>
  </main>
</div>
<div class="toast-container" id="toastContainer"></div>
<script>
function switchTab(t){document.getElementById('tab-import').style.display=t==='import'?'block':'none';document.getElementById('tab-export').style.display=t==='export'?'block':'none';document.getElementById('tab-import-btn').classList.toggle('active',t==='import');document.getElementById('tab-export-btn').classList.toggle('active',t==='export')}
function toggleGuide(){document.getElementById('guideToggle').classList.toggle('open');document.getElementById('guideBody').classList.toggle('open')}
function extractCookieLocal(input){let t=(input||'').trim();if(/^curl\b/i.test(t)||t.indexOf('--url')>=0||/-b\s/.test(t)){let m=t.match(/(?:-b|--cookie)\s+\^?"([^"]*?)\^?"/);if(m&&m[1]&&m[1].indexOf('=')>=0)return m[1].trim();m=t.match(/(?:-b|--cookie)\s+\^?'([^']*?)\^?'/);if(m&&m[1]&&m[1].indexOf('=')>=0)return m[1].trim();m=t.match(/(?:-H|--header)\s+\^?"?cookie:\s*([^"\n]+?)\^?"?/i);if(m&&m[1]&&m[1].indexOf('=')>=0)return m[1].trim();m=t.match(/(?:-H|--header)\s+\^?'?cookie:\s*([^'\n]+?)\^?'?/i);if(m&&m[1]&&m[1].indexOf('=')>=0)return m[1].trim();m=t.match(/uin=\d+[^\n"']*?qm_keyst=[^"'\s;]+/);if(m)return m[0].trim()}return t}
function checkCookieInput(){const raw=document.getElementById('cookie').value;const badge=document.getElementById('cookieBadge');if(!raw.trim()){badge.style.display='none';return}const ex=extractCookieLocal(raw);if(raw.trim().toLowerCase().startsWith('curl')||raw.includes('--url')||/-b\s/.test(raw)){badge.style.display='inline-flex';badge.textContent='cURL 已识别';badge.classList.add('detected')}else if(ex.includes('uin=')&&(ex.includes('qm_keyst')||ex.includes('qqmusic_key'))){badge.style.display='inline-flex';badge.textContent='Cookie 有效';badge.classList.add('detected')}else{badge.style.display='inline-flex';badge.textContent='待识别';badge.classList.remove('detected')}}
function updateSongCount(){const t=document.getElementById('songs').value.trim();const b=document.getElementById('songCount');if(!t){b.style.display='none';return}b.style.display='inline-flex';b.textContent=t.split('\n').filter(l=>l.trim()).length+' 首'}
function toast(m,t='info'){const c=document.getElementById('toastContainer');const e=document.createElement('div');e.className='toast '+t;const ic={success:'<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>',error:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',info:'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>'};e.innerHTML=ic[t]+'<span>'+m+'</span>';c.appendChild(e);setTimeout(()=>{e.style.opacity='0';e.style.transform='translateX(100%)';e.style.transition='all 0.3s';setTimeout(()=>e.remove(),300)},3000)}
function setStage(idx){for(let i=0;i<4;i++){const s=document.getElementById('stage-'+i);s.classList.remove('active','done');const d=s.querySelector('.progress-stage-dot');if(i<idx){s.classList.add('done');d.innerHTML='<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>'}else if(i===idx){s.classList.add('active');d.textContent=i+1}else{d.textContent=i+1}}}
function addLog(m,t=''){const s=document.getElementById('logStream');s.classList.add('show');const l=document.createElement('div');l.className='log-line '+t;const n=new Date();l.innerHTML='<span class="time">'+String(n.getHours()).padStart(2,'0')+':'+String(n.getMinutes()).padStart(2,'0')+':'+String(n.getSeconds()).padStart(2,'0')+'</span>'+m;s.appendChild(l);s.scrollTop=s.scrollHeight}
function updateProgress(p,m){document.getElementById('barFill').style.width=p+'%';document.getElementById('statusText').textContent=m;document.getElementById('pctText').textContent=p+'%'}
function getStage(m,p){if(m&&m.indexOf('读取')>=0)return 0;if(m&&m.indexOf('解析')>=0)return 1;if(m&&m.indexOf('匹配')>=0)return 2;if(m&&m.indexOf('加歌')>=0)return 3;if(p>=70)return 3;if(p>=15)return 2;if(p>=10)return 1;return 0}
let lastStage=-1;
function startImport(){
  const u=document.getElementById('playlist_url').value.trim();
  const c=extractCookieLocal(document.getElementById('cookie').value);
  if(c.indexOf('\n')>=0){toast('没提取到 cookie：请点开 musics.fcg 请求的 Request Headers，复制「cookie:」冒号后的整段值粘贴过来','error');return}
  const s=document.getElementById('songs').value.trim();
  if(!u){toast('请填写目标歌单链接','error');return}
  if(!c){toast('请粘贴 Cookie 或 cURL 命令','error');return}
  if(!s){toast('请粘贴要导入的歌单内容','error');return}
  const btn=document.getElementById('btnImport'),bt=document.getElementById('btnImportText');
  btn.disabled=true;bt.textContent='导入中…';
  document.getElementById('progressSection').classList.add('show');
  document.getElementById('resultSection').classList.remove('show');
  document.getElementById('resultSection').innerHTML='';
  document.getElementById('logStream').innerHTML='';
  document.getElementById('logStream').classList.remove('show');
  lastStage=-1;
  setStage(0);updateProgress(5,'正在读取目标歌单信息…');addLog('提交导入任务…');
  fetch('/api/import',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({playlist_url:u,cookie:c,songs:s})})
    .then(r=>r.json()).then(d=>{if(d.task_id){poll(d.task_id)}else{fail('提交失败')}})
    .catch(e=>fail('网络错误：'+e));
}
function poll(tid){
  fetch('/api/status/'+tid).then(r=>r.json()).then(d=>{
    const p=d.progress||0,m=d.message||'';
    updateProgress(p,m);
    const st=getStage(m,p);
    if(st!==lastStage&&m){setStage(st);addLog(m,'');lastStage=st}
    if(d.status==='done'){finish(d)}
    else if(d.status==='error'){fail(m||'出错了')}
    else{setTimeout(()=>poll(tid),800)}
  }).catch(e=>fail('查询状态失败：'+e));
}
function finish(d){
  const btn=document.getElementById('btnImport'),bt=document.getElementById('btnImportText');
  btn.disabled=false;bt.textContent='开始导入';
  setStage(4);updateProgress(100,'完成');addLog('导入完成','ok');
  showResult(d.result||{});
}
function fail(m){
  const btn=document.getElementById('btnImport'),bt=document.getElementById('btnImportText');
  btn.disabled=false;bt.textContent='开始导入';
  toast(m||'出错了','error');addLog(m||'出错了','err');
}
function showResult(r){
  const el=document.getElementById('resultSection');
  let h='<div class="result-summary"><div class="stat-card success"><div class="stat-num">'+(r.added||0)+'</div><div class="stat-label">成功导入</div></div><div class="stat-card skip"><div class="stat-num">'+(r.skipped||0)+'</div><div class="stat-label">跳过</div></div><div class="stat-card fail"><div class="stat-num">'+(r.failed||0)+'</div><div class="stat-label">失败</div></div></div>';
  if(r.skipped_detail&&r.skipped_detail.length){
    h+='<div class="result-detail"><div class="detail-header open" onclick="toggleDetail(this)"><div class="left"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>跳过的歌曲</div><div style="display:flex;align-items:center;gap:10px;"><span class="count">'+r.skipped_detail.length+' 首</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div><div class="detail-body open">';
    r.skipped_detail.forEach(x=>{const rc=(x.reason||'').indexOf('已')>=0?'exists':'nomatch';h+='<div class="skip-item"><span class="song-name">'+x.name+' - '+x.singer+'</span><span class="song-reason '+rc+'">'+x.reason+'</span></div>'});
    h+='</div></div>';
  }
  if(r.fail_detail&&r.fail_detail.length){
    h+='<div class="result-detail" style="margin-top:12px;"><div class="detail-header" onclick="toggleDetail(this)"><div class="left"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>失败详情</div><div style="display:flex;align-items:center;gap:10px;"><span class="count">'+(r.failed||0)+' 首</span><svg class="chevron" viewBox="0 0 24 24"><polyline points="6 9 12 15 18 9"/></svg></div></div><div class="detail-body">';
    r.fail_detail.forEach(f=>{h+='<div class="skip-item"><span class="song-name">code='+f.code+'（'+f.count+' 首）</span><span class="song-reason nomatch">失败</span></div>'});
    h+='</div></div>';
  }
  el.innerHTML=h;el.classList.add('show');
  toast('导入完成！成功 '+(r.added||0)+' 首','success');
}
function toggleDetail(h){const b=h.nextElementSibling;h.classList.toggle('open');b.classList.toggle('open')}
function doExport(){
  const u=document.getElementById('export_url').value.trim();
  if(!u){toast('请填写至少一个歌单链接','error');return}
  const btn=document.getElementById('btnExport'),bt=document.getElementById('btnExportText');
  btn.disabled=true;bt.textContent='导出中…';
  fetch('/api/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({playlist_url:u})})
    .then(r=>r.json()).then(d=>{
      btn.disabled=false;bt.textContent='导出歌单';
      if(d.error){toast(d.error,'error');return}
      document.getElementById('exportResultSection').style.display='block';
      document.getElementById('exportResultSection').classList.add('show');
      document.getElementById('exportMeta').innerHTML='<div class="meta-pill"><svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>'+(d.playlist_count||1)+' 个歌单</div><div class="meta-pill"><svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>'+d.count+' 首</div>';
      document.getElementById('export_output').value=d.text;
      document.getElementById('export_output').dataset.name=d.name;
      toast('导出成功：'+d.count+' 首','success');
    }).catch(e=>{btn.disabled=false;bt.textContent='导出歌单';toast('网络错误：'+e,'error')});
}
function copyExport(){const t=document.getElementById('export_output');t.select();document.execCommand('copy');toast('已复制到剪贴板','success')}
function downloadTxt(){const t=document.getElementById('export_output');const name=(t.dataset.name||'歌单导出').replace(/[\/:*?"<>|]/g,'_');const b=new Blob([t.value],{type:'text/plain;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=name+'.txt';a.click();toast('已下载 txt 文件','success')}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False)
