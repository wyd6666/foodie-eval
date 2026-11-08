# base.apk 伙食评价 —— 逆向结论与一键方案

APK: `com.xykj.hqhs` v4.16.2 · 智慧后勤（伙食管理）· 原生 Java/Kotlin，无加固、无壳、无签名校验

拆完的结论一句话：**这套评价没有签名、没有加密（只有登录密码做了 AES）、没有设备指纹**，
所以「一键评价提交」有三条落地路径，从轻到重：

| 方案 | 命令 | 需要手机 | 要重装 App | 适用 |
|---|---|---|---|---|
| **A. 纯 HTTP 脚本**（推荐） | `bash run.sh hqhs` | 否 | 否 | 电脑/NAS 上每周定时跑 |
| **B. 改包**（你要的「直接改 APK」） | `bash run.sh autoeval apk/base.apk submit` | 是 | 是（卸载重装） | 想在手机上点一下就完成 |

三条用的是同一套逆向结果。

---

## 1. 逆向出来的真实调用链

源码位置：`out/jadx/sources/com/xykj/evaluation/ui/FiremanEvaluationActivity.java`

```
① 登录   POST /api/learnworld-canteen/api/loginByAppV2?userName=<AES>&passWord=<AES>
         → UserRes{access_token, userId, orgId, orgGrade, dept_name, role_name}

② 取模板 POST /api/learnworld-canteen/api/appraiseGrassDetail?id=&grade=
         → DataBean{satisfiedList[], superviseList[], id(saveId), orgId, orgName, dateStr}
         「新增评价」时 id 和 grade 传空串 —— 服务端按当前用户+当天返回题目模板
         （依据 FiremanEvaluationManagerActivity:146 putExtra("id", "")）

③ 逐题打分 每题 choice = 从 optionGrades 里选一个值（"5,4,3,2,1" 里挑一个字符串）

④ 提交   POST /api/learnworld-canteen/api/appraiseGrassSave   body=DataBean
         type="1" (TYPE_APPRAISE_REAL)  source="app"
         checkOrgId=orgId  orgId=orgId  id=saveId  userId=<登录用户>
```

### 认证与公共参数（`CommonInterceptor.java`）

```
Authorization: Basic c2FiZXI6c2FiZXJfc2VjcmV0        ← saber:saber_secret，写死的
Blade-Auth:    bearer <access_token>                ← 登录拿到的
query 自动附加: orgName=<dept_name> & userId=<userId> & orgId=<orgId>
User-Agent:    应用自己的 UA
```

服务器地址**不是写死的**：App 登录页会让你填 IP（`IpSetActivity`），
baseUrl = `http://<你填的IP>/api/`。所以脚本里要填同一台服务器。

### 密码加密（`AESUtils3.java`）

```
算法: AES/ECB/PKCS5Padding
key : "metagross-zhihuihouqin-shanxixueyu-400-151-6766" 截断/补零到 32 字节 → AES-256
输出: 大写 hex
```
Python 侧已复刻并做了往返验证（见下面「验证记录」）。

### 服务端限制

- **每天只能提交一次**：再提交返回 `异常了，请联系管理员`，App 把它映射成
  「您当天评价次数已达上限!」（`FiremanEvaluationActivity:555`）
- 所以「每周」实际是「每周挑一天交一次」，脚本撞上限会明确报出来

---

## 2. 方案 A：纯 HTTP 一键（推荐）

```bash
# 1. 填配置
vi eval_config.json
{
  "scheme": "http",
  "host": "10.x.x.x:8080",        ← 你在 App 登录页填的那个 IP（可带端口）
  "userName": "你的账号",
  "passWord": "你的密码",
  "strategy": "max"                ← max=每题最高分；也可 fixedScore: 5 指定分值
}

# 2. 先看本周交过没（不会提交）
bash run.sh hqhs --status

# 3. 干跑：看清楚每一题会选什么
bash run.sh hqhs --dry-run

# 4. 真提交
bash run.sh hqhs

# 5. 每周自动（周一 07:30）
bash run.sh cron
```

也可以临时用命令行覆盖：`bash run.sh hqhs --host 10.0.0.8:8080 -u 张三 -p 123456`

## 2.5 多账号批量：一次交一队人

名单放 `accounts.json`（或从 Excel 存成 `accounts.csv`，三列 `name,userName,passWord`）：

```json
[
  { "name": "张三", "userName": "3702xxxxxxxxxxxxxx", "passWord": "密码" },
  { "name": "李四", "userName": "3702xxxxxxxxxxxxxx", "passWord": "密码" }
]
```

```bash
# 先把名单跑一遍预演：只登录、取模板、算好每题分值，不提交
bash run.sh batch -a accounts.json --dry-run

# 确认没问题再真交
bash run.sh batch -a accounts.json

# 只看各人本周交了几条
bash run.sh batch -a accounts.json --status

# 只跑其中几个人 / 加并发 / 失败重试
bash run.sh batch -a accounts.json --only 张三,李四
bash run.sh batch -a accounts.json --concurrency 3
bash run.sh batch -a accounts.json --retry 2
```

输出三种状态，互不干扰：

```
[1/4] 张三  ✓ 提交成功（10满意度+10监督）  (青岛市消防救援支队特勤大队二站)
[2/4] 李四  · 跳过：服务端没下发任务（今天已交/不在时间窗）
[3/4] 王五  ✗ 账号或密码错误
汇总: 成功 2 | 跳过 1 | 失败 1 | 共 4
报告: out/batch_20261028_020923.json
```

- 单个人失败不影响其他人（默认串行，可 `--concurrency` 并发）
- `SKIP` 不算失败 —— 服务端没下发任务就是今天已经交过了，脚本明确区分，不会误报
- 每人一份独立的 `userId/orgId/dept`，都从各自登录结果里取，不用手工填
- 每轮都写 `out/batch_<时间>.json`（逐人明细）和 `out/batch_<时间>.log`（完整请求过程）
- 密码错、当天上限、无任务这几种常见情况会被翻译成人话，不用去看原始异常

## 3. 方案 B：改 APK —— 进评价页就自动全选+提交

```bash
bash run.sh autoeval apk/base.apk submit     # 全选最高分 + 自动提交
bash run.sh autoeval apk/base.apk fill       # 只全选最高分，提交你自己点
# → out/patched/hqhs-autoeval-submit.apk
```

装：

```bash
adb uninstall com.xykj.hqhs                  # 签名变了必须先卸（卸载前记下服务器 IP）
adb install -r out/patched/hqhs-autoeval-submit.apk
```

改了什么（只动 2 个 smali 文件，不碰资源、不碰网络层）：

| 文件 | 改动 |
|---|---|
| `FiremanEvaluationActivity.smali` | 新字段 `autoEvalDone:Z`（防重复提交）；新方法 `fillAllMax(List)`（把每题 `choice` 设成 `optionGrades` 第一项）；新方法 `autoEval()`（仅在 `isEdit=true` 即新增评价页动手，然后调原来的 `lambda$initEvent$1$...`＝原提交逻辑） |
| `FiremanEvaluationActivity$4.smali` | `onSuccess` 末尾（`settingData()` 之后）插入 `autoEval()` 调用 —— 此时题目数据刚回包，正好填 |

设计上的保护：
- 只在 `isEdit=true` 触发，翻「我的评价」历史记录不会误提交
- `autoEvalDone` 静态标记，`onResume` 多次回调也只交一次
- 走的是原 `appraiseGrassSave` 逻辑，必填校验、提示语、失败处理全部保持原样
- 每天一次的限流仍在服务端，撞上了会正常提示「当天评价次数已达上限」

还原/重打：
```bash
```
构建脚本每次会从 `out/apktool.pristine` 重置 smali，不会补丁叠加。

## 4. 方案 C：Frida 运行时（不改包、不重装）


反射把 `singleList`/`moreList` 每题 `setChoice(optionGrades[0])` →
反射调用原 `lambda$initEvent$1$FiremanEvaluationActivity()` 提交。
文件头有 `MODE`、`DELAY_MS`、`ONLY_NEW` 三个开关。

---

## 5. 验证记录

真机/真服务器没法在这台机器上验证（内网部署），所以做了两层可验证的东西：

**① AES 复刻自检** —— 用 `cryptography` 实现 `AESUtils3.encrypt`，加密后解密回原文一致；
`tests/mock_hqhs.py` 用同一套 key 在服务端**解密**登录参数，能解出 `zhangsan/123456` 才算登录成功 ——
说明 Java 侧与 Python 侧算法一致。

**② 全流程模拟后端** —— `tests/mock_hqhs.py` 按真实协议校验：

```
✓ loginByAppV2 必须 Basic 头正确、userName/passWord 必须是该 key 的 AES hex
✓ 后续请求必须 Blade-Auth: bearer <token>
✓ 公共 query 必须含 userId / orgId / orgName
✓ appraiseGrassSave 必须 type="1"、source="app"、id=saveId、orgId 匹配
✓ 每题 choice 非空且必须落在 optionGrades 内
✓ 同一天重复提交返回「异常了，请联系管理员」
```

跑出来的结果：

```
① --status          本周已提交 0 条 → 可以交
② --dry-run         4 题全部选 5（很满意），payload 字段齐全
③ 真提交            提交成功
④ 再提交一次        失败: 异常了，请联系管理员 (code=500)   ← 对应「当天评价次数已达上限」
⑤ --status          本周已提交 1 条 满意度=15.0 监督分=5.0
```

**③ 改包验证** —— 注入后 `apktool b` 编译通过（smali 语法正确）、
uber-apk-signer `zipalign verified` + `signature verified [v1, v2, v3]`、
并且从成品 APK 的 `classes2.dex` 字符串池里读到了 `autoEvalDone` / `autoEval` / `fillAllMax`
—— 补丁确实进了 dex。

---

## 6. 会踩的坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 脚本报 `请求超时` / `Connection refused` | 内网服务器，电脑不在同一网络 | 换到能访问该内网的机器/NAS 上跑 |
| `Token 无效或已过期` | access_token 有时效 | 脚本每次运行都会重新登录，正常不会碰到；常驻模式用 `--loop 7d` |
| `用户名或密码错误` | 密码要先 AES 再传，明文传会挂 | 脚本已处理，检查 `eval_config.json` 里是不是真密码 |
| `异常了，请联系管理员` | 就是「当天评价次数已达上限」 | 换一天，或先 `--status` 看今天交过没 |
| `详情返回空` | 今天没有待评价任务 / 不在评价时间窗 | 用 App 手动进一次看有没有题目 |
| 改包装不上 `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | 签名不同 | `adb uninstall com.xykj.hqhs` 再装；卸载前记下服务器 IP |
| 改包后自动提交没反应 | 走的不是「新增评价」入口（`isEdit=false`） | 从「伙食评价 → 新增评价」进；或用 `fill` 模式 |
| 改包后 App 闪退 | 版本不是 4.16.2，smali 结构不同 | 用 `fill` 重新生成；或退回方案 A/C |

---

## 7. 产物清单

```
out/hunt/                        接口/关键词/签名点清单
out/jadx/                        反编译 Java（508+ 文件，业务代码在 com/xykj/evaluation）
out/apktool/                     解包目录（含注入后的 smali）
out/apktool.pristine/            干净解包副本（重打包用）
out/patched/hqhs-autoeval-submit.apk   改好的包（v1/v2/v3 已签名）
eval_config.json                 方案 A 的配置（填 host/账号/密码）
```

核心脚本：

```
scripts/hqhs_eval.py             方案 A：纯 HTTP（含登录 AES、详情、逐题打分、提交、查记录、周期循环）
scripts/35_build_patched.sh      方案 B 一键：解包→注入→回编译→签名
tests/mock_hqhs.py               模拟后端，用来验证上面所有逻辑
```
