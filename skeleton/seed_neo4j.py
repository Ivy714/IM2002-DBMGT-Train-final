"""
TransitFlow — Neo4j Seeding Script
=============================================================
功能：
1. 自動讀取 databases/data/metro_stations.json
2. 建立車站節點與轉乘關係
3. 增加健壯性檢查 (路徑、連線處理)
4. 與 schema.sql 的 station_id 完美對齊
"""

import json
import os
import sys
from neo4j import GraphDatabase

def seed_from_json():
    json_path = "databases/data/metro_stations.json"
    
    # 1. 健壯性檢查：路徑確認
    if not os.path.exists(json_path):
        print(f"❌ 錯誤：找不到檔案 {json_path}")
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        stations = json.load(f)

    # 連線設定
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7688")
    user = os.getenv("NEO4J_USER", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "transitflow")
    
    driver = GraphDatabase.driver(uri, auth=(user, pwd))

    try:
        with driver.session(database="neo4j") as session:
            print("🧹 正在清理舊資料...")
            session.run("MATCH (n) DETACH DELETE n")
            
            # 2. 建立所有車站節點
            print(f"🏗️ 正在建立 {len(stations)} 個車站節點...")
            for s in stations:
                session.run("""
                    MERGE (n:Station {station_id: $id})
                    SET n.name = $name, 
                        n.lines = $lines, 
                        n.type = 'Metro',
                        n.is_nr_interchange = $is_nr
                """, id=s['station_id'], 
                     name=s['name'], 
                     lines=s['lines'], 
                     is_nr=s.get('is_interchange_national_rail', False))

            # 3. 建立相鄰關係
            print("🔗 正在建立 METRO_LINK 關係...")
            for s in stations:
                for adj in s['adjacent_stations']:
                    session.run("""
                        MATCH (a:Station {station_id: $id1}), (b:Station {station_id: $id2})
                        MERGE (a)-[:METRO_LINK {line: $line, travel_time_min: $time}]->(b)
                    """, id1=s['station_id'], 
                         id2=adj['station_id'], 
                         line=adj['line'], 
                         time=adj['travel_time_min'])

            # 4. 建立與國鐵的轉乘連結
            print("🚉 正在建立 INTERCHANGE_TO 轉乘站點...")
            for s in stations:
                if s.get('is_interchange_national_rail'):
                    nr_id = s['interchange_national_rail_station_id']
                    session.run("""
                        MATCH (m:Station {station_id: $m_id})
                        MERGE (nr:Station {station_id: $nr_id})
                        SET nr.type = 'Rail', 
                            nr.name = 'National Rail Station',
                            nr.is_nr_interchange = true
                        MERGE (m)-[:INTERCHANGE_TO {walking_time_min: 5}]->(nr)
                        MERGE (nr)-[:INTERCHANGE_TO {walking_time_min: 5}]->(m)
                    """, m_id=s['station_id'], nr_id=nr_id)

        print("✅ 全地圖節點與轉乘關係已成功部署！")
    
    except Exception as e:
        print(f"❌ 部署過程中發生錯誤: {e}")
    
    finally:
        driver.close()

if __name__ == "__main__":
    seed_from_json()