# Spring PetClinic 固定源码片段

本目录保留两个独立公开仓库在固定提交中的八个**完整原始文件**，供离线复核 Code2KB 从真实混合语言源码到知识产物的链路和多模块升级范围。源文件版权声明保持原样；原项目采用 Apache License 2.0，本仓库根目录亦附该许可证。这里只复制测试所需文件，不包含依赖、构建产物或运行服务。

| 来源 | 固定提交 | 本目录文件 | 原文件 SHA-256 |
| --- | --- | --- | --- |
| [spring-petclinic-angular](https://github.com/spring-petclinic/spring-petclinic-angular) | `aae775a0cc1fb2e00901eea350f6ecfc69ef6a88` | `frontend/src/app/owners/owner.service.ts` | `acf97110c1bbd2bdfae43915bef702464bb5a56e4b0e9e5d5a2a3a75cb93fe49` |
| 同上 | 同上 | `frontend/src/environments/environment.ts` | `f607900559602acd8d56f1458cb61372b2b7d6dc22945d58f2bc267cc56a0573` |
| [spring-petclinic-rest](https://github.com/spring-petclinic/spring-petclinic-rest) | `afc8fc1d3b8ec8de69414482b3bd70a1da78cb95` | `backend/src/main/resources/openapi.yml` | `a1a8ee2f853ebd8af89cd5a958158ac16550b5627da1cf59dca9736e95a597f4` |
| 同上 | 同上 | `backend/src/main/java/org/springframework/samples/petclinic/rest/controller/v1/OwnerRestControllerV1.java` | `19291723b9b2f6545595f098116cbf3fd5ee5676aa55ae20f8079b51b5b2d883` |
| 同上 | 同上 | `backend/src/main/java/org/springframework/samples/petclinic/rest/controller/v1/PetRestControllerV1.java` | `e541bd39d7063bdc51254cb436b2d66bedfa560528d1e31fed9644984fb6e299` |
| 同上 | 同上 | `backend/src/main/java/org/springframework/samples/petclinic/rest/controller/v1/VisitRestControllerV1.java` | `d4081e597429d71ee503c9ecc83fac8f086b238ec8c0e4110e239e7aeb26018a` |
| 同上 | 同上 | `backend/src/main/java/org/springframework/samples/petclinic/rest/controller/v1/VetRestControllerV1.java` | `a8d452ddad26b93dc830997c8ef84a478ad2c5b45c07b510bdc1de8939e29eed` |
| 同上 | 同上 | `backend/src/main/java/org/springframework/samples/petclinic/rest/controller/v1/SpecialtyRestControllerV1.java` | `afe529480a43b9075bcb32645a032abc07835b8d10da952a329a54a073a7974d` |

测试在临时目录分别建立两个 Git 仓库，以这些原文件形成可重现的固定快照。Adapter 只提出保守候选；测试中的跨仓库关系由明确标注的人工源码锚点核对，不能解读成自动解析能力，也不能证明实际部署、权限或线上回答质量。

0.8 升级演练在临时后端仓库中生成一个受控第二提交：把姓氏筛选条件从仅检查 `null` 改成同时排除空白字符串。该提交不是上游发布，也没有运行 PetClinic 服务。两个临时源码快照固定提交时间，完整提交号记录在 [检索运行记录](fts5-run.json) 中；原始八个文件保持不变。

1.0 多模块范围案例使用同一后端固定提交中的五个控制器，只对 Owner 做上述受控变更。事实标注与量测边界见 [五模块案例](../../upgrade-petclinic-five-module/README.md)。它不代表真实项目的人工工时。

回归通过实际发布、关系审计和 `preview-upgrade --all-modules` 命令验证影响定位；修订后重新取证、批准、发布和审计。词法基线与 SQLite FTS5 使用相同业务单元、三个相同问题及 `top_k=1`，分别记录排名，包含一个无关词零命中的控制项。正文限定保全、受众隔离与出处定位通过断言检查；不据此宣称模型最终回答已验证。

重新生成运行记录：

```sh
CODE2KB_RECORD_PUBLIC_FTS=conformance/public-source/petclinic/fts5-run.json \
  python3 -B -m unittest discover -s validation/tests -p test_petclinic_public_source.py -q
```
