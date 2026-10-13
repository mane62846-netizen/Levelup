# -*- coding: utf-8 -*-
"""
dashboard_server.py — RAGHU Level Up Dashboard Backend
Serves index.html + JSON APIs consumed by the frontend.
"""

import asyncio
import json
import os
import time
from typing import Dict, List, Any, Optional
from aiohttp import web

# ==================== EXP TABLE (Free Fire) ====================
EXP_TABLE = {
    1: 0, 2: 48, 3: 202, 4: 544, 5: 1012, 6: 1844, 7: 2792, 8: 3800,
    9: 4870, 10: 6004, 11: 7192, 12: 8448, 13: 9760, 14: 11140,
    15: 12566, 16: 14060, 17: 15610, 18: 17224, 19: 18902, 20: 20632,
    21: 22424, 22: 24278, 23: 26192, 24: 28166, 25: 30200, 26: 32294,
    27: 34448, 28: 37804, 29: 41274, 30: 44870, 31: 48582, 32: 53394,
    33: 58566, 34: 64096, 35: 69994, 36: 76460, 37: 83506, 38: 91128,
    39: 99322, 40: 108092, 41: 120144, 42: 133266, 43: 147472,
    44: 162760, 45: 179126, 46: 196572, 47: 215368, 48: 235516,
    49: 257010, 50: 279860, 51: 304056, 52: 348318, 53: 394982,
    54: 444044, 55: 495508, 56: 549364, 57: 633756, 58: 721744,
    59: 813336, 60: 908522, 61: 1041438, 62: 1180352, 63: 1325266,
    64: 1476184, 65: 1634300, 66: 1840946, 67: 2056594, 68: 2281242,
    69: 2514880, 70: 2757530, 71: 3059506, 72: 3372284, 73: 3699456,
    74: 4041030, 75: 4397002, 76: 4829104, 77: 5282204, 78: 5756304,
    79: 6251408, 80: 6776502, 81: 7381324, 82: 8043154, 83: 8752982,
    84: 9510808, 85: 10316338, 86: 11277190, 87: 12291748,
    88: 13360304, 89: 14482858, 90: 15659418, 91: 17026708,
    92: 18453950, 93: 19941280, 94: 21488570, 95: 23095858,
    96: 24763138, 97: 26490428, 98: 28378704, 99: 30124996,
    100: 32032884,
}


class BotState:
    def __init__(self):
        self.accounts: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, Any]] = []
        self.max_logs = 500
        self.total_matches = 0
        self.total_matches_started = 0
        self.total_gained_exp = 0
        self.total_active_matches = 0
        self.start_time = time.time()
        self.account_workers: Dict[str, asyncio.Task] = {}
        self.refresh_callbacks: Dict[str, Any] = {}
        self.account_credentials: Dict[str, Dict[str, Any]] = {}
        self._accounts_file = "accounts.json"
        self._paused: Dict[str, bool] = {}

    # ---------- Logging ----------
    def log(self, message: str, level: str = "info", uid: Optional[str] = None):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
            "uid": str(uid) if uid else None,
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

    # ---------- Register / Update ----------
    def register_account(self, uid: str, nickname: str, region: str,
                         level: int, exp: int, likes: int = 0):
        uid_str = str(uid)
        now_ts = time.time()
        if uid_str not in self.accounts:
            self.accounts[uid_str] = {
                "uid": uid_str,
                "nickname": nickname or f"Player_{uid_str[:6]}",
                "region": region or "IND",
                "level": int(level) or 1,
                "initial_exp": int(exp),
                "current_exp": int(exp),
                "gained_exp": 0,
                "likes": int(likes or 0),
                "status": "ONLINE",
                "matches_played": 0,
                "matches_completed": 0,
                "active_matches": 0,
                "last_match_time": None,
                "last_updated": time.strftime("%H:%M:%S"),
                "uptime_seconds": 0,
                "is_paused": False,
                "_registered_at": now_ts,
            }
        else:
            acc = self.accounts[uid_str]
            if nickname:
                acc["nickname"] = nickname
            if region:
                acc["region"] = region
            if level and int(level) > 0:
                acc["level"] = int(level)
            acc["current_exp"] = int(exp)
            acc["gained_exp"] = max(0, int(exp) - acc["initial_exp"])
            acc["likes"] = int(likes or 0)
            acc["status"] = "ONLINE"
            acc["last_updated"] = time.strftime("%H:%M:%S")
        self.recalc_totals()

    def update_exp(self, uid: str, current_exp: int, level: Optional[int] = None):
        uid_str = str(uid)
        if uid_str not in self.accounts:
            return
        acc = self.accounts[uid_str]
        old_exp = acc["current_exp"]
        acc["current_exp"] = int(current_exp)
        if level is not None and int(level) > 0:
            acc["level"] = int(level)
        acc["gained_exp"] = max(0, int(current_exp) - acc["initial_exp"])
        acc["last_updated"] = time.strftime("%H:%M:%S")
        diff = int(current_exp) - old_exp
        if diff > 0:
            self.log(
                f"Account {acc['nickname']} ({uid_str}) +{diff} EXP | Total: +{acc['gained_exp']}",
                "success",
                uid_str,
            )
        self.recalc_totals()

    def update_status(self, uid: str, status: str, active_matches: Optional[int] = None):
        uid_str = str(uid)
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            acc["status"] = status
            if active_matches is not None:
                acc["active_matches"] = int(active_matches)
            acc["last_updated"] = time.strftime("%H:%M:%S")

    def increment_match(self, uid: str, completed: bool = True):
        uid_str = str(uid)
        self.total_matches += 1
        if uid_str in self.accounts:
            acc = self.accounts[uid_str]
            acc["matches_played"] += 1
            if completed:
                acc["matches_completed"] = acc.get("matches_completed", 0) + 1
            acc["last_match_time"] = time.strftime("%H:%M:%S")
            acc["last_updated"] = time.strftime("%H:%M:%S")
            self.log(
                f"Account {acc['nickname']} finished Match #{acc['matches_played']}",
                "info",
                uid_str,
            )

    def increment_match_started(self, uid: str):
        self.total_matches_started += 1

    def recalc_totals(self):
        self.total_gained_exp = sum(
            acc.get("gained_exp", 0) for acc in self.accounts.values()
        )
        self.total_active_matches = sum(
            acc.get("active_matches", 0) for acc in self.accounts.values()
        )

    # ---------- Pause ----------
    def set_paused(self, uid: str, paused: bool):
        uid_str = str(uid)
        self._paused[uid_str] = paused
        if uid_str in self.accounts:
            self.accounts[uid_str]["is_paused"] = paused
            self.accounts[uid_str]["status"] = "PAUSED" if paused else "ONLINE"
            self.accounts[uid_str]["last_updated"] = time.strftime("%H:%M:%S")

    def is_paused(self, uid: str) -> bool:
        return self._paused.get(str(uid), False)

    # ---------- Uptime ----------
    def refresh_uptimes(self):
        now = time.time()
        for acc in self.accounts.values():
            if acc.get("is_paused"):
                continue
            registered = acc.get("_registered_at", now)
            acc["uptime_seconds"] = int(now - registered)

    # ---------- Snapshot for /api/stats ----------
    def get_snapshot(self) -> Dict[str, Any]:
        self.refresh_uptimes()
        uptime = max(1.0, time.time() - self.start_time)
        exp_per_hour = int(self.total_gained_exp / max(0.016, uptime / 3600))
        accounts_list = []
        for acc in self.accounts.values():
            a = dict(acc)
            a.pop("_registered_at", None)
            a["is_paused"] = bool(
                self._paused.get(str(a["uid"]), a.get("is_paused", False))
            )
            accounts_list.append(a)
        return {
            "accounts": accounts_list,
            "logs": self.logs[-200:],
            "total_accounts": len(self.accounts),
            "total_matches": self.total_matches,
            "total_matches_started": self.total_matches_started,
            "total_gained_exp": self.total_gained_exp,
            "total_active_matches": self.total_active_matches,
            "exp_per_hour": exp_per_hour,
            "uptime": uptime,
            "server_time": time.strftime("%H:%M:%S"),
        }

    # ---------- File IO ----------
    def load_accounts_from_file(self) -> List[Dict]:
        if os.path.exists(self._accounts_file):
            try:
                with open(self._accounts_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []

    def save_accounts_to_file(self, accounts: List[Dict]):
        try:
            with open(self._accounts_file, "w", encoding="utf-8") as f:
                json.dump(accounts, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"Failed to save accounts: {e}", "error")


bot_state = BotState()


# ==================== API HANDLERS ====================
async def api_stats(request):
    return web.json_response(bot_state.get_snapshot())


async def api_logs(request):
    return web.json_response({"logs": bot_state.logs})


async def api_logs_clear(request):
    bot_state.logs = []
    bot_state.log("Logs cleared via dashboard", "info")
    return web.json_response({"status": "ok"})


async def api_account_add(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

    uid = str(data.get("uid", "")).strip()
    password = str(data.get("password", "")).strip()
    token = str(data.get("token", "")).strip()

    if not uid and not token:
        return web.json_response(
            {"status": "error", "error": "UID or token required"}, status=400
        )

    accounts = bot_state.load_accounts_from_file()

    if uid and any(str(a.get("uid")) == uid for a in accounts):
        return web.json_response(
            {"status": "error", "error": "Account already exists"}, status=400
        )

    if uid and password:
        accounts.append({"uid": uid, "password": password})
        bot_state.log(f"New account {uid} added via dashboard", "success", uid)
        bot_state.register_account(
            uid=uid, nickname=f"Player_{uid[:6]}", region="IND", level=1, exp=0,
        )
    elif token:
        temp_uid = f"tok_{int(time.time())}"
        accounts.append({"uid": temp_uid, "token": token})
        bot_state.log(f"Token account {temp_uid} added", "success", temp_uid)
        bot_state.register_account(
            uid=temp_uid, nickname="Token User", region="IND", level=1, exp=0,
        )
        uid = temp_uid

    bot_state.save_accounts_to_file(accounts)

    cb = bot_state.refresh_callbacks.get("start_worker")
    if cb and uid:
        try:
            asyncio.create_task(cb(uid, password or token))
        except Exception as e:
            bot_state.log(f"Worker start failed: {e}", "error", uid)

    return web.json_response({"status": "ok", "uid": uid})


async def api_account_delete(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"status": "error", "error": "UID required"}, status=400)

    accounts = bot_state.load_accounts_from_file()
    new_accounts = [a for a in accounts if str(a.get("uid")) != uid]
    bot_state.save_accounts_to_file(new_accounts)

    worker = bot_state.account_workers.get(uid)
    if worker and not worker.done():
        worker.cancel()
    bot_state.account_workers.pop(uid, None)
    bot_state.accounts.pop(uid, None)
    bot_state._paused.pop(uid, None)
    bot_state.recalc_totals()
    bot_state.log(f"Account {uid} deleted via dashboard", "warning", uid)
    return web.json_response({"status": "ok"})


async def api_account_pause(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"status": "error", "error": "UID required"}, status=400)

    current = bot_state.is_paused(uid)
    new_state = not current
    bot_state.set_paused(uid, new_state)
    bot_state.log(
        f"Account {uid} {'paused' if new_state else 'resumed'}",
        "warning" if new_state else "success",
        uid,
    )
    return web.json_response({"status": "ok", "is_paused": new_state})


async def api_account_pause_all(request):
    paused_count = 0
    for uid in list(bot_state.accounts.keys()):
        if not bot_state.is_paused(uid):
            paused_count += 1
        bot_state.set_paused(uid, True)
    bot_state.log(f"All accounts paused ({paused_count})", "warning")
    return web.json_response({"status": "ok", "all_paused": True})


async def api_account_refresh(request):
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

    uid = str(data.get("uid", "")).strip()
    if not uid:
        return web.json_response({"status": "error", "error": "UID required"}, status=400)

    bot_state.log(f"Manual sync requested for {uid}", "info", uid)
    cb = bot_state.refresh_callbacks.get("refresh_account")
    if cb:
        try:
            asyncio.create_task(cb(uid))
        except Exception as e:
            bot_state.log(f"Refresh failed: {e}", "error", uid)
    return web.json_response({"status": "ok"})


# ==================== STATIC ====================
async def index_handler(request):
    if os.path.exists("index.html"):
        return web.FileResponse("index.html")
    return web.Response(text="index.html not found.", content_type="text/plain")


async def favicon_handler(request):
    return web.Response(status=204)


# ==================== SERVER ====================
async def start_web_dashboard(host: str = "0.0.0.0", port: int = 20335):
    app = web.Application()

    @web.middleware
    async def cors_middleware(request, handler):
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            try:
                response = await handler(request)
            except web.HTTPException as ex:
                response = ex
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Session-Token"
        return response

    app.middlewares.append(cors_middleware)

    app.router.add_get("/", index_handler)
    app.router.add_get("/favicon.ico", favicon_handler)
    app.router.add_get("/api/stats", api_stats)
    app.router.add_get("/api/logs", api_logs)
    app.router.add_post("/api/logs/clear", api_logs_clear)
    app.router.add_post("/api/account/add", api_account_add)
    app.router.add_post("/api/account/delete", api_account_delete)
    app.router.add_post("/api/account/pause", api_account_pause)
    app.router.add_post("/api/account/pause_all", api_account_pause_all)
    app.router.add_post("/api/account/refresh", api_account_refresh)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    print(f"[Dashboard] ✅ Running at http://{host}:{port}")
    print(f"[Dashboard] 📊 Open: http://localhost:{port}")


if __name__ == "__main__":
    async def _test():
        await start_web_dashboard()
        while True:
            await asyncio.sleep(3600)
    try:
        asyncio.run(_test())
    except KeyboardInterrupt:
        print("\nStopped.")