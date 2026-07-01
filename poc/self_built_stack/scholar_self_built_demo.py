#!/usr/bin/env python3
"""自建栈 PoC（角度1+3+6 对照样例）：scholarly 取元数据 + 反爬位 + 住宅代理位 的最小集成骨架。

================================ ⚠️ 合规警告（务必先读）================================
直接抓取 Google Scholar 违反其 ToS 与 robots.txt，处于灰色地带，**仅供研究 / 学习 / 极小量自用**。
生产、合规、规模化场景请改用同目录的 `openalex_oa_pipeline.py` / `scholar_multi_pipeline.py`
（角度2 开放 API 主线：无人机验证、合规、稳定、字段齐全）。
====================================================================================

本脚本是「**确需直抓 Scholar 时**」的自建路线**对照样例**，演示三个角度如何拼装成一套栈：
  - 角度1（载体）：`scholarly` 取作者 / 文献元数据。
  - 角度3（反爬位）：`curl_cffi`(L1 TLS) / `nodriver`(L3 CDP) 等指纹对抗为**可选开关，默认关**；
                     内置「检测到验证码立即停」。
  - 角度6（代理位）：住宅 / 移动代理从 `--proxy` 或环境变量 `PROXY` 读取，**默认无**。
设计依据见同目录《检索成果-角度1-GitHub开源项目直检》《检索成果-角度3-反爬与反reCAPTCHA技术深度》
《检索成果-角度6-代理基础设施》。

安全默认：
  * **默认 dry-run**：不发任何 Scholar 请求，只打印「将要执行的计划 + 当前配置 + 合规提示」。
  * 真正联网需显式 `--execute`，且**强制极小量 + 限速（默认 10s）+ 指数退避 + 验证码即停**。
  * `--demo`：强制只取 1 条 + 强制限速，最稳妥的「能不能跑通」自检。
  * 缺少 `scholarly` / 可选依赖 / 代理时**优雅降级**（给提示而非崩溃）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# —— 自建路线的关键安全常量（呼应角度3/6 的限速与退避建议）——
DEFAULT_DELAY = 10.0          # 每次请求间隔（秒）。角度3：基线限速，别硬刚。
DEFAULT_MAX = 3              # 非 demo 时默认也只取极小量。
MAX_RETRIES = 4              # 指数退避最大重试次数。
BACKOFF_BASE = 5.0          # 指数退避基数（秒）：5,10,20,40 ...
# 命中以下任一标记即判定「被人机验证拦截」，立即停止（角度3：触发后退避换会话，不硬刚）。
CAPTCHA_MARKERS = (
    "captcha", "recaptcha", "unusual traffic", "/sorry/",
    "not a robot", "are you a robot", "cannot fetch", "blocked",
)


def load_scholarly():
    """尝试导入 scholarly（角度1 载体）。未安装时返回 None，由调用方优雅降级。"""
    try:
        import scholarly as _sch  # type: ignore  # noqa: F401  （可选运行时依赖，未装则降级）
        from scholarly import scholarly as scholarly_api  # type: ignore
        return scholarly_api
    except Exception:
        return None


def _mask(url: str) -> str:
    """隐藏代理 URL 中的账号密码，避免泄露到日志。"""
    if not url or "@" not in url:
        return url or ""
    head, tail = url.rsplit("@", 1)
    scheme = head.split("://", 1)[0] if "://" in head else ""
    return f"{scheme}://***:***@{tail}" if scheme else f"***@{tail}"


def setup_proxy(scholarly_api, proxy_url):
    """角度6：把住宅/移动代理喂给 scholarly 的 ProxyGenerator。

    返回 (是否启用, 说明文本)。无代理 / 设置失败均**不抛异常**，仅降级提示。
    """
    if not proxy_url:
        return False, ("未配置代理（角度6）：直抓 Scholar 极易被封 IP / 弹验证码。"
                       "强烈建议设 PROXY 环境变量或 --proxy 指向**住宅代理**（见角度6）。")
    if scholarly_api is None:
        return False, "scholarly 未安装，代理位暂不生效（仅记录配置）。"
    try:
        from scholarly import ProxyGenerator  # type: ignore
        pg = ProxyGenerator()
        ok = pg.SingleProxy(http=proxy_url, https=proxy_url)
        if ok:
            scholarly_api.use_proxy(pg)
            return True, f"已启用单一代理（角度6）：{_mask(proxy_url)}"
        return False, "代理设置失败（ProxyGenerator.SingleProxy 返回 False）——请检查代理可用性。"
    except Exception as e:  # 网络/依赖/代理异常都降级
        return False, f"代理设置异常（已降级为无代理）：{e}"


def antibot_status(engine: str):
    """角度3：反爬「位」。检查所选指纹对抗引擎是否可用（默认 none = 走 scholarly 默认传输）。

    说明：scholarly 自带请求传输；要真正替换为 curl_cffi(L1)/nodriver(L3) 需在「取页」层接管，
    属生产化改造（见角度3）。本骨架只做**可用性探测 + 接入点说明**，不强行改写 scholarly 内部。
    返回 (是否可用, 说明文本)。
    """
    engine = (engine or "none").lower()
    if engine in ("none", "requests"):
        return True, "反爬引擎=none（默认）：用 scholarly 默认传输；轻量但易被识别，仅适合极小量。"
    if engine == "curl_cffi":
        try:
            import curl_cffi  # noqa: F401
            return True, ("反爬引擎=curl_cffi（角度3·L1）：可在取页层用 impersonate 模拟真实 "
                          "Chrome 的 TLS/HTTP2 指纹（需自行接管 scholarly 取页或改用静态解析）。")
        except Exception:
            return False, "已选 curl_cffi 但未安装：`pip install curl_cffi`（角度3·L1）。已降级为默认传输。"
    if engine == "nodriver":
        try:
            import nodriver  # noqa: F401
            return True, ("反爬引擎=nodriver（角度3·L3）：直连 CDP、规避自动化协议指纹，"
                          "benchmark 表现最佳；需以浏览器方式取页后再交给解析（生产化改造）。")
        except Exception:
            return False, "已选 nodriver 但未安装：`pip install nodriver`（角度3·L3）。已降级为默认传输。"
    return False, f"未知反爬引擎 {engine!r}，已降级为默认传输。可选：none / curl_cffi / nodriver。"


def looks_like_captcha(text: str) -> bool:
    """根据文本/异常信息判断是否疑似命中人机验证或封禁。"""
    low = (text or "").lower()
    return any(m in low for m in CAPTCHA_MARKERS)


def polite_sleep(delay: float, reason: str = "") -> None:
    """限速等待（角度3：基线限速 + 抖动留给生产化）。"""
    tag = f"（{reason}）" if reason else ""
    print(f"    · 限速等待 {delay:.0f}s{tag} ...", file=sys.stderr)
    time.sleep(max(0.0, delay))


def run_live_demo(scholarly_api, query: str, max_n: int, delay: float, out_dir: Path) -> int:
    """真正联网的**极小量**抓取（仅 --execute 时调用）。验证码即停 + 指数退避。"""
    print(f"[live] scholarly 检索（角度1）：{query!r}，最多 {max_n} 条 ...", file=sys.stderr)
    try:
        search = scholarly_api.search_pubs(query)
    except Exception as e:
        msg = str(e)
        if looks_like_captcha(msg):
            print(f"[stop] 一开始就疑似命中人机验证：{msg}。立即停止（角度3：不硬刚）。", file=sys.stderr)
            return 3
        print(f"[err] 检索初始化失败：{msg}", file=sys.stderr)
        return 2

    records, got = [], 0
    while got < max_n:
        attempt, item = 0, None
        while attempt <= MAX_RETRIES:
            try:
                item = next(search)
                break
            except StopIteration:
                item = None
                break
            except Exception as e:
                msg = str(e)
                if looks_like_captcha(msg):
                    print(f"[stop] 检测到验证码/封禁：{msg}。立即停止并保存已得结果（角度3）。",
                          file=sys.stderr)
                    item = None
                    attempt = MAX_RETRIES + 1
                    break
                attempt += 1
                if attempt > MAX_RETRIES:
                    print(f"[err] 连续失败超过 {MAX_RETRIES} 次，放弃：{msg}", file=sys.stderr)
                    break
                back = BACKOFF_BASE * (2 ** (attempt - 1))
                print(f"[retry {attempt}/{MAX_RETRIES}] 取条目失败：{msg}", file=sys.stderr)
                polite_sleep(back, reason="指数退避")
        if item is None:
            break

        bib = (item.get("bib") if isinstance(item, dict) else {}) or {}
        rec = {
            "title": bib.get("title"),
            "authors": bib.get("author"),
            "year": bib.get("pub_year"),
            "venue": bib.get("venue"),
            "num_citations": item.get("num_citations") if isinstance(item, dict) else None,
            "pub_url": item.get("pub_url") if isinstance(item, dict) else None,
            "eprint_url": item.get("eprint_url") if isinstance(item, dict) else None,
        }
        got += 1
        records.append(rec)
        print(f"  [{got:>2}/{max_n}] {(rec['title'] or '')[:72]}", file=sys.stderr)
        if got < max_n:
            polite_sleep(delay, reason="基线限速")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "metadata.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[done] 取得 {len(records)} 条，写入 {out_file}", file=sys.stderr)
    print(json.dumps({"query": query, "fetched": len(records),
                      "out": out_file.as_posix()}, ensure_ascii=False))
    return 0


def print_dry_run(cfg: dict) -> int:
    """默认 dry-run：不联网，只打印计划与配置（满足「绝不在本任务里真的抓 Scholar」）。"""
    print("=" * 78)
    print("DRY-RUN（默认）：不会发出任何 Google Scholar 请求。加 --execute 才会真正联网。")
    print("=" * 78)
    print("【将要执行的自建栈流水线（角度1+3+6）】")
    print("  1) 角度6 代理位 → 2) 角度3 反爬位 → 3) 角度1 scholarly 检索 → 限速/退避/验证码即停 → 入库")
    print("")
    print("【当前配置】")
    print(f"  query        : {cfg['query']!r}")
    print(f"  max          : {cfg['max']}（demo={cfg['demo']}；demo 时强制 1 条）")
    print(f"  delay        : {cfg['delay']:.0f}s（基线限速）")
    print(f"  反爬引擎      : {cfg['engine']}  ->  {cfg['antibot_note']}")
    print(f"  代理(角度6)   : {'启用' if cfg['proxy_on'] else '未启用'}  ->  {cfg['proxy_note']}")
    print(f"  scholarly    : {'已安装' if cfg['has_scholarly'] else '未安装（pip install scholarly）'}")
    print(f"  out          : {cfg['out']}")
    print("")
    print("【合规提示】直抓 Scholar 违反 ToS/robots.txt，仅研究自用；生产请走角度2 主线（见 ../）。")
    print("【下一步】确认配置无误后，加 --execute 进行极小量真实抓取（务必先配住宅代理）。")
    # dry-run 同样给一个机器可读摘要，便于脚本化校验
    print(json.dumps({
        "mode": "dry-run", "query": cfg["query"], "max": cfg["max"],
        "engine": cfg["engine"], "proxy_on": cfg["proxy_on"],
        "has_scholarly": cfg["has_scholarly"],
    }, ensure_ascii=False))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="自建栈 PoC（角度1+3+6）：scholarly + 反爬位 + 代理位，默认 dry-run、强合规警告。")
    ap.add_argument("query", nargs="?", default=None,
                    help='检索关键词，例如 "deep learning"；省略且 --demo 时用内置示例词。')
    ap.add_argument("--demo", action="store_true",
                    help="自检模式：强制只取 1 条 + 强制限速（最稳妥的跑通验证）。")
    ap.add_argument("--execute", action="store_true",
                    help="真正联网抓取（否则默认 dry-run，不发任何 Scholar 请求）。")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX,
                    help=f"最多取多少条（默认 {DEFAULT_MAX}；--demo 强制 1）。")
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY,
                    help=f"请求间隔秒（默认 {DEFAULT_DELAY:.0f}；--demo 不低于该值）。")
    ap.add_argument("--engine", default="none", choices=["none", "requests", "curl_cffi", "nodriver"],
                    help="角度3 反爬引擎位（默认 none）。curl_cffi=L1 指纹、nodriver=L3 CDP。")
    ap.add_argument("--proxy", default=None,
                    help="角度6 代理，如 http://user:pass@host:port；默认读环境变量 PROXY。")
    ap.add_argument("--out", default="out_self_built", help="输出目录（默认 ./out_self_built）。")
    args = ap.parse_args(argv)

    # 合规横幅永远先打印
    print("#" * 78, file=sys.stderr)
    print("# 自建栈 PoC（角度1+3+6）｜[!] 直抓 Google Scholar 属灰色地带，仅研究自用。", file=sys.stderr)
    print("# 合规/生产首选角度2 开放 API 主线：../openalex_oa_pipeline.py / ../scholar_multi_pipeline.py", file=sys.stderr)
    print("#" * 78, file=sys.stderr)

    query = args.query or ("deep learning" if args.demo else None)
    if not query:
        print("[err] 请提供检索关键词，或加 --demo 使用内置示例词。", file=sys.stderr)
        return 1

    max_n = 1 if args.demo else max(1, args.max)
    delay = max(args.delay, DEFAULT_DELAY) if args.demo else max(0.0, args.delay)

    scholarly_api = load_scholarly()
    proxy_url = args.proxy or os.environ.get("PROXY")
    proxy_on, proxy_note = setup_proxy(scholarly_api, proxy_url)
    engine_ok, antibot_note = antibot_status(args.engine)

    cfg = {
        "query": query, "max": max_n, "delay": delay, "demo": args.demo,
        "engine": args.engine, "antibot_note": antibot_note, "engine_ok": engine_ok,
        "proxy_on": proxy_on, "proxy_note": proxy_note,
        "has_scholarly": scholarly_api is not None, "out": args.out,
    }

    # 配置层提示（无论 dry-run 还是 live 都先告知）
    print(f"[cfg] 代理：{proxy_note}", file=sys.stderr)
    print(f"[cfg] 反爬：{antibot_note}", file=sys.stderr)

    if not args.execute:
        return print_dry_run(cfg)

    # —— 以下为 --execute 真实联网路径（极小量 + 限速 + 退避 + 验证码即停）——
    if scholarly_api is None:
        print("[degrade] 未安装 scholarly，无法真正抓取。请 `pip install scholarly` 后重试。", file=sys.stderr)
        print("[hint] 仅想看流程？去掉 --execute 即为 dry-run。", file=sys.stderr)
        return 0  # 优雅降级，不崩溃
    if not proxy_on:
        print("[warn] 未启用代理仍要 --execute：直抓 Scholar 极易被封，已强制 demo 级（1 条）。", file=sys.stderr)
        max_n = 1
    print("[live] 即将进行极小量真实抓取（角度1+3+6）。如非本意请 Ctrl-C。", file=sys.stderr)
    polite_sleep(min(delay, DEFAULT_DELAY), reason="启动前缓冲")
    return run_live_demo(scholarly_api, query, max_n, delay, Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
