#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/mock_hqhs.py — 模拟 com.xykj.hqhs 后端（多账号版），验证 hqhs_eval / hqhs_batch

校验项与真实协议一致：
  - loginByAppV2 的 userName/passWord 必须是 AES/ECB/PKCS5 + 内置 key 的大写 hex
  - 后续请求必须带 Blade-Auth: bearer <token>
  - 公共 query 必须含 userId / orgId / orgName
  - appraiseGrassSave 的 body 必须 type="1"、source="app"，每题 choice 落在 optionGrades 内
  - 同一天重复提交 → 500 "异常了，请联系管理员"（App 侧显示"当天评价次数已达上限"）
  - 当天已交的账号，detail 空参返回空题目（模拟"没有待评价任务"）

内置账号: zhangsan / lisi / wangwu  密码都是 123456
"""
import json, sys, datetime
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

KEY = "metagross-zhihuihouqin-shanxixueyu-400-151-6766"
BASIC = "Basic c2FiZXI6c2FiZXJfc2VjcmV0"
SAVE_ID = "SAVE-20261028-01"

USERS = {
    "zhangsan": {"pass": "123456", "userId": "U10086", "orgId": "ORG-201",
                 "dept_name": "特勤一站", "orgName": "特勤一站", "role_name": "就餐人员", "orgGrade": "5"},
    "lisi":     {"pass": "123456", "userId": "U10087", "orgId": "ORG-202",
                 "dept_name": "特勤二站", "orgName": "特勤二站", "role_name": "就餐人员", "orgGrade": "5"},
    "wangwu":   {"pass": "123456", "userId": "U10088", "orgId": "ORG-203",
                 "dept_name": "特勤三站", "orgName": "特勤三站", "role_name": "管理员", "orgGrade": "5"},
}
STATE = {"submitted": defaultdict(dict), "tokens": {}}   # user -> {date: body}


def aes_decrypt(hexstr):
    key = (KEY + "0" * 32)[:32].encode()
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    raw = dec.update(bytes.fromhex(hexstr)) + dec.finalize()
    unp = padding.PKCS7(128).unpadder()
    return (unp.update(raw) + unp.finalize()).decode("utf-8")


def build_detail(user):
    u = USERS[user]

    def item(i, name, grades="2,1,0", names="满意,一般,不满意"):
        return {"id": f"T{i}", "appraiseSubId": f"SUB{i}", "appraiseSubName": name,
                "optionNames": names, "optionGrades": grades,
                "choice": None, "num": str(i), "isUploadFile": "1", "fileType": None, "filePath": None}
    return {
        "id": SAVE_ID, "orgId": u["orgId"], "orgName": u["orgName"],
        "dateStr": datetime.date.today().strftime("%Y-%m-%d"),
        "satisfiedList": [
            item(1, "是否对饭菜口味满意？"),
            item(2, "是否对饭菜温度满意？"),
            item(3, "是否对饭菜新鲜度满意？"),
        ],
        "superviseList": [
            item(4, "是否对就餐环境满意？"),
        ],
    }


class H(BaseHTTPRequestHandler):
    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json;charset=UTF-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _fail(self, msg, code=500):
        self._send({"code": code, "success": False, "msg": msg, "data": None})

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n).decode("utf-8", "replace")
        body = json.loads(raw) if raw.strip().startswith("{") else None
        sys.stderr.write(f"[mock] POST {u.path} q={q}\n")

        if not u.path.startswith("/api/"):
            return self._fail(f"bad base path: {u.path}", 404)
        p = u.path[5:]

        # ---------- 登录 ----------
        if p.endswith("learnworld-canteen/api/loginByAppV2"):
            if self.headers.get("Authorization") != BASIC:
                return self._fail("Basic 认证头不对", 401)
            try:
                un, pw = aes_decrypt(q["userName"]), aes_decrypt(q["passWord"])
            except Exception as e:
                return self._fail(f"参数不是合法 AES hex: {e}", 400)
            sys.stderr.write(f"[mock] 解出 user={un} pwd={pw}\n")
            if un not in USERS:
                return self._fail("用户名不存在", 401)
            if USERS[un]["pass"] != pw:
                return self._fail("用户名或密码错误", 401)
            tok = f"token-{un}"
            STATE["tokens"][tok] = un
            data = dict(USERS[un], userName=un, name=un, access_token=tok)
            return self._send({"code": 200, "success": True, "msg": "登录成功", "data": data})

        # ---------- 鉴权 ----------
        auth = (self.headers.get("Blade-Auth") or "").replace("bearer ", "")
        who = STATE["tokens"].get(auth)
        if not who:
            return self._fail("Token 无效或已过期", 401)
        if q.get("userId") != USERS[who]["userId"]:
            return self._fail("公共参数 userId 缺失/不符", 400)
        if q.get("orgId") != USERS[who]["orgId"]:
            return self._fail("公共参数 orgId 缺失/不符", 400)
        today = datetime.date.today().isoformat()

        # ---------- 详情 ----------
        if p.endswith("appraiseGrassDetail"):
            if q.get("id", "") == "":      # 新增场景：今天已交就不给模板
                if STATE["submitted"][who].get(today):
                    return self._send({"code": 200, "success": True, "msg": "成功",
                                       "data": {"satisfiedList": [], "superviseList": [],
                                                "id": SAVE_ID, "orgId": USERS[who]["orgId"]}})
                return self._send({"code": 200, "success": True, "msg": "成功",
                                   "data": build_detail(who)})
            return self._send({"code": 200, "success": True, "msg": "成功",
                               "data": build_detail(who)})

        # ---------- 提交 ----------
        if p.endswith("appraiseGrassSave"):
            if getattr(self.server, "limit_on_save", False):
                # 模拟「详情能拿到模板，但提交时撞当天上限」——用来验证 batch 是否记为 SKIP
                return self._fail("异常了，请联系管理员")
            if STATE["submitted"][who].get(today):
                return self._fail("异常了，请联系管理员")
            if not body:
                return self._fail("body 为空", 400)
            need = {"satisfiedList", "superviseList", "type", "checkOrgId", "orgId", "id", "userId", "source"}
            miss = need - set(body)
            if miss:
                return self._fail(f"body 缺字段: {miss}", 400)
            if body["type"] != "1" or body["source"] != "app":
                return self._fail("type/source 不对", 400)
            if body["orgId"] != USERS[who]["orgId"]:
                return self._fail("orgId 不对", 400)
            for g in ("satisfiedList", "superviseList"):
                for i, it in enumerate(body[g], 1):
                    if not it.get("choice"):
                        return self._fail(f"{g} 第{i}题未评分", 400)
                    if it["choice"] not in it.get("optionGrades", "").split(","):
                        return self._fail(f"{g} 第{i}题 choice 越界", 400)
            STATE["submitted"][who][today] = body
            sys.stderr.write(f"[mock] {who} 提交成功 {len(body['satisfiedList'])}+"
                             f"{len(body['superviseList'])} 题\n")
            return self._send({"code": 200, "success": True, "msg": "提交成功", "data": None})

        # ---------- 列表 ----------
        if p.endswith("appraiseGrassPage"):
            recs = [{"id": SAVE_ID, "dateStr": d, "timeStr": "07:31:02",
                     "orgName": USERS[who]["orgName"], "orgGrade": "5",
                     "satisfiedScore": 6.0, "superviseScore": 2.0, "evaluationNum": "1"}
                    for d in STATE["submitted"][who]]
            return self._send({"code": 200, "success": True, "msg": "成功",
                               "data": {"records": recs, "total": len(recs)}})

        return self._fail(f"未实现的接口: {p}", 404)

    def do_GET(self):
        if getattr(self.server, "fake_redirect", False):
            # 用来验证 hqhs_eval 的 http->https 自动切换
            self.send_response(301)
            self.send_header("Location", "https://" + (self.headers.get("Host") or "127.0.0.1") + self.path)
            self.end_headers()
            return
        self._send({"code": 200, "success": True, "msg": "ok", "data": None})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    print(f"mock hqhs backend (multi-account) on 127.0.0.1:{port}", file=sys.stderr)
    srv = HTTPServer(("127.0.0.1", port), H)
    srv.fake_redirect = "--redirect" in sys.argv
    srv.limit_on_save = "--limit-on-save" in sys.argv
    print(f"fake_redirect={srv.fake_redirect}", file=sys.stderr)
    srv.serve_forever()
