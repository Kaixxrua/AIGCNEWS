# Worktree 自动回收

`scripts/worktree_gc.py` 只回收能够证明已经完成且不再被使用的 worktree，默认仅输出计划，传入 `--apply` 才执行 `git worktree remove`。禁止用 `rm -rf` 绕过 Git 注册信息和安全检查。

## 公开 session

公开仓库只处理 `AIGCNEWS/.claude/worktrees/` 下的 `session/*`：

1. 更新 `origin/main` 后，任务 HEAD 必须是 main 的祖先，或者 `git cherry` 证明单提交补丁已由 squash 等价合并；
2. tracked、staged 和 untracked 文件必须全部干净；忽略的依赖与构建缓存可随 worktree 一起回收；
3. 不能包含另一个注册 worktree，不能处于 Git lock 状态；
4. 同 UID 进程的 cwd、root、可执行文件和打开的文件描述符均不能指向候选目录；
5. 最近活动时间必须超过 24 小时。

未满足任一条件时跳过，不 reset、stash、强制删除或删除分支。

## 私有 Godot worktree

`.private-worktrees` 可能包含被 Git 忽略的大型源码与 PCK/WASM 制品，因此即使 `git status` 干净也不能自动删除。私有回收还要求：

- 当前 HEAD 已普通推送到私有 `origin`；
- 外部 `.private-releases/<release-id>` checkout 保存同一 HEAD 和 `aigcnews-private-release.json`；
- worktree 完全干净且无进程占用；
- 先显式生成与路径、branch、HEAD、release descriptor 摘要绑定的授权记录；
- 授权记录超过 24 小时宽限期。

授权命令：

```bash
python3 scripts/worktree_gc.py authorize-private \
  --repo ~/aigcnews_private \
  --worktree ~/.private-worktrees/<name> \
  --preserved-release-root ~/.private-releases/<release-id> \
  --authorization-dir ~/.config/aigcnews/private-worktree-cleanup
```

脏文件、运行中的 Godot/浏览器验证进程或不匹配的快照都会拒绝授权。

## 定时器

安装并立即进行一次保守扫描：

```bash
scripts/install_worktree_gc.sh
```

用户级 systemd timer 每小时运行并增加最多 10 分钟随机延迟。检查状态：

```bash
systemctl --user status aigcnews-worktree-gc.timer
journalctl --user -u aigcnews-worktree-gc.service
```
