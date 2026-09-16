# -*- coding: utf-8 -*-
"""
从 app.py 里抽出内嵌前端，生成一个可以直接上传到 B 站 Toy 的纯静态页面。

背景：Toy 只做静态托管，跑不了 Python；而这个工具的签名/请求 QQ 音乐接口
必须由后端完成（浏览器直连会被 CORS 拦死）。所以 Toy 版采用前后端分离：
    Toy 静态页（UI，bilibili.com 域名）  ->  跨域 fetch  ->  Render 后端（API）

用法：
    python3 build_toy.py                      # 输出到 dist-toy/
    python3 build_toy.py --api https://xxx    # 指定别的后端地址
    python3 build_toy.py --zip                # 顺便打包 dist-toy/玩具箱_Toy版.zip
改完 app.py 后重新跑一次即可同步。
"""
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
APP_PY = os.path.join(HERE, "app.py")
DEFAULT_API = "https://qq-music-playlist-tool.onrender.com"

# ---------------------------------------------------------------- 注入片段
HEADER = r"""
<script>
/* ===== Toy 静态版专用：后端地址 + 网络容错 ===== */
var API_BASE = "__API_BASE__";
var FETCH_TIMEOUT_MS = 90000;

/* 包装 fetch：统一超时 + 把 Render 冷启动/网络拦截翻译成人话 */
(function () {
  var _fetch = window.fetch.bind(window);
  window.fetch = function (url, opt) {
    opt = opt || {};
    var isApi = typeof url === 'string' && url.indexOf(API_BASE) === 0;
    var done = false;
    var timer = setTimeout(function () {
      done = true;
      opt.__abort && opt.__abort();
    }, FETCH_TIMEOUT_MS);
    var ac = (typeof AbortController !== 'undefined') ? new AbortController() : null;
    if (ac) { opt.signal = ac.signal; opt.__abort = function(){ ac.abort(); }; }
    if (isApi) { opt.credentials = 'omit'; opt.mode = 'cors'; }
    var p = _fetch(url, opt).then(function (r) { clearTimeout(timer); return r; });
    p.catch(function (e) {
      clearTimeout(timer);
      if (e && (e.name === 'AbortError' || done)) {
        e.message = '请求超时（超过 ' + (FETCH_TIMEOUT_MS/1000) + ' 秒）。歌单数较多时 '
                  + '处理确实会更久，请稍后重试一次。';
      } else {
        e.message = '无法连接后端服务。免费后端一段时间无人访问会休眠，'
                  + '首次调用需要几十秒唤醒；若多次失败请联系作者。';
      }
      throw e;
    });
    return p;
  };
})();

/* 页面右上角的状态灯：探测后端是醒着还是在启动 */
(function () {
  function paint (state) {
    var el = document.getElementById('toyStatus');
    if (!el) return;
    el.style.display = 'inline-flex';
    var map = {
      checking: ['#f59e0b', '正在连接后端…'],
      online:   ['#22c55e', '后端已就绪'],
      sleeping: ['#ef4444', '连接后端失败']
    };
    var c = map[state] || map.checking;
    el.style.background = 'rgba(255,255,255,.05)';
    el.style.border = '1px solid rgba(255,255,255,.12)';
    el.style.borderRadius = '999px';
    el.style.padding = '5px 12px';
    el.style.fontSize = '12px';
    el.style.alignItems = 'center';
    el.style.gap = '7px';
    el.style.color = '#9aa0b4';
    el.innerHTML = '<span style="width:7px;height:7px;border-radius:50%;background:'
                 + c[0] + ';display:inline-block;"></span>' + c[1];
  }
  function probe () {
    paint('checking');
    fetch(API_BASE + '/').then(function (r) {
      paint(r.ok ? 'online' : 'sleeping');
    }).catch(function () { paint('sleeping'); });
  }
  window.addEventListener('DOMContentLoaded', function () {
    var host = document.querySelector('.safety-bar') || document.querySelector('.topbar-inner') || document.body;
    if (host && !document.getElementById('toyStatus')) {
      var el = document.createElement('span');
      el.id = 'toyStatus';
      el.style.marginLeft = '10px';
      host.appendChild(el);
    }
    probe();
  });
})();
</script>
"""

# 3 处相对路径 -> 绝对地址
REPLACES = [
    ("fetch('/api/import'", "fetch(API_BASE+'/api/import'"),
    ("fetch('/api/status/'+tid", "fetch(API_BASE+'/api/status/'+tid"),
    ("fetch('/api/export'", "fetch(API_BASE+'/api/export'"),
]


def extract_html():
    src = open(APP_PY, encoding="utf-8").read()
    m = re.search(r'^HTML = r"""(.*?)"""\s*$', src, re.S | re.M)
    if not m:
        raise SystemExit("没能在 app.py 里定位到 HTML = r\"\"\" ... \"\"\" 块")
    html = m.group(1)
    if html.startswith("\n"):
        html = html[1:]
    return html


def build(api_base, outdir):
    html = extract_html()

    for old, new in REPLACES:
        if old not in html:
            raise SystemExit("未找到待替换的调用：%s" % old)
        html = html.replace(old, new)

    inject = HEADER.replace("__API_BASE__", api_base.rstrip("/"))
    html = html.replace("<script>", inject + "\n<script>", 1)

    # Toy 是纯静态托管，页面里不能残留任何同源 API 假设
    assert "fetch('/api/" not in html, "仍有相对路径的 API 调用没被改写"
    # 静态页不该引用任何外部 CDN
    ext = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)', html)
    if ext:
        raise SystemExit("页面引用了外部资源，Toy 可能无法加载：%s" % ext)

    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "index.html")
    open(out, "w", encoding="utf-8").write(html)
    print("[生成] %s  (%.1f KB)" % (out, len(html.encode()) / 1024.0))
    return out


def make_zip(outdir, name="歌单工具箱_Toy静态版.zip"):
    zp = os.path.join(HERE, name)
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _d, files in os.walk(outdir):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.relpath(full, outdir))
    print("[打包] %s  (%.1f KB)" % (zp, os.path.getsize(zp) / 1024.0))
    return zp


if __name__ == "__main__":
    api, do_zip = DEFAULT_API, False
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--api" and i + 1 < len(argv):
            api = argv[i + 1]
        if a == "--zip":
            do_zip = True
    dist = os.path.join(HERE, "dist-toy")
    build(api, dist)
    if do_zip:
        make_zip(dist)
