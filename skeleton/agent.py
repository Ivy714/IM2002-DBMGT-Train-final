"""
TransitFlow Agent
=================
Integrates:
  - PostgreSQL (relational): schedules, fares, bookings, cancel, policy RAG
  - Neo4j (graph): route finding
  - train-mock-data JSON: station name lookup, policy fallback
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Optional

from databases.graph import queries as graph
from databases.relational import queries as pg
from databases.relational.queries import auto_select_adjacent_seats
from skeleton.config import DATA_DIR
from skeleton.llm_provider import llm

_STATION_INDEX: dict[str, str] = {}


def _load_station_index() -> None:
    global _STATION_INDEX
    if _STATION_INDEX:
        return
    for fname in ("metro_stations.json", "national_rail_stations.json"):
        path = DATA_DIR / fname
        if not path.exists():
            continue
        for s in json.loads(path.read_text(encoding="utf-8")):
            _STATION_INDEX[s["name"].strip().lower()] = s["station_id"]
            _STATION_INDEX[s["station_id"].lower()] = s["station_id"]


def _inject_station_ids(text: str) -> str:
    _load_station_index()
    result = text
    for name in sorted(_STATION_INDEX, key=len, reverse=True):
        if len(name) <= 3 and not name.startswith(("ms", "nr")):
            continue
        sid = _STATION_INDEX[name]
        if re.search(rf"(?i)\b{re.escape(name)}\s*\({sid}\)", result):
            continue
        pat = re.compile(re.escape(name), re.IGNORECASE)
        if name.startswith(("ms", "nr")):
            result = pat.sub(sid, result)
        elif pat.search(result):
            result = pat.sub(f"{name} ({sid})", result, count=1)
    return result


def _extract_station_ids(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for m in re.findall(r"\b(MS\d{2}|NR\d{2})\b", text, re.I):
        sid = m.upper()
        if sid not in seen:
            seen.add(sid)
            ordered.append(sid)
    return ordered


def _parse_route_endpoints(text: str, ids: list[str]) -> tuple[str, str]:
    m = re.search(
        r"(?:FROM|從)\s+(MS\d{2}|NR\d{2}).*?(?:TO|到|→|->)\s+(MS\d{2}|NR\d{2})",
        text,
        re.I,
    )
    if m:
        return m.group(1).upper(), m.group(2).upper()
    if len(ids) >= 2:
        return ids[0], ids[1]
    return ids[0], ids[0]


def _extract_travel_date(text: str) -> str:
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    return m.group(1) if m else "2026-06-01"


def _extract_booking_id(text: str) -> Optional[str]:
    m = re.search(r"\b(BK-[A-Z0-9]+|BK\d{3,})\b", text, re.I)
    return m.group(1).upper() if m else None


def _policy_search(query: str) -> list[dict]:
    try:
        emb = llm.embed(query)
        docs = pg.query_policy_vector_search(emb)
        if docs:
            return docs
    except Exception:
        pass
    return []


def _format_refund_delay(minutes: int) -> str:
    for p in json.loads((DATA_DIR / "refund_policy.json").read_text(encoding="utf-8")):
        if p.get("policy_id") != "RF005":
            continue
        for rule in p.get("compensation_rules", []):
            cond = rule.get("condition", "")
            if 30 <= minutes < 60 and ("30" in cond or "59" in cond):
                return f"【RF005】{cond} → {rule['compensation']}"
            if 60 <= minutes < 120 and ("60" in cond or "119" in cond):
                return f"【RF005】{cond} → {rule['compensation']}"
            if minutes >= 120 and "120" in cond:
                return f"【RF005】{cond} → {rule['compensation']}"
    return "延誤補償請參考 RF005；天災相關見 RF009。"


def _format_route(data: dict, *, cost_mode: bool = False, child: bool = False) -> str:
    if not data.get("found"):
        return "找不到可行路線。"
    fare = float(data.get("total_fare_usd", data.get("total_cost", 0)))
    if child:
        fare = round(fare * 0.5, 2)
        note = "（兒童半價）"
    else:
        note = ""
    lines = ["【路線】"]
    if data.get("path"):
        lines.append("  → " + " → ".join(s["name"] for s in data["path"]))
    if cost_mode:
        lines.append(f"  票價約 ${fare:.2f} USD {note}")
    else:
        lines.append(f"  時間約 {data.get('total_time_min', '?')} 分鐘")
    return "\n".join(lines)


def _format_booking_result(ok: bool, res: Any) -> str:
    if not ok:
        return f"訂票失敗：{res}"
    return (
        f"【訂票成功】\n"
        f"  訂單編號：{res.get('booking_id')}\n"
        f"  班次：{res.get('schedule_id')}\n"
        f"  路線：{res.get('origin_station_id')} → {res.get('destination_station_id')}\n"
        f"  日期：{res.get('travel_date')}\n"
        f"  艙等：{res.get('fare_class')}\n"
        f"  座位：{res.get('coach')}{res.get('seat_id')}\n"
        f"  金額：${res.get('amount_usd')} USD\n"
        f"  狀態：{res.get('status')}"
    )


def _format_cancel_result(ok: bool, res: Any) -> str:
    if not ok:
        return f"取消失敗：{res}"
    return (
        f"【取消成功】\n"
        f"  訂單：{res.get('booking_id')}\n"
        f"  原票價：${res.get('original_amount_usd')} USD\n"
        f"  退款：${res.get('refund_amount_usd')} USD\n"
        f"  手續費：${res.get('admin_fee_usd')} USD\n"
        f"  政策：{res.get('policy_note')}"
    )


def _handle_booking_cancel(msg: str, augmented: str, email: Optional[str]) -> Optional[str]:
    if not email:
        if any(k in msg.lower() for k in ("book", "訂票", "cancel", "取消")):
            return "請先登入後再訂票或取消訂單（右上角 Login）。"
        return None

    profile = pg.query_user_profile(email)
    if not profile:
        return "找不到登入使用者資料，請重新登入。"

    lower = msg.lower()
    uid = profile["user_id"]

    # Cancel booking
    if any(k in lower for k in ("cancel", "取消")) and not any(
        k in lower for k in ("policy", "政策")
    ):
        bid = _extract_booking_id(augmented)
        if not bid:
            return "請提供訂單編號，例如：Cancel booking BK001"
        ok, res = pg.execute_cancellation(bid, uid)
        return _format_cancel_result(ok, res)

    # Make booking
    not_viewing = not any(
        k in lower for k in ("my booking", "show my", "booking history", "我的訂單")
    )
    wants_book = not_viewing and (
        any(k in lower for k in ("book me", "make a booking", "book a ticket", "訂票", "幫我訂", "buy a ticket"))
        or re.search(r"\bbook\b", lower)
    )

    if wants_book:
        ids = _extract_station_ids(augmented)
        if len(ids) < 2:
            return "訂票請提供起訖站，例如：Book NR01 to NR05 on 2026-06-01"
        if not (ids[0].startswith("NR") and ids[1].startswith("NR")):
            return "目前訂票功能僅支援國鐵（NR 站點之間）。"

        origin, dest = _parse_route_endpoints(augmented, ids)
        travel_date = _extract_travel_date(augmented)
        fare_class = "first" if "first" in lower else "standard"

        avail = pg.query_national_rail_availability(origin, dest, travel_date)
        if not avail:
            return f"找不到 {origin}→{dest} 在 {travel_date} 的國鐵班次。"

        schedule_id = avail[0]["schedule_id"]
        seats = pg.query_available_seats(schedule_id, travel_date, fare_class)
        if not seats:
            return f"{schedule_id} 在 {travel_date} 的 {fare_class} 艙已無空位。"

        seat_id = seats[0]["seat_id"]
        if "any" in lower or "auto" in lower:
            picked = auto_select_adjacent_seats(seats, 1)
            seat_id = picked[0] if picked else seat_id

        ok, res = pg.execute_booking(
            user_id=uid,
            schedule_id=schedule_id,
            origin_station_id=origin,
            destination_station_id=dest,
            travel_date=travel_date,
            fare_class=fare_class,
            seat_id=seat_id,
            ticket_type="return" if "return" in lower else "single",
        )
        return _format_booking_result(ok, res)

    return None


def _handle_data_query(msg: str, augmented: str, email: Optional[str]) -> Optional[str]:
    lower = msg.lower()
    ids = _extract_station_ids(augmented)

    if email and any(
        k in lower
        for k in ("my booking", "my bookings", "show my", "booking history", "我的訂", "訂單")
    ):
        data = pg.query_user_bookings(email)
        lines = [f"【{email} 的訂單】"]
        for b in data["national_rail"][:6]:
            lines.append(
                f"  國鐵 {b['booking_id']}: {b.get('origin_name', b.get('origin_station_id'))}"
                f"→{b.get('destination_name', b.get('destination_station_id'))} "
                f"{b['travel_date']} {b['status']} ${b['amount_usd']}"
            )
        for t in data["metro"][:6]:
            lines.append(
                f"  捷運 {t['trip_id']}: {t.get('origin_name')}→{t.get('destination_name')} "
                f"{t['travel_date']} {t['status']} ${t['amount_usd']}"
            )
        if not data["national_rail"] and not data["metro"]:
            lines.append("  （尚無紀錄）")
        return "\n".join(lines)

    delay = None
    m = re.search(r"(\d+)\s*(?:minutes?|mins?|分鐘)", msg, re.I)
    if m:
        delay = int(m.group(1))
    if delay is not None and any(k in lower for k in ("delay", "compensation", "延誤", "補償")):
        return _format_refund_delay(delay)

    if any(k in lower for k in ("luggage", "行李", "baggage")):
        docs = _policy_search("metro luggage policy" if "metro" in lower or "捷運" in msg else "national rail luggage")
        if docs:
            return f"【{docs[0]['title']}】\n{docs[0]['content'][:800]}"
        tp = json.loads((DATA_DIR / "travel_policies.json").read_text(encoding="utf-8"))
        net = "national_rail" if any(k in lower for k in ("rail", "國鐵", "train")) else "metro"
        lug = tp.get(net, {}).get("luggage", {})
        return (
            f"【行李政策】每人 {lug.get('items_per_passenger', '?')} 件；"
            f" {lug.get('max_dimensions_per_item_cm', lug.get('notes', ''))}"
        )

    if any(k in lower for k in ("policy", "refund", "政策", "退款", "bicycle", "寵物")):
        docs = _policy_search(msg)
        if docs:
            return f"【{docs[0]['title']}】\n{docs[0]['content'][:900]}"

    if len(ids) >= 2:
        origin, dest = _parse_route_endpoints(augmented, ids)
        child = any(k in lower for k in ("child", "兒童", "小孩"))

        if any(k in lower for k in ("train", "schedule", "班次", "timetable", "服務")):
            if origin.startswith("NR"):
                rows = pg.query_national_rail_availability(origin, dest)
                if not rows:
                    return f"國鐵 {origin}→{dest} 無班次。"
                lines = [f"【國鐵班次 {origin}→{dest}】"]
                for r in rows[:4]:
                    fare = pg.query_national_rail_fare(
                        r["schedule_id"], "standard", r.get("stops_travelled", 1)
                    )
                    lines.append(
                        f"  • {r['schedule_id']} {r.get('line')} {r.get('service_type')} "
                        f"首班 {r.get('first_train_time')} 標準艙 ${fare['total_fare_usd'] if fare else '?'}"
                    )
                return "\n".join(lines)
            rows = pg.query_metro_schedules(origin, dest)
            lines = [f"【捷運班次 {origin}→{dest}】"]
            for r in rows[:4]:
                lines.append(f"  • {r['schedule_id']} 線路 {r.get('line')}")
            return "\n".join(lines) if rows else f"捷運 {origin}→{dest} 無班次。"

        closed = any(k in lower for k in ("closed", "封閉", "關閉", "avoid", "避開"))
        if closed:
            avoid = next((x for x in ids if x not in (origin, dest)), None)
            if avoid:
                routes = graph.query_alternative_routes(origin, dest, avoid)
                if not routes:
                    return f"避開 {avoid} 後，{origin}→{dest} 無替代路線。"
                lines = [f"【避開 {avoid} 的替代路線】"]
                for i, legs in enumerate(routes, 1):
                    stops = [legs[0]["from_station_id"]] + [lg["to_station_id"] for lg in legs]
                    lines.append(f"  {i}. {' → '.join(stops)}")
                return "\n".join(lines)

        if any(k in lower for k in ("ripple", "漣漪", "波及")):
            affected = graph.query_delay_ripple(ids[0], hops=2)
            lines = [f"【{ids[0]} 延誤影響】"]
            for a in affected[:10]:
                lines.append(f"  • {a.get('name')} ({a.get('station_id')})")
            return "\n".join(lines) if affected else f"{ids[0]} 無影響站。"

        want_cost = any(k in lower for k in ("cheap", "cheapest", "便宜", "fare", "票價", "多少錢"))
        data = graph.query_cheapest_route(origin, dest) if want_cost else graph.query_shortest_route(origin, dest)
        return _format_route(data, cost_mode=want_cost, child=child)

    if len(ids) == 1 and any(k in lower for k in ("connection", "鄰站", "連接")):
        conns = graph.query_station_connections(ids[0])
        lines = [f"【{ids[0]} 連接】"]
        for c in conns[:8]:
            lines.append(
                f"  • {c.get('name')} ({c.get('station_id')}) "
                f"{c.get('relationship')} {c.get('travel_time_min', '')}分"
            )
        return "\n".join(lines) if conns else f"{ids[0]} 無連接。"

    return None


def run_agent(
    user_message: str,
    history: list[dict],
    debug: bool = False,
    current_user_email: Optional[str] = None,
) -> tuple:
    msg = user_message.strip()
    augmented = _inject_station_ids(msg)

    for handler_name, handler in (
        ("booking_cancel", lambda: _handle_booking_cancel(msg, augmented, current_user_email)),
        ("data", lambda: _handle_data_query(msg, augmented, current_user_email)),
    ):
        reply = handler()
        if reply:
            new_h = history + [{"role": "user", "content": msg}, {"role": "assistant", "content": reply}]
            if debug:
                return reply, new_h, f"intent={handler_name}"
            return reply, new_h

    system = (
        f"你是 TransitFlow 助手。今日 {date.today().isoformat()}。"
        f"登入：{current_user_email or '未登入'}。"
        "可協助路線、班次、票價、退款政策；登入後可訂國鐵票與取消。"
    )
    answer = llm.chat(messages=history + [{"role": "user", "content": augmented}], system_prompt=system)
    new_h = history + [{"role": "user", "content": msg}, {"role": "assistant", "content": answer}]
    if debug:
        return answer, new_h, "fallback=llm"
    return answer, new_h
