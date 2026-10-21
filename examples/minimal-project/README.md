# 最小知识项目示例

知识项目必须指向本机真实存在的 Git 仓库绝对路径和固定提交，因此静态示例不能携带一个对所有机器都有效的提交号。

运行下面的命令，会在临时目录创建一个小型源码 Git 仓库和知识项目，并执行 `check`：

```bash
python3 -B examples/create_demo.py
```

开始新项目时：

1. 复制 [`../../templates/知识库配置.example.json`](../../templates/知识库配置.example.json) 到独立项目根目录并命名为 `知识库配置.json`；
2. 将 `repositories` 中的路径和提交替换为本机真实值；
3. 复制 [`../../templates/功能大纲.md`](../../templates/功能大纲.md) 到项目的 `知识源/功能大纲.md`；
4. 按 [`../../skills/extract-app-knowledge/SKILL.md`](../../skills/extract-app-knowledge/SKILL.md) 完成全范围盘点；
5. 从 Code2KB Spec 根目录运行 `check`。

仓库测试和演示脚本都会动态创建源码提交，避免静态示例使用失效的提交号。
