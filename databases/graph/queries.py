from neo4j import GraphDatabase
from config import settings
from typing import Any, Dict, List

class TransitQueryManager:
    """
    TransitQueryManager: 負責與 Neo4j 圖資料庫進行互動的核心類別。
    封裝了交通路徑規劃與延遲影響查詢的所有邏輯。
    """
    
    def __init__(self):
        """初始化 Neo4j Driver 連線，並處理連線異常"""
        try:
            # 從 config.py 讀取設定進行初始化
            self.driver = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
        except Exception as e:
            print(f"Driver Initialization Failed: {e}")
            self.driver = None

    def close(self):
        """關閉資料庫連線，釋放資源"""
        if self.driver:
            self.driver.close()

    def query_shortest_route(self, origin_id: str, destination_id: str, network: str = "auto") -> Dict[str, Any]:
        """
        計算起訖站之間的時間最短路徑：
        1. 根據起訖站 ID 的字首判定網絡類型 (Metro/Rail)。
        2. 使用 Cypher 的 reduce 函數累加 travel_time 與 walking_time。
        3. 回傳包含路徑與總時間的結構化字典。
        """
        if not self.driver: return {"error": "Neo4j driver not initialized."}

        # 根據起訖點判定查詢的關係路徑模式 (Path Pattern)
        if origin_id.upper().startswith("MS") and destination_id.upper().startswith("MS"):
            rel_pattern = "METRO_LINK*..15"
        elif origin_id.upper().startswith("NR") and destination_id.upper().startswith("NR"):
            rel_pattern = "RAIL_LINK*..15"
        else:
            rel_pattern = "METRO_LINK|RAIL_LINK|INTERCHANGE_TO*..15"

        # 定義 Cypher 查詢語句，使用參數化查詢以防止注入攻擊
        cypher_query = f"""
        MATCH p = (start {{station_id: $origin_id}})-[:{rel_pattern}]->(end {{station_id: $destination_id}})
        WITH p, 
             reduce(s = 0, r IN relationships(p) | 
                s + 
                CASE WHEN "travel_time_min" IN keys(r) THEN coalesce(properties(r)["travel_time_min"], 0) ELSE 0 END +
                CASE WHEN "walking_time_min" IN keys(r) THEN coalesce(properties(r)["walking_time_min"], 0) ELSE 0 END
             ) AS total_time
        RETURN p, total_time
        ORDER BY total_time ASC LIMIT 1
        """
        
        with self.driver.session() as session:
            record = session.run(cypher_query, origin_id=origin_id, destination_id=destination_id).single()
            if not record: return {"found": False, "error": "No route found."}
            
            # 解析路徑中的節點資料，自動標示站點類型
            path = record["p"]
            stations_path = [{
                "station_id": node.get("station_id"),
                "name": node.get("name", "Unknown"),
                "type": "Metro" if node.get("station_id", "").startswith("MS") else "Rail"
            } for node in path.nodes]
            
            return {"found": True, "total_time_min": record["total_time"], "path": stations_path}

    def query_cheapest_route(self, origin_id: str, destination_id: str, network: str = "auto") -> Dict[str, Any]:
        """
        計算起訖站之間費用最便宜的路徑：
        使用 cost 屬性進行累加並排序。
        """
        if not self.driver: return {"error": "Neo4j driver offline."}
        
        # 判定關係模式，若為同一網絡則鎖定特定關係，跨網則啟用轉乘模式
        rel_pattern = "METRO_LINK*..15" if (origin_id.upper().startswith("MS") and destination_id.upper().startswith("MS")) else "METRO_LINK|RAIL_LINK|INTERCHANGE_TO*..15"

        cypher_query = f"""
        MATCH p = (start {{station_id: $origin_id}})-[:{rel_pattern}]->(end {{station_id: $destination_id}})
        WITH p, reduce(s = 0, r IN relationships(p) | s + CASE WHEN "cost" IN keys(r) THEN coalesce(properties(r)["cost"], 0) ELSE 0 END) AS total_cost
        RETURN p, total_cost ORDER BY total_cost ASC LIMIT 1
        """
        with self.driver.session() as session:
            record = session.run(cypher_query, origin_id=origin_id, destination_id=destination_id).single()
            return {"found": True, "total_cost": record["total_cost"]} if record else {"found": False}

    def query_delay_ripple(self, station_id: str, depth: int = 2) -> List[Dict[str, Any]]:
        """
        分析車站延誤後的 ripple effect (漣漪效應)：
        搜尋指定深度內所有受到影響的相鄰車站。
        """
        if not self.driver: return []
        
        # 搜尋變長路徑關係 (Variable-length path)，排除自身站點，回傳受影響站點清單
        cypher_query = f"""
        MATCH (s {{station_id: $station_id}})-[*1..{depth}]-(affected)
        WHERE affected.station_id <> $station_id
        RETURN DISTINCT affected.station_id AS station_id, affected.name AS name
        """
        with self.driver.session() as session:
            # 直接將 Neo4j 的 Record 轉換為字典清單回傳
            return [record.data() for record in session.run(cypher_query, station_id=station_id)]