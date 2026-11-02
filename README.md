# 物品映射

物料库、物料盒地图、BOM 导入与匹配。账号登录后数据按用户隔离。

后端启动时会检查数据库。数据库不存在就先创建，并写入管理员账号 `admin`，密码 `admin`。库已经存在但还没有这个账号时也会补上，已有账号的密码不会被重置。管理员登录后可以在「账户管理」里增删改查账号；删除账号会同时删除该账号的物料、物料盒和项目。

## 本地启动

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
npm run serve
npm install
```

浏览器打开 `http://localhost:8080`。开发服务器把 `/api` 转发到 `8000`。

## Docker

在项目根目录准备 `.env`（可从 `.env.example` 复制），然后：

```powershell
docker compose up -d --build
```

浏览器打开 `http://localhost:8000`。SQLite 数据库和物料图片都在数据卷 `/data` 里。

## 服务器部署包

在开发机项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\pack.ps1
```

得到 `release\cms-deploy.zip`。上传到 Linux 服务器后：

```bash
unzip cms-deploy.zip -d cms
cd cms
chmod +x deploy/up.sh
./deploy/up.sh
```

脚本会在没有 `.env` 时自动生成，并写入随机 `SECRET_KEY`。浏览器打开 `http://服务器IP:8000`。首次启动的管理员账号是 `admin` / `admin`，登录后请立刻修改。

服务器需要已安装 Docker Engine 和 Compose 插件，并且第一次构建时能访问 Docker Hub、npm 和 PyPI。数据库在名为 `cms-data` 的卷里，重新构建镜像不会清掉已有数据。

## 1Panel

页面和接口打在同一个目录里，由一个 Python 进程一起提供。在开发机执行：

```powershell
powershell -ExecutionPolicy Bypass -File deploy\pack-1panel.ps1
```

得到 `release\cms-1panel.zip`。上传到 1Panel 所在服务器并解压，然后在「网站 → 运行环境」里创建 Python 3.11 或 3.12 环境：

- 运行目录：解压后的目录
- 应用端口：`8000`
- 启动命令：`pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple && python run.py`

启动后，用这个运行环境创建网站。没有域名时打开端口外部访问，浏览器打开 `http://服务器IP:8000`。详细步骤在压缩包里的 `DEPLOY.txt`。


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

## 备注
项目在第一次启动之前会自己新建一个SQLite数据库，并填入一个管理员账号
账号：admin
密码：admin