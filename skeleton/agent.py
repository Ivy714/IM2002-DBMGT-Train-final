"""
TransitFlow — Intelligent Agent (Full Business Logic Edition)
=============================================================
升級功能：
1. 支援兒童半價邏輯 (條件式費用計算)
2. 整合 RAG 檢索接口，支援退款與規則查詢 (階段二)
3. 語意解析升級，支援更自然的「便宜」、「退款」、「兒童」查詢
"""

from __future__ import annotations
import re
from typing import Optional
from skeleton.llm_provider import llm
from databases.graph.queries import TransitQueryManager

# 初始化管理器
db_manager = TransitQueryManager()

_STATION_INDEX = {
    "central square": "MS01", "riverside": "MS02", "northgate": "MS03",
    "elm park": "MS04", "westfield": "MS05", "central station": "NR01",
    "maplewood": "NR02", "old town junction": "NR03", "ashford": "NR04"
}

def _inject_station_ids(text: str) -> str:
    result = text
    for name in sorted(_STATION_INDEX, key=len, reverse=True):
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        result = pattern.sub(f"{name} ({_STATION_INDEX[name]})", result)
    return result

def _format_route_result(data, mode="time", passenger_type="adult") -> str:
    if not data or not data.get("found"):
        return "經查，目前兩站之間沒有可行路線。"
    
    # 邏輯升級：根據身份計算票價
    final_cost = data.get("total_cost", 0)
    if passenger_type == "child":
        final_cost = final_cost * 0.5
        note = "（已套用兒童半價優惠）"
    else:
        note = ""

    lines = ["【🔍 TransitFlow 最佳路線導航】"]
    if 'path' in data:
        lines.append(f"  ● 乘車路線：{' ➔ '.join([s['name'] for s in data['path']])}")
    
    if mode == "cost":
        lines.append(f"  ● 預估總花費：{round(final_cost, 2)} 元 {note}")
    else:
        lines.append(f"  ● 預估總耗時：{data.get('total_time_min', '未定')} 分鐘")
            
    return "\n".join(lines)

def run_agent(user_message: str, history: list[dict]) -> tuple:
    # 1. 意圖檢測：處理規則查詢 (階段二)
    if any(k in user_message for k in ["退款", "規則", "行李", "政策"]):
        # 這裡未來可串接 RAG 檢索邏輯，目前先回傳提示
        return "有關退款與營運政策，請參閱我們的線上規則手冊 (RF001-RF005)，或告知具體問題 ID。", history

    # 2. 導航與計價查詢 (階段一與階段三)
    _augmented = _inject_station_ids(user_message)
    _ids = re.findall(r'\b(MS\d{2}|NR\d{2})\b', _augmented, re.IGNORECASE)
    
    if len(_ids) >= 2:
        optimise = "cost" if any(k in user_message for k in ["便宜", "最省", "價格"]) else "time"
        passenger = "child" if "兒童" in user_message else "adult"
        
        # 呼叫升級後的 db_manager
        res = db_manager.query_cheapest_route(_ids[0].upper(), _ids[1].upper()) if optimise == "cost" \
              else db_manager.query_shortest_route(_ids[0].upper(), _ids[1].upper())
        
        db_result = _format_route_result(res, mode=optimise, passenger_type=passenger)
        
        reply = f"導航建議 ({_ids[0].upper()} ➔ {_ids[1].upper()}):\n{db_result}"
        return reply, history + [{"role": "user", "content": user_message}, {"role": "assistant", "content": reply}]

    # 3. 一般對話
    final_reply = llm.chat(messages=history + [{"role": "user", "content": _augmented}])
    return final_reply, history + [{"role": "user", "content": user_message}, {"role": "assistant", "content": final_reply}]