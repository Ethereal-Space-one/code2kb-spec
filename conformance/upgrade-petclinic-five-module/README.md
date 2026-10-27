# PetClinic 五模块升级范围案例

基线为 [Spring PetClinic REST](https://github.com/spring-petclinic/spring-petclinic-rest) 的固定公开提交 `afc8fc1d3b8ec8de69414482b3bd70a1da78cb95`。五个完整控制器文件存放在相邻的 `public-source/petclinic/backend/` 目录，并保留上游版权声明。本案例在临时 Git 仓库中生成受控的第二提交，仅修改 Owner 的空白姓氏分支；第二提交不是上游版本。

`expected.json` 是先按五份固定源码独立标注的答案差异，不从升级计划输出反填。四个未变文件的 Git blob 和证据摘录必须保持相同；但因为全局仓库提交改变，五个模块的 `source_revisions`、证据快照和审核记录都要重新核对。

测试只验证只读计划对五个模块的语义复核范围、基线迁移范围及批准刷新范围。**它不执行自动迁移、任务账本或发布，也不测量人工工时**。因此即使候选范围为 1/5，也不能据此宣称 1.0 的自动增量执行有净收益；阶段 D 仍受实施规划中的投入闸门约束。
