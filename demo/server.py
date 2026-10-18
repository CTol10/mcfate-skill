#!/usr/bin/env python3
"""McFate 本地 UX 原型：把 Skill 的回合结构做成能点着玩的界面。

只绑 127.0.0.1，不对外。后端直接调用 `mcfate_core`，与 CLI 共用同一份推荐逻辑，
因此界面上看到的分数、抽样、券判定与命令行完全一致，不存在第二套实现。

    python demo/server.py            # 默认 8788
    python demo/server.py --port 9000

数据说明：演示环境用 `examples/sample-menu.json` 的菜单快照（官方菜单价，门店编码为占位符）。
没有 `calculate-price`，所以「就它了」只给订单摘要，不编造应付金额。
"""

from __future__ import annotations

import argparse
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent
SKILL = ROOT.parent / "mcfate"
sys.path.insert(0, str(SKILL / "scripts"))

from mcfate_core import cli, normalize, profile as profile_lib  # noqa: E402

MENU_PATH = SKILL / "examples" / "sample-menu.json"
COUPON_PATH = SKILL / "examples" / "sample-coupons.json"
PROFILE_PATH = ROOT / ".demo-profile.json"
INDEX_PATH = ROOT / "index.html"


def load_menu() -> Dict[str, Any]:
    return json.loads(MENU_PATH.read_text(encoding="utf-8"))


def load_coupons() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(COUPON_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def enrich(result: Dict[str, Any]) -> Dict[str, Any]:
    """给界面补上结构化字段（理由、分数明细、预算结论），避免前端去解析文本行。"""
    detail = result.get("detail") or []
    budget = result.get("budget")
    tolerance = cli.config.BUDGET_TOLERANCE_YUAN
    cards = []
    for index, candidate in enumerate(result.get("candidates") or []):
        row = detail[index] if index < len(detail) else {}
        item = row.get("item") or {}
        score = row.get("score") or {}
        price = candidate.get("price")
        if price is None:
            within: Optional[bool] = None
        else:
            within = True if budget is None else price <= budget + tolerance
        cards.append(
            {
                "code": candidate.get("code"),
                "name": candidate.get("name"),
                "price": price,
                "sign": candidate.get("sign"),
                "mark": candidate.get("mark"),
                "score": candidate.get("score"),
                "components": score.get("components") or {},
                "reasons": score.get("reasons") or [],
                "gaps": score.get("data_gaps") or [],
                "category": item.get("category") or "未分类",
                "role": item.get("role") or "main",
                "within_budget": within,
            }
        )
    result["cards"] = cards
    return result


def recommend(payload: Dict[str, Any]) -> Dict[str, Any]:
    request = dict(payload)
    request["menu"] = load_menu()
    if request.get("mode") == "save" or request.get("with_coupons"):
        coupons = load_coupons()
        if coupons is not None:
            request["coupons"] = coupons
    request.setdefault("store", {"code": "1234567", "name": "演示门店（到店自取）", "order_type": 1, "be_type": 1})

    rejected = [str(code) for code in (request.get("rejected") or [])]
    if rejected:
        request["rejected"] = rejected

    result = cli.build_recommendation(request, profile_path=str(PROFILE_PATH))
    if not result.get("ok"):
        return result

    result = enrich(result)
    result["echo"] = {
        "mode": request.get("mode"),
        "style": request.get("style"),
        "budget": request.get("budget"),
        "exclude": request.get("exclude") or [],
        "seed": result.get("seed"),
        "rejected_count": len(rejected),
    }
    return result


def record(payload: Dict[str, Any]) -> Dict[str, Any]:
    store = profile_lib.Profile.load(PROFILE_PATH)
    try:
        entry = store.mark(
            str(payload.get("code") or ""),
            str(payload.get("name") or ""),
            str(payload.get("category") or ""),
            str(payload.get("status") or "tried"),
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    store.prune_rejected()
    store.save(PROFILE_PATH)
    return {"ok": True, "entry": entry, "summary": store.summary()}


def gallery() -> Dict[str, Any]:
    store = profile_lib.Profile.load(PROFILE_PATH)
    items = normalize.normalize_menu(load_menu())
    return {"ok": True, "summary": store.summary(), "progress": store.progress(items)}


class Handler(BaseHTTPRequestHandler):
    server_version = "McFateDemo/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # 安静一点，别刷屏
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send_json(self, payload: Dict[str, Any], status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            if not INDEX_PATH.exists():
                self.send_error(HTTPStatus.NOT_FOUND, "index.html missing")
                return
            body = INDEX_PATH.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/api/gallery":
            self._send_json(gallery())
            return
        if self.path == "/api/meta":
            menu = normalize.normalize_menu(load_menu())
            categories = sorted({item.category for item in menu})
            self._send_json(
                {
                    "ok": True,
                    "menu_total": len(menu),
                    "categories": categories,
                    "styles": sorted(cli.config.STYLE_WEIGHTS),
                    "modes": ["decide", "save", "blindbox"],
                    "note": "演示使用示例菜单快照，不含 calculate-price",
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:  # noqa: N802
        payload = self._read_json()
        if self.path == "/api/recommend":
            self._send_json(recommend(payload))
            return
        if self.path == "/api/record":
            self._send_json(record(payload))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "not found")


def main() -> int:
    parser = argparse.ArgumentParser(description="McFate 本地 UX 原型")
    parser.add_argument("--port", type=int, default=8788)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"McFate 演示已启动：http://127.0.0.1:{args.port}")
    print("Ctrl+C 结束")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
