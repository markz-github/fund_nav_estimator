# 任务框架设计复盘

## 背景

信息流模块需要完成三类工作：

- 扫描视频来源，保存视频基础信息。
- 向 Bilinote 提交视频总结任务，并保存返回的 `task_id`。
- 定时轮询 Bilinote 任务状态，拿到最终笔记结果后入库。

最初实现把这些动作放在同一条“生成视频总结”流程里处理：一次任务既会检查运行中的 Bilinote 任务，也会继续提交新的 Bilinote 任务，还会根据 Bilinote 是否已完成来写任务日志状态。这个设计在功能上能跑通，但状态语义逐渐变得复杂。

## 初始设计

最开始的设计倾向于把视频处理流程放在 `information_videos.status` 中：

```text
note_pending
note_running
note_done
note_failed
summarized
```

`information_video_notes.status` 记录 Bilinote 笔记状态：

```text
pending
running
done
failed
```

`task_logs.status` 记录任务日志状态：

```text
running
success
partial
failed
skipped
```

当 Bilinote 返回 `running` 时，最初的任务日志也会写成 `running`。这样做的意图是表达“还有外部任务没完成”，但实际产生了歧义：后端本地任务已经结束了，任务日志却仍显示 `running`。

## 暴露的问题

### 任务日志语义混乱

`task_logs.status = running` 同时表达了两件事：

- 本地后端任务正在运行。
- 外部 Bilinote 任务还没完成。

这导致运行状态页里出现已经结束但仍显示 `running` 的历史日志。用户需要额外判断 `finished_at`、`duration_ms` 才能知道任务是否真的还在执行，状态模型变得不直观。

### 任务和业务结果耦合

提交 Bilinote 任务和获取 Bilinote 结果本质上是两类任务：

- 提交任务：调用 `/api/generate_note`，拿到 `task_id`。
- 轮询任务：调用 `/api/task_status/{task_id}`，获取最终正文。

初始设计把两者放进一个 `generate_information_video_notes` 任务里，使“任务执行结果”和“业务对象状态”混在一起。

### 视频表承担过多流程状态

`information_videos` 本应保存视频基础信息和来源，但一开始也承担了笔记生成流程状态。这样会让视频表变成流程控制表，后续如果一个视频生成多条笔记，状态会更难表达。

### 笔记唯一约束不合适

早期 `information_video_notes` 使用 `video_id + provider` 唯一约束，意味着一个视频同一 provider 只能有一条笔记。后续确认一个视频可能用不同模型、参数或重试方式生成多条笔记，因此这个唯一约束不适合长期模型。

## 调整后的原则

### 1. 视频只保存视频事实

`information_videos` 主要用于保存视频基础信息：

- 来源账号。
- 平台。
- 外部视频 ID。
- 标题。
- 链接。
- 作者。
- 发布时间。
- 原始响应。

视频表不应成为任务执行关系表。

### 2. 笔记只保存笔记事实

`information_video_notes` 保存笔记生成结果和外部任务信息：

- `video_id`
- `provider`
- `external_task_id`
- `status`
- `note_text`
- `error_message`
- `raw_response`
- `generated_at`

一个视频允许有多条笔记，因此去掉 `video_id + provider` 唯一约束，改为普通索引。

### 3. 所有执行都进入任务日志

`task_logs` 记录“某一次任务执行”的事实，而不是业务对象的长期状态。

任务日志状态只表达本地任务执行状态：

```text
running   本地后端任务正在执行
success   本次任务成功完成
partial   本次任务部分成功
failed    本次任务失败
skipped   本次任务没有可处理对象
```

外部异步任务是否还在等待，不再用 `task_logs.status = running` 表达。

### 4. 提交和轮询拆成两个任务类型

Bilinote 流程拆为两个独立任务：

```text
submit_information_video_note_task
poll_information_video_notes
```

提交任务只负责：

- 找到待提交的视频。
- 创建 `information_video_notes` 记录。
- 调用 Bilinote `/api/generate_note`。
- 保存 Bilinote 返回的 `task_id`。
- 在 `task_logs.external_task_id` 中记录该 `task_id`。

轮询任务只负责：

- 扫描 `information_video_notes.status = running` 的记录。
- 使用 `external_task_id` 调用 `/api/task_status/{task_id}`。
- 成功时写入 `note_text` 并置为 `done`。
- 失败或超时时置为 `failed`。

## 调整后的表职责

### information_videos

保存视频基础信息和来源信息。

不负责表达 Bilinote 外部任务是否执行完。

### information_video_notes

保存笔记记录。

`status` 表示这条笔记自身的生成状态：

```text
pending
running
done
failed
```

### task_logs

保存任务执行历史。

新增字段：

```text
target_type
target_id
external_task_id
```

用于记录任务目标和外部任务 ID。例如提交 Bilinote 时：

```text
task_type = submit_information_video_note_task
target_type = video
target_id = 视频 ID
external_task_id = Bilinote task_id
status = success
```

轮询 Bilinote 时：

```text
task_type = poll_information_video_notes
status = success / failed / skipped
```

## 状态判断规则

最终收敛后的判断规则是：只看对应表自己的 `status`，不跨字段猜测。

### 判断任务是否正在执行

只看：

```text
task_logs.status
```

`running` 只表示本地后端任务正在执行。

### 判断 Bilinote 是否还在等待

只看：

```text
information_video_notes.status = running
```

### 判断某条视频是否已有笔记

查：

```text
information_video_notes.video_id = information_videos.id
```

一个视频可以有多条笔记，页面展示时可选择最新一条。

## 为什么不再兼容旧 running 数据

曾经考虑过在查询任务日志时自动判断：

```text
status = running
且 finished_at 有值或 duration_ms 有值
```

然后自动归一成 `success`。这个方案能清理旧数据表现，但会把“猜测旧数据”的逻辑放进正常程序路径，增加长期复杂度。

最终决定：程序只看 `status`。旧数据如果需要修正，使用一次性 SQL 处理，不在业务代码里兼容。

## 经验总结

- 任务日志只记录执行历史，不表达业务对象长期状态。
- 外部异步任务要拆成“提交”和“轮询”两个任务。
- 外部系统的 `task_id` 既应记录在业务结果表中，也应记录在提交任务日志中，方便排查。
- 状态字段可以都是字符串，但必须明确每张表的状态语义。
- 不要让一个表同时承担事实数据、流程控制和任务执行历史三种职责。
- 旧数据修复应该用一次性迁移或 SQL，不应污染正常判断逻辑。

## 当前结论

本次调整后的任务框架更适合 Bilinote 这类异步外部服务：

```text
视频事实 -> 提交任务 -> 保存 task_id -> 定时轮询 -> 保存笔记结果
```

任务之间不需要建立强关系。必要的排查信息通过 `target_type`、`target_id`、`external_task_id` 保存在 `task_logs` 中；业务结果通过 `information_video_notes` 保存。这样运行状态页看任务，视频页面看业务结果，二者边界清楚。
