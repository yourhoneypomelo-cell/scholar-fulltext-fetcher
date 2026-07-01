"""Zotero Web API 直写客户端(纯 requests,best-effort、全程容错)。

把"下载成功的文献"一键写入用户自己的 Zotero 个人库 / 群组库:
  1. 逐条构造 journalArticle 条目(title / DOI / creators(authors) / date / publicationTitle),
     POST https://api.zotero.org/{users|groups}/{id}/items(每批 ≤50)。—— 必做。
  2. 对有本地 PDF(pdf_path)的条目,可选把 PDF 作为子附件上传。—— 增强,失败不影响条目写入。

设计原则(与本项目其它模块一致):
  - 纯函数式、对异常高度容忍:任何网络/解析错误只记日志,绝不抛出影响主流程(pipeline 已跑完)。
  - 不改动任何既有数据结构:results 元素既支持 dataclass(FetchResult/Paper)也支持 dict。
    字段映射以 fulltext_fetcher/models.py 与 poc/scholar_multi_pipeline.py 为准,缺失字段留空
    (Zotero 侧可凭 DOI 自行补全)。
  - requests 为本项目既有强制依赖(见 requirements.txt),不新增任何依赖。

合规:使用者自备 Zotero API Key,仅写入本人有写权限的库。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

_API_BASE = "https://api.zotero.org"
_API_VERSION = "3"
_BATCH = 50          # Zotero /items 单次最多 50 条
_TIMEOUT = 30.0


# ── 小工具:容错日志 / 字段读取 ──────────────────────────────────────────────
def _log(log: Any, level: str, msg: str, *args: Any) -> None:
    """容忍 log 为 None 或非标准 logger:能记就记,记不了就静默(绝不因日志抛错)。"""
    if log is None:
        return
    fn = getattr(log, level, None)
    if callable(fn):
        try:
            fn(msg, *args)
        except Exception:  # noqa: BLE001 - 日志失败绝不影响主流程
            pass


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """同时支持 dict(get)与 dataclass/对象(getattr)读取字段。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _authors_to_creators(authors: Any) -> List[Dict[str, str]]:
    """把 authors 映射为 Zotero creators。

    兼容:List[str](models.Paper.authors)、List[dict]({'name'} 或 {'family','given'})、
    以及单个字符串(容错)。空/无名者跳过。
    """
    if isinstance(authors, str):
        authors = [authors] if authors.strip() else []
    creators: List[Dict[str, str]] = []
    for a in authors or []:
        if isinstance(a, dict):
            if a.get("family") or a.get("given"):
                creators.append({
                    "creatorType": "author",
                    "firstName": (a.get("given") or "").strip(),
                    "lastName": (a.get("family") or "").strip(),
                })
                continue
            name = (a.get("name") or a.get("literal") or "").strip()
        else:
            name = str(a).strip()
        if name:
            creators.append({"creatorType": "author", "name": name})
    return creators


def build_item(result: Any) -> Dict[str, Any]:
    """由一条结果(FetchResult / Paper / dict)构造 Zotero journalArticle 条目载荷。

    映射(缺失留空):
      title            ← title
      DOI              ← doi
      creators         ← authors
      date             ← year
      publicationTitle ← journal / publicationTitle / venue
    """
    year = _get(result, "year")
    journal = (_get(result, "journal")
               or _get(result, "publicationTitle")
               or _get(result, "venue")
               or "")
    return {
        "itemType": "journalArticle",
        "title": (_get(result, "title") or "").strip(),
        "creators": _authors_to_creators(_get(result, "authors")),
        "date": str(year) if year else "",
        "DOI": (_get(result, "doi") or "").strip(),
        "publicationTitle": (journal or "").strip(),
    }


# ── HTTP 编排 ────────────────────────────────────────────────────────────────
def _extract_keys(body: Dict[str, Any]) -> Dict[int, str]:
    """从 /items 响应中提取 {批内下标: itemKey}。兼容 success / successful 两种字段。"""
    idx_to_key: Dict[int, str] = {}
    for k, v in (body.get("success") or {}).items():
        try:
            idx = int(k)
        except (TypeError, ValueError):
            continue
        if v:
            idx_to_key[idx] = v
    if not idx_to_key:
        for k, v in (body.get("successful") or {}).items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                continue
            key = (v or {}).get("key") or ((v or {}).get("data") or {}).get("key")
            if key:
                idx_to_key[idx] = key
    return idx_to_key


def _post_items_batch(session: Any, items: List[Dict[str, Any]], api_key: str,
                      library_id: str, library_type: str, log: Any) -> Dict[int, str]:
    """POST 一批(≤50)条目;返回 {批内下标: itemKey}。失败返回空 dict(不抛错)。"""
    url = f"{_API_BASE}/{library_type}s/{library_id}/items"
    headers = {
        "Zotero-API-Key": api_key,
        "Zotero-API-Version": _API_VERSION,
        "Content-Type": "application/json",
    }
    resp = session.post(url, headers=headers,
                        data=json.dumps(items).encode("utf-8"), timeout=_TIMEOUT)
    if resp.status_code not in (200, 201):
        _log(log, "warning", "Zotero 写入返回 HTTP %s: %s",
             resp.status_code, (getattr(resp, "text", "") or "")[:200])
        return {}
    body = resp.json() or {}
    failed = body.get("failed") or {}
    if failed:
        _log(log, "warning", "Zotero 本批 %d 条写入失败: %s",
             len(failed), json.dumps(failed, ensure_ascii=False)[:200])
    return _extract_keys(body)


def _upload_attachment(session: Any, parent_key: str, pdf_path: str, api_key: str,
                       library_id: str, library_type: str, log: Any) -> bool:
    """把本地 PDF 作为子附件上传到某父条目(增强功能,全程容错)。

    Zotero 文件上传四步:创建 attachment 条目 → 请求上传授权 → 直传存储 → 注册上传完成。
    任何一步失败/异常都返回 False,绝不影响条目本身。
    """
    if not pdf_path or not os.path.isfile(pdf_path):
        return False
    base = f"{_API_BASE}/{library_type}s/{library_id}/items"
    auth_key = {"Zotero-API-Key": api_key, "Zotero-API-Version": _API_VERSION}
    filename = os.path.basename(pdf_path)

    # 1) 创建 attachment 子条目(imported_file)
    tpl = [{
        "itemType": "attachment",
        "parentItem": parent_key,
        "linkMode": "imported_file",
        "title": "Full Text PDF",
        "contentType": "application/pdf",
        "filename": filename,
        "charset": "",
        "note": "",
        "tags": [],
        "relations": {},
    }]
    r = session.post(base, headers={**auth_key, "Content-Type": "application/json"},
                     data=json.dumps(tpl).encode("utf-8"), timeout=_TIMEOUT)
    if r.status_code not in (200, 201):
        _log(log, "warning", "Zotero 附件条目创建失败 HTTP %s", r.status_code)
        return False
    keys = _extract_keys(r.json() or {})
    attach_key = keys.get(0)
    if not attach_key:
        return False

    # 2) 请求上传授权(md5/filename/filesize/mtime + params=1)
    with open(pdf_path, "rb") as f:
        content = f.read()
    md5 = hashlib.md5(content).hexdigest()
    file_url = f"{base}/{attach_key}/file"
    form_headers = {**auth_key,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "If-None-Match": "*"}
    ra = session.post(file_url, headers=form_headers, data={
        "md5": md5,
        "filename": filename,
        "filesize": str(len(content)),
        "mtime": str(int(os.path.getmtime(pdf_path) * 1000)),
        "params": "1",
    }, timeout=_TIMEOUT)
    if ra.status_code != 200:
        _log(log, "warning", "Zotero 附件上传授权失败 HTTP %s", ra.status_code)
        return False
    auth = ra.json() or {}
    if auth.get("exists"):
        return True  # 服务端已存在同一文件,无需再传

    upload_url = auth.get("url")
    upload_key = auth.get("uploadKey")
    if not upload_url or upload_key is None:
        return False

    # 3) 直传存储(prefix + 文件字节 + suffix)
    payload = (auth.get("prefix", "") or "").encode("utf-8") + content \
        + (auth.get("suffix", "") or "").encode("utf-8")
    ru = session.post(upload_url,
                      headers={"Content-Type": auth.get("contentType", "application/pdf")},
                      data=payload, timeout=_TIMEOUT * 3)
    if ru.status_code not in (200, 201):
        _log(log, "warning", "Zotero 附件直传失败 HTTP %s", ru.status_code)
        return False

    # 4) 注册上传完成
    reg = session.post(file_url, headers=form_headers, data={"upload": upload_key},
                       timeout=_TIMEOUT)
    if reg.status_code not in (200, 204):
        _log(log, "warning", "Zotero 附件注册失败 HTTP %s", reg.status_code)
        return False
    return True


def push_items(api_key: str, library_id: str, library_type: str = "user",
               results: Optional[List[Any]] = None, log: Any = None,
               *, upload_pdf: bool = True, session: Any = None) -> int:
    """把结果列表写入 Zotero 库,返回成功写入的条目数。全程容错,绝不抛出。

    参数:
      api_key/library_id : 用户自备的 Zotero API Key 与库 ID(users/{id} 或 groups/{id})。
      library_type       : "user"(默认)| "group"。
      results            : FetchResult / Paper / dict 的列表(调用方通常只传成功项)。
      log                : 可选 logger(有 info/warning 即可);None 时静默。
      upload_pdf         : 是否为有 pdf_path 的条目附带上传 PDF(增强,默认开)。
      session            : 可选 requests.Session(便于测试注入;默认自建)。
    """
    results = list(results or [])
    if not api_key or not library_id:
        _log(log, "warning", "未提供 Zotero key / library id,跳过入库。")
        return 0
    if not results:
        return 0
    library_type = (library_type or "user").lower()
    if library_type not in ("user", "group"):
        library_type = "user"

    if session is None:
        try:
            import requests  # 已是本项目强制依赖(requirements.txt)
        except ImportError:  # 极端环境兜底:缺依赖也不影响主流程
            _log(log, "warning", "缺少 requests,无法写入 Zotero,已跳过。")
            return 0
        session = requests.Session()

    total_ok = 0
    n = len(results)
    for start in range(0, n, _BATCH):
        chunk = results[start:start + _BATCH]
        items = [build_item(r) for r in chunk]
        try:
            idx_to_key = _post_items_batch(session, items, api_key,
                                           library_id, library_type, log)
        except Exception as e:  # noqa: BLE001 - 单批异常只跳过本批
            _log(log, "warning", "Zotero 批次写入异常(跳过本批): %s", e)
            idx_to_key = {}
        total_ok += len(idx_to_key)

        if upload_pdf:
            for local_idx, key in idx_to_key.items():
                pdf_path = _get(chunk[local_idx], "pdf_path")
                if not pdf_path:
                    continue
                try:
                    _upload_attachment(session, key, pdf_path, api_key,
                                       library_id, library_type, log)
                except Exception as e:  # noqa: BLE001 - 附件失败忽略
                    _log(log, "warning", "Zotero 附件上传异常(忽略): %s", e)

        if start + _BATCH < n:
            time.sleep(1.0)  # 礼貌限速,避免触发 Zotero 写入频控

    _log(log, "info", "Zotero 入库完成:成功 %d/%d 条 → %s 库 %s",
         total_ok, n, library_type, library_id)
    return total_ok


# ── 不联网 selftest:python -m fulltext_fetcher.zotero(或加 --selftest)───────
def _selftest() -> int:
    """monkeypatch 掉 HTTP,断言条目载荷结构与批量编排正确,最后打印 ZOTERO_OK。"""
    import tempfile

    class _FakeResp:
        def __init__(self, status: int, payload: Any = None, text: str = ""):
            self.status_code = status
            self._payload = {} if payload is None else payload
            self.text = text

        def json(self) -> Any:
            return self._payload

    class _FakeSession:
        """按 URL/表单内容模拟 Zotero /items 与文件上传四步的最小假服务端。"""
        def __init__(self) -> None:
            self.calls: List[Dict[str, Any]] = []

        def post(self, url, headers=None, data=None, timeout=None):  # noqa: ANN001
            self.calls.append({"url": url, "headers": headers or {}, "data": data})
            if url.endswith("/file"):
                body = data if isinstance(data, dict) else {}
                if "upload" in body:                       # 第4步:注册
                    return _FakeResp(204)
                return _FakeResp(200, {                     # 第2步:授权
                    "url": "https://storage.test/put",
                    "prefix": "PRE", "suffix": "SUF",
                    "contentType": "application/pdf", "uploadKey": "UPKEY123",
                })
            if url.endswith("/items"):                      # 条目/附件条目创建
                raw = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
                items = json.loads(raw)
                return _FakeResp(200, {
                    "success": {str(i): f"KEY{i:04d}" for i in range(len(items))},
                    "successful": {}, "failed": {},
                })
            return _FakeResp(201)                            # 第3步:直传存储

    # ① build_item 直测:完整对象 → itemType / DOI / creators / date / publicationTitle
    class _R:
        title = "Deep Learning"
        doi = "10.1000/xyz"
        authors = ["Alice Smith", "Bob Lee"]
        year = 2021
        journal = "Nature"
        pdf_path = None

    it = build_item(_R())
    assert it["itemType"] == "journalArticle", it
    assert it["title"] == "Deep Learning" and it["DOI"] == "10.1000/xyz", it
    assert it["date"] == "2021" and it["publicationTitle"] == "Nature", it
    assert it["creators"] == [
        {"creatorType": "author", "name": "Alice Smith"},
        {"creatorType": "author", "name": "Bob Lee"},
    ], it["creators"]

    # dict 输入 + venue 回退 + 结构化作者(family/given)
    it2 = build_item({"title": "T2", "doi": "10.2/a", "venue": "JMLR",
                      "authors": [{"family": "Ng", "given": "Andrew"}]})
    assert it2["publicationTitle"] == "JMLR" and it2["date"] == "", it2
    assert it2["creators"] == [
        {"creatorType": "author", "firstName": "Andrew", "lastName": "Ng"}], it2["creators"]

    # 仅有 title/doi 的精简结果(如 FetchResult)也不报错、creators 为空
    it3 = build_item({"title": "OnlyTitle", "doi": "10.3/b"})
    assert it3["itemType"] == "journalArticle" and it3["creators"] == [], it3

    # ② push_items(仅条目)——断言真正发出的批量载荷结构 + 返回计数
    fake = _FakeSession()
    results = [
        {"title": "P1", "doi": "10.1/p1", "authors": ["A"], "year": 2020, "journal": "J1"},
        {"title": "P2", "doi": "10.2/p2", "authors": ["B", "C"], "year": 2021, "journal": "J2"},
    ]
    n_ok = push_items("FAKEKEY", "123456", "user", results, None,
                      upload_pdf=False, session=fake)
    assert n_ok == 2, n_ok
    call = fake.calls[0]
    assert call["url"] == "https://api.zotero.org/users/123456/items", call["url"]
    assert call["headers"]["Zotero-API-Key"] == "FAKEKEY", call["headers"]
    assert call["headers"]["Zotero-API-Version"] == "3", call["headers"]
    sent = json.loads(call["data"].decode("utf-8"))
    assert len(sent) == 2 and sent[0]["itemType"] == "journalArticle", sent
    assert sent[0]["DOI"] == "10.1/p1" and sent[1]["DOI"] == "10.2/p2", sent
    assert sent[1]["creators"] == [
        {"creatorType": "author", "name": "B"},
        {"creatorType": "author", "name": "C"},
    ], sent[1]["creators"]

    # ③ group 库 URL 正确
    fake_g = _FakeSession()
    push_items("K", "999", "group", [{"title": "G", "doi": "10.9/g"}], None,
               upload_pdf=False, session=fake_g)
    assert fake_g.calls[0]["url"] == "https://api.zotero.org/groups/999/items", fake_g.calls[0]

    # ④ 缺凭据 / 空结果 → 返回 0 且不发任何请求
    empty = _FakeSession()
    assert push_items("", "123", "user", results, None, session=empty) == 0
    assert push_items("K", "", "user", results, None, session=empty) == 0
    assert push_items("K", "1", "user", [], None, session=empty) == 0
    assert empty.calls == [], empty.calls

    # ⑤ 附件四步编排(fake):创建条目 → 授权 → 直传 → 注册
    with tempfile.TemporaryDirectory() as d:
        pdf = os.path.join(d, "paper.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 fake pdf content")
        fa = _FakeSession()
        assert _upload_attachment(fa, "PARENT", pdf, "K", "123", "user", None) is True
        urls = [c["url"] for c in fa.calls]
        assert len(fa.calls) == 4, urls
        assert urls[0].endswith("/items"), urls
        assert urls[1].endswith("/file") and "upload" not in (fa.calls[1]["data"] or {}), urls
        assert urls[2] == "https://storage.test/put", urls
        assert urls[3].endswith("/file") and "upload" in (fa.calls[3]["data"] or {}), urls

        # push_items(upload_pdf=True)整合:1 条目 POST + 4 步附件 = 5 次调用
        fp = _FakeSession()
        assert push_items("K", "1", "user",
                          [{"title": "W", "doi": "10.1/w", "pdf_path": pdf}], None,
                          upload_pdf=True, session=fp) == 1
        assert len(fp.calls) == 5, [c["url"] for c in fp.calls]

    print("ZOTERO_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
