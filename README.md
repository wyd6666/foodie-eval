<div align="center">

# 伙食评价一键提交

**把一周 40 分钟的机械点击，压缩成 40 秒。**

粘一份名单，点两下，一天十几个人的评价全交完。

![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-3DA639)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![Dependencies](https://img.shields.io/badge/dependencies-1-brightgreen)
![Platform](https://img.shields.io/badge/Windows%20%7C%20macOS%20%7C%20Linux%20%7C%20NAS-lightgrey)

[快速开始](#快速开始) · [功能](#功能) · [部署方式](#部署方式对比) · [常见问题](#常见问题) · [技术细节](#技术细节)

</div>

---

## 这是什么

单位每周要做伙食满意度测评。手机上要这么干：

> 打开 App → 登录 → 进评价页 → 20 道题一道道点「满意」→ 提交 → 退出 → 换下一个账号……

一个人 2 分钟，50 个人 将近两个小时。而且**这是工作**。

这个项目把整套动作变成脚本。不装 App、不碰手机、不用模拟点击 —— 直接跟服务器说话，走的是 App 里那套一模一样的接口。

```
┌─ 手机手动 ─────────────────┐      ┌─ 这个脚本 ────────────────┐
│                            │      │                           │
│  开 App        15 秒        │      │  粘名单        5 秒        │
│  登录          10 秒        │      │  点「预演」    2 秒        │
│  进评价页      15 秒        │      │  点「提交」    33 秒       │
│  点 20 道题    30 秒        │      │                           │
│  提交          10 秒        │      │  ─────────────────────    │
│  退出          5 秒         │      │  13 个人 · 40 秒           │
│                            │      │                           │
│  × 50 个人 = 100 分钟        │      │  零漏题 · 零漏交           │
└────────────────────────────┘      └───────────────────────────┘
```

---

## 快速开始

### 只想自己电脑上用（60 秒）

```bash
# 1. 装 Python 3.8+（Windows 安装时务必勾选 Add Python to PATH）
# 2. 解压后双击
网页版.bat
```

浏览器弹出来，粘名单，点两下。完事。

### 想部署到服务器 / NAS（3 分钟）

```bash
git clone <你的仓库地址>
cd hqhs-eval

# 改两行：eval_config.json 里的 host、compose 里的 HQHS_PASSWORD
docker compose -f docker-compose.lan.yml up -d --build
```

打开 `http://服务器IP:8080`，局域网里任何设备都能用。

> 拉不到基础镜像？`bash 准备镜像.sh` 会自动换国内源。实在不行看 [部署手册](部署手册.md#五方式-d服务器上不用-docker)，直接跑 Python 只要一个 `requests`。

### 名单格式

一行一个人，三种写法都认：

```text
张三 370101199001011234 密码
李四=370101199001011235=密码
370101199001011236,密码,王五
```

也可以直接把 Excel / txt **拖进网页的虚线框**。

---

## 功能

### 干活的部分

- ✅ **批量提交** —— 一次几十个账号，逐条实时显示结果
- ✅ **先预演后提交** —— 预演只登录和算分，不碰服务器数据
- ✅ **防重复** —— 本地台账记住当天交过谁，再点也不会重交
- ✅ **可调间隔** —— 填 30~50 秒就一个个慢慢来，等待时间带 ±20% 随机抖动，比固定节拍更像人手
- ✅ **随时可停** —— 跑 9 分钟的批次，中途按「停止」正在跑的收手，没开始的立刻放弃
- ✅ **失败不中断** —— 一个账号密码错了，剩下的人照常跑

### 隐私的部分

- 🔒 **默认打码** —— 姓名 `张**`、账号 `6402****12`、机构 `青岛****`，点一下才展开
- 🔒 **名单自动遮住** —— 输入框不编辑时整块蒙上，同事路过看不到身份证
- 🔒 **两种密码** —— 静态密码，或手机 Authenticator 的 6 位动态码（TOTP，30 秒一变）
- 🔒 **错误 5 次锁 10 分钟** —— 防爆破

### 工程的部分

- 📦 **零第三方加密依赖** —— 装了 `cryptography` 就用，没装自动切内置纯 Python AES-256，密文逐字节一致
- 📦 **单文件前端** —— 整个页面是一个 `index.html`，没有 npm、没有构建步骤
- 📦 **只用标准库跑服务** —— `http.server.ThreadingHTTPServer`，没有 Flask/FastAPI
- 📦 **一个 commit 就能回滚** —— 每次打包自动存源码快照到 `versions/`

---

## 部署方式对比

| 方式 | 适合谁 | 别人能访问 | 难度 |
|:---|:---|:---:|:---:|
| **Windows 双击** | 只有自己一台电脑 | ❌ | ⭐ |
| **Mac / Linux 命令行** | 自己电脑，喜欢终端 | ❌ | ⭐ |
| **Docker**（1Panel / 群晖 / 通用） | 有 NAS 或服务器 | ✅ 局域网 | ⭐⭐ |
| **systemd 直接跑** | 有 Linux 服务器，不想装 Docker | ✅ 局域网 | ⭐⭐ |

每种方式的完整步骤（含防火墙、端口、镜像加速、systemd 自启）见 **[部署手册.md](部署手册.md)**。

---

## 常见问题

<details>
<summary><b>会不会被服务器当成爬虫？</b></summary>

<br>

「开始」按钮右边有个「间隔」输入框：

- 填 `0` → 几个账号同时发，13 人 40 秒跑完
- 填 `30~50` → 一个交完再交下一个，节奏接近人手点击

每次等待会在设定值上下浮动 20%（`4.8s / 3.1s / 5.2s…`），固定节拍反而更像脚本。

</details>

<details>
<summary><b>交重了怎么办？</b></summary>

<br>

本地有台账 `out/submitted.json`，当天交过的人在结果里显示「跳过」，不会真的再提交一次。

页面顶部也会提示「今天已经有 X 个人交过了」。

想强制重交，勾「忽略今天已交过」。

</details>

<details>
<summary><b>账号密码填错了会怎样？</b></summary>

<br>

那个人显示「失败：用户名不存在 / 密码错误」，**其他人照常跑完**，不会整批中断。

点「环境自检」能批量验证名单里的密码对不对。

</details>

<details>
<summary><b>为什么我部署后版本号一直不变？</b></summary>

<br>

`docker compose up -d` **不会重建镜像** —— 镜像已存在就直接用旧的。必须：

```bash
docker compose -f docker-compose.lan.yml build --no-cache
docker compose -f docker-compose.lan.yml up -d --force-recreate
```

或者直接跑包里的 `重建.sh`。

</details>

<details>
<summary><b>拉不到 Docker 镜像？</b></summary>

<br>

```bash
bash 准备镜像.sh
```

它会依次试 `docker.m.daocloud.io` / `docker.1ms.run` / `docker.1panel.live`，拉下来打成 `python:3.11-slim` 标签，之后构建就不联网了。

或者干脆不用 Docker：

```bash
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests
.venv/bin/python web/server.py --host 0.0.0.0 --port 8080 --password '你的密码'
```

整个应用只需要 **1 个** 第三方包。

</details>

<details>
<summary><b>能连公网用吗？</b></summary>

<br>

能，但不建议直接暴露端口。页面里传的是明文账号密码，最少要做这几件：

1. 设访问密码（或动态码）
2. 走 HTTPS（反向代理申请 Let's Encrypt，或者 `HQHS_TLS: "self-signed"`）
3. 用 `HQHS_ALLOW_IP` 或防火墙限制来源

更省事的做法是 Cloudflare Tunnel：不开端口、不用公网 IP、自带证书。

</details>

---

## 技术细节

<details>
<summary><b>点开看逆向过程和接口</b></summary>

<br>

反编译 APK（`com.xykj.hqhs` v4.16.2，原生 Java，无壳）找到三个接口：

| 动作 | 接口 | 参数 |
|:---|:---|:---|
| 登录 | `POST /api/loginByAppV2` | `userName` / `passWord`，AES 加密后转大写 hex |
| 取评价模板 | `POST /api/appraiseGrassDetail` | `id` / `grade` |
| 提交 | `POST /api/appraiseGrassSave` | 完整表单 |

**加密**：`AES/ECB/PKCS5Padding`，密钥 32 字节（AES-256），实现见 `AESUtils3.java`。

**认证**：`Authorization: Basic c2FiZXI6c2FiZXJfc2VjcmV0` + `Blade-Auth: bearer <token>`。公共 query 带 `orgName` / `userId` / `orgId`。

**评分**：`optionGrades` 形如 `"2,1,0"`，取最大值即满分。满意度 10 题（20 分）+ 监督 10 题（30 分）。

**踩过的坑**：新增评价时 `grade` 必须传用户的 `orgGrade`（如 `"5"`），传空串会拿到空模板 —— 因为 `ObjectUtils.isNull("")` 返回 `true`，App 会回落到 `userRes.getOrgGrade()`。

**服务端限制**：同日重复提交返回 `异常了，请联系管理员`（App 显示"您当天评价次数已达上限!"）。

完整接口文档和字段说明见 [hqhs-README.md](hqhs-README.md)。

</details>

<details>
<summary><b>点开看项目结构</b></summary>

<br>

```
web/
  server.py           后端（http.server，无框架）
  index.html          单文件前端（HTML + CSS + JS 全在里面）
scripts/
  hqhs_eval.py        核心：登录 / 取模板 / 填分 / 提交
  aes_pure.py         纯 Python AES-256-ECB（免装 cryptography）
  import_accounts.py  名单解析（3 种格式 + 坏行定位）
  hqhs_batch.py       多账号批量（--dry-run / --status / --interval）
  onekey.py           一键编排（一键评价.bat 调它）
  manage_accounts.py  加人、删人、看名单
  selfcheck.py        环境自检
win/                  9 个 Windows 快捷批处理
部署手册.md             四种部署方式
部署到1Panel.md        1Panel 细节（端口、镜像加速、常见坑）
hqhs-README.md        接口原理
```

</details>

<details>
<summary><b>点开看命令行用法</b></summary>

<br>

```bash
bash run.sh hqhs    [--dry-run|--status]     # 单账号提交 / 查状态
bash run.sh batch   [-a accounts.json]       # 批量（--dry-run 预演）
bash run.sh import  名单.txt                 # 导入名单
bash run.sh add     姓名 账号 密码           # 加一个人（自动去重+备份）
bash run.sh addfile 新人.txt                 # 批量追加
bash run.sh list    [--check]                # 看名单，--check 顺便验密码
bash run.sh del     账号                     # 删一个人
bash run.sh web     [--port 8080]            # 启动网页版
bash run.sh check                            # 环境自检
```

</details>

---

## 环境变量

Docker 部署时全部通过 `environment` 配：

| 变量 | 作用 | 默认 |
|:---|:---|:---|
| `HQHS_PASSWORD` | 访问密码 | 无 |
| `HQHS_TOTP_SECRET` | 动态码密钥（优先级高于配置文件） | 无 |
| `HQHS_ALLOW_INSECURE` | 无密码也允许启动 | 关 |
| `HQHS_ALLOW_IP` | IP 白名单 | 全部放行 |
| `HQHS_TLS` | `self-signed` 开自签 HTTPS | 关 |
| `HQHS_TRUST_PROXY` | 在反向代理后面时设为 `1` | 关 |
| `HQHS_HOST_PORT` | 宿主机端口 | 8080 |
| `HQHS_PORT` | 容器内监听端口 | 8080 |

---

## 注意

- 评价内容仍然是「全部满意」这个标准答案，和人工点的一模一样
- 服务端限制每人每天只能交三次，重复会被拒（本地台账是为了避免重复提交）
- 只在你被授权使用的系统上跑

## License

[MIT](LICENSE)

<div align="center">
<sub>如果这个项目帮你省下一个下午，点个 ⭐ 吧</sub>
</div>
