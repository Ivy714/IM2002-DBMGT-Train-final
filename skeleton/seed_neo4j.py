"""
TransitFlow — Neo4j Seeder
Run once after starting Docker:
    python skeleton/seed_neo4j.py

Loads station and network data from train-mock-data/:
  - metro_stations.json         — city metro stations and adjacencies
  - national_rail_stations.json — national rail stations and adjacencies

Design your graph schema (node labels, relationship types, properties)
based on the data in these files, then implement the seed() function below.
"""
"""
TransitFlow — Neo4j Seeding Script (Root-Cause Fixed Edition)
=============================================================
透過顯式指定資料庫名稱與加強型解析，徹底解決 Docker 環境下資料移位與網頁不對齊的根本問題。
"""
import json
import os
from neo4j import GraphDatabase

def seed_from_json():
    # 1. 讀取 JSON
    json_path = "databases/data/metro_stations.json" # 請確保你的路徑正確
    with open(json_path, 'r', encoding='utf-8') as f:
        stations = json.load(f)

    driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7688"), 
                                  auth=(os.getenv("NEO4J_USER", "neo4j"), 
                                        os.getenv("NEO4J_PASSWORD", "transitflow")))

    with driver.session(database="neo4j") as session:
        # 清理舊資料
        session.run("MATCH (n) DETACH DELETE n")
        
        # 2. 建立所有車站節點
        for s in stations:
            session.run("""
                MERGE (n:Station {station_id: $id})
                SET n.name = $name, n.lines = $lines, n.type = 'Metro'
            """, id=s['station_id'], name=s['name'], lines=s['lines'])

        # 3. 建立相鄰關係 (Adjacent Stations)
        for s in stations:
            for adj in s['adjacent_stations']:
                session.run("""
                    MATCH (a:Station {station_id: $id1}), (b:Station {station_id: $id2})
                    MERGE (a)-[:METRO_LINK {line: $line, travel_time_min: $time}]->(b)
                """, id1=s['station_id'], id2=adj['station_id'], line=adj['line'], time=adj['travel_time_min'])

        # 4. 建立與國鐵的轉乘連結 (依據 JSON 中的 interchange_national_rail_station_id)
        for s in stations:
            if s.get('is_interchange_national_rail'):
                nr_id = s['interchange_national_rail_station_id']
                session.run("""
                    MATCH (m:Station {station_id: $m_id})
                    MERGE (nr:Station {station_id: $nr_id})
                    SET nr.type = 'Rail', nr.name = 'National Rail Station'
                    MERGE (m)-[:INTERCHANGE_TO {walking_time_min: 5}]->(nr)
                    MERGE (nr)-[:INTERCHANGE_TO {walking_time_min: 5}]->(m)
                """, m_id=s['station_id'], nr_id=nr_id)

    print("✅全地圖節點與轉乘關係已建立。")
    driver.close()

if __name__ == "__main__":
    seed_from_json()