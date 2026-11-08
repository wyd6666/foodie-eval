# 部署到 1Panel（局域网版）

只有一个编排文件：`docker-compose.lan.yml`。局域网里用，不需要域名、证书、反向代理。

---

## 三步

### 1. 上传文件

1Panel → **主机 → 文件** → 新建目录 `/opt/1panel/apps/hqhs/hqhs-eval`，把这几样传上去（保持目录结构）：

```
hqhs-eval/
├── Dockerfile
├── docker-compose.lan.yml
├── eval_config.json          ← 改一下 host
├── web/
│   ├── server.py
│   ├── index.html
│   └── requirements.txt
└── scripts/
    ├── hqhs_eval.py
    ├── aes_pure.py
    └── import_accounts.py
```

改 `eval_config.json`，填评价服务器的地址：

```json
{
  "scheme": "http",
  "host": "sd.你的服务器地址",
  "presets": ["sd.你的服务器地址"],
  "strategy": "max",
  "timeout": 15,
  "log_dir": "out"
}
```

> 就是手机上 App 登录页里填的那个地址，不要带 `http://`，也不要带 `/api/`。

### 2. 创建容器

1Panel → **容器 → 编排 → 创建编排**

- 名称：`hqhs-eval`
- 来源：**粘贴内容** → 把 `docker-compose.lan.yml` 整个粘进去
- 只改一行：

```yaml
      HQHS_PASSWORD: "改成你的密码"
```

点确认。第一次要构建镜像，2~5 分钟。

> 如果卡在拉基础镜像，先跑 `bash 准备镜像.sh`（见下面「镜像拉不下来」）。

### 3. 放行端口

1Panel → **主机 → 防火墙 → 端口规则** → 添加 `8080/TCP` 放行。

---

## 完事

浏览器打开：

```
http://服务器内网IP:8080
```

例：`http://192.168.1.100:8080`

输密码 → 填服务器地址（页面会记住）→ 粘名单 → 先预演 → 直接提交。

---

## 端口怎么定

编排里这一行：

```yaml
ports:
  - "8080:8080"
    ↑     ↑
  宿主机  容器内
```

- **前面的数字**是宿主机端口，想换就改它（比如 `"8090:8080"`）
- **后面的 8080** 是容器里的程序端口，**别动**
- 不要加 `127.0.0.1:` 开头 —— 加了就只有服务器本机能访问，局域网其他设备连不上

改完记得同步 1Panel 防火墙的放行端口。

端口冲突先查：

```bash
ss -lntp | grep 8080
```

---

## 不要访问密码（可选）

编排里：

```yaml
    environment:
      # HQHS_PASSWORD: "改成你的密码"      ← 注释掉
      HQHS_ALLOW_INSECURE: "1"             ← 加这行
```

容器里必然监听 `0.0.0.0`，没密码时程序默认拒绝启动，这个开关就是明确表示「我知道没密码，继续」。

> 关掉密码后，任何能打开这个网址的人都能看到名单、替你提交。只在可信内网这么干。

---

## 动态密码（TOTP，推荐）

不记固定密码，用手机上的 Authenticator 生成 6 位码，30 秒变一次。

### 1. 生成密钥

```bash
docker exec hqhs-eval python /app/web/server.py --gen-totp
```

```
新的动态码密钥（填到 eval_config.json 的 totp_secret）：

  CKIPUCGHOAUDU443LCNZPNGEU2CFXJ2R

用 Authenticator（Google / 微软 / 1Password）添加这个链接：

  otpauth://totp/hqhs-eval:hqhs-eval?secret=CKIP...&issuer=hqhs-eval&period=30&digits=6

当前验证码：685321
```

### 2. 填进配置

```json
{
  "host": "sd.你的服务器地址",
  "totp_secret": "CKIPUCGHOAUDU443LCNZPNGEU2CFXJ2R",
  "totp_window": 1,
  "auth_mode": ""
}
```

- `totp_secret`：上面那串，**大写、不要空格**
- `totp_window`：容差时间窗（1 = ±30 秒），手机时间不准就调到 2~3
- `auth_mode`：留空 = 有密钥就**只认动态码**；填 `both` = 密码和动态码都认；填 `password` = 只认静态密码

改完重启：

```bash
docker restart hqhs-eval
```

### 3. 手机导入

装 **Google Authenticator** / **微软 Authenticator** / **1Password**，
选「手动输入密钥」，把 `totp_secret` 填进去（或把 `otpauth://` 链接转二维码扫）。

### 4. 登录

网页会提示「请输入手机上的 6 位动态码」，输那 6 个数字就行。

启动日志会打印当前码，方便对时：

```
 访问密码: 动态码（TOTP）（登录后 12 小时免登录）
 动态码  : 当前 487812（下一个 637360，容差 ±30 秒）
           导入: otpauth://totp/hqhs-eval:...
```

日志里的码和手机上不一样 = 手机时间不准，把 `totp_window` 调成 2。

### 三种模式对照

| `auth_mode` | 登录用什么 |
|---|---|
| 留空（默认） | 有 `totp_secret` 就只认动态码；没密钥就用静态密码 |
| `totp` | 只认动态码，静态密码直接拒 |
| `password` | 只认静态密码，动态码不生效 |
| `both` | 两个都认 |

### 安全细节

- 同一个 6 位码**只能用一次**（防重放），用过的记 2 分钟
- 密码和动态码共用失败计数，错 5 次照样锁 10 分钟
- 密钥在 `eval_config.json` 里，**拿到它等于能算出所有验证码**，别外传
- 环境变量 `HQHS_TOTP_SECRET` 优先级高于配置文件

### 算法

标准 RFC 6238（和银行 App、Google Authenticator 一致），用官方测试向量验过：

```
T=59s          → 94287082  ✓
T=1111111109s  → 07081804  ✓
```

---

## 更新版本

**关键：`docker compose up -d` 不会重建镜像**，镜像已经存在就直接用旧的。必须显式构建。

包里的 `重建.sh` 就是干这个的：

```bash
cd /opt/1panel/apps/hqhs/hqhs-eval
bash 重建.sh
```

它做三件事：清缓存构建镜像 → 强制重建容器 → 打印容器里的版本号。

输出里看到 `VERSION = "5.2.0"` 才算成功。

或者手动：

```bash
docker compose -f docker-compose.lan.yml build --no-cache
docker compose -f docker-compose.lan.yml up -d --force-recreate
docker exec hqhs-eval grep VERSION /app/web/server.py
```

### 为什么 1Panel 的「重建」不管用

编排里这一行决定了会不会重建：

```yaml
image: hqhs-eval:5.2      # 跟版本号走
```

`docker compose up -d` 的规则是「镜像存在就直接用」。如果这里写的是固定标签（比如 `hqhs-eval:lan`），
这个镜像永远存在，**永远不重建**，改多少文件都没用。

现在的标签跟版本号走，换新包后标签变了，Docker 发现本地没有就自动构建。

### 怎么确认更新成功

页面标题旁：

| 显示 | 含义 |
|---|---|
| `v5.2.0 · AES:cryptography` | ✅ 全部更新成功 |
| `v5.2.0 · … · 前端 5.2 不一致` **红色** | 后端新了前端旧，只覆盖了一半文件 |
| 还是 `v4.3.0` | 镜像没换，回到上面 `重建.sh` |

**`web/` 和 `scripts/` 两个目录要一起覆盖**，只换一个会出现"页面新、接口旧"。

---

## 镜像拉不下来

1Panel 里构建时报这个，就是拉不到基础镜像：

```
failed to resolve source metadata for python:3.11-slim: i/o timeout
```

### 办法一：预拉镜像打标签（最快）

```bash
cd /opt/1panel/apps/hqhs/hqhs-eval
bash 准备镜像.sh
```

它依次试几个国内源，拉下来后打成 `python:3.11-slim` 的标签。之后 `docker build` 发现本地已有，直接跳过联网。

也可以手动两句：

```bash
docker pull docker.m.daocloud.io/library/python:3.11-slim
docker tag docker.m.daocloud.io/library/python:3.11-slim python:3.11-slim
```

### 办法二：配 Docker 镜像加速

1Panel → **容器 → 配置 → 镜像加速**，填：

```
https://docker.m.daocloud.io
```

或者改 `/etc/docker/daemon.json`：

```json
{ "registry-mirrors": ["https://docker.m.daocloud.io"] }
```

```bash
systemctl restart docker
```

### 办法三：干脆不用 Docker（最稳）

这个应用只需要一个 Python 包，PyPI 走清华源国内很快：

```bash
cd /opt/1panel/apps/hqhs/hqhs-eval

apt install -y python3 python3-venv
python3 -m venv .venv
.venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests

.venv/bin/python web/server.py --host 0.0.0.0 --port 8080 --password '你的密码'
```

看到启动横幅就成了，Ctrl+C 停掉后做成开机自启：

```bash
cat > /etc/systemd/system/hqhs-eval.service <<'EOF'
[Unit]
Description=hqhs eval web
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/1panel/apps/hqhs/hqhs-eval
ExecStart=/opt/1panel/apps/hqhs/hqhs-eval/.venv/bin/python web/server.py --host 0.0.0.0 --port 8080 --password 你的密码
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload && systemctl enable --now hqhs-eval
```

不用 Docker 的话，`cryptography` 也不用装 —— 脚本里内置了纯 Python 的 AES 实现，实测密文完全一致，只是慢 1 毫秒。

---

## 日常维护

**看日志**

```bash
docker logs --tail 50 hqhs-eval                                        # 程序输出
cat /opt/1panel/apps/hqhs/hqhs-eval/data/web_$(date +%Y%m%d).log       # 运行日志
cat /opt/1panel/apps/hqhs/hqhs-eval/data/submitted.json                # 当天台账
```

**改服务器地址**

直接改宿主机上的 `eval_config.json`，不用重启容器（挂载是实时的）。或者在网页上填一次点保存。

**备份台账**

1Panel → 计划任务 → 备份目录 → `/opt/1panel/apps/hqhs/hqhs-eval/data` → 每天。

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 打开是 502 / 拒绝连接 | 容器没起，或端口没放行 | `docker ps`、防火墙 |
| 页面能开但按钮没反应 | 前端 JS 出错 | F12 看 Console，或页面顶部红条会提示 |
| 一直转圈 | 后端在连内网评价服务器，慢 | 看日志确认服务器能访问 |
| 所有人都被锁 10 分钟 | 局域网直连不该有 `HQHS_TRUST_PROXY` | 有这个变量就删掉 |
| 日志里 Permission denied | 容器内 uid 1000 没写权限 | `sudo chown -R 1000:1000 ./data` |
| 版本号没变 | 镜像没重建 | 跑 `重建.sh` |
| 前端版本不一致（红条） | 只覆盖了一半文件 | `web/` 和 `scripts/` 一起覆盖 |
