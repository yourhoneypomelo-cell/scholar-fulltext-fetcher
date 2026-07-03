"""Cookie 持久化(JSON + 过期). 零依赖,离线可测."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class StoredCookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    secure: bool = False
    http_only: bool = False
    expires: Optional[float] = None  # unix ts; None = session cookie

    def is_expired(self, now: Optional[float] = None) -> bool:
        if self.expires is None:
            return False
        return (now or time.time()) >= self.expires

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "StoredCookie":
        return cls(
            name=str(d.get("name") or ""),
            value=str(d.get("value") or ""),
            domain=str(d.get("domain") or ""),
            path=str(d.get("path") or "/"),
            secure=bool(d.get("secure")),
            http_only=bool(d.get("http_only")),
            expires=d.get("expires"),
        )


@dataclass
class CookieStore:
    """按 provider 分区的 Cookie 仓库."""
    path: str
    version: int = 1
    providers: Dict[str, List[StoredCookie]] = field(default_factory=dict)
    updated_ts: Optional[float] = None

    def save(self) -> None:
        self.updated_ts = time.time()
        os.makedirs(os.path.dirname(os.path.abspath(self.path)) or ".", exist_ok=True)
        payload = {
            "version": self.version,
            "updated_ts": self.updated_ts,
            "providers": {
                k: [c.to_dict() for c in v] for k, v in self.providers.items()
            },
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "CookieStore":
        if not os.path.isfile(path):
            return cls(path=path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        store = cls(path=path, version=int(data.get("version") or 1))
        store.updated_ts = data.get("updated_ts")
        raw = data.get("providers") or {}
        if isinstance(raw, dict):
            for prov, items in raw.items():
                if isinstance(items, list):
                    store.providers[str(prov)] = [
                        StoredCookie.from_dict(x) for x in items if isinstance(x, dict)
                    ]
        return store

    def set_cookies(self, provider: str, cookies: List[StoredCookie]) -> None:
        self.providers[provider] = list(cookies)

    def get_valid_cookies(self, provider: str, now: Optional[float] = None) -> List[StoredCookie]:
        now = now or time.time()
        return [c for c in self.providers.get(provider, []) if not c.is_expired(now)]

    def cookie_header(self, provider: str, now: Optional[float] = None) -> Optional[str]:
        valid = self.get_valid_cookies(provider, now)
        if not valid:
            return None
        return "; ".join(f"{c.name}={c.value}" for c in valid if c.name)
