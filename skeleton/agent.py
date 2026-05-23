"""
TransitFlow — Intelligent Agent
================================
Merged Premium Edition

融合重點：
1. 保留 agent_optimized.py 的模組化架構
2. 加回 agent.py 專門的延誤波及格式化
3. 強化 station ID 抽取、驗證、network 判斷
4. 支援最快路線、最便宜路線、跨網絡轉乘、替代路線、延誤影響
5. 路線查詢走硬規則，避免 LLM 捏造
"""

from __future__ import annotations

import re
from typing import Any, Optional

from skeleton.llm_provider import llm
from databases.relational.queries import (
    query_policy_vector_search,
)
from databases.graph.queries import (
    query_shortest_route,
    query_cheapest_route,
    query_alternative_routes,
    query_interchange_path,
    query_delay_ripple,
)


# ── Station name → ID lookup ──────────────────────────────────────────────────

_STATION_INDEX: dict[str, str] = {
    "central square": "MS01", "riverside": "MS02", "northgate": "MS03",
    "elm park": "MS04", "westfield": "MS05", "harbour view": "MS06",
    "old town": "MS07", "university": "MS08", "queensbridge": "MS09",
    "parkside": "MS10", "greenhill": "MS11", "lakeshore": "MS12",
    "clifton": "MS13", "eastwick": "MS14", "ferndale": "MS15",
    "hilltop": "MS16", "broadmoor": "MS17", "sunnyvale": "MS18",
    "redwood": "MS19", "thornton": "MS20",

    "central station": "NR01", "maplewood": "NR02",
    "old town junction": "NR03", "ashford": "NR04",
    "stonehaven": "NR05", "bridgeport": "NR06",
    "ferndale halt": "NR07", "coalport": "NR08",
    "dunmore": "NR09", "langford end": "NR10",
}

_VALID_STATION_ID = re.compile(r"^(MS|NR)\d{2}$", re.IGNORECASE)
_STATION_ID_PATTERN = re.compile(r"\b(MS\d{2}|NR\d{2})\b", re.IGNORECASE)


# ── Keyword sets ──────────────────────────────────────────────────────────────

_ROUTE_KEYWORDS = {
    "route", "way", "path", "directions", "how to get", "navigate",
    "路線", "怎麼走", "去", "到", "導航", "乘車", "轉乘",
}

_COST_KEYWORDS = {
    "cheap", "cheapest", "cost", "fare", "price", "lowest fare",
    "最便宜", "便宜", "最省", "票價", "費用", "價格", "花費", "省錢",
}

_ALTERNATIVE_KEYWORDS = {
    "avoid", "closed", "closure", "incident", "alternative", "bypass", "skip",
    "避開", "繞過", "封閉", "封站", "事故", "替代", "改道",
}

_RIPPLE_KEYWORDS = {
    "ripple", "affected", "impact", "delay impact", "delay", "delayed",
    "波及", "影響", "連帶", "周邊", "延誤", "延誤影響",
}


SYSTEM_PROMPT = """你是一個非常有用的繁體中文交通助理 TransitFlow。
如果是路線、乘車查詢，請直接根據提供的真實數據回答，絕對不可自己捏造數據、站點名稱或數字！
回答請保持簡短、精確、流暢。
"""


# ── Utility helpers ───────────────────────────────────────────────────────────

def _inject_station_ids(text: str) -> str:
    """將使用者輸入中的站名補上 station ID，提升硬規則解析準確度。"""
    result = text
    seen_ids: set[str] = set()

    for name in sorted(_STATION_INDEX, key=len, reverse=True):
        sid = _STATION_INDEX[name]
        if sid in seen_ids:
            continue

        pattern = re.compile(re.escape(name), re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(f"{name} ({sid})", result)
            seen_ids.add(sid)

    return result


def _extract_station_ids(text: str) -> list[str]:
    """依照出現順序抽取不重複 station ID。"""
    ids: list[str] = []

    for raw_id in _STATION_ID_PATTERN.findall(text):
        sid = raw_id.upper()
        if sid not in ids:
            ids.append(sid)

    return ids


def _is_valid_station_id(station_id: str) -> bool:
    return bool(_VALID_STATION_ID.match(station_id or ""))


def _network_from_station_pair(origin_id: str, destination_id: str) -> str:
    if origin_id.startswith("MS") and destination_id.startswith("MS"):
        return "metro"
    if origin_id.startswith("NR") and destination_id.startswith("NR"):
        return "rail"
    return "auto"


def _is_cross_network(origin_id: str, destination_id: str) -> bool:
    return origin_id[:2] != destination_id[:2]


def _contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


# ── Formatters ────────────────────────────────────────────────────────────────

def _normalise_route_item(item: Any) -> str:
    """將 Neo4j 回傳的節點統一轉為顯示文字。"""
    if isinstance(item, dict):
        name = item.get("name") or item.get("station_name") or "未知站"
        station_id = item.get("station_id") or item.get("id")

        if station_id:
            return f"{name} ({station_id})"
        return str(name)

    return str(item)


def _metric_lines(data: dict[str, Any]) -> list[str]:
    """整理路線的時間、費用、轉乘次數等指標。"""
    lines: list[str] = []

    if data.get("total_time_min") is not None:
        lines.append(f"  ● 預估總耗時：{data['total_time_min']} 分鐘")

    if data.get("total_cost_usd") is not None:
        lines.append(f"  ● 預估總費用：${data['total_cost_usd']} USD")
    elif data.get("total_cost") is not None:
        lines.append(f"  ● 預估總費用：${data['total_cost']} USD")

    if data.get("transfer_count") is not None:
        lines.append(f"  ● 轉乘次數：{data['transfer_count']} 次")

    if data.get("route_type"):
        lines.append(f"  ● 路線類型：{data['route_type']}")

    if data.get("avoid_station_id"):
        lines.append(f"  ● 已避開站點：{data['avoid_station_id']}")

    return lines


def _format_route_result(data: Any, *, title: str = "TransitFlow 路線查詢結果") -> str:
    """將 graph query 結果格式化為穩定的繁體中文回覆。"""
    if not data:
        return "經查，目前沒有找到可行路線。"

    if isinstance(data, dict):
        if data.get("error"):
            return f"查詢發生錯誤：{data['error']}"

        if data.get("found") is False:
            return data.get("message") or "經查，目前兩站之間沒有可行路線。"

        if "path" in data:
            path = data.get("path") or []
            route_str = " ➔ ".join(_normalise_route_item(node) for node in path) or "未提供路徑"

            output = [
                f"【🔍 {title}】",
                f"  ● 乘車路線：{route_str}",
            ]
            output.extend(_metric_lines(data))
            return "\n".join(output)

    if isinstance(data, list):
        if not data:
            return "經查，目前沒有找到可行替代路線。"

        output = [f"【🔍 {title}】"]

        for idx, route in enumerate(data, 1):
            if isinstance(route, dict):
                path = route.get("path") or route.get("stations") or route.get("route") or []
                route_str = " ➔ ".join(_normalise_route_item(node) for node in path) or str(route)

                output.append(f"  ● 方案 {idx}：{route_str}")

                for metric in _metric_lines(route):
                    output.append(f"    {metric.strip()}")
            else:
                output.append(f"  ● 方案 {idx}：{route}")

        return "\n".join(output)

    return f"【🔍 查詢結果】\n{data}"


def _format_delay_ripple(station_id: str, affected: Any) -> str:
    """專門格式化延誤波及結果。"""
    if not affected:
        return f"車站 {station_id} 的延誤目前沒有查到連帶受影響的周邊站點。"

    if isinstance(affected, dict):
        if affected.get("error"):
            return f"查詢發生錯誤：{affected['error']}"
        affected = affected.get("affected_stations") or affected.get("stations") or affected.get("path") or []

    if not isinstance(affected, list):
        return f"【⚠️ 延誤波及警示】\n  ● 事故站：{station_id}\n  ● 查詢結果：{affected}"

    station_labels = [_normalise_route_item(station) for station in affected]
    joined = "、".join(station_labels)

    return (
        f"【⚠️ 延誤波及警示】\n"
        f"  ● 事故站：{station_id}\n"
        f"  ● 受波及站點：{joined}"
    )


# ── Intent detection ──────────────────────────────────────────────────────────

def _route_intent_and_params(message: str) -> tuple[Optional[str], dict[str, Any], Optional[str]]:
    """
    判斷使用者訊息是否應該繞過 LLM，直接查詢 graph database。

    Returns:
        tool_name, params, validation_error
    """
    augmented = _inject_station_ids(message)
    lower = augmented.lower()
    station_ids = _extract_station_ids(augmented)

    # A. 單站延誤波及查詢
    if len(station_ids) >= 1 and _contains_any(lower, _RIPPLE_KEYWORDS):
        return "find_delay_ripple", {
            "station_id": station_ids[0],
            "depth": 2,
        }, None

    # B. 路線查詢
    is_route_query = len(station_ids) >= 2 and (
        _contains_any(lower, _ROUTE_KEYWORDS)
        or _contains_any(lower, _COST_KEYWORDS)
        or _contains_any(lower, _ALTERNATIVE_KEYWORDS)
    )

    if not is_route_query:
        return None, {}, None

    origin_id, destination_id = station_ids[0], station_ids[1]

    if not _is_valid_station_id(origin_id) or not _is_valid_station_id(destination_id):
        return None, {}, "站點代碼格式不正確，請使用例如 MS01 或 NR01 的格式。"

    network = _network_from_station_pair(origin_id, destination_id)
    optimise_by = "cost" if _contains_any(lower, _COST_KEYWORDS) else "time"

    # C. 替代路線 / 繞過事故站
    if _contains_any(lower, _ALTERNATIVE_KEYWORDS):
        if len(station_ids) < 3:
            return None, {}, "請提供要避開的事故或封閉站點 ID，例如：從 MS01 到 MS09 繞過 MS05。"

        avoid_station_id = station_ids[2]

        if avoid_station_id in {origin_id, destination_id}:
            return None, {}, "避開站點不能與起點或終點相同，請重新指定事故或封閉站點。"

        return "find_alternative_routes", {
            "origin_id": origin_id,
            "destination_id": destination_id,
            "avoid_station_id": avoid_station_id,
            "network": network,
        }, None

    # D. 一般最快 / 最便宜 / 跨網絡路線
    return "find_route", {
        "origin_id": origin_id,
        "destination_id": destination_id,
        "network": network,
        "optimise_by": optimise_by,
    }, None


# ── Tool executor ─────────────────────────────────────────────────────────────

def _execute_tool(
    tool_name: str,
    params: dict[str, Any],
    current_user_email: Optional[str] = None,
) -> str:
    try:
        if tool_name == "find_route":
            origin_id = params["origin_id"]
            destination_id = params["destination_id"]
            network = params.get("network", "auto")
            optimise_by = params.get("optimise_by", "time")

            if _is_cross_network(origin_id, destination_id):
                result = query_interchange_path(origin_id, destination_id)
                return _format_route_result(result, title="TransitFlow 跨網絡轉乘路線")

            if optimise_by == "cost":
                result = query_cheapest_route(
                    origin_id=origin_id,
                    destination_id=destination_id,
                    network=network,
                )
                return _format_route_result(result, title="TransitFlow 最便宜路線")

            result = query_shortest_route(
                origin_id=origin_id,
                destination_id=destination_id,
                network=network,
            )
            return _format_route_result(result, title="TransitFlow 最快路線")

        if tool_name == "find_alternative_routes":
            result = query_alternative_routes(
                params["origin_id"],
                params["destination_id"],
                params["avoid_station_id"],
                params.get("network", "auto"),
            )
            return _format_route_result(result, title="TransitFlow 替代路線")

        if tool_name == "find_delay_ripple":
            station_id = params["station_id"]
            depth = int(params.get("depth", 2))
            result = query_delay_ripple(station_id, depth)
            return _format_delay_ripple(station_id, result)

        if tool_name == "search_policy":
            embedding = llm.embed(params["query"])
            return str(query_policy_vector_search(embedding)[:1])

        return "暫時無相關數據。"

    except KeyError as exc:
        return f"工具參數缺失：{exc}"
    except Exception as exc:
        return f"資料庫查詢失敗：{exc}"


# ── History helper ────────────────────────────────────────────────────────────

def _append_history(
    history: list[dict],
    user_message: str,
    assistant_message: str,
) -> list[dict]:
    new_history = list(history)
    new_history.append({"role": "user", "content": user_message})
    new_history.append({"role": "assistant", "content": assistant_message})
    return new_history


# ── Main agent entry point ────────────────────────────────────────────────────

def run_agent(
    user_message: str,
    history: list[dict],
    debug: bool = False,
    current_user_email: Optional[str] = None,
) -> tuple[str, list[dict]]:
    """
    TransitFlow 主代理流程：
    1. 先嘗試用硬規則判斷 route / cheapest / alternative / ripple
    2. 若是 deterministic 查詢，直接呼叫 database tool
    3. 只有一般對話才交給 LLM
    """
    tool_name, params, validation_error = _route_intent_and_params(user_message)

    if validation_error:
        reply = f"您好！我是 TransitFlow。{validation_error}"
        return reply, _append_history(history, user_message, reply)

    if tool_name:
        db_result = _execute_tool(tool_name, params, current_user_email)

        origin = params.get("origin_id")
        destination = params.get("destination_id")

        if origin and destination:
            heading = f"為您查詢從 {origin} 到 {destination} 的導航資訊："
        else:
            heading = "為您查詢相關交通影響資訊："

        debug_line = f"\n\n[debug] tool={tool_name}, params={params}" if debug else ""

        reply = (
            f"您好！我是 TransitFlow。{heading}\n\n"
            f"{db_result}"
            f"{debug_line}\n\n"
            f"祝您旅途愉快！"
        )

        return reply, _append_history(history, user_message, reply)

    # 一般對話才交給 LLM
    augmented_message = _inject_station_ids(user_message)
    recent_history = history[-4:] if len(history) > 4 else history

    full_messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in recent_history
    ]
    full_messages.append({"role": "user", "content": augmented_message})

    final_reply = llm.chat(
        messages=full_messages,
        system_prompt=SYSTEM_PROMPT,
    )

    return final_reply, _append_history(history, user_message, final_reply)


# ── Interactive Terminal Chat Loop ────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("🤖 TransitFlow 智慧交通助理")
    print("=" * 60)
    print("指令提示：輸入 'debug on/off' 切換除錯模式，'exit' 離開\n")

    chat_history: list[dict] = []
    debug_mode = False

    while True:
        try:
            user_input = input("User > ").strip()

            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit"}:
                print("再見！祝您旅途愉快。")
                break

            if user_input.lower() == "debug on":
                debug_mode = True
                print("[DEBUG 模式已開啟]")
                continue

            if user_input.lower() == "debug off":
                debug_mode = False
                print("[DEBUG 模式已關閉]")
                continue

            print("🤖 TransitFlow 正在精準檢索資料庫並生成回覆...")

            reply, chat_history = run_agent(
                user_message=user_input,
                history=chat_history,
                debug=debug_mode,
            )

            print(f"\nAssistant > {reply}")
            print("-" * 50)

        except KeyboardInterrupt:
            print("\n再見！")
            break