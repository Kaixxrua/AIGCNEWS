# 内容移除（Takedown）操作手册

免责声明页对权利人承诺的通道与 SLA（`kaixxrua@gmail.com`，24 小时内核实移除并回复）。
本手册是该承诺的执行侧：**收到请求 → 定位 → 删除存储 → 清缓存 → 回复并留痕**。

SLA 口径：收到包含 ① 内容链接或标题 ② 权利证明 ③ 联系方式 的有效通知后 24 小时内完成移除。
处理记录（请求时间、删除语句/操作、回复时间）留档，作为"及时停止、无主观恶意"的减责证据。

## 1. 公众号文章（wechat_articles）

定位（按标题/原文链接/公众号名模糊匹配）：

```sql
SELECT a.id, a.account_id, a.title, a.article_url, oa.nickname
FROM wechat_articles a
JOIN wechat_official_accounts oa ON oa.id = a.account_id
WHERE a.title ILIKE '%关键词%'
   OR a.article_url ILIKE '%关键词%'
   OR oa.nickname ILIKE '%关键词%';
```

删除单篇：

```sql
DELETE FROM wechat_articles WHERE id = <id>;
```

删除整个公众号（`wechat_articles.account_id` 外键 ON DELETE CASCADE，文章随行删除；
关注关系 `wechat_account_follows` 同样级联）：

```sql
DELETE FROM wechat_official_accounts WHERE id = <account_id>;
```

## 2. X 推文（documents 表，source = 'x'）

```sql
SELECT id, title, url, published_date FROM documents
WHERE source = 'x' AND (title ILIKE '%关键词%' OR url ILIKE '%status/1234567890%');

DELETE FROM documents WHERE source = 'x' AND id = '<id>';
```

## 3. 服务端媒体缓存

- 微信侧：`storage/wechat`（`settings.wechat_media_cache_dir`，相对后端工作目录）。
  文章配图（mmbiz.qpic.cn）自 2026-08 起已改为流式直转不落地，目录里只剩头像
  （mmbiz.qlogo.cn）与**历史遗留的文章图**。一次性历史清理：

  ```bash
  rm -rf <backend>/storage/wechat/*
  ```

  代价：头像下次访问重新回源重建，无数据损失。按文件无法反查所属文章
  （URL 哈希命名），涉及移除时直接整目录清空即可。
- X 侧：`storage/x_media`（视频封面等），同样整目录清空。
- 邮件订阅/推送渠道不缓存正文，无需额外处理。

## 4. 边缘节点缓存

前端 VPS 的 nginx sidecar 按 `/api/media/*` 缓存。删除源站内容后需同步失效：
清空 sidecar 的 proxy_cache 目录（或 `proxy_cache_path` 对应 zone）并 reload nginx。
另外文章图响应头为 `Cache-Control: private`，nginx 默认不会缓存带 private 的响应；
若 sidecar 配置了 `proxy_ignore_headers`，必须改为尊重源站 Cache-Control，否则
private 语义失效。

## 5. 回复请求方（模板）

> 您好，您反馈的内容（<标题/链接>）已于 <时间> 从本站移除，范围包括数据库存储、
> 服务端缓存与边缘缓存。本站为个人聚合工具，展示层仅提供摘要与原文链接，
> 感谢理解与配合。

## 6. 留痕

在 issue 或运维日志记录：请求到达时间、内容定位结果、删除/清缓存执行时间、
回复时间。24 小时 SLA 的执行证据在争议场景下是重要减责情节。
