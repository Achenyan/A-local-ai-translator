# 本地 AI 翻译助手

把本地大模型翻译做成"拖进来就翻"的桌面工具：**离线、免费、不偷数据**。

英/日 → 简体中文，拖拽文件即翻，模型全在你自己电脑上跑。

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Platform](https://img.shields.io/badge/Platform-Windows-0078d4)

## ✨ 功能特性
- 📥 **拖拽翻译**：把 `.json / .txt / .md / .srt` 文件拖进窗口，自动开始翻译，完成后自动归档到「已翻译」目录
- 🤖 **本地模型**：支持 Ollama 全系模型（qwen3、llama 等），一键下载/切换，模型常驻显存策略可选
- 🔀 **翻译模式**：短线（用完即卸，省显存） / 长线（常驻显存，翻译更快）
- 🎛️ **EZ / 高级双模式**：EZ 图形化（磁贴式模型选择、翻译倾向预设）；高级模式全功能（任务列表、模型管理、日志、自定义 Prompt）
- 🌐 **第三方 API**：OpenAI 兼容接口（DeepSeek / 通义 / Kimi / OpenAI 等），地址/Key/模型名一键配置
- 🌓 **跟随系统主题**：深/浅色 + Windows 强调色自适应
- 🧩 **双语言界面**：中文 / English 一键切换
- 📋 **日志系统**：`app.log` 记录全过程（启动/翻译/错误），出问题发这个文件即可

## 🚀 快速开始

### 方式一：直接运行源码（推荐开发/体验）

```bash
# 1. 安装 Python 3.10+，安装 Ollama（https://ollama.com/download）
# 2. 安装依赖
pip install -r requirements.txt
# 3. 下载一个模型（首次）
ollama pull qwen3:0.6b
# 4. 运行
python gui_translate.py
```

### 方式二：打包成 exe（发布给普通用户）

```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --collect-all tkinterdnd2 gui_translate.py
# 产物在 dist/本地AI翻译助手.exe
```

> 也可以直接运行 `build.bat`（需先装 pyinstaller）。

### 方式三：不装 Ollama

软件检测不到 Ollama 时会提示引导安装（附带的 `OllamaSetup.exe` 一键装）；也可以跳过本地引擎，在「模型管理 → 第三方 API」里配置在线接口直接翻译。

## 🖼️ 界面预览

<img width="1026" height="608" alt="image" src="https://github.com/user-attachments/assets/ae567acb-d0e1-4bbc-b04d-3bd85e9d86e2" />
<img width="1026" height="608" alt="image" src="https://github.com/user-attachments/assets/7cfb249a-aea3-4816-a224-7fbbfb484d4d" />



| EZ 模式 | 高级模式 |
|---|---|
| 磁贴选模型 / 拖拽即翻 | 任务列表 / 模型管理 / 日志 |

## 🎮 显卡要求

| 模型 | 最低显卡 |
|---|---|
| qwen3:0.6b / 1.7b | CPU / 核显即可 |
| qwen3:4b | GTX 2060 6G |
| qwen3:8b | RTX 3060 12G / RTX 4060 8G |
| qwen3:30b | RTX 4060 Ti 16G |

AMD 显卡：RX 6000/7000 系列支持（Ollama 内置 ROCm），老卡自动退回 CPU 模式。

## 📦 模型存储

默认模型目录 `E:\ollama-models`（可在「模型管理 → 更改」切换），也可用 Ollama 默认目录。

## 📖 常见问题

**Q: 提示"无法连接 Ollama"？**
A: 未安装 Ollama 或未启动。安装后重新打开软件即可自动拉起。

**Q: 翻译很慢？**
A: 首次使用某模型需要加载进显存（10~60 秒），之后秒回；或切换「长线翻译」模式常驻显存。

**Q: 支持哪些文件格式？**
A: `.json`（mtool导出）、`.txt`、`.md`、`.srt` 字幕。
下图为mtool导出待翻译文件教程
<img width="782" height="423" alt="image" src="https://github.com/user-attachments/assets/0c26baec-16b0-4a9c-967a-de369ec15902" />

**Q: 会不会上传我的文件？**
A: 不会。本地翻译全程离线；只有配置了第三方 API 时，内容才会发给你自己配置的接口。

## 🤝 贡献者
-开发者：Achenyan987

-代码（不分先后）：Achenyan987；deepseek

-灵感来源：https://mtool.app/
（为了省那点订阅费开发了这个软件）

-底层支持：https://github.com/ollama/ollama
https://github.com/QwenLM/Qwen3

## 📜 License

MIT License，详见 [LICENSE](LICENSE)。

## ☕ 赞助

如果你觉得好用，欢迎赞助支持持续开发：[赞助页](https://sponsor-achenyan.pages.dev)
