# AI Session Context — TransitFlow

**How to use this file:**
At the start of every AI coding session, paste the full contents of this file as your first message to your AI assistant. This gives the AI the context it needs to produce code that fits your codebase and is consistent with your teammates' work.

**Who maintains this file:**
Whoever makes a schema change or architectural decision updates this file in the same commit. Treat it like a team contract.

---

## Project Overview

TransitFlow is a Python-based AI chat assistant for a fictional transit operator. It queries three databases — PostgreSQL (relational + vector), Neo4j (graph) — and uses an LLM to answer user questions. Our task as students is to design the database schema and implement the query functions in `databases/relational/queries.py` and `databases/graph/queries.py`.

## Tech Stack

- Language: Python 3.11+
- Relational DB: PostgreSQL via `psycopg2` with `RealDictCursor`
- Graph DB: Neo4j via the `neo4j` Python driver
- Vector search: `pgvector` extension (already implemented — do not modify)
- Web UI: Gradio
- LLM: Google Gemini or local Ollama (configured via `.env`)

## Coding Conventions

- **Naming:** `snake_case` for all Python names and SQL identifiers
- **Docstrings:** All functions must have a docstring with `Args:` and `Returns:` sections
- **Return types:** Use type hints. Read-only functions return `list[dict]` or `Optional[dict]`
- **Empty results:** Return `[]` or `None` (as documented), never raise an exception for "not found"
- **SQL:** Use `%s` placeholders for all user inputs — never string-format into SQL
- **Relational pattern:** Use `_connect()` helper + `psycopg2.extras.RealDictCursor`:
  ```python
  with _connect() as conn:
      with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
          cur.execute("SELECT ...", (param,))
          return [dict(row) for row in cur.fetchall()]
  ```
- **Graph pattern:** Use `_driver()` helper + session:
  ```python
  with _driver() as driver:
      with driver.session() as session:
          result = session.run("MATCH ...", station_id=station_id)
          return [dict(record) for record in result]
  ```

## Agreed Relational Schema

<!-- ============================================================
  FILL THIS IN after your team completes the schema design workshop.
  Paste your final CREATE TABLE statements here.
  ============================================================ -->

```sql
-- TODO: paste your final schema.sql contents here after team review
```

## Agreed Graph Schema

<!-- ============================================================
  FILL THIS IN after your team agrees on Neo4j node labels and
  relationship types.
  ============================================================ -->

```
Node labels:
- TODO

Relationship types:
- TODO

Key properties:
- TODO
```

## Function Signatures We Are Implementing

These are fixed contracts. AI-generated code must match these signatures exactly.

### Relational (`databases/relational/queries.py`)

```python
# Read-only
def query_national_rail_availability(origin_id: str, destination_id: str, travel_date: Optional[str] = None) -> list[dict]: ...
def query_national_rail_fare(schedule_id: str, fare_class: str, stops_travelled: int) -> Optional[dict]: ...
def query_metro_schedules(origin_id: str, destination_id: str) -> list[dict]: ...
def query_metro_fare(schedule_id: str, stops_travelled: int) -> Optional[dict]: ...
def query_available_seats(schedule_id: str, travel_date: str, fare_class: str) -> list[dict]: ...
def query_user_profile(user_email: str) -> Optional[dict]: ...
def query_user_bookings(user_email: str) -> dict: ...  # returns {"national_rail": [...], "metro": [...]}
def query_payment_info(booking_id: str) -> Optional[dict]: ...

# Write operations
def execute_booking(user_id, schedule_id, origin_station_id, destination_station_id, travel_date, fare_class, seat_id, ticket_type="single") -> tuple[bool, dict | str]: ...
def execute_cancellation(booking_id: str, user_id: str) -> tuple[bool, dict | str]: ...

# Auth
def register_user(email, first_name, surname, year_of_birth, password, secret_question, secret_answer) -> tuple[bool, str]: ...
def login_user(email: str, password: str) -> Optional[dict]: ...
def get_user_secret_question(email: str) -> Optional[str]: ...
def verify_secret_answer(email: str, answer: str) -> bool: ...
def update_password(email: str, new_password: str) -> bool: ...
```

### Graph (`databases/graph/queries.py`)

```python
def query_shortest_route(origin_id: str, destination_id: str, network: str = "auto") -> dict: ...
def query_cheapest_route(origin_id: str, destination_id: str, network: str = "auto", fare_class: str = "standard") -> dict: ...
def query_alternative_routes(origin_id, destination_id, avoid_station_id, network="auto", max_routes=3) -> list[list[dict]]: ...
def query_interchange_path(origin_id: str, destination_id: str) -> dict: ...
def query_delay_ripple(delayed_station_id: str, hops: int = 2) -> list[dict]: ...
def query_station_connections(station_id: str) -> list[dict]: ...
```

## Team Decisions Log

<!-- Add entries as you make decisions. Format: "Decision: X. Why: Y." -->

- [ ] Decision: PostgreSQL schema 分為 relational schema 與 vector schema。Why: Relational schema 儲存結構化交通與交易資料；vector schema 的 `policy_documents` 供 RAG / Help Desk semantic search 使用。
- [ ] Decision: Graph routing / adjacency / closures 不放在 PostgreSQL。Why: `schema.sql` 明確註記 graph routing、adjacency、closures 由 Neo4j 負責。
- [ ] Decision: Policy text / semantic Q&A 不放在一般 relational tables。Why: `schema.sql` 明確註記 policy semantic Q&A 由 pgvector 的 `policy_documents` 負責。
- [ ] Decision: 使用 ENUM 限制固定欄位值。Why: `network_type`、`service_type`、`fare_class`、`ticket_type`、`journey_status`、`payment_method`、`payment_status`、`day_of_week` 都有固定合法值。
- [ ] Decision: 使用 `users`、`user_credentials`、`user_security_questions` 分離使用者基本資料、密碼資料與安全問題。Why: 密碼與安全問題答案以 hash / salt 儲存，避免直接放在 `users` table。
- [ ] Decision: Metro 與 National Rail stations 分成 `metro_stations` 與 `national_rail_stations`。Why: 兩個 network 有不同 station metadata，且互相轉乘欄位透過 foreign key 連結。
- [ ] Decision: Station line membership 拆成 `metro_station_lines` 與 `national_rail_station_lines`。Why: 一個 station 可能屬於多條 line，因此以獨立 table 表示多對多關係。
- [ ] Decision: Metro 與 National Rail schedules 分成 `metro_schedules` 與 `national_rail_schedules`。Why: National Rail 有 `service_type` 與 fare class；Metro 使用固定 base fare / per-stop rate。
- [ ] Decision: National Rail fare 拆成 `national_rail_schedule_fares`。Why: 同一 schedule 依 `fare_class` 有不同 `base_fare_usd` 與 `per_stop_rate_usd`。
- [ ] Decision: Schedule stops 使用 `metro_schedule_stops` 與 `national_rail_schedule_stops` 儲存停靠順序。Why: 可用 `stop_order` 與 `travel_time_from_origin_min` 計算路徑與 travel time。
- [ ] Decision: National Rail schedule stops 使用 `is_stopping`。Why: Express service 可能經過但不停靠部分 stations。
- [ ] Decision: National Rail seat data 使用 `seat_layouts`、`coaches`、`seats` 三層設計。Why: 可依 schedule、coach、fare class 與 seat_id 管理座位。
- [ ] Decision: 使用 `journeys` 作為 National Rail bookings 與 Metro trips 的共同父層資料表。Why: `payments` 與 `feedback` 可以用真正的 foreign key 統一參照 `journeys(journey_id)`。
- [ ] Decision: National Rail booking 儲存在 `bookings`。Why: National Rail 支援 advance booking、fare class、coach、seat_id、travel_date 與 departure_time。
- [ ] Decision: Metro trip 儲存在 `metro_trips`。Why: Metro 使用 same-day trip / tap-in travel model，並支援 `day_pass_ref` 表示 day pass 後續搭乘紀錄。
- [ ] Decision: `payments` 使用 `journey_id` 連到 `journeys`。Why: 同一套 payment schema 可同時支援 National Rail bookings 與 Metro trips。
- [ ] Decision: `feedback` 使用 `journey_id` 與 `user_id`，並限制 `(journey_id, user_id)` 唯一。Why: 同一使用者對同一趟 journey 只能留下一次 feedback。
- [ ] Decision: Neo4j 使用 `MetroStation` 與 `NationalRailStation` 作為 node labels。Why: Metro 與 National Rail 是不同 network，但可透過 interchange relationship 連接。
- [ ] Decision: Neo4j 使用 `METRO_LINK`、`RAIL_LINK`、`INTERCHANGE_TO` 作為 relationship types。Why: 可清楚區分 Metro 連線、Rail 連線與跨 network 轉乘。
- [ ] Decision: Neo4j `station_id` 加上 unique constraints。Why: `seed.cypher` 定義 `MetroStation.station_id` 與 `NationalRailStation.station_id` 必須唯一。

## Prompts That Worked

<!-- Share prompts that produced good output so teammates can reuse them. -->

### Schema design prompt that worked:
```
請根據本專案的 train-mock-data JSON 檔案與 TransitFlow 需求，設計 PostgreSQL relational schema。

請特別處理：
1. 使用者、認證資料與安全問題
2. Metro stations / National Rail stations
3. Metro schedules / National Rail schedules
4. Schedule stops 與 operates_on
5. National Rail fare classes
6. National Rail seat layouts、coaches、seats
7. National Rail bookings 與 Metro trips
8. Payments 與 feedback 如何同時支援兩種 journey
9. pgvector policy_documents 保留不修改
10. primary keys、foreign keys、constraints、indexes、views
```

### Query implementation prompt that worked:
```
請根據 AI_SESSION_CONTEXT.md 與 schema.sql，實作 databases/relational/queries.py 中的指定 function。

要求：
1. function signature 必須完全符合 AI_SESSION_CONTEXT.md
2. 使用 _connect() helper
3. 使用 psycopg2.extras.RealDictCursor
4. 所有 SQL user inputs 必須使用 %s placeholders
5. read-only function 找不到資料時回傳 [] 或 None，不要 raise exception
6. 回傳格式必須符合 docstring 與 agent.py tool calling 需求
請根據 AI_SESSION_CONTEXT.md 與 seed.cypher，實作 databases/graph/queries.py 中的指定 function。
```

### Graph query implementation prompt that worked:
```
要求：
1. function signature 必須完全符合 AI_SESSION_CONTEXT.md
2. 使用 _driver() helper 與 Neo4j session
3. Graph node labels 使用 MetroStation、NationalRailStation
4. Relationship types 使用 METRO_LINK、RAIL_LINK、INTERCHANGE_TO
5. 支援 shortest route、cheapest route、alternative routes、interchange path、delay ripple、station connections
6. 找不到路徑時回傳清楚的 dict 或空 list
```

### RAG policy chunk prompt that worked:
```
請根據 booking_rules.json、refund_policy.json、travel_policies.json、ticket_types.json，產生可匯入 pgvector 的 policy_chunks.json。

要求：
1. chunk_id 必須唯一且可追溯來源，例如 RF001_W1、BR_NATIONAL_RAIL_ADVANCE_BOOKING
2. 每個 chunk 要包含 title、category、document_type、policy_id、content、metadata、source_file
3. content 必須用自然語言整理，方便 semantic search 回答使用者問題
4. metadata 必須保留 network_type、ticket_type、service_type、fare_class、refund_percent、time_window 等可過濾欄位
5. 不要修改 PostgreSQL 的 policy_documents schema
6. 輸出格式必須能被 seed_vectors.py 讀取並寫入 pgvector
```
