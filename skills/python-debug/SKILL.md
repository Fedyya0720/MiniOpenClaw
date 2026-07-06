---
name: python-debug
description: 当用户报告 Python 脚本报错或行为异常，需要系统性排查并修复时使用。
---

# Python 调试 Skill

## 何时使用
用户运行 Python 脚本遇到报错（traceback）、输出不符合预期、或脚本挂起/超时。

## 步骤
1. **复现错误**：用 `bash` 运行脚本，捕获完整的 traceback。一次只复现一个问题。
2. **定位根因**：从 traceback 最底部向上读，找到第一个用户代码行（非标准库）。用 `read` 查看相关文件和行号。
3. **假设验证**：在脑海中形成"为什么会出错"的假设，用 `bash` 跑一小段 Python 验证（如打印变量类型/值）。
4. **最小修复**：用 `edit` 做最小改动。一次只改一处，改完立刻运行验证。
5. **确认修复**：运行原脚本确认错误消失，且没有引入新错误。

## 注意
- 不要猜测变量值——用 `bash` 跑 `python -c "..."` 确认。
- 修改库代码要格外小心——优先改用户代码。
- 如果错误涉及外部依赖（pip 包），先检查 `pip list` 确认版本。

## 常见模式
- `NameError` → 变量/函数名拼写错误，或未导入
- `TypeError: 'NoneType' object is not subscriptable` → 函数返回了 None，检查 return 语句
- `FileNotFoundError` → 路径错误或文件不存在，确认工作目录
- `IndentationError` → 混用 tab 和空格，统一用 4 空格缩进
