# NAS AI — 智能局域网云盘

基于 FastAPI + LangGraph + ChromaDB 构建的智能 NAS 系统，支持 AI 对话式文件管理、RAG 知识库问答及自动化评估。

## 功能

- **文件管理** — 文件浏览、上传、下载、在线播放（支持 Range 流式传输）、重命名、移动、复制、删除
- **AI Agent 对话** — 基于 LangGraph 的自然语言文件操作，集成文件搜索、信息查询、播放/下载链接生成、文件移动复制、知识库检索等工具
- **RAG 知识库问答** — 文档解析（PDF/DOCX/TXT/Markdown）→ 文本分块 → BGE 向量嵌入 → ChromaDB 语义检索 → LLM 生成
- **自动化评估** — RAG 检索/生成质量评估（命中率、MRR、Precision@K、Recall@K、LLM-as-Judge 忠实度与相关性） + Agent 任务成功率/延迟/Token 评估

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端框架 | FastAPI |
| 数据库 | SQLite |
| ORM | SQLAlchemy |
| 认证 | JWT (access + refresh token) |
| AI Agent | LangGraph + ChatOpenAI (DeepSeek) |
| 向量数据库 | ChromaDB |
| 嵌入模型 | BAAI/bge-small-zh-v1.5 |
| 文档解析 | PyMuPDF / python-docx |
| 文本分块 | LangChain RecursiveCharacterTextSplitter |

## 快速开始

### 环境要求

- Python 3.9+
- 系统已安装 ffmpeg（视频元信息提取）

### 安装

```bash
git clone https://github.com/shhhhhhjokerist/FM.git
cd FM/fastapi
pip install -r requirements.txt
```

### 配置

通过环境变量配置：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `MEDIA_DIR` | NAS 主目录 | `F:\movies` |
| `AGENT_API_KEY` | LLM API 密钥 | — |
| `AGENT_BASE_URL` | LLM API 地址 | `https://api.deepseek.com/v1` |
| `AGENT_MODEL` | 模型名 | `deepseek-v4-flash` |
| `CHROMA_DB_DIR` | ChromaDB 存储路径 | `project_root/chroma_db` |

### 启动

```bash
cd fastapi
python run.py
```

服务启动后访问 `http://localhost:8000/docs` 查看 Swagger API 文档。

### 运行评估

```bash
cd fastapi
python evaluation/run_eval.py --mode rag     # RAG 评估
python evaluation/run_eval.py --mode agent   # Agent 评估
```

## API 概览

| 路由 | 说明 |
|---|---|
| `/auth/*` | 注册、登录、刷新 Token、登出、修改密码 |
| `/media/*` | 文件浏览、搜索、上传、下载、播放、重命名、移动、复制、删除 |
| `/documents/*` | 文档索引扫描、上传、列表、删除 |
| `/rag/query` | RAG 语义检索 |
| `/rag/ask` | RAG 检索 + LLM 生成问答 |
| `/agent/chat` | AI Agent 对话式文件操作 |

## 项目结构

```
fastapi/
├── run.py                  # 服务入口
└── app/
    ├── __init__.py          # 应用初始化
    ├── config.py            # 配置
    ├── db.py                # 数据库
    ├── jwt_helper.py        # JWT 辅助
    ├── models/              # 数据模型
    ├── routes/              # API 路由
    ├── agents/              # LangGraph Agent 定义
    └── services/            # 核心服务（文件扫描、RAG 管道、评估）
```
