# 物品映射

物料库、物料盒地图、BOM 导入与匹配。账号登录后数据按用户隔离。

后端启动时会检查数据库。数据库不存在就先创建，并写入管理员账号 `admin`，密码 `admin`。库已经存在但还没有这个账号时也会补上，已有账号的密码不会被重置。管理员登录后可以在「账户管理」里增删改查账号；删除账号会同时删除该账号的物料、物料盒和项目。

## 本地开发

后端：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

前端（另开一个终端）：

```powershell
cd frontend
npm install
npm run serve
```

浏览器打开 `http://localhost:8080`。开发服务器把 `/api` 转发到 `8000`。

## Docker

在项目根目录准备 `.env`（可从 `.env.example` 复制），然后：

```powershell
docker compose up -d
```

浏览器打开 `http://localhost:8000`。SQLite 数据库在数据卷 `/data/app.db`。

改用 MySQL 时设置：

```text
DATABASE_URL=mysql+pymysql://user:password@host:3306/cms?charset=utf8mb4
```

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `DATABASE_URL` | 默认 SQLite，可改为 MySQL |
| `SECRET_KEY` | 登录 Cookie 签名 |
| `DEEPSEEK_API_KEY` | 留空时只做精确匹配和规则预筛 |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | 默认 `deepseek-chat` |
| `COOKIE_SECURE` | HTTPS 部署时设为 `1` |

立创商品查询和 DeepSeek 只在服务端调用，密钥不会进入前端包。

## 样例

`temp` 目录中的两份文件可直接上传：

- `BOM_V1.31_V1.31_2026-10-23.xlsx`：立创 EDA 分组 BOM，有效物料 45 条（序号 1 到 45，文件末尾有一行空行）
- `树莓派_PIOC2_RP2354B系统板_PCB1_20261020_083237-立创_20261020.xls`：立创商城报价单，采购套数 2，含 `C105580` 和位号 `R13,R14`
