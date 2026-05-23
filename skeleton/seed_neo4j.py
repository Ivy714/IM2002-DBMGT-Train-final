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

import os
import sys
from neo4j import GraphDatabase

# ── 讀取 Neo4j 配置 ──────────────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7688")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "transitflow")


def run_seeder():
    print("\n" + "="*60)
    print("🌱 TransitFlow 正在為 Neo4j 圖資料庫注入種子資料...")
    print(f"🔗 連線目標：{NEO4J_URI}")
    print("="*60)

    # 尋找 seed.cypher 檔案路徑
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cypher_path = os.path.join(base_dir, "databases", "graph", "seed.cypher")
    
    if not os.path.exists(cypher_path):
        print(f"❌ 錯誤：找不到種子檔案，預期路徑應為：{cypher_path}")
        sys.exit(1)

    # 讀取並解析 Cypher 語句
    with open(cypher_path, "r", encoding="utf-8") as f:
        cypher_content = f.read()

    # 精準解析：以分號分割，並細緻清洗空行與註解
    statements = []
    for chunk in cypher_content.split(";"):
        lines = []
        for line in chunk.split("\n"):
            line_cleaned = line.strip()
            # 排除純註解行
            if line_cleaned and not line_cleaned.startswith("//"):
                lines.append(line_cleaned)
        
        stmt = " ".join(lines).strip()
        if stmt:
            statements.append(stmt)

    # 開始執行資料庫寫入
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        
        # 💡 根本解決點：顯式指定 database="neo4j"，強制與網頁端對齊同一個預設資料庫
        with driver.session(database="neo4j") as session:
            
            print(f"🧹 正在清理舊有的邊與轉乘關係...")
            session.run("MATCH ()-[r:METRO_LINK|RAIL_LINK|INTERCHANGE_TO]->() DELETE r")
            session.run("MATCH (n:Station) DELETE n")
            
            print(f"🚀 正在執行共 {len(statements)} 項 Cypher 圖形結構建置...")
            for idx, stmt in enumerate(statements, 1):
                try:
                    # 使用 write_transaction 或直接 session.run
                    session.run(stmt)
                except Exception as stmt_error:
                    # 捕捉約束重複建立等非致命錯誤
                    if "already exists" in str(stmt_error).lower() or "equivalent" in str(stmt_error).lower():
                        continue
                    else:
                        print(f"⚠️  執行第 {idx} 條指令時出現非致命提示：{str(stmt_error)}")
            
        driver.close()
        print("  ● 已顯式導向 'neo4j' 預設資料庫，網頁快取已可正常同步。")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ 資料庫連線或寫入失敗：{str(e)}")
        print("💡 請確認 VS Code 中的 .env 檔案之 NEO4J_URI 埠號是否確實為 7688。")
        sys.exit(1)


if __name__ == "__main__":
    run_seeder()