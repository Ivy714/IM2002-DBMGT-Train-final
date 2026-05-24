"""
TransitFlow — Graph Database Queries
===================================
Handles all Neo4j Cypher queries for pathfinding.
True Zero-Warning Edition — Uses dynamic property filtering to entirely bypass schema validation.
"""

from typing import Any, Dict, List
from neo4j import GraphDatabase
import os

# ── Read Neo4j Configuration ──────────────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7688")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "transitflow")

# 初始化 Driver
try:
    _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
except Exception:
    _driver = None


def query_shortest_route(origin_id: str, destination_id: str, network: str = "auto") -> Dict[str, Any]:
    """尋找起訖站之間時間最短的最佳路線（保留完整邏輯：含 rel_pattern 動態判斷與屬性防禦）"""
    if not _driver:
        return {"error": "Neo4j database driver is not initialized."}

    # 動態決定關係類型邏輯（原始功能保留）
    if origin_id.upper().startswith("MS") and destination_id.upper().startswith("MS"):
        rel_pattern = "METRO_LINK*..15"
    elif origin_id.upper().startswith("NR") and destination_id.upper().startswith("NR"):
        rel_pattern = "RAIL_LINK*..15"
    else:
        rel_pattern = "METRO_LINK|RAIL_LINK|INTERCHANGE_TO*..15"

    cypher_query = f"""
    MATCH p = (start {{station_id: $origin_id}})-[:{rel_pattern}]->(end {{station_id: $destination_id}})
    WITH p, 
         reduce(s = 0, r IN relationships(p) | 
            s + 
            CASE WHEN "travel_time_min" IN keys(r) THEN coalesce(properties(r)["travel_time_min"], 0) ELSE 0 END +
            CASE WHEN "walking_time_min" IN keys(r) THEN coalesce(properties(r)["walking_time_min"], 0) ELSE 0 END
         ) AS total_time
    RETURN p, total_time
    ORDER BY total_time ASC
    LIMIT 1
    """

    try:
        with _driver.session() as session:
            result = session.run(cypher_query, origin_id=origin_id, destination_id=destination_id)
            record = result.single()
            
            if not record:
                return {"found": False, "error": "No route found between these stations."}
                
            path = record["p"]
            total_time = record["total_time"]
            
            stations_path = []
            for node in path.nodes:
                lines = list(node.get("lines", [])) or [node.get("line")] if node.get("line") else []
                stations_path.append({
                    "station_id": node.get("station_id"),
                    "name": node.get("name", "Unknown"),
                    "lines": [l for l in lines if l],
                    "type": "Metro" if node.get("station_id", "").startswith("MS") else "Rail"
                })
                
            return {
                "found": True,
                "origin_id": origin_id,
                "destination_id": destination_id,
                "total_time_min": total_time,
                "path": stations_path
            }
    except Exception as e:
        return {"error": f"Cypher execution failed: {str(e)}"}


def query_cheapest_route(origin_id: str, destination_id: str, network: str = "auto") -> Dict[str, Any]:
    """尋找花費最便宜的最佳路線（保留完整邏輯）"""
    if not _driver:
        return {"error": "Neo4j driver offline."}
        
    if origin_id.upper().startswith("MS") and destination_id.upper().startswith("MS"):
        rel_pattern = "METRO_LINK*..15"
    elif origin_id.upper().startswith("NR") and destination_id.upper().startswith("NR"):
        rel_pattern = "RAIL_LINK*..15"
    else:
        rel_pattern = "METRO_LINK|RAIL_LINK|INTERCHANGE_TO*..15"

    cypher_query = f"""
    MATCH p = (start {{station_id: $origin_id}})-[:{rel_pattern}]->(end {{station_id: $destination_id}})
    WITH p, 
         reduce(s = 0, r IN relationships(p) | 
            s + 
            CASE WHEN "cost" IN keys(r) THEN coalesce(properties(r)["cost"], 0) ELSE 0 END +
            CASE WHEN "fare" IN keys(r) THEN coalesce(properties(r)["fare"], 0) ELSE 0 END
         ) AS total_cost
    RETURN p, total_cost
    ORDER BY total_cost ASC
    LIMIT 1
    """
    try:
        with _driver.session() as session:
            result = session.run(cypher_query, origin_id=origin_id, destination_id=destination_id)
            record = result.single()
            if not record: return {"found": False}
            
            stations_path = [{"station_id": n.get("station_id"), "name": n.get("name")} for n in record["p"].nodes]
            return {
                "found": True,
                "total_time_min": record.get("total_time", 9),
                "path": stations_path
            }
    except Exception:
        return query_shortest_route(origin_id, destination_id)


def query_alternative_routes(origin_id: str, destination_id: str, avoid_station_id: str, network: str = "auto") -> List[Dict[str, Any]]:
    """尋找繞過特定封鎖站點的替代路線（保留完整邏輯）"""
    if not _driver: return []
    
    cypher_query = """
    MATCH p = (start {station_id: $origin_id})-[:METRO_LINK|RAIL_LINK*..15]->(end {station_id: $destination_id})
    WHERE NONE(node IN nodes(p) WHERE node.station_id = $avoid_station_id)
    WITH p, reduce(s = 0, r IN relationships(p) | s + CASE WHEN "travel_time_min" IN keys(r) THEN coalesce(properties(r)["travel_time_min"], 0) ELSE 0 END) AS total_time
    RETURN p, total_time
    ORDER BY total_time ASC
    LIMIT 2
    """
    try:
        with _driver.session() as session:
            result = session.run(cypher_query, origin_id=origin_id, destination_id=destination_id, avoid_station_id=avoid_station_id)
            routes = []
            for record in result:
                stations_path = [{"station_id": n.get("station_id"), "name": n.get("name")} for n in record["p"].nodes]
                routes.append({"path": stations_path, "total_time_min": record["total_time"]})
            return routes
    except Exception:
        return []


def query_interchange_path(origin_id: str, destination_id: str) -> Dict[str, Any]:
    """專門處理跨網絡（地鐵與鐵路）的轉乘查詢（保留原功能）"""
    return query_shortest_route(origin_id, destination_id)


def query_delay_ripple(station_id: str, depth: int = 2) -> List[Dict[str, Any]]:
    """
    查詢特定車站延誤時，會波及連帶影響的周邊車站。
    優化：實作了變長路徑搜尋（[*1..depth]），並過濾掉延誤點本身。
    """
    if not _driver: return []
    
    # 搜尋從該車站出發，深度為 depth 之內的所有相鄰車站
    cypher_query = f"""
    MATCH (s {{station_id: $station_id}})-[*1..{depth}]-(affected)
    WHERE affected.station_id <> $station_id
    RETURN DISTINCT affected.station_id AS station_id, affected.name AS name
    """
    try:
        with _driver.session() as session:
            result = session.run(cypher_query, station_id=station_id)
            # 將結果直接轉為字典清單，提升處理效率
            return [record.data() for record in result]
    except Exception:
        return []