"""McFate 命令行入口：模型负责理解与调用 MCP，脚本负责确定性计算。

用法示例：
    python scripts/mcfate.py recommend --input payload.json
    python scripts/mcfate.py rerank --input quotes.json
    python scripts/mcfate.py coupon-plan --input payload.json
    python scripts/mcfate.py record --code 1100 --name 巨无霸 --status liked
    python scripts/mcfate.py profile --summary
    python scripts/mcfate.py export --out backup.json

所有子命令都输出 JSON，便于模型直接读取结构化结论，再决定如何措辞。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import config, coupons as coupon_lib, normalize, pricing, render, sampler
from .constraints import Constraints, apply as apply_constraints, prioritize_main
from .models import Candidate, MenuItem
from .profile import Profile, default_path, merge
from .scoring import ScoringContext, score_item

EXIT_OK = 0
EXIT_INPUT_ERROR = 2


def _load_payload(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    if path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("输入文件必须是 JSON 对象")
    return data


def _emit(payload: Dict[str, Any], output: Optional[str] = None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text)


def _expand(payload: Dict[str, Any]) -> Dict[str, Any]:
    """允许 payload 用 *_file 引用外部 JSON，避免把整份菜单重复塞进请求。

    支持 menu_file / coupons_file；内联字段优先，外部文件失败时记录警告而不是崩溃。
    """
    result = dict(payload)
    warnings: List[str] = list(result.get("_warnings") or [])
    for key, file_key in (("menu", "menu_file"), ("coupons", "coupons_file")):
        if result.get(key) or not result.get(file_key):
            continue
        path = Path(str(result[file_key]))
        try:
            result[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            warnings.append(f"{file_key} 读取失败：{exc}")
            result[key] = None
    result["_warnings"] = warnings
    return result


def _seed(value: Optional[int]) -> int:
    if value is None:
        return random.SystemRandom().randrange(1, 10**6)
    return int(value)


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def _coupon_hint(item: MenuItem, checks: Sequence[coupon_lib.CouponCheck]) -> str:
    if not checks:
        return "暂无结构化券数据，未计入任何优惠"
    hits = [c for c in checks if c.applicable and (not c.coupon.product_codes or item.code in c.coupon.product_codes)]
    usable = [c for c in hits if c.status in (config.COUPON_USABLE, config.COUPON_NEEDS_EXTRA)]
    if usable:
        titles = "、".join(c.coupon.title for c in usable[:2])
        return f"「{titles}」覆盖这款；实际优惠以官方算价为准"
    unverified = [c for c in checks if c.status == config.COUPON_UNVERIFIED]
    if unverified:
        return "券的适用范围/门槛接口未返回，未计入节省"
    return "当前券与这款不匹配，未计入节省"


def _coupon_summary(picked: Sequence[Candidate], hints: Dict[str, str]) -> str:
    """多候选共用一行优惠说明：只说能验证的部分，不把未验证的券算成优惠。"""
    texts = {hints.get(candidate.code, "") for candidate in picked}
    if not texts or texts == {""}:
        return "未计入任何优惠"
    if len(texts) == 1:
        return texts.pop()
    usable = [candidate.item.name for candidate in picked if "覆盖这款" in hints.get(candidate.code, "")]
    if usable:
        return f"{'、'.join(usable)} 有券覆盖，其余未验证；实际优惠以官方算价为准"
    return "券的适用范围/门槛未全部返回，未计入节省"


def build_recommendation(
    payload: Dict[str, Any],
    *,
    seed: Optional[int] = None,
    profile_path: Optional[str] = None,
) -> Dict[str, Any]:
    """推荐主流程。CLI 与本地 UX 原型共用这一份实现，避免两套逻辑漂移。

    返回结果字典；`ok=False` 表示输入不足或参数非法，由调用方决定退出码。
    """
    mode = str(payload.get("mode") or "decide")
    style = str(payload.get("style") or ("adventure" if mode == "blindbox" else config.DEFAULT_STYLE))
    if style not in config.STYLE_WEIGHTS:
        return {"ok": False, "error": f"未知风格：{style}", "allowed": sorted(config.STYLE_WEIGHTS)}

    budget = payload.get("budget")
    budget = None if budget in (None, "", 0) else float(budget)
    exclude = payload.get("exclude") or []
    seed = _seed(payload.get("seed") if payload.get("seed") is not None else seed)
    rng = _rng(seed)

    menu_items = normalize.normalize_menu(payload.get("menu"))
    warnings: List[str] = list(payload.get("_warnings") or [])
    if not menu_items:
        return {
            "ok": False,
            "error": "未解析到任何在售餐品，无法推荐",
            "hint": "请确认已调用 query-meals 并传入其原始返回；不要凭接口名臆造数据",
        }

    profile = Profile.from_dict(payload.get("profile")) if payload.get("profile") else Profile.load(Path(profile_path) if profile_path else default_path())
    warnings.extend(profile.warnings)
    if not profile.history_reliable:
        warnings.append("个人档案中没有明确标记的尝试记录，新鲜感/偏好按中性值计算")

    coupon_rows, coupon_status, coupon_note = normalize.normalize_coupons(payload.get("coupons"))
    coupon_codes = [code for row in coupon_rows for code in row.product_codes]

    recent = list(payload.get("recent") or profile.recent_codes())
    recent_categories = list(payload.get("recent_categories") or profile.recent_categories())
    rejected = list(payload.get("rejected") or []) + list(profile.rejected_codes)

    constraints = Constraints.build(budget, exclude)
    outcome = apply_constraints(menu_items, constraints)

    count = int(payload.get("count") or (1 if mode == "blindbox" else config.DEFAULT_RESULT_COUNT))
    count = max(1, min(count, config.MAX_RESULT_COUNT))
    candidate_items, main_notes = prioritize_main(outcome.kept, count)
    warnings.extend(main_notes)

    ctx = ScoringContext.build(
        style=style,
        profile=profile,
        recent_codes=recent,
        recent_categories=recent_categories,
        coupon_codes=coupon_codes,
    )

    scored: List[Candidate] = []
    for item in candidate_items:
        scored.append(Candidate(item=item, score=score_item(item, ctx), flags=outcome.flag_for(item.code)))

    picked = sampler.select(
        scored,
        count,
        rng,
        score_of=lambda c: c.score.total,
        code_of=lambda c: c.code,
        rejected=rejected,
    )

    checks: List[coupon_lib.CouponCheck] = []
    for candidate in picked:
        for coupon in coupon_rows:
            checks.append(coupon_lib.check(coupon, [candidate.code], candidate.item.price))

    store = payload.get("store") or {}
    # 回合结构：盲盒与单结果走“揭晓”，多候选走“摆盘”。动作只在回合末尾出现一次。
    turn = "reveal" if (mode == "blindbox" or count == 1) else "board"
    hints = {candidate.code: _coupon_hint(candidate.item, checks) for candidate in picked}

    result: Dict[str, Any] = {
        "ok": True,
        "mode": mode,
        "style": style,
        "budget": budget,
        "seed": seed,
        "turn": turn,
        "header": render.header(mode, style, budget, store.get("name")),
        "detail": [candidate.to_dict() for candidate in picked],
        "meta": {
            "menu_total": len(menu_items),
            "kept": len(outcome.kept),
            "dropped": outcome.dropped[:20],
            "dropped_count": len(outcome.dropped),
            "history_reliable": profile.history_reliable,
            "recent_used": recent[: config.RECENT_LIMIT],
            "rejected_used": sorted({str(c) for c in rejected}),
            "coupon_status": coupon_status,
            "coupon_note": coupon_note,
            "warnings": warnings,
            # 硬性：本轮输出后必须停下等用户选，不得自行核价/下单/再抽
            "stop_after_turn": True,
        },
    }

    if turn == "reveal":
        card = render.reveal_block(picked[0], budget, seed, style, hints[picked[0].code])
        result["sign"] = card["sign"]
        result["candidates"] = [card]
        result["reveal_lines"] = card["lines"]
    else:
        entries = [render.board_entry(index, candidate) for index, candidate in enumerate(picked)]
        result["candidates"] = entries
        result["board_lines"] = render.board_block(
            entries,
            budget,
            _coupon_summary(picked, hints),
            len(outcome.dropped),
        )

    result["actions"] = render.actions_for(turn)
    result["next_actions"] = [action["label"] for action in result["actions"]]

    if mode == "save":
        combos, combo_notes = coupon_lib.suggest_combos(coupon_rows, outcome.kept, budget)
        result["combos"] = [combo.to_dict() for combo in combos]
        result["combo_notes"] = combo_notes
        if combos and store.get("code"):
            result["pricing_requests"] = pricing.price_requests(
                combos,
                str(store["code"]),
                int(store.get("order_type") or 1),
                int(store.get("be_type") or 1),
                be_code=store.get("be_code"),
            )
        result["actions"] = [
            {"id": "price", "label": "去核价", "hint": "按 pricing_requests 调用 calculate-price，带券与不带券各一次"},
            {"id": "again", "label": "换一组组合", "hint": "重新生成组合，避开已看过的"},
            {"id": "retune", "label": "改预算", "hint": "只改预算上限，其余条件不变"},
        ]
        result["next_actions"] = [action["label"] for action in result["actions"]]

    return result


def cmd_recommend(args: argparse.Namespace) -> int:
    try:
        payload = _expand(_load_payload(args.input))
    except (OSError, ValueError) as exc:
        _emit({"ok": False, "error": f"输入解析失败：{exc}"})
        return EXIT_INPUT_ERROR
    result = build_recommendation(payload, seed=args.seed, profile_path=args.profile)
    _emit(result, args.output)
    return EXIT_OK if result.get("ok") else EXIT_INPUT_ERROR



def cmd_rerank(args: argparse.Namespace) -> int:
    try:
        payload = _load_payload(args.input)
    except (OSError, ValueError) as exc:
        _emit({"ok": False, "error": f"输入解析失败：{exc}"})
        return EXIT_INPUT_ERROR

    budget = payload.get("budget")
    budget = None if budget in (None, "", 0) else float(budget)
    entries = []
    for row in payload.get("entries") or []:
        if not isinstance(row, dict):
            continue
        quote = normalize.normalize_quote(row.get("quote"))
        item = dict(row)
        item["quote"] = quote
        entries.append(item)

    ranked = pricing.rerank(entries, budget)
    for row in ranked:
        row["budget"] = budget
    best = next((row for row in ranked if row["state"] == config.PRICE_PRICED), None)
    _emit(
        {
            "ok": True,
            "budget": budget,
            "ranked": ranked,
            "recommended": best.get("label") if best else None,
            "note": "以上金额全部来自 calculate-price 官方算价；未核价方案不展示金额。",
        },
        args.output,
    )
    return EXIT_OK


def cmd_coupon_plan(args: argparse.Namespace) -> int:
    try:
        payload = _expand(_load_payload(args.input))
    except (OSError, ValueError) as exc:
        _emit({"ok": False, "error": f"输入解析失败：{exc}"})
        return EXIT_INPUT_ERROR

    items = normalize.normalize_menu(payload.get("menu"))
    coupons, status, note = normalize.normalize_coupons(payload.get("coupons"))
    selected = [str(code) for code in (payload.get("items") or [])]
    by_code = {item.code: item for item in items}
    subtotal = payload.get("subtotal")
    if subtotal is None and selected:
        prices = [by_code[code].price for code in selected if code in by_code and by_code[code].price is not None]
        subtotal = round(sum(prices), 2) if prices else None
    subtotal = None if subtotal is None else float(subtotal)
    budget = payload.get("budget")
    budget = None if budget in (None, "", 0) else float(budget)

    checks = [coupon_lib.check(coupon, selected, subtotal) for coupon in coupons]
    combos, combo_notes = coupon_lib.suggest_combos(coupons, items, budget)

    _emit(
        {
            "ok": True,
            "coupon_status": status,
            "coupon_note": note,
            "subtotal_menu_price": subtotal,
            "checks": [check.to_dict() for check in checks],
            "combos": [combo.to_dict() for combo in combos],
            "combo_notes": combo_notes,
            "rules": [
                "券面额不等于净收益：为凑门槛多买的金额必须单独列出",
                "接口未返回的门槛/范围/叠加规则一律标注为未知",
                "任何节省金额都必须由官方算价结果支撑",
            ],
        },
        args.output,
    )
    return EXIT_OK


def cmd_record(args: argparse.Namespace) -> int:
    path = Path(args.profile) if args.profile else default_path()
    profile = Profile.load(path)
    try:
        entry = profile.mark(args.code, args.name or args.code, args.category or "", args.status, args.day)
    except ValueError as exc:
        _emit({"ok": False, "error": str(exc)})
        return EXIT_INPUT_ERROR
    profile.prune_rejected()
    profile.save(path)
    _emit({"ok": True, "saved_to": str(path), "entry": entry, "summary": profile.summary(args.day)}, args.output)
    return EXIT_OK


def cmd_profile(args: argparse.Namespace) -> int:
    path = Path(args.profile) if args.profile else default_path()
    profile = Profile.load(path)
    summary = profile.summary(args.today)
    payload: Dict[str, Any] = {"ok": True, "profile_path": str(path), "summary": summary}
    if args.menu:
        try:
            raw = json.loads(Path(args.menu).read_text(encoding="utf-8"))
            items = normalize.normalize_menu(raw)
            payload["progress"] = profile.progress(items)
        except (OSError, ValueError) as exc:
            payload["progress_error"] = f"菜单读取失败：{exc}"
    _emit(payload, args.output)
    return EXIT_OK


def cmd_export(args: argparse.Namespace) -> int:
    path = Path(args.profile) if args.profile else default_path()
    profile = Profile.load(path)
    target = Path(args.out) if args.out else Path("mcfate-profile-export.json")
    target.write_text(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    _emit({"ok": True, "exported_to": str(target), "summary": profile.summary()}, args.output)
    return EXIT_OK


def cmd_import(args: argparse.Namespace) -> int:
    path = Path(args.profile) if args.profile else default_path()
    profile = Profile.load(path)
    try:
        incoming = json.loads(Path(args.src).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _emit({"ok": False, "error": f"导入文件读取失败：{exc}"})
        return EXIT_INPUT_ERROR
    merged = merge(profile, incoming)
    merged.save(path)
    _emit({"ok": True, "saved_to": str(path), "summary": merged.summary()}, args.output)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcfate", description="麦门食运局 McFate：确定性推荐内核")
    parser.add_argument("--output", help="把结果同时写入指定文件")
    parser.add_argument("--profile", help="个人档案路径，默认 ~/.mcfate/profile.json")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(target: argparse.ArgumentParser) -> None:
        """让全局参数写在子命令后面也能生效（default=SUPPRESS 避免覆盖已解析值）。"""
        target.add_argument("--output", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        target.add_argument("--profile", default=argparse.SUPPRESS, help=argparse.SUPPRESS)

    p = sub.add_parser("recommend", help="生成推荐候选")
    p.add_argument("--input", required=True, help="payload JSON 路径")
    p.add_argument("--seed", type=int, default=None, help="随机种子，保证可复现")
    add_common(p)
    p.set_defaults(func=cmd_recommend)

    p = sub.add_parser("rerank", help="用官方算价结果重新排序")
    p.add_argument("--input", required=True)
    add_common(p)
    p.set_defaults(func=cmd_rerank)

    p = sub.add_parser("coupon-plan", help="券可用性判定与组合建议")
    p.add_argument("--input", required=True)
    add_common(p)
    p.set_defaults(func=cmd_coupon_plan)

    p = sub.add_parser("record", help="记录已尝试/喜欢/不喜欢/不再推荐")
    p.add_argument("--code", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--category", default="")
    p.add_argument("--status", required=True, choices=["tried", "liked", "disliked", "rejected"])
    p.add_argument("--day", default=None, help="记录日期 YYYY-MM-DD，默认今天")
    add_common(p)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("profile", help="查看个人图鉴摘要")
    p.add_argument("--summary", action="store_true", help="兼容用参数，默认即输出摘要")
    p.add_argument("--menu", help="可选：菜单 JSON，用于计算品类探索进度")
    p.add_argument("--today", default=None)
    add_common(p)
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("export", help="导出个人档案")
    p.add_argument("--out", default=None)
    add_common(p)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help="导入并合并个人档案")
    p.add_argument("--src", required=True)
    add_common(p)
    p.set_defaults(func=cmd_import)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
