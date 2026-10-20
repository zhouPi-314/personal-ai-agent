# 数据库设计

PostgreSQL 18 + SQLAlchemy 2.x + Alembic。当前**只有设计，没有建表**。

## 表

| 表 | 作用 | 关键字段 |
|---|---|---|
| `users` | 单用户起步，预留多用户 | `id`, `display_name`, `created_at` |
| `conversations` | 会话 | `id`, `user_id`, `channel`(web/qq/task), `title` |
| `messages` | 消息 | `id`, `conversation_id`, `role`, `content`, `source`, `trust_level`, `token_count` |
| `memories` | 长期记忆 | `id`, `user_id`, `kind`(trait/fact/topic/pending), `content`, `source_message_id`, `confidence`, `expires_at`, `revoked_at` |
| `project_memories` | 项目级记忆 | `id`, `project_key`, `content`, `source_message_id` |
| `agent_tasks` | 任务 | `id`, `user_id`, `status`, `workspace`, `permission_level`, `started_at`, `finished_at`, `timeout_sec` |
| `tool_calls` | 工具调用 | `id`, `task_id`, `tool`, `args_digest`, `result_digest`, `status`, `denied_reason` |
| `approvals` | 人工审批 | `id`, `task_id`, `requested_action`, `status`, `approved_at`, `expires_at` |
| `audit_logs` | 审计（只追加） | `id`, `actor`, `action`, `target`, `result`, `created_at` |
| `token_usage` | 用量与费用 | `id`, `provider`, `model`, `conversation_id`, `task_id`, `input_tokens`, `output_tokens`, `cost` |
| `devices` | 设备授权 | `id`, `device_key`, `public_key`, `last_seen_at`, `revoked_at` |

## 几个刻意的选择

1. **记忆带来源**（`source_message_id`）：能回答「它为什么记得这件事」，能撤销错误记忆。
2. **`confidence` + `expires_at`**：推断出来的信息不该和用户明说的事实同权。
3. **`args_digest` / `result_digest` 存摘要而非全文**：审计要能定位，不必保存敏感原文。
4. **软删除**：`revoked_at` 为空才算有效，物理删除只走导出/删除流程。
5. **`trust_level` 在消息上**：区分「用户亲口说的」和「从网页抓来的」，供 Policy 判断。

## 迁移与备份

- 迁移：Alembic，一改一迁移，禁止手改生产表结构。
- 备份：`pg_dump` 定时 + 恢复演练；备份文件不入库。
- 向量检索：暂不启用 pgvector，先用全文检索 + 标签，确有效果瓶颈再评估。
