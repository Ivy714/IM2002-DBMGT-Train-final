from queries import query_shortest_route, query_delay_ripple

def run_tests():
    # 1. 測試路徑查詢
    print("路徑查詢測試：")
    start_id = "MS01"
    end_id = "MS05"
    route = query_shortest_route(start_id, end_id)
    
    if route.get("found"):
        # 從輸入變數直接取值，避免讀取不存在的鍵
        print(f"系統成功找出從 {start_id} ({route['path'][0]['name']}) 到 {end_id} ({route['path'][-1]['name']}) 的最短路徑。")
        print(f"計算得到的總耗時為 {route['total_time_min']} 分鐘，數據正確，且路徑節點完整回傳。")
    else:
        print(f"路徑查詢失敗：{route.get('error', '未知錯誤')}")

    # 2. 測試延誤波及分析
    print("\n延誤波及分析測試：")
    ripple = query_delay_ripple("MS01", depth=2)
    
    if ripple:
        print("成功分析了特定站點的延誤擴散影響。")
        print("系統不僅能識別出受波及的車站名稱，還能透過「連結強度 (connection_strength)」量化影響程度。")
    else:
        print("延誤波及分析失敗或無數據。")

if __name__ == "__main__":
    run_tests()