# 资料卡（数据库原理）

| 资料 | 类型 | 可信度 | 对应知识点 | 备注 |
|---|---|---|---|---|
| 王珊、萨师煊《数据库系统概论》第五版 | 教材 | 高 | 全部 | 假设的教材，待确认 |
| 本机实验一、实验二（数据库原理MySQL/） | 实验 | 高 | db.sql.* | 已经写过的 SQL，可以直接拿来复习 |
| CMU 15-445 | 公开课 | 高 | 事务、并发、恢复 | 讲机制最清楚，期末不考实现细节 |

## 前人踩过的坑

- “没有选修 1 号课程的学生”不能写成 `SC.Cno <> '1'` 的连接：选了 1 号又选了别的课的人会被选进来，一门课都没选的人会漏掉。用 NOT EXISTS。
- “选修了全部课程”是除法，SQL 里写成双重 NOT EXISTS：不存在一门课，他没有选。
- WHERE 里不能用聚集函数，分组后的条件写在 HAVING。
- 判断 BCNF 只看决定因素是否含码；判断 3NF 还要看右边是不是主属性。
- 最小依赖集不唯一，判分看等价和三个条件，不看字面。
- 检查点之前已经提交的事务恢复时不用管；检查点之后提交的要 REDO；故障时还没提交的要 UNDO。

## 网上资料（2026-10-24 检索，播放量和日期取自当天的搜索结果页）

### 视频（B 站，均未逐个看过，按主题和播放量挑选）

| 视频 | 时长 | 播放 / 发布 | 对应知识点 | 链接 |
|---|---|---|---|---|
| 【数据库系统概论】三小时复习期末速成不挂科（没睡醒冬） | 3:14:10 | 418.1 万 / 2022-03-28 | 全书串讲 | https://www.bilibili.com/video/BV1Bq4y1Y7GC |
| 数据库系统概论数据库原理期末大题速成技巧（牛奶墙） | 1:42:13 | 50.6 万 / 2022-12-04 | 大题 | https://www.bilibili.com/video/BV1ud4y1s7A4 |
| 必考题型1：求闭包 | 5:06 | 5 万 / 2023-02-14 | db.norm.fd | https://www.bilibili.com/video/BV1Ns4y1a7uW |
| 必考题型2：求候选码 | 14:54 | 3 万 / 2023-02-18 | db.norm.keys | https://www.bilibili.com/video/BV1XG4y1P7SR |
| 必考题型3：求最小函数依赖集 | 12:59 | 7.6 万 / 2023-03-16 | db.norm.cover | https://www.bilibili.com/video/BV1UL411k7Xs |
| 常考题型4：分解为3NF | 14:57 | 3.3 万 / 2024-12-25 | db.norm.decomp | https://www.bilibili.com/video/BV15XCAY7EKe |
| 【数据库速成】范式的概念及范式判断（兔子帮） | 10:49 | 6.9 万 / 2026-01-08 | db.norm.nf | https://www.bilibili.com/video/BV16FimBsEwe |
| 【数据库速成】画E-R图&转关系模式 期末大题 必考15分（兔子帮） | 15:54 | 25.4 万 / 2026-01-05 | db.design.er | https://www.bilibili.com/video/BV1p2iJBJE7N |
| 涉及3者关系的ER图（兔子帮） | 11:17 | 5.8 万 / 2026-01-08 | db.design.er | https://www.bilibili.com/video/BV1WmidBsEka |
| 深刻理解SQL语言中的exists和not exists（四姨夫） | 11:01 | 3.3 万 / 2024-03-15 | db.sql.nested、db.sql.division | https://www.bilibili.com/video/BV1vu4m1M7Vm |
| 10分钟选择题速成-9.1数据不一致问题（兔子帮） | 7:07 | 2.6 万 / 2026-01-04 | db.cc.anomaly | https://www.bilibili.com/video/BV1m9iEBREN1 |

### 往年真卷（GitHub，免费，可信度中：学生上传，答案不保证全对）

| 来源 | 内容 | 注意 | 链接 |
|---|---|---|---|
| 中山大学 SYSU-Exam | 约 20 份数据库系统原理期中/期末卷，多数带答案（2007—2016，另有 2021） | 抽查的 2013、2016 卷是英文、按 Database System Concepts 出题，不是王珊教材；SQL、闭包、范式、事务题型可通用 | https://github.com/sysuexam/SYSU-Exam/tree/master/%E6%95%B0%E6%8D%AE%E5%BA%93%E7%B3%BB%E7%BB%9F%E5%8E%9F%E7%90%86 |
| 浙江大学 zju-icicles | 2018、2019 期末 A 卷 + 参考答案与评分细则，另有 2016、2017 复习包 | 英文，按 Database System Concepts | https://github.com/QSCTech/zju-icicles/tree/master/%E6%95%B0%E6%8D%AE%E5%BA%93%E7%B3%BB%E7%BB%9F%E5%8E%9F%E7%90%86/%E8%AF%95%E5%8D%B7 |

### 练习与深入

| 资料 | 用途 | 链接 |
|---|---|---|
| 力扣 SQL 50（免费学习计划） | SQL 编写题刷量，在线判题 | https://leetcode.cn/studyplan/sql-free-50/ |
| SQLZoo | 英文 SQL 练习，从 SELECT 到 JOIN 分级 | https://sqlzoo.net/ |
| CMU 15-445 Fall 2026 | 事务、并发控制、恢复讲得最透；期末不考实现细节 | https://15445.courses.cs.cmu.edu/ |
| Database System Concepts 官方站 | 官方课件 | https://www.db-book.com/ |

没找到：按王珊教材出的、带答案的公开期末卷（搜到的多在百度文库、道客巴巴等付费平台）。中国大学MOOC 上人大的课程搜索页需要页面渲染，这次没打开验证。
