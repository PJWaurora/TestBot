# Hybrid Recall Phase 2 实施规格

> Version: 0.2
> Language: zh-CN  
> Owner: Brain / Memory Engine  
> Scope: Phase 2 hybrid recall，让 AI 不只靠关键词召回 memory。  
> Depends on: [Memory Quality Phase 1](memory-quality-phase1.zh-CN.md)、[Memory Lifecycle API](../api/memory-api.md)。  
> Status: 首版实现已落地；后续重点是上线观察、调权重、补真实数据库集成测试。

---

## 1. Phase 1 变更复盘

Phase 1 已完成的基础能力：

- `memory_items` 增加 `memory_class`、`lifecycle_status`、`stability`、`decay_score`、`contradiction_count`、`source_count`、`quality_score`。
- AI 默认只召回：

```text
status = 'active'
lifecycle_status IN ('confirmed', 'reinforced')
```

- `/memory debug recall <text>` 已能输出当前关键词召回的 score breakdown。
- `/memory extract [count]` 已能从近期群聊消息抽取 memory，并写入 lifecycle/quality 字段。
- extractor 已支持 `memory_class`，并能通过 `conflicts_with_memory_id` 把旧 memory 标记为 `contradicted`。
- `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED=false` 可作为上线回滚开关。
- `memory_embeddings` 表已经存在，字段为 `embedding vector(1536)`，但当前没有写入任务、向量索引、向量召回或 embedding 配置。

Phase 1 当前不足：

- `recall()` 仍主要依赖 `content ILIKE` 与 `_keywords(text)`，语义相近但无共同词的记忆召回不到。
- `debug recall` 只解释结构化/关键词分数，不能说明向量相似度。
- `memory_embeddings` 没有唯一约束，无法表达“某个 memory + 某个 model 只有一个当前 embedding”。
- AI prompt 只拿最终 `memory_to_dict()`，没有暴露 recall 来源、分数或压缩原因。

Phase 2 应只解决 recall 质量，不扩大到 conversation state、prompt compiler、tool calling 或 proactive。

---

## 2. 目标

Phase 2 的目标：

> 在保持 Phase 1 lifecycle 安全边界的前提下，把 memory recall 从“关键词检索”升级为“关键词 + FTS + embedding + scope/entity rerank”的混合召回。

必须完成：

- 增加 embedding 配置、写入、刷新和错误处理。
- 给 `memory_embeddings` 增加可用的 model 唯一约束和 vector index。
- `recall_context()` 同时使用 keyword/FTS 候选和 vector 候选。
- 统一 `MemoryScore`，把 `vector_similarity`、`keyword_match`、`entity_relevance`、`scope_relevance`、`quality_score`、`recency_weight` 合并排序。
- `debug recall` 输出候选来源和分数明细。
- 保证 `weak / stale / contradicted / archived / deleted` 默认仍不进入 AI prompt。

成功标准：

- 用户问“我平时不喜欢什么回复风格？”时，可以召回“用户不喜欢长篇回复”这类无直接关键词重合的 memory。
- 当前用户和当前群相关的 memory 排名高于泛化 group/global memory。
- embedding 服务不可用时，关键词/FTS recall 仍可工作，AI 不报错。
- 所有新能力都能通过 env 关闭。

---

## 3. 非目标

Phase 2 不做：

- 不做完整 entity graph。
- 不做 conversation state。
- 不做 prompt compiler。
- 不做 WebUI。
- 不做 proactive AI。
- 不让 LLM 决定哪些 lifecycle 状态可召回。
- 不自动把所有历史消息重新抽取为 memory。

---

## 4. 配置

新增 Brain env：

```text
MEMORY_EMBEDDING_ENABLED=false
MEMORY_EMBEDDING_BASE_URL=
MEMORY_EMBEDDING_API_KEY=
MEMORY_EMBEDDING_MODEL=
MEMORY_EMBEDDING_DIMENSIONS=1536
MEMORY_EMBEDDING_TIMEOUT=20
MEMORY_EMBEDDING_BATCH_SIZE=32
MEMORY_VECTOR_RECALL_ENABLED=false
MEMORY_VECTOR_RECALL_LIMIT=20
MEMORY_KEYWORD_RECALL_LIMIT=50
MEMORY_RECALL_FINAL_LIMIT=8
```

默认策略：

- `MEMORY_EMBEDDING_ENABLED=false`，避免没有 embedding 服务时影响当前部署。
- `MEMORY_VECTOR_RECALL_ENABLED=false`，允许先只写 embedding，不改变 AI recall。
- `MEMORY_RECALL_FINAL_LIMIT` 默认继续等价于当前 `DEFAULT_MEMORY_LIMIT`。
- `MEMORY_EMBEDDING_BASE_URL/API_KEY/MODEL` 可独立配置；不自动复用 chat model，避免误把 chat endpoint 当 embedding endpoint。

OpenAI-compatible embeddings endpoint：

```text
POST <MEMORY_EMBEDDING_BASE_URL>/v1/embeddings
Authorization: Bearer <MEMORY_EMBEDDING_API_KEY>
Content-Type: application/json
```

Payload:

```json
{
  "model": "text-embedding-model",
  "input": ["memory text 1", "memory text 2"]
}
```

Expected response:

```json
{
  "data": [
    {"embedding": [0.01, 0.02]}
  ]
}
```

---

## 5. Schema 设计

新增 migration：

```text
database/migrations/000006_memory_embedding_recall.up.sql
database/migrations/000006_memory_embedding_recall.down.sql
```

建议变更：

```sql
ALTER TABLE memory_embeddings
    ADD COLUMN content_hash TEXT NOT NULL DEFAULT '',
    ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE UNIQUE INDEX memory_embeddings_memory_model_unique_idx
    ON memory_embeddings (memory_id, embedding_model);
```

向量索引建议：

```sql
CREATE INDEX memory_embeddings_embedding_ivfflat_idx
    ON memory_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

注意：

- pgvector `ivfflat` 需要数据量达到一定规模才有明显收益。小数据量环境可以先只保留 exact scan。
- 如果未来 embedding 维度可变，当前 `vector(1536)` 表结构会限制模型选择。Phase 2 不建议直接改成多维度混合；保持 `MEMORY_EMBEDDING_DIMENSIONS=1536` 和表结构一致。
- `content_hash` 用于判断 memory content 是否变化后需要重新 embedding。

Down migration：

- 删除 vector index。
- 删除唯一 index。
- 删除 `content_hash`、`updated_at`。

---

## 6. 服务设计

新增文件建议：

```text
brain-python/services/memory_embedding.py
```

核心结构：

```python
@dataclass
class EmbeddingConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str
    dimensions: int
    timeout: float
    batch_size: int

def config_from_env() -> EmbeddingConfig: ...
def embed_texts(texts: list[str], config: EmbeddingConfig) -> list[list[float]]: ...
```

`PostgresMemoryStore` 新增方法：

```python
def list_memories_missing_embeddings(self, *, model: str, limit: int) -> list[MemoryRecord]
def upsert_memory_embedding(self, memory_id: int, *, model: str, content_hash: str, embedding: list[float]) -> None
def vector_candidates(self, request: ChatRequest, query_embedding: list[float], *, limit: int) -> list[MemoryCandidate]
```

新增数据结构：

```python
@dataclass(frozen=True)
class MemoryCandidate:
    record: MemoryRecord
    sources: tuple[str, ...]  # keyword, fts, vector
    keyword_match: float = 0.0
    fts_rank: float = 0.0
    vector_similarity: float = 0.0
```

不要把 embedding HTTP 调用塞进 `memory.py`。`memory.py` 可以负责 store/query/rerank，HTTP client 应单独放在 `memory_embedding.py`，这样测试边界清楚。

---

## 7. 写入路径

Phase 2 支持两种写入路径。

### 7.1 Extract 后同步写入

在 `/memory extract` 完成后：

```text
extract_group_memories()
  -> upsert_extracted_memory()
  -> collect inserted/updated memory IDs
  -> optionally enqueue or run embedding write
```

建议第一版不要在 extractor 主路径里同步等待 embedding HTTP。原因：

- extractor 已经调用 LLM，再串联 embedding 会增加失败面。
- embedding 失败不应该导致 memory 抽取失败。

建议实现：

```python
safe_index_memories(memory_ids)
```

失败只记录到 logs / run metadata，不回滚 memory item。

### 7.2 Admin 手动补索引

新增命令：

```text
/memory embedding status
/memory embedding index [limit]
```

行为：

- `status` 返回当前 embedding 配置、缺失 embedding 数、最近 run 状态。
- `index [limit]` 扫描缺失或 content_hash 变化的 memory，批量写 embedding。
- 仅管理员可用。

---

## 8. 召回路径

当前：

```text
recall_context()
  -> store.recall(request, text)
  -> debug_recall()
  -> keyword candidates
  -> memory_score()
```

Phase 2：

```text
recall_context()
  -> build RecallRequest
  -> keyword/FTS candidates
  -> vector candidates, if enabled and embedding query succeeds
  -> merge by memory_id
  -> rerank with HybridMemoryScore
  -> compress final list
  -> memory_to_dict()
```

Candidate generation:

| Source | Query | Limit | Failure behavior |
| --- | --- | --- | --- |
| keyword | current `_keywords()` + `ILIKE` | `MEMORY_KEYWORD_RECALL_LIMIT` | Existing behavior. |
| FTS | `to_tsvector('simple', content) @@ plainto_tsquery('simple', text)` | `MEMORY_KEYWORD_RECALL_LIMIT` | If SQL fails, log and continue with keyword. |
| vector | query embedding + pgvector cosine distance | `MEMORY_VECTOR_RECALL_LIMIT` | If config/upstream/db fails, log and continue without vector. |

Vector SQL sketch:

```sql
SELECT memory_items.*, 1 - (memory_embeddings.embedding <=> %s::vector) AS vector_similarity
FROM memory_embeddings
JOIN memory_items ON memory_items.id = memory_embeddings.memory_id
WHERE embedding_model = %s
  AND status = 'active'
  AND COALESCE(lifecycle_status, 'confirmed') IN ('confirmed', 'reinforced')
  AND <scope filter>
ORDER BY memory_embeddings.embedding <=> %s::vector
LIMIT %s;
```

---

## 9. Rerank 公式

Phase 2 `HybridMemoryScore`：

```text
total =
  keyword_match      * 0.18
+ fts_rank           * 0.12
+ vector_similarity  * 0.25
+ entity_relevance   * 0.18
+ scope_relevance    * 0.12
+ quality_score      * 0.10
+ recency_weight     * 0.05
```

Rules:

- `vector_similarity` 必须归一化到 `0..1`。
- 没有 vector 来源时 `vector_similarity = 0`，不要因为未启用 vector 导致 keyword recall 全部低分不可用。
- `quality_score` 是 Phase 1 的可信度，不应被 vector 相似度压倒。
- `scope_relevance` 与 `entity_relevance` 必须继续保障当前用户/当前群优先。
- 默认 final limit 仍为 8，避免 prompt 过长。

建议阈值：

```text
MEMORY_VECTOR_MIN_SIMILARITY=0.68
MEMORY_RECALL_MIN_SCORE=0.20
```

第一版可以只记录阈值，不强制过滤；上线观察后再收紧。

---

## 10. Context 压缩

Phase 2 不做 LLM summary 压缩，先做确定性压缩：

```text
dedupe exact normalized content
dedupe same memory_id
prefer current user > relationship > group > global
prefer reinforced > confirmed
prefer higher total score
cap final memory count
cap content length
```

`memory_to_dict()` 可扩展可选 debug 字段，但默认 AI prompt 不需要暴露全部分数。

建议：

```python
def memory_to_dict(record: MemoryRecord, score: HybridMemoryScore | None = None) -> dict[str, Any]
```

默认保持向后兼容。Debug path 可以传 score。

---

## 11. Debug / Admin 输出

`/memory debug recall <text>` Phase 2 输出：

```text
召回调试：
#42 total=0.83 eligible=yes lifecycle=reinforced sources=keyword,vector
  keyword=0.50 fts=0.31 vector=0.78 entity=0.90 scope=1.00 quality=0.74 recency=0.60
  用户不喜欢长篇回复。
```

新增 metadata：

```json
{
  "module": "memory",
  "command": "debug_recall",
  "count": 8,
  "vector_enabled": true,
  "vector_error": ""
}
```

如果 vector 失败：

```text
召回调试：vector unavailable: missing MEMORY_EMBEDDING_MODEL
```

但仍输出 keyword/FTS 候选。

---

## 12. API / 文档更新

需要更新：

- [Memory Lifecycle API](../api/memory-api.md)
  - 新增 Embedding Recall 配置、命令、debug 输出。
- [AI Runtime API](../api/ai-runtime-api.md)
  - 说明 memory context 可能来自 hybrid recall，但 AI route 不直接调用 embedding。
- [Database Schema](../api/database-schema.md)
  - 记录 `000006_memory_embedding_recall`。
- [Cognitive Agent 分阶段设计](cognitive-agent-phases.zh-CN.md)
  - Phase 2 状态从阶段设计改成详细规格已完成。

---

## 13. 测试计划

新增或扩展：

```text
brain-python/tests/test_memory_embedding.py
brain-python/tests/test_memory_core.py
brain-python/tests/test_ai_runtime.py
```

必须覆盖：

- embedding config 缺失时禁用，不影响当前 recall。
- embeddings endpoint URL normalization。
- embeddings response shape validation。
- `list_memories_missing_embeddings()` 能找出缺失或 content_hash 变化的 memory。
- `upsert_memory_embedding()` 对同一 `(memory_id, model)` 更新而不是重复插入。
- vector candidates SQL 包含 lifecycle filter 和 scope filter。
- keyword + vector candidates merge by `memory_id`。
- hybrid score 排序：当前用户/当前群优先。
- vector failure 时 `recall_context()` 返回 keyword/FTS 结果。
- `debug recall` 包含 `sources`、`vector_similarity`、`fts_rank`。

验证命令：

```bash
brain-python/.venv/bin/python -m pytest \
  brain-python/tests/test_memory_core.py \
  brain-python/tests/test_memory_embedding.py \
  brain-python/tests/test_memory_extractor.py \
  brain-python/tests/test_ai_runtime.py
```

当前 `brain-python/tests/test_main.py::test_health` 在本工作区有 hang 记录，Phase 2 实现前应单独修复或隔离，否则会持续干扰全量测试信号。

---

## 14. 分步实施

### Step 1: Embedding config/client

- 新增 `memory_embedding.py`。
- 实现 env config、URL normalization、HTTP request、response validation。
- 单元测试不需要真实网络。

### Step 2: Schema

- 新增 `000006_memory_embedding_recall` migration。
- 加 `content_hash`、`updated_at`、唯一索引。
- 加 vector index；如果本地 pgvector 小数据量测试不稳定，可先只测试 SQL 文件存在和 store SQL。

### Step 3: Index write path

- Store 增加缺失 embedding 扫描和 upsert。
- `/memory embedding index [limit]` 手动触发。
- `/memory extract` 后可 best-effort index 新增/更新 memory。

### Step 4: Hybrid candidate generation

- 保留现有 keyword path。
- 增加 FTS path。
- 增加 vector path，并保证失败降级。
- 用 `MemoryCandidate` 合并来源。

### Step 5: Rerank / debug

- 替换或扩展 `MemoryScore`。
- `debug recall` 输出完整来源和分数。
- `recall_context()` 默认只返回 final compressed list。

### Step 6: Rollout

- 先部署 `MEMORY_EMBEDDING_ENABLED=true`，`MEMORY_VECTOR_RECALL_ENABLED=false`，只写 embedding。
- 确认 `/memory embedding status` 正常。
- 再开启 `MEMORY_VECTOR_RECALL_ENABLED=true`。
- 观察 debug recall 与 AI 回复质量。

---

## 15. 最小完成清单

- [x] `memory_embedding.py`。
- [x] `000006_memory_embedding_recall` migration。
- [x] embedding env 写入 `.env.example` 和 docs。
- [x] `/memory embedding status`。
- [x] `/memory embedding index [limit]`。
- [x] extract 后 best-effort 写 embedding。
- [x] FTS candidates。
- [x] vector candidates。
- [x] candidate merge by memory ID。
- [x] `HybridMemoryScore`。
- [x] `debug recall` 输出 source/score breakdown。
- [x] vector failure fallback。
- [x] 单元测试覆盖 config/client/store/rerank/debug。

---

## 16. 风险与处理

| 风险 | 影响 | 处理 |
| --- | --- | --- |
| embedding model 维度与 `vector(1536)` 不一致 | 写入失败 | config 显式要求 `MEMORY_EMBEDDING_DIMENSIONS=1536`，写入前校验长度。 |
| embedding 服务慢或不可用 | recall 变慢或失败 | vector recall 失败降级，不影响 keyword/FTS；写入任务 best-effort。 |
| vector 相似度压过 scope | 跨人/跨群记忆误召回 | rerank 中 entity/scope 权重必须保留，scope filter 仍在 SQL 层执行。 |
| prompt memory 过多 | AI 回复变差、成本上升 | final limit、content cap、确定性 dedupe。 |
| debug 输出过长 | 群内刷屏 | debug recall 只输出 top 10，必要时只在私聊允许更详细输出。 |
| `memory_embeddings` 重复行 | 排序不稳定 | Phase 2 migration 加 `(memory_id, embedding_model)` 唯一索引。 |
