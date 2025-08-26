# region COPYRIGHT

# Copyright © 2025 [MinerMouse]
# Luogu UID:1203704
# 本软件著作权归作者所有，代发布者仅协助发布，除经过授权，不享有任何著作权。

# endregion

# server.py

import asyncio, json, logging, hashlib
from datetime import datetime, timedelta
from pathlib import Path
import websockets
import configparser
import re

# 接口版本号
API_VERSION = "1.0.0"

logging.basicConfig(level=logging.INFO)

INI_PATH = Path(__file__).with_name("server.ini")
logging.info(f"加载配置文件: {INI_PATH.exists()}")

def load_config():
    cfg = configparser.ConfigParser()
    cfg["SERVER"] = {"host": "localhost", "port": "8765", "owner_password": ""}  # 默认
    logging.info(f"当前工作目录: {Path.cwd()}")
    logging.info(f"配置文件路径: {INI_PATH.absolute()}")
    
    # 无论配置文件是否存在，都加载现有配置
    if INI_PATH.exists():
        logging.info(f"配置文件存在: {INI_PATH}")
        cfg.read(INI_PATH, encoding="utf-8")
        logging.info(f"读取配置: {cfg['SERVER']}")
        
        # 询问用户是否要修改IP地址和端口
        change_config = input("是否要修改IP地址和端口？(y/n): ").lower() == 'y'
        if change_config:
            path = input(f"请输入你的电脑IP地址 (当前: {cfg['SERVER']['host']}): ")
            if path:
                cfg["SERVER"]["host"] = path
            
            port_input = input(f"请输入你的电脑端口 (当前: {cfg['SERVER']['port']}): ")
            if port_input:
                cfg["SERVER"]["port"] = port_input
    else:
        logging.info(f"配置文件不存在")
        path = input("请输入你的电脑IP地址: ")
        cfg["SERVER"]["host"] = path
        port = int(input("请输入你的电脑端口(默认8765): ") or 8765)
        cfg["SERVER"]["port"] = str(port)
    
    # 每次启动都询问房主密码
    print("\n===== 房主密码设置 =====")
    current_has_password = bool(cfg["SERVER"]["owner_password"])
    if current_has_password:
        print(f"当前状态: {'已设置密码' if current_has_password else '未设置密码'}")
        
        change_password = input("是否要修改房主密码？(y/n): ").lower() == 'y'
        if change_password:
            owner_password = input("请输入新的房主密码 (直接回车保持为空): ")
            if owner_password:
                # 存储加密后的密码
                hashed_password = hashlib.sha256(owner_password.encode()).hexdigest()
                cfg["SERVER"]["owner_password"] = hashed_password
                print("房主密码已更新")
            else:
                cfg["SERVER"]["owner_password"] = ""
                print("房主密码已清除")
        else:
            print("保持现有密码设置")
    else:
        owner_password = input("请输入房主密码 (直接回车为不设置(无人能成为房主)): ")
        if owner_password:
            # 存储加密后的密码
            hashed_password = hashlib.sha256(owner_password.encode()).hexdigest()
            cfg["SERVER"]["owner_password"] = hashed_password
            print("房主密码已设置")
        else:
            print("未设置房主密码")
    
    # 保存配置文件
    logging.info(f"保存配置: ip = {cfg['SERVER']['host']}, port = {cfg['SERVER']['port']} ")
    try:
        with open(INI_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
        logging.info(f"配置已保存到 {INI_PATH}")
    except Exception as e:
        logging.error(f"保存配置失败: {e}")
    
    host = cfg["SERVER"]["host"]
    port = int(cfg["SERVER"]["port"])
    owner_password = cfg["SERVER"]["owner_password"]
    
    # 验证IP地址有效性
    try:
        import socket
        socket.inet_aton(host)  # 验证IPv4地址格式
        logging.info(f"使用配置中的IP地址: {host}")
    except socket.error:
        logging.warning(f"无效的IP地址 {host} , 请关闭后使用ipconfig重新查询并输入")
        return
    
    return host, port, owner_password

class ChatServer:
    def __init__(self, host, port, owner_password):
        self.host = host
        self.port = port
        self.owner_password = owner_password
        self.clients = {}                # websocket -> username
        self.user_order = []             # 按加入顺序保存用户名
        self.user_prefs = {}             # username -> preferences
        self.rooms = {
            "global": {
                "name": "全局聊天室",
                "members": set(),
                "created": datetime.now().isoformat()
            }
        }                                # room_id -> room_info
        self.user_rooms = {}             # username -> room_id
        self.expiring_rooms = {}         # room_id -> expiry_time (datetime object)
        self.expiry_task = None          # 房间过期检查任务
        self.owner = None                # 房主用户名
        self.muted_users = set()         # 被禁言的用户集合
        self.banned_words = []           # 屏蔽词列表
        self.kicked_users = []           # 被踢出的用户列表，包含时间戳

    async def add_user(self, username):
        if username not in self.user_order:
            self.user_order.append(username)
            # 默认加入全局聊天室
            await self.join_room(username, "global")
        return self.user_order

    async def join_room(self, username, room_id):
        if room_id not in self.rooms:
            return False
        
        # 离开当前房间
        if username in self.user_rooms:
            old_room = self.user_rooms[username]
            self.rooms[old_room]["members"].discard(username)
        
        # 加入新房间
        self.user_rooms[username] = room_id
        self.rooms[room_id]["members"].add(username)
        return True

    def create_room(self, room_id, room_name, expiry_hours=1):
        if room_id in self.rooms:
            return False
        
        # 默认房间有效期为1小时
        expiry_time = datetime.now() + timedelta(hours=expiry_hours)
        
        self.rooms[room_id] = {
            "name": room_name,
            "members": set(),
            "created": datetime.now().isoformat(),
            "expires": expiry_time.isoformat()
        }
        
        # 添加到待检查过期的房间列表
        self.expiring_rooms[room_id] = expiry_time
        return True

    async def register(self, websocket, username):
        self.clients[websocket] = username
        logging.info(f"{username} 加入了聊天室")
        await self.add_user(username)
        await self.broadcast({
            "type": "user_list",
            "users": self.user_order,
            "owner": self.owner
        })
        await self.send_room_info(websocket)
        # 发送API版本信息
        await websocket.send(json.dumps({
            "type": "api_version",
            "version": API_VERSION
        }))

    async def unregister(self, websocket):
        username = self.clients.pop(websocket, None)
        if username and username in self.user_order:
            self.user_order.remove(username)
            logging.info(f"{username} 退出了聊天室")
            await self.broadcast({
                "type": "user_list",
                "users": self.user_order
            })

    async def broadcast(self, message, room_id=None):
        disconnected = []
        targets = []
        
        if room_id:
            # 发送给指定房间成员
            if room_id in self.rooms:
                targets = [ws for ws, name in self.clients.items() 
                          if name in self.rooms[room_id]["members"]]
        else:
            # 发送给所有连接
            targets = list(self.clients.keys())
        
        for ws in targets:
            try:
                await ws.send(json.dumps(message))
            except websockets.ConnectionClosed:
                disconnected.append(ws)
        
        for ws in disconnected:
            await self.unregister(ws)

    async def send_room_info(self, websocket):
        if websocket in self.clients:
            username = self.clients[websocket]
            current_room = self.user_rooms.get(username, "global")
            await websocket.send(json.dumps({
                "type": "room_info",
                "current_room": current_room,
                "room_name": self.rooms[current_room]["name"],
                "rooms": {k: v["name"] for k, v in self.rooms.items()}
            }))

    async def check_room_expiry(self):
        """定期检查房间是否过期"""
        while True:
            current_time = datetime.now()
            
            # 检查是否有房间需要发送即将过期通知 (10分钟前)
            for room_id, expiry_time in list(self.expiring_rooms.items()):
                time_diff = (expiry_time - current_time).total_seconds()
                if 0 < time_diff <= 600:  # 10分钟内过期
                    # 发送即将过期通知
                    await self.broadcast({
                        "type": "system_message",
                        "content": f"房间 {self.rooms[room_id]['name']} 将在10分钟后删除",
                        "timestamp": current_time.isoformat()
                    }, room_id)
                    # 从待通知列表中移除
                    del self.expiring_rooms[room_id]
            
            # 检查是否有房间已过期需要删除
            for room_id, room_info in list(self.rooms.items()):
                if room_id != "global" and "expires" in room_info:
                    if datetime.fromisoformat(room_info["expires"]) <= current_time:
                        # 发送房间删除通知
                        await self.broadcast({
                            "type": "system_message",
                            "content": f"房间 {room_info['name']} 已过期并被删除",
                            "timestamp": current_time.isoformat()
                        }, room_id)
                        # 将房间成员移至全局聊天室
                        for username in list(room_info["members"]):
                            await self.join_room(username, "global")
                            # 通知用户房间已变更
                            for ws, name in self.clients.items():
                                if name == username:
                                    await self.send_room_info(ws)
                                    break
                        # 删除房间
                        del self.rooms[room_id]
            
            await asyncio.sleep(60)  # 每分钟检查一次

    async def handle_client(self, websocket, path=None):
        try:
            async for raw in websocket:
                data = json.loads(raw)
                username = self.clients.get(websocket)
                
                # 检查是否是房主验证
                if data["type"] == "verify_owner":
                    password = data["password"]
                    is_hashed = data.get("is_hashed", False)
                    
                    if is_hashed:
                        # 如果是已哈希的密码，直接比较
                        if password == self.owner_password:
                            self.owner = data["username"]
                            await websocket.send(json.dumps({
                                "type": "owner_verified",
                                "success": True
                            }))
                            await self.broadcast({
                                "type": "owner_changed",
                                "owner": self.owner
                            })
                        else:
                            await websocket.send(json.dumps({
                                "type": "owner_verified",
                                "success": False
                            }))
                    else:
                        # 否则对密码进行哈希后再比较
                        hashed_password = hashlib.sha256(password.encode()).hexdigest()
                        if hashed_password == self.owner_password:
                            self.owner = data["username"]
                            await websocket.send(json.dumps({
                                "type": "owner_verified",
                                "success": True
                            }))
                            await self.broadcast({
                                "type": "owner_changed",
                                "owner": self.owner
                            })
                        else:
                            await websocket.send(json.dumps({
                            "success": False,
                            "message": "密码错误"
                        }))
                    continue
                
                if data["type"] == "register":
                    await self.register(websocket, data["username"])
                elif data["type"] == "message":
                    # 检查是否被禁言
                    if username in self.muted_users:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "您已被禁言，无法发送消息"
                        }))
                        continue
                    
                    # 检查屏蔽词
                    content = data["content"]
                    contains_banned_word = False
                    for word in self.banned_words:
                        if re.search(word, content, re.IGNORECASE):
                            contains_banned_word = True
                            break
                    
                    if contains_banned_word:
                        await websocket.send(json.dumps({
                            "type": "banned_word",
                            "message": "您输入的内容含有屏蔽词，请重新输入"
                        }))
                        continue
                    
                    room_id = self.user_rooms.get(username, "global")
                    await self.broadcast({
                        "type": "message",
                        "username": username,
                        "content": content,
                        "timestamp": datetime.now().isoformat(),
                        "room": room_id,
                        "is_owner": username == self.owner
                    }, room_id)
                elif data["type"] == "private_message":
                    # 检查是否被禁言
                    if username in self.muted_users:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "您已被禁言，无法发送消息"
                        }))
                        continue
                    
                    target = data["target"]
                    sender = username
                    content = data["content"]
                    
                    # 检查屏蔽词
                    contains_banned_word = False
                    for word in self.banned_words:
                        if re.search(word, content, re.IGNORECASE):
                            contains_banned_word = True
                            break
                    
                    if contains_banned_word:
                        await websocket.send(json.dumps({
                            "type": "banned_word",
                            "message": "您输入的内容含有屏蔽词，请重新输入"
                        }))
                        continue
                    
                    for ws, name in self.clients.items():
                        if name == target:
                            await ws.send(json.dumps({
                                "type": "private_message",
                                "from": sender,
                                "content": content,
                                "timestamp": datetime.now().isoformat(),
                                "room": self.user_rooms.get(sender, "global")
                            }))
                            await websocket.send(json.dumps({
                                "type": "private_message_sent",
                                "to": target,
                                "content": content,
                                "timestamp": datetime.now().isoformat()
                            }))
                            break
                elif data["type"] == "get_users":
                    await websocket.send(json.dumps({
                        "type": "user_list",
                        "users": list(self.clients.values())
                    }))
                elif data["type"] == "create_room":
                    username = self.clients[websocket]
                    room_id = data.get("room_id")
                    room_name = data.get("room_name", f"{username}的房间")
                    if self.create_room(room_id, room_name):
                        await self.join_room(username, room_id)
                        await self.send_room_info(websocket)
                        await self.broadcast({
                            "type": "system_message",
                            "content": f"{username} 创建了房间 {room_name}",
                            "timestamp": datetime.now().isoformat()
                        })
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "房间已存在"
                        }))
                elif data["type"] == "join_room":
                    username = self.clients[websocket]
                    room_id = data.get("room_id")
                    if await self.join_room(username, room_id):
                        await self.send_room_info(websocket)
                        await self.broadcast({
                            "type": "system_message",
                            "content": f"{username} 加入了房间 {self.rooms[room_id]['name']}",
                            "timestamp": datetime.now().isoformat()
                        }, room_id)
                    else:
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "房间不存在"
                        }))
                elif data["type"] == "file_upload":
                    username = self.clients[websocket]
                    room_id = self.user_rooms.get(username, "global")
                    await self.handle_file(data, websocket, room_id)
                # 房主特有功能
                elif data["type"] == "kick_user" and username == self.owner:
                    target = data["target"]
                    # 找到目标用户的websocket连接
                    target_ws = None
                    for ws, name in self.clients.items():
                        if name == target:
                            target_ws = ws
                            break
                    
                    if target_ws:
                        await target_ws.send(json.dumps({
                            "type": "kicked",
                            "message": "您被房主踢出聊天室"
                        }))
                        await self.unregister(target_ws)
                        # 添加到被踢出列表
                        self.kicked_users.append({
                            "username": target,
                            "kicked_by": username,
                            "timestamp": datetime.now().isoformat(),
                            "reason": "被房主踢出聊天室"
                        })
                        
                        await self.broadcast({
                            "type": "system_message",
                            "content": f"{target} 被房主踢出聊天室",
                            "timestamp": datetime.now().isoformat()
                        })
                
                elif data["type"] == "mute_user" and username == self.owner:
                    target = data["target"]
                    self.muted_users.add(target)
                    await self.broadcast({
                        "type": "system_message",
                        "content": f"{target} 被房主禁言",
                        "timestamp": datetime.now().isoformat()
                    })
                
                elif data["type"] == "unmute_user" and username == self.owner:
                    target = data["target"]
                    if target in self.muted_users:
                        self.muted_users.remove(target)
                        await self.broadcast({
                            "type": "system_message",
                            "content": f"{target} 的禁言已被解除",
                            "timestamp": datetime.now().isoformat()
                        })
                
                elif data["type"] == "add_banned_word" and username == self.owner:
                    word = data["word"]
                    if word not in self.banned_words:
                        self.banned_words.append(word)
                        await websocket.send(json.dumps({
                            "type": "banned_word_updated",
                            "success": True,
                            "message": f"屏蔽词 '{word}' 已添加"
                        }))
                
                elif data["type"] == "remove_banned_word" and username == self.owner:
                    word = data["word"]
                    if word in self.banned_words:
                        self.banned_words.remove(word)
                        await websocket.send(json.dumps({
                            "type": "banned_word_updated",
                            "success": True,
                            "message": f"屏蔽词 '{word}' 已移除"
                        }))
                
                elif data["type"] == "owner_broadcast" and username == self.owner:
                    content = data["content"]
                    await self.broadcast({
                        "type": "owner_broadcast",
                        "content": content,
                        "timestamp": datetime.now().isoformat()
                    })
                
                elif data["type"] == "get_banned_words" and username == self.owner:
                    # 房主获取屏蔽词列表
                    await websocket.send(json.dumps({
                        "type": "banned_words_list",
                        "words": self.banned_words
                    }))
                elif data["type"] == "get_muted_users" and username == self.owner:
                    # 房主获取被禁言用户列表
                    await websocket.send(json.dumps({
                        "type": "muted_users_list",
                        "users": list(self.muted_users)
                    }))
                elif data["type"] == "get_kicked_users" and username == self.owner:
                    # 房主获取被踢出用户列表
                    await websocket.send(json.dumps({
                        "type": "kicked_users_list",
                        "users": self.kicked_users
                    }))
                elif data["type"] == "close_room" and username == self.owner:
                    # 房主关闭房间
                    room_id = data.get("room_id")
                    if room_id and room_id != "global" and room_id in self.rooms:
                        # 发送房间关闭通知
                        await self.broadcast({
                            "type": "system_message",
                            "content": f"房间 {self.rooms[room_id]['name']} 已被房主关闭",
                            "timestamp": datetime.now().isoformat()
                        }, room_id)
                        # 将房间成员移至全局聊天室
                        for user_name in list(self.rooms[room_id]["members"]):
                            await self.join_room(user_name, "global")
                            # 通知用户房间已变更
                            for ws, name in self.clients.items():
                                if name == user_name:
                                    await self.send_room_info(ws)
                                    break
                        # 删除房间
                        del self.rooms[room_id]
                        # 如果房间在过期检查列表中，也删除
                        if room_id in self.expiring_rooms:
                            del self.expiring_rooms[room_id]
                
                elif data["type"] == "set_preference":
                    if username not in self.user_prefs:
                        self.user_prefs[username] = {}
                    self.user_prefs[username].update(data)
        except websockets.ConnectionClosed:
            pass
        except json.decoder.JSONDecodeError:
            logging.INFO(self, "JSON解析错误", "输入不能为空")
        finally:
            # 如果离开的用户是房主，清空房主状态
            if websocket in self.clients and self.clients[websocket] == self.owner:
                self.owner = None
                await self.broadcast({
                    "type": "owner_changed",
                    "owner": None
                })
            await self.unregister(websocket)

    async def handle_file(self, data, websocket, room_id):
        try:
            username = self.clients[websocket]
            filename = data["filename"]
            content = data["content"]
            recv_dir = Path("recvfiles")
            recv_dir.mkdir(exist_ok=True)
            file_path = recv_dir / filename
            with open(file_path, "wb") as f:
                f.write(bytes.fromhex(content))
            
            # 只发送给设置了接收文件的用户
            targets = []
            for ws, name in self.clients.items():
                if name in self.rooms[room_id]["members"] and self.user_prefs.get(name, {}).get('receive_files', True):
                    targets.append(ws)
            
            for ws in targets:
                try:
                    await ws.send(json.dumps({
                        "type": "file_shared",
                        "username": username,
                        "filename": filename,
                        "size": len(content) // 2,
                        "timestamp": datetime.now().isoformat(),
                        "room": room_id
                    }))
                except websockets.ConnectionClosed:
                    await self.unregister(ws)
            await websocket.send(json.dumps({"type": "file_progress", "progress": 100}))
        except Exception as e:
            await websocket.send(json.dumps({"type": "file_error", "message": str(e)}))

    async def run(self):
        logging.info(f"TouchMouse V2.0 Beta 服务器监听 {self.host}:{self.port}")
        # 启动房间过期检查任务
        self.expiry_task = asyncio.create_task(self.check_room_expiry())
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()
            # 取消过期检查任务
            if self.expiry_task and not self.expiry_task.done():
                self.expiry_task.cancel()
                try:
                    await self.expiry_task
                except asyncio.CancelledError:
                    pass

if __name__ == "__main__":
    config = load_config()
    if config is None:
        exit(1)
    host, port, owner_password = config
    try:
        asyncio.run(ChatServer(host, port, owner_password).run())
    except OSError as e:
        logging.error(f"端口已被占用,将自动退出...")
        exit(1)
    except Exception as e:
        logging.error(f"未知错误导致服务器启动失败: {e}")
        exit(1)
