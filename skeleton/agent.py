"""
TransitFlow — Intelligent Agent
================================
此版本已調整以配合 TransitQueryManager 類別架構與精確的介面顯示格式。
"""

from __future__ import annotations
import re
from typing import Optional
from skeleton.llm_provider import llm
from databases.graph.queries import TransitQueryManager

# 初始化圖資料庫管理器
db_manager = TransitQueryManager()

# ── Station name → ID lookup ──────────────────────────────────────────────────
_STATION_INDEX: dict[str, str] = {
    "central square": "MS01", "riverside":   "MS02", "northgate":  "MS03",
    "elm park":       "MS04", "westfield":   "MS05", "harbour view": "MS06",
    "old town":       "MS07", "university":  "MS08", "queensbridge": "MS09",
    "parkside":       "MS10", "greenhill":   "MS11", "lakeshore":  "MS12",
    "clifton":        "MS13", "eastwick":    "MS14", "ferndale":   "MS15",
    "hilltop":        "MS16", "broadmoor":   "MS17", "sunnyvale":  "MS18",
    "redwood":        "MS19", "thornton":    "MS20",
    "central station":   "NR01", "maplewood":     "NR02",
    "old town junction": "NR03", "ashford":        "NR04",
    "stonehaven":        "NR05", "bridgeport":     "NR06",
    "ferndale halt":     "NR07", "coalport":       "NR08",
    "dunmore":           "NR09", "langford end":   "NR10",
}

def _inject_station_ids(text: str) -> str:
    result = text
    seen_ids: set[str] = set()
    for name in sorted(_STATION_INDEX, key=len, reverse=True):
        sid = _STATION_INDEX[name]
        if sid in seen_ids: continue
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(f"{name} ({sid})", result)
            seen_ids.add(sid)
    return result

SYSTEM_PROMPT = "你是一個非常有用的繁體中文交通助理 TransitFlow。回答請保持簡短、精確、流暢。"

def _format_route_result_for_small_llm(data) -> str:
    if not data or (isinstance(data, dict) and not data.get("found", True)):
        return "經查，目前兩站之間沒有可行路線。"
    try:
        if isinstance(data, dict) and 'path' in data:
            station_names = [f"{s['name']} ({s['station_id']})" for s in data['path']]
            route_str = " ➔ ".join(station_names)
            return f"【🔍 TransitFlow 最佳路線導航】\n  ● 乘車路線：{route_str}\n  ● 預估總耗時：{data.get('total_time_min', '未定')} 分鐘"
        return str(data)
    except:
        return "查詢解析失敗。"

def _execute_tool(tool_name: str, params: dict) -> str:
    try:
        if tool_name == "find_route":
            res = db_manager.query_shortest_route(params["origin_id"], params["destination_id"])
            return _format_route_result_for_small_llm(res)
        return "暫時無相關數據。"
    except Exception as e:
        return f"資料庫查詢失敗: {str(e)}"

def run_agent(user_message: str, history: list[dict]) -> tuple:
    _augmented_message = _inject_station_ids(user_message)
    _station_ids = re.findall(r'\b(MS\d{2}|NR\d{2})\b', _augmented_message, re.IGNORECASE)
    
    if len(_station_ids) >= 2:
        params = {"origin_id": _station_ids[0].upper(), "destination_id": _station_ids[1].upper()}
        db_result = _execute_tool("find_route", params)
        safe_reply = (
            f"您好！我是 TransitFlow。為您查詢從 {_station_ids[0].upper()} 到 {_station_ids[1].upper()} 的導航資訊：\n\n"
            f"{db_result}\n\n"
            f"祝您旅途愉快！"
        )
        return safe_reply, history + [{"role": "user", "content": user_message}, {"role": "assistant", "content": safe_reply}]

    final_reply = llm.chat(messages=history + [{"role": "user", "content": _augmented_message}], system_prompt=SYSTEM_PROMPT)
    return final_reply, history + [{"role": "user", "content": user_message}, {"role": "assistant", "content": final_reply}]

if __name__ == "__main__":
    chat_history = []
    print("\n" + "="*60)
    print("🤖 TransitFlow 智慧交通")
    print("============================================================\n")

    while True:
        try:
            u = input("\nUser > ").strip()
            if u.lower() in ["exit", "quit"]: break
            
            print("\n🤖 Agent 正在精準檢索資料庫並生成路線...")
            reply, chat_history = run_agent(u, chat_history)
            print(f"\nAssistant > {reply}")
            print("-" * 50)
        except KeyboardInterrupt: break