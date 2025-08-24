# region COPYRIGHT

# Copyright © 2025 [MinerMouse]
# Luogu UID:1203704
# 本软件著作权归作者所有，代发布者仅协助发布，除经过授权，不享有任何著作权。

# endregion

# server.py

import asyncio, json, logging
from datetime import datetime
from pathlib import Path
import websockets
import configparser

logging.basicConfig(level=logging.INFO)

INI_PATH = Path(__file__).with_name("server.ini")
logging.info(f"加载配置文件: {INI_PATH.exists()}")

def load_config():
    cfg = configparser.ConfigParser()
    cfg["SERVER"] = {"host": "localhost", "port": "8765"}  # 默认
    logging.info(f"当前工作目录: {Path.cwd()}")
    logging.info(f"配置文件路径: {INI_PATH.absolute()}")
    if INI_PATH.exists():
        logging.info(f"配置文件存在: {INI_PATH}")
        cfg.read(INI_PATH, encoding="utf-8")
        logging.info(f"读取配置: {cfg['SERVER']}")
    else:
        logging.info(f"配置文件不存在")
        path = input("请输入你的电脑IP地址: ")
        cfg["SERVER"]["host"] = path
        port = int(input("请输入你的电脑端口(默认8765): ") or 8765)
        cfg["SERVER"]["port"] = str(port)
        logging.info(f"创建默认配置: ip = {cfg['SERVER']['host']}, port = {cfg['SERVER']['port']} ")
        try:
            with open(INI_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)
            logging.info(f"配置已保存到 {INI_PATH}")
        except Exception as e:
            logging.error(f"保存配置失败: {e}")
    host = cfg["SERVER"]["host"]
    port = int(cfg["SERVER"]["port"])
    
    # 验证IP地址有效性
    try:
        import socket
        socket.inet_aton(host)  # 验证IPv4地址格式
        logging.info(f"使用配置中的IP地址: {host}")
    except socket.error:
        logging.warning(f"无效的IP地址 {host} , 请关闭后使用ipconfig重新查询并输入")
        return
    
    return host, port

class ChatServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.clients = {}                # websocket -> username
        self.user_order = []             # 按加入顺序保存用户名

    def add_user(self, username):
        if username not in self.user_order:
            self.user_order.append(username)
        return self.user_order

    async def register(self, websocket, username):
        self.clients[websocket] = username
        logging.info(f"{username} 加入了聊天室")
        self.add_user(username)
        await self.broadcast({
            "type": "user_list",
            "users": self.user_order
        })

    async def unregister(self, websocket):
        username = self.clients.pop(websocket, None)
        if username and username in self.user_order:
            self.user_order.remove(username)
            logging.info(f"{username} 退出了聊天室")
            await self.broadcast({
                "type": "user_list",
                "users": self.user_order
            })

    async def broadcast(self, message):
        disconnected = []
        for ws in list(self.clients):
            try:
                await ws.send(json.dumps(message))
            except websockets.ConnectionClosed:
                disconnected.append(ws)
        for ws in disconnected:
            await self.unregister(ws)

    async def handle_client(self, websocket, path=None):
        try:
            async for raw in websocket:
                data = json.loads(raw)
                if data["type"] == "register":
                    await self.register(websocket, data["username"])
                elif data["type"] == "message":
                    await self.broadcast({
                        "type": "message",
                        "username": self.clients[websocket],
                        "content": data["content"],
                        "timestamp": datetime.now().isoformat()
                    })
                elif data["type"] == "private_message":
                    target = data["target"]
                    sender = self.clients[websocket]
                    for ws, name in self.clients.items():
                        if name == target:
                            await ws.send(json.dumps({
                                "type": "private_message",
                                "from": sender,
                                "content": data["content"],
                                "timestamp": datetime.now().isoformat()
                            }))
                            await websocket.send(json.dumps({
                                "type": "private_message_sent",
                                "to": target,
                                "content": data["content"],
                                "timestamp": datetime.now().isoformat()
                            }))
                            break
                elif data["type"] == "get_users":
                    await websocket.send(json.dumps({
                        "type": "user_list",
                        "users": list(self.clients.values())
                    }))
                elif data["type"] == "file_upload":
                    await self.handle_file(data, websocket)
        except websockets.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)

    async def handle_file(self, data, websocket):
        try:
            username = self.clients[websocket]
            filename = data["filename"]
            content = data["content"]
            recv_dir = Path("recvfiles")
            recv_dir.mkdir(exist_ok=True)
            file_path = recv_dir / filename
            with open(file_path, "wb") as f:
                f.write(bytes.fromhex(content))
            await self.broadcast({
                "type": "file_shared",
                "username": username,
                "filename": filename,
                "size": len(content) // 2,
                "timestamp": datetime.now().isoformat()
            })
            await websocket.send(json.dumps({"type": "file_progress", "progress": 100}))
        except Exception as e:
            await websocket.send(json.dumps({"type": "file_error", "message": str(e)}))

    async def run(self):
        logging.info(f"TouchMouse V1.0 服务器监听 {self.host}:{self.port}")
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()

if __name__ == "__main__":
    host, port = load_config()
    asyncio.run(ChatServer(host, port).run())
