# 自建栈 PoC（角度1+3+6 对照样例）

> scholarly 取元数据（角度1）+ 反爬位（角度3）+ 住宅代理位（角度6）的**最小集成骨架**。
> 与上级目录 `../`（角度2 开放 API 主线 PoC）形成「**自建 vs 走正门**」对照。
> 整理人：谷歌学术人机认证-152（任务发起：140）｜日期：2026-07-01

---

## ⚠️ 合规警告（务必先读）

- **直接抓取 Google Scholar 违反其 ToS 与 `robots.txt`**，处于灰色地带，**仅供研究 / 学习 / 极小量自用**。
- **生产、合规、规模化请改用上级目录的角度2 主线**：`../openalex_oa_pipeline.py` / `../scholar_multi_pipeline.py`（开放 API：**无人机验证、合规、稳定**）。
- 本样例**默认 dry-run**（不发任何 Scholar 请求）；即便 `--execute` 也**强制极小量 + 限速 + 指数退避 + 验证码即停**，**请勿用于大规模抓取**。
- 直抓前请**自备住宅代理**并遵守限速；触发验证码应**立即退避**，不要硬刚（见《检索成果-角度3》）。

---

## 这是什么

「**确需直抓 Scholar 时**」的自建路线**对照样例**，演示角度1/3/6 如何拼成一套栈：

| 槽位 | 角度 | 本样例做法 | 默认 |
| --- | --- | --- | --- |
| 载体 | **角度1** | `scholarly` 取文献元数据（标题/作者/年/被引/链接） | 必需（联网时） |
| 反爬位 | **角度3** | `--engine` 选 `none`/`curl_cffi`(L1)/`nodriver`(L3)；做可用性探测 + 接入点说明 | `none`（关） |
| 代理位 | **角度6** | `--proxy` 或环境变量 `PROXY` → 喂给 scholarly 的 `ProxyGenerator.SingleProxy` | 无 |

内置安全：**限速默认 10s** + **指数退避** + **「检测到验证码立即停」** + **缺依赖/缺代理优雅降级**（提示而非崩溃）。

---

## 安装

```bash
# dry-run 不需要任何依赖；真正联网（--execute）才需要 scholarly
pip install -r requirements.txt
# 可选：角度3 指纹对抗引擎（按需，取消 requirements.txt 中注释）
# pip install curl_cffi      # 或 nodriver
```

## 用法

```bash
# 1) 默认 dry-run：只打印计划与配置，不发任何 Scholar 请求（最安全，先看这个）
python scholar_self_built_demo.py "deep learning"

# 2) 自检模式：强制 1 条 + 强制限速（dry-run 下查看 demo 计划）
python scholar_self_built_demo.py --demo

# 3) 查看「带代理 + curl_cffi 反爬位」时的配置（仍是 dry-run，不联网）
python scholar_self_built_demo.py "graph neural network" --engine curl_cffi --proxy http://user:pass@host:port

# 4) 真正联网的极小量抓取（⚠️ 谨慎！务必先配住宅代理）：
PROXY="http://user:pass@residential-host:port" \
python scholar_self_built_demo.py "deep learning" --demo --execute
```

### 参数
- `query`：检索关键词（省略且 `--demo` 时用内置示例词 `deep learning`）。
- `--demo`：强制只取 1 条 + 强制限速（最稳妥的跑通验证）。
- `--execute`：**真正联网**（否则默认 dry-run）。
- `--max N`：最多取多少条（默认 3；`--demo` 强制 1）。
- `--delay S`：请求间隔秒（默认 10；`--demo` 不低于 10）。
- `--engine`：角度3 反爬位 `none|requests|curl_cffi|nodriver`（默认 `none`）。
- `--proxy URL`：角度6 代理；默认读环境变量 `PROXY`。
- `--out DIR`：输出目录（默认 `./out_self_built`）。

### 输出
- `out_self_built/metadata.jsonl`：每行一条文献元数据（仅 `--execute` 成功时）。
- 终端：dry-run / live 均打印一行 JSON 摘要，便于脚本化校验。

---

## 与角度2 主线的对照（为什么默认还是走正门）

| 维度 | 本样例（自建：角度1+3+6） | `../` 角度2 主线 |
| --- | --- | --- |
| 人机验证 | 有，需限速/代理/（必要时）打码 | **无** |
| 合规 | 灰色（违反 ToS） | **白色，官方鼓励** |
| 维护成本 | 高（随反爬升级失效） | 低（稳定 API） |
| 适用 | 确需 Scholar 原生被引/版本时的小量自用 | **绝大多数需求的首选** |

> 结论：**能走角度2 就走角度2**；本样例只为「确需直抓 Scholar」时提供一个可读的集成骨架。
> 反爬技术细节见《检索成果-角度3》、代理供应商与自建代理池见《检索成果-角度6》、
> 现成 GitHub 载体见《检索成果-角度1》。
