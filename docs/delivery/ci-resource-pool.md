# 共享资源池与资源并发准入

本文摘述[本地交付控制器](../local-delivery.md)，具体约束以原文为准。

## 共享池与隔离

- CI 使用现有独立 LXD 模板、nested Docker 和 **6 CPU / 12 GiB 共享池**。
- 不挂载生产目录、宿主 Docker socket、私有素材或 GitHub 凭据；保留完整基线检查。
- 共享池与模板参数属于仓库外可信 JSON 配置，不将生产配置或私有制品提交进仓库。

## 资源准入与并发边界

- 实际 CPU 与内存到达 **90%** 时不准入。
- 多个提交进入持久队列，先校验包含最新 main，再运行 CI；落地前再次核对 base 和 head。不满足则交回原任务处理，不将旧验证用于新提交。
- CI、landing、release、mirror 分别有进程锁；失败、控制器中断或回执缺失均不放行。
- `queue.sqlite` 按 branch+SHA 保存单独交付，`runs/<id>/ci.json` 保存精确 SHA 回执，日志位于同一目录。

原文：[权威与隔离](../local-delivery.md#权威与隔离)、[切换步骤与恢复](../local-delivery.md#切换步骤与恢复)。
