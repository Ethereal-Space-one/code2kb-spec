# Spring PetClinic 固定源码片段

本目录保留两个独立公开仓库在固定提交中的四个**完整原始文件**，供离线复核 Code2KB 从真实混合语言源码到知识产物的链路。源文件版权声明保持原样；原项目采用 Apache License 2.0，本仓库根目录亦附该许可证。这里只复制测试所需文件，不包含依赖、构建产物或运行服务。

| 来源 | 固定提交 | 本目录文件 | 原文件 SHA-256 |
| --- | --- | --- | --- |
| [spring-petclinic-angular](https://github.com/spring-petclinic/spring-petclinic-angular) | `aae775a0cc1fb2e00901eea350f6ecfc69ef6a88` | `frontend/src/app/owners/owner.service.ts` | `acf97110c1bbd2bdfae43915bef702464bb5a56e4b0e9e5d5a2a3a75cb93fe49` |
| 同上 | 同上 | `frontend/src/environments/environment.ts` | `f607900559602acd8d56f1458cb61372b2b7d6dc22945d58f2bc267cc56a0573` |
| [spring-petclinic-rest](https://github.com/spring-petclinic/spring-petclinic-rest) | `afc8fc1d3b8ec8de69414482b3bd70a1da78cb95` | `backend/src/main/resources/openapi.yml` | `a1a8ee2f853ebd8af89cd5a958158ac16550b5627da1cf59dca9736e95a597f4` |
| 同上 | 同上 | `backend/src/main/java/org/springframework/samples/petclinic/rest/controller/v1/OwnerRestControllerV1.java` | `19291723b9b2f6545595f098116cbf3fd5ee5676aa55ae20f8079b51b5b2d883` |

测试在临时目录分别建立两个 Git 仓库，以这些原文件形成可重现的固定快照。Adapter 只提出保守候选；测试中的跨仓库关系由明确标注的人工源码锚点核对，不能解读成自动解析能力，也不能证明实际部署、权限或线上回答质量。
