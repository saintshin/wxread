# 定时任务维护

主工作流 `deploy.yml` 每天北京时间01:17运行。

`maintenance.yml` 每周一北京时间10:23独立运行，支持手动执行：

1. 读取主工作流的真实状态；仅在 `disabled_inactivity` 时重新启用，保留人工停用状态。
2. 首次执行或距上次记录至少30天时，将最新运行、最近定时运行的时间、结果及链接保存到 `.github/workflow-health.json`，提交到默认分支；每周检查，通常相隔30—36天更新一次。
3. 状态文件只包含公开运行元数据，不保存Cookie、Token、日志或环境变量。

维护任务使用仓库自动提供的临时 `GITHUB_TOKEN`，仅该任务授予 `actions: write` 和 `contents: write`。通过Contents API更新单个状态文件，避免从旧检出覆盖新代码。维护任务与主任务使用不同并发组，手动验证维护不会启动或取消阅读任务。

真实状态记录用于长期排查漏跑，同时让默认分支定期得到实际更新，降低公开仓库因长期不活跃而停用定时任务的风险。GitHub定时调度仍可能延迟，不能保证永不漏跑；如果两个工作流均被手动停用或权限受限，仍需人工处理。

查看：Actions → **Workflow health maintenance**。失败时检查日志中的HTTP状态以及仓库分支保护/组织策略。主脚本报错与调度停用是不同问题，本维护任务不会修改主脚本或登录凭据。

本地验证：`python .github/scripts/test_workflow_health.py`。只读预览：设置 `GITHUB_REPOSITORY=saintshin/wxread` 后运行 `python .github/scripts/workflow_health.py --dry-run`。
