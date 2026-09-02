# 工坊 Copilot Island

隔离的 Vite + React 构建边界。产物输出到 `../../static/copilot/`，由工坊页以经典脚本加载。

```powershell
cd frontend/copilot
npm install
npm run build
```

约定：

- 不引入 Next.js、streamdown、shiki、`@xyflow/react`
- Tailwind 不导入 preflight
- Conversation / Suggestion / Task 源码来自 vercel/ai-elements（Apache-2.0）
- 双击 `start.bat` 不需要 Node：请提交构建产物
