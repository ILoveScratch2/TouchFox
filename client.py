# region COPYRIGHT

# Copyright © 2025 [MinerMouse]
# Luogu UID:1203704
# Portions Copyright © 2025 ILoveScratch2

# endregion

# client.py

import sys, os, json, asyncio, websockets, threading, queue, datetime, re, logging
from pathlib import Path
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QThread, Signal, QEvent
from PySide6.QtGui import QFont, QIntValidator, QAction, QColor
import markdown
from qt_material import apply_stylesheet, list_themes
import configparser
import hashlib

# 版本定义
APP_VERSION = "3.0.1"

# 全局常量
OWNER_COLOR = QColor(Qt.white)  # 房主名字颜色
DEFAULT_TEXT_COLOR = QColor(0xE0, 0xE0, 0xE0)  # 亮灰色文本 (默认暗主题)
LIGHT_TEXT_COLOR = QColor(0x33, 0x33, 0x33)  # 深灰色文本 (亮主题)

# 配置文件路径
CLIENT_CONFIG_PATH = Path(__file__).with_name("client.ini")

logging.basicConfig(level=logging.INFO)
INI_PATH = Path(__file__).with_name("server.ini")

class WS(QThread):
    msg = Signal(dict)
    error = Signal(str)

    def __init__(self, url, name):
        super().__init__()
        self.url, self.name, self.q, self.running = url, name, queue.Queue(), True

    def send(self, t, d): self.q.put((t, d))

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._go())
        except Exception as e:
            self.error.emit(str(e))

    async def _go(self):
        uri = f"ws://{self.url}"
        async with websockets.connect(uri, ping_interval=20) as ws:
            await ws.send(json.dumps({"type": "register", "username": self.name}))
            threading.Thread(target=self._sender, args=(ws,), daemon=True).start()
            async for m in ws:
                self.msg.emit(json.loads(m))

    def _sender(self, ws):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while self.running:
            try:
                t, d = self.q.get(timeout=0.1)
                loop.run_until_complete(ws.send(json.dumps({"type": t, **d})))
            except queue.Empty:
                pass


class ChatWindow(QMainWindow):
    def __init__(self, name, url):
        super().__init__()
        self.name, self.url = name, url
        self.current_room = "global"
        self.room_list = {}
        self.setWindowTitle(f"TouchFox Version {APP_VERSION} {name}")
        self.resize(800, 600)

        central = QWidget()
        lay = QVBoxLayout(central)

        # 上：左侧在线列表 + 中间聊天 + 右侧房间
        top = QHBoxLayout()
        
        # 左侧：用户列表 + 系统消息区域
        left = QVBoxLayout()
        self.user_list = QListWidget()
        self.user_list.addItem("在线用户")
        self.user_list.setFixedWidth(150)
        self.user_list.itemDoubleClicked.connect(self.on_user_double_click)
        left.addWidget(self.user_list)
        
        # 中间：聊天区域
        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        
        # 右侧布局
        right = QVBoxLayout()
        self.room_info = QLabel("当前房间: 全局聊天室")
        self.room_info.setWordWrap(True)  # 允许自动换行
        self.room_info.setMinimumHeight(40)  # 为多行文本预留空间
        
        # 按钮表格布局
        btn_grid = QGridLayout()
        btn_grid.setSpacing(8)
        
        # 房间管理按钮 - 移到右侧
        self.create_room_btn = QPushButton("创建房间")
        self.create_room_btn.clicked.connect(self.show_create_room_dialog)
        self.join_room_btn = QPushButton("加入房间")
        self.join_room_btn.clicked.connect(self.show_join_room_dialog)
        
        # 操作按钮
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_msg)
        self.preview_btn = QPushButton("预览")
        self.preview_btn.clicked.connect(self.toggle_preview)
        self.file_btn = QPushButton("发送文件")
        self.file_btn.clicked.connect(self.upload_file)
        
        # 第一行
        btn_grid.addWidget(self.create_room_btn, 0, 0)
        btn_grid.addWidget(self.join_room_btn, 0, 1)
        
        # 第二行
        btn_grid.addWidget(self.send_btn, 1, 0)
        btn_grid.addWidget(self.preview_btn, 1, 1)
        
        # 第三行
        btn_grid.addWidget(self.file_btn, 2, 0, 1, 2)  # 跨两列
        
        right.addWidget(self.room_info)
        right.addLayout(btn_grid)
        right.setContentsMargins(10, 10, 10, 10)
        
        # 使用QSplitter实现边栏(hhh)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(12)
        splitter.setOpaqueResize(True)
        splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #666;
                border-radius: 4px;
                margin: 0 2px;
                height: 95%;
            }
            QSplitter::handle:hover {
                background-color: #888;
            }
        """)
        
        # 左侧：用户列表
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(200)
        
        # 中间：聊天区域
        chat_widget = QWidget()
        chat_layout = QVBoxLayout()
        chat_layout.addWidget(self.chat)
        chat_widget.setLayout(chat_layout)
        
        # 右侧：按钮区域
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setMaximumWidth(200)
        
        splitter.addWidget(left_widget)
        splitter.addWidget(chat_widget)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(1, 1)  # 聊天区域可拉伸
        
        lay.addWidget(splitter)

        # 下：输入 + 进度
        self.input = QTextEdit()
        self.input.setMaximumHeight(80)
        self.input.textChanged.connect(self.update_preview)

        self.preview = QTextEdit()
        self.preview.setMaximumHeight(100)
        self.preview.setReadOnly(True)
        self.preview.setVisible(False)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        
        lay.addWidget(self.preview)
        lay.addWidget(self.input)
        lay.addWidget(self.progress)

        self.setCentralWidget(central)

        # 房主状态
        self.is_owner = False
        self.banned_words = []
        self.saved_hashed_password = self.load_saved_password()
        
        # 存储被禁言和踢出的用户列表
        self.muted_users_list = []
        self.kicked_users_list = []
        
        # 主题状态跟踪
        self.is_dark_theme = True  # 默认使用暗色主题
        self.current_text_color = DEFAULT_TEXT_COLOR
        self.current_theme = 'dark_teal.xml'  # 初始主题，与main函数中的设置保持一致

        # WebSocket
        self.ws = WS(url, name)
        self.ws.msg.connect(self.handle)
        self.ws.error.connect(self.on_error)
        self.ws.start()
        menubar = self.menuBar()

        # 如果有保存的密码，显示一个对话框询问用户是否自动登录
        if self.saved_hashed_password:
            reply = QMessageBox.question(self, "自动验证房主身份", 
                                         "检测到保存的房主密码，是否自动验证房主身份？",
                                         QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                # 使用保存的哈希密码进行自动验证
                self.auto_verify_owner()

        # 房主菜单
        owner_menu = menubar.addMenu("房主功能")
        self.verify_owner_action = QAction("验证房主身份", self)
        self.verify_owner_action.triggered.connect(self.verify_owner)
        owner_menu.addAction(self.verify_owner_action)

        self.kick_user_action = QAction("踢人", self)
        self.kick_user_action.triggered.connect(self.kick_user)
        self.kick_user_action.setEnabled(False)
        owner_menu.addAction(self.kick_user_action)

        self.mute_user_action = QAction("禁言", self)
        self.mute_user_action.triggered.connect(self.mute_user)
        self.mute_user_action.setEnabled(False)
        owner_menu.addAction(self.mute_user_action)

        self.unmute_user_action = QAction("解除禁言", self)
        self.unmute_user_action.triggered.connect(self.unmute_user)
        self.unmute_user_action.setEnabled(False)
        owner_menu.addAction(self.unmute_user_action)

        self.banned_words_action = QAction("屏蔽词管理", self)
        self.banned_words_action.triggered.connect(self.manage_banned_words)
        self.banned_words_action.setEnabled(False)
        owner_menu.addAction(self.banned_words_action)

        self.broadcast_action = QAction("房主广播", self)
        self.broadcast_action.triggered.connect(self.owner_broadcast)
        self.broadcast_action.setEnabled(False)
        owner_menu.addAction(self.broadcast_action)
        
        # 添加分隔线
        owner_menu.addSeparator()
        
        # 显示被禁言用户列表
        self.show_muted_action = QAction("显示被禁言用户", self)
        self.show_muted_action.triggered.connect(self.show_muted_users)
        self.show_muted_action.setEnabled(False)
        owner_menu.addAction(self.show_muted_action)
        
        # 显示被踢出用户列表
        self.show_kicked_action = QAction("显示被踢出用户", self)
        self.show_kicked_action.triggered.connect(self.show_kicked_users)
        self.show_kicked_action.setEnabled(False)
        owner_menu.addAction(self.show_kicked_action)

        # 添加分隔线
        owner_menu.addSeparator()
        
        # 关闭房间
        self.close_room_action = QAction("关闭房间", self)
        self.close_room_action.triggered.connect(self.close_room)
        self.close_room_action.setEnabled(False)
        owner_menu.addAction(self.close_room_action)

        theme_menu = menubar.addMenu("主题")
        for t in list_themes():
            theme_menu.addAction(t, lambda t=t: self.set_theme(t))
            
        # 设置菜单
        settings_menu = menubar.addMenu("设置")
        self.receive_files_action = QAction("接收文件", self, checkable=True)
        self.receive_files_action.setChecked(True)
        self.receive_files_action.triggered.connect(self.toggle_receive_files)
        settings_menu.addAction(self.receive_files_action)
        
        # 窗口置顶选项
        self.stay_on_top_action = QAction("窗口置顶", self, checkable=True)
        self.stay_on_top_action.setChecked(False)
        self.stay_on_top_action.triggered.connect(self.toggle_stay_on_top)
        settings_menu.addAction(self.stay_on_top_action)
        
        menubar.addAction("字体", self.change_font)
        menubar.addAction("关于", self.show_about)

        export_menu = menubar.addMenu("导出")
        export_menu.addAction("导出 TXT", lambda: self.export_chat("txt"))
        export_menu.addAction("导出 MD", lambda: self.export_chat("md"))
        export_menu.addAction("导出 HTML", lambda: self.export_chat("html"))
    
    def set_theme(self, theme):
        apply_stylesheet(QApplication.instance(), theme)
        self.current_theme = theme
        # 更新主题类型状态
        self.update_theme_type(theme)
        # 通知所有消息渲染方法更新颜色
        
    def update_theme_type(self, theme):
        # 判断是否为亮色主题（通常包含light关键词）
        self.is_dark_theme = "light" not in theme.lower()
        # 更新文本颜色
        self.current_text_color = DEFAULT_TEXT_COLOR if self.is_dark_theme else LIGHT_TEXT_COLOR

    # ---------- 消息 ----------
    def on_user_double_click(self, item):
        if item.text() != "在线用户":
            current_text = self.input.toPlainText()
            if not current_text.startswith("@"):
                self.input.setPlainText(f"@{item.text()} ")
                self.input.setFocus()

    def load_saved_password(self):
        """从配置文件加载保存的加密密码"""
        if not CLIENT_CONFIG_PATH.exists():
            return None
        
        try:
            cfg = configparser.ConfigParser()
            cfg.read(CLIENT_CONFIG_PATH, encoding="utf-8")
            if "OWNER" in cfg and "hashed_password" in cfg["OWNER"]:
                return cfg["OWNER"]["hashed_password"]
        except Exception as e:
            logging.error(f"加载保存的密码失败: {e}")
        return None
    
    def save_password(self, password):
        """将加密后的密码保存到配置文件"""
        try:
            cfg = configparser.ConfigParser()
            if CLIENT_CONFIG_PATH.exists():
                cfg.read(CLIENT_CONFIG_PATH, encoding="utf-8")
            
            # 创建OWNER部分（如果不存在）
            if "OWNER" not in cfg:
                cfg["OWNER"] = {}
            
            # 加密并保存密码
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            cfg["OWNER"]["hashed_password"] = hashed_password
            
            # 写入配置文件
            with open(CLIENT_CONFIG_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception as e:
            logging.error(f"保存密码失败: {e}")
    
    def clear_saved_password(self):
        """清除保存的密码"""
        try:
            if CLIENT_CONFIG_PATH.exists():
                cfg = configparser.ConfigParser()
                cfg.read(CLIENT_CONFIG_PATH, encoding="utf-8")
                if "OWNER" in cfg:
                    del cfg["OWNER"]
                    with open(CLIENT_CONFIG_PATH, "w", encoding="utf-8") as f:
                        cfg.write(f)
                # 同时更新内存中的保存密码
                self.saved_hashed_password = None
        except Exception as e:
            logging.error(f"清除保存的密码失败: {e}")
    
    def auto_verify_owner(self):
        """使用保存的哈希密码自动验证房主身份"""
        if self.saved_hashed_password:
            self.ws.send('verify_owner', {
                'username': self.name,
                'password': self.saved_hashed_password,
                'is_hashed': True
            })
    
    def verify_owner(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("房主验证")
        lay = QFormLayout(dlg)
        
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.Password)
        lay.addRow("房主密码:", password_input)
        
        # 添加记住密码选项
        remember_password = QCheckBox("记住密码")
        lay.addRow(remember_password)
        
        btn = QPushButton("验证")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        
        if dlg.exec():
            password = password_input.text()
            
            # 如果用户选择记住密码，则保存加密后的密码
            if remember_password.isChecked():
                self.save_password(password)
            else:
                # 否则清除之前保存的密码（如果有）
                self.clear_saved_password()
            
            self.ws.send('verify_owner', {
                'username': self.name,
                'password': password
            })

    def handle(self, data):
        t = data.get('type')
        if t == 'user_list':
            self.user_list.clear()
            self.user_list.addItem("在线用户")
            owner = data.get('owner')
            for user in data['users']:
                item = QListWidgetItem(user)
                if user == owner:
                    # 房主名字颜色为白色
                    item.setForeground(QColor(Qt.white))
                self.user_list.addItem(item)
        elif t == 'kicked':
            QMessageBox.warning(self, "被踢出", data.get('message', "您被房主踢出聊天室"))
            self.close()
        elif t == 'error':
            QMessageBox.warning(self, "错误", data.get('message', "发生错误"))
        elif t == 'owner_verified':
            if data['success']:
                QMessageBox.information(self, "验证成功", "房主身份验证成功")
                self.is_owner = True
                # 启用房主功能
                self.kick_user_action.setEnabled(True)
                self.mute_user_action.setEnabled(True)
                self.unmute_user_action.setEnabled(True)
                self.banned_words_action.setEnabled(True)
                self.broadcast_action.setEnabled(True)
                self.show_muted_action.setEnabled(True)
                self.show_kicked_action.setEnabled(True)
                self.close_room_action.setEnabled(True)
                # 获取当前屏蔽词列表、被禁言用户和被踢出用户列表
                self.ws.send('get_banned_words', {})
                self.ws.send('get_muted_users', {})
                self.ws.send('get_kicked_users', {})
            else:
                QMessageBox.warning(self, "验证失败", data.get('message', "密码错误"))
        elif t == 'owner_changed':
            owner = data.get('owner')
            self.is_owner = (owner == self.name)
            # 更新房主功能菜单状态
            enabled = self.is_owner
            self.kick_user_action.setEnabled(enabled)
            self.mute_user_action.setEnabled(enabled)
            self.unmute_user_action.setEnabled(enabled)
            self.banned_words_action.setEnabled(enabled)
            self.broadcast_action.setEnabled(enabled)
            self.show_muted_action.setEnabled(enabled)
            self.show_kicked_action.setEnabled(enabled)
            self.close_room_action.setEnabled(enabled)
            # 显示系统消息
            if owner:
                self.add_sys(f"{owner} 成为了房主")
            else:
                self.add_sys("当前没有房主")
        elif t == 'banned_words_list':
            self.banned_words = data.get('words', [])
        elif t == 'muted_users_list':
            self.muted_users_list = data.get('users', [])
        elif t == 'kicked_users_list':
            # 从服务器获取的是包含详细信息的列表，但我们只需要用户名
            self.kicked_users_list = [user['username'] for user in data.get('users', [])]
        elif t == 'banned_word':
            QMessageBox.warning(self, "包含屏蔽词", data.get('message', "您输入的内容含有屏蔽词，请重新输入"))
        elif t == 'room_info':
            try:
                if not all(key in data for key in ['current_room', 'rooms', 'room_name']):
                    raise ValueError("缺少必要的房间信息字段")
                
                self.current_room = data['current_room']
                self.room_list = data['rooms']
                room_name = data['room_name']
                self.room_info.setText(f"当前房间: {room_name} (ID: {self.current_room})")
                
                # 不再显示房间成员列表
                
                # 清空聊天框并显示系统消息
                self.chat.clear()
                self.add_sys(f"已切换到房间: {room_name}")
                
            except Exception as e:
                self.add_sys(f"房间切换失败: {str(e)}")
                logging.error(f"处理room_info失败: {e}")
        elif t == 'message':
            if 'room' in data and data['room'] != self.current_room:
                return  # 忽略其他房间的消息
            # 传递房主状态给add方法
            is_owner = data.get('is_owner', False)
            self.add(data['username'], data['content'], data['timestamp'], is_owner)
        elif t == 'owner_broadcast':
            # 处理房主广播
            self.add_broadcast(data['content'], data['timestamp'])
        elif t == 'user_joined':
            username = data['username']
            self.add_sys(f"{username} 加入了聊天")
            # 更新在线用户列表
            self.user_list.clear()
            self.user_list.addItem("在线用户")
            for user in sorted(self.user_order + [username]):
                if user != "在线用户":
                    self.user_list.addItem(user)
            # 不再更新房间成员列表

        elif t == 'user_left':
            username = data['username']
            self.add_sys(f"{username} 离开了聊天")
            # 更新在线用户列表
            items = self.user_list.findItems(username, Qt.MatchExactly)
            for item in items:
                self.user_list.takeItem(self.user_list.row(item))
            # 不再更新房间成员列表
        elif t == 'private_message':
            room_info = f" [来自: {data.get('room', '未知房间')}]" if 'room' in data else ""
            self.add_priv(data['from'] + " → 我" + room_info, data['content'], data['timestamp'])
        elif t == 'private_message_sent':
            self.add_priv("我 → " + data['to'], data['content'], data['timestamp'])
        elif t == 'file_shared':
            if 'room' in data and data['room'] != self.current_room:
                return  # 忽略其他房间的文件
            if not self.receive_files_action.isChecked():
                logging.info(f"用户选择不接收文件: {data['filename']}")
                return  # 用户选择不接收文件
            self.add_sys(f"{data['username']} 分享了文件 {data['filename']}")
        elif t == 'file_progress':
            self.progress.setValue(data['progress'])
            self.progress.setVisible(data['progress'] < 100)
        elif t == 'file_error':
            QMessageBox.warning(self, "文件错误", data['message'])
            self.progress.setVisible(False)

    def toggle_receive_files(self, checked):
        self.ws.send('set_preference', {
            'receive_files': checked
        })
    
    def toggle_stay_on_top(self):
        # 切换窗口置顶状态
        is_stay_on_top = self.stay_on_top_action.isChecked()
        if is_stay_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
        self.show()

    def on_error(self, msg):
        QMessageBox.warning(self, "连接失败", f"无法连接到服务器：{msg}")
        self.close()

    # ---------- 渲染 ----------
    def add_sys(self, txt):
        # 改进的系统消息样式 - 移到左侧
        bubble_style = '''
            background-color: rgba(158, 158, 158, 0.15);
            border: 1px solid rgba(158, 158, 158, 0.3);
            border-radius: 18px 18px 18px 4px;
            padding: 8px 12px;
            margin: 6px auto 6px 0;
            display: inline-block;
            max-width: 60%;
            float: left;
            clear: both;
            font-style: italic;
        '''
        # 使用与当前主题协调的系统消息颜色
        sys_color = '#9E9E9E' if self.is_dark_theme else '#616161'
        self.chat.append(f'<div style="{bubble_style}"><span style="color: {sys_color};">{txt}</span></div>')

    def add(self, user, content, ts, is_owner=False):
        dt = datetime.datetime.fromisoformat(ts).strftime('%H:%M')
        
        html = markdown.markdown(content, extensions=['nl2br', 'fenced_code'])
        
        # 判断是否是自己发送的消息和是否是房主
        is_self = user == self.name
        
        if is_self:
            # 自己发送的消息 - 左侧气泡
            bubble_style = '''
                background-color: rgba(66, 133, 244, 0.25);
                border: 1px solid rgba(66, 133, 244, 0.5);
                border-radius: 18px 18px 18px 4px;
                padding: 12px 16px;
                margin: 6px auto 6px 0;
                display: inline-block;
                max-width: 70%;
                float: left;
                clear: both;
            '''
            color_style = 'font-weight: bold; color: #1565C0;'  # 深蓝色，更适合蓝色半透明背景
        else:
            # 他人发送的消息 - 左侧气泡
            bubble_style = '''
                background-color: rgba(102, 187, 106, 0.25);
                border: 1px solid rgba(102, 187, 106, 0.5);
                border-radius: 18px 18px 18px 4px;
                padding: 12px 16px;
                margin: 6px auto 6px 0;
                display: inline-block;
                max-width: 70%;
                float: left;
                clear: both;
            '''
            if is_owner:
                color_style = 'font-weight: bold; color: white;'  # 房主名字为白色
            else:
                color_style = 'font-weight: bold; color: #2E7D32;'  # 深绿色，更适合绿色半透明背景   
        # 使用当前主题对应的文本颜色
        content_color = self.get_color_hex(self.current_text_color)
        self.chat.append(f'<div style="{bubble_style}"><span style="{color_style}">[{dt}] {user}</span><br><span style="color: {content_color};">{html}</span></div>')
    
    def get_color_hex(self, qcolor):
        """将QColor对象转换为CSS十六进制颜色字符串"""
        return f'#{qcolor.red():02X}{qcolor.green():02X}{qcolor.blue():02X}'

    def add_broadcast(self, content, ts):
        dt = datetime.datetime.fromisoformat(ts).strftime('%H:%M')
        
        html = markdown.markdown(content, extensions=['nl2br', 'fenced_code'])
        
        # 房主广播样式
        bubble_style = '''
            background-color: rgba(255, 193, 7, 0.25);
            border: 1px solid rgba(255, 193, 7, 0.5);
            border-radius: 18px 18px 18px 4px;
            padding: 12px 16px;
            margin: 6px auto;
            display: inline-block;
            max-width: 70%;
            float: left;
            clear: both;
        '''
        title_style = 'font-weight: bold; color: #FFA000;'  # 橙色标题
        # 使用当前主题对应的文本颜色
        content_color = self.get_color_hex(self.current_text_color)
        self.chat.append(f'<div style="{bubble_style}"><span style="{title_style}">[{dt}] 房主广播</span><br><span style="color: {content_color};">{html}</span></div>')

    def add_priv(self, title, content, ts):
        dt = datetime.datetime.fromisoformat(ts).strftime('%H:%M')
        
        html = markdown.markdown(content, extensions=['nl2br', 'fenced_code'])
        
        # 判断是自己发送的私聊还是接收的私聊
        if title.startswith('我 →'):
            # 自己发送的私聊 - 左侧气泡
            bubble_style = '''
                background-color: rgba(255, 112, 67, 0.25);
                border: 1px solid rgba(255, 112, 67, 0.5);
                border-radius: 18px 18px 18px 4px;
                padding: 12px 16px;
                margin: 6px auto 6px 0;
                display: inline-block;
                max-width: 70%;
                float: left;
                clear: both;
            '''
            color_style = 'font-weight: bold; color: #E65100;'  # 深橙色，更适合橙色半透明背景
        else:
            # 接收的私聊 - 左侧气泡
            bubble_style = '''
                background-color: rgba(156, 39, 176, 0.25);
                border: 1px solid rgba(156, 39, 176, 0.5);
                border-radius: 18px 18px 18px 4px;
                padding: 12px 16px;
                margin: 6px auto 6px 0;
                display: inline-block;
                max-width: 70%;
                float: left;
                clear: both;
            '''
            color_style = 'font-weight: bold; color: #6A1B9A;'  # 深紫色，更适合紫色半透明背景
        
        # 使用当前主题对应的文本颜色
        content_color = self.get_color_hex(self.current_text_color)
        self.chat.append(f'<div style="{bubble_style}"><span style="{color_style}">[私聊] {title}</span><br><span style="color: {content_color};">{html}</span></div>')

    def toggle_preview(self):
        vis = not self.preview.isVisible()
        self.preview.setVisible(vis)
        self.preview_btn.setText("隐藏预览" if vis else "预览")
        self.update_preview()

    def update_preview(self):
        if self.preview.isVisible():
            self.preview.setHtml(markdown.markdown(self.input.toPlainText(), extensions=['nl2br']))

    def change_font(self):
        ok, font = QFontDialog.getFont(self.chat.font(), self)
        if ok:
            for w in (self.chat, self.input, self.preview):
                w.setFont(font)

    def show_about(self):
        QMessageBox.about(self, "关于",
                          f"TouchFox Version {APP_VERSION}\n"
                          "Made with love by ILoveScratch2\n"
                          "Email: ilovescratch@foxmail.com")

    def show_create_room_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("创建房间")
        lay = QFormLayout(dlg)
        
        room_id = QLineEdit()
        room_name = QLineEdit()
        create_btn = QPushButton("创建")
        
        lay.addRow("房间ID:", room_id)
        lay.addRow("房间名称:", room_name)
        lay.addRow(create_btn)
        
        def do_create():
            try:
                self.ws.send('create_room', {
                    'room_id': room_id.text(),
                    'room_name': room_name.text() or f"{self.name}的房间"
                })
                dlg.close()
            except:
                QMessageBox.warning(self, "错误", "创建房间失败")
        
        create_btn.clicked.connect(do_create)
        dlg.exec()

    def show_join_room_dialog(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("加入房间")
        lay = QFormLayout(dlg)
        
        room_list = QComboBox()
        for room_id, name in self.room_list.items():
            room_list.addItem(f"{name} ({room_id})", room_id)
        
        join_btn = QPushButton("加入")
        lay.addRow("选择房间:", room_list)
        lay.addRow(join_btn)
        
        def do_join():
            room_id = room_list.currentData()
            self.ws.send('join_room', {'room_id': room_id})
            dlg.close()
        
        join_btn.clicked.connect(do_join)
        dlg.exec()

    def send_msg(self):
        try:
            txt = self.input.toPlainText().strip()
            if not txt: 
                QMessageBox.warning(self, "发送失败", "消息内容不能为空")
                return
            
            # 检查是否是房间命令
            if txt.startswith("/room "):
                cmd = txt[6:].strip()
                if cmd == "list":
                    self.ws.send('get_rooms', {})
                elif cmd.startswith("join "):
                    room_id = cmd[5:].strip()
                    if not room_id:
                        QMessageBox.warning(self, "错误", "必须指定房间ID")
                        return
                    self.ws.send('join_room', {'room_id': room_id})
                elif cmd.startswith("create "):
                    parts = cmd[7:].split(maxsplit=1)
                    room_id = parts[0]
                    if not room_id:
                        QMessageBox.warning(self, "错误", "必须指定房间ID")
                        return
                    room_name = parts[1] if len(parts) > 1 else f"{self.name}的房间"
                    self.ws.send('create_room', {
                        'room_id': room_id,
                        'room_name': room_name
                    })
                return
            
            m = re.match(r'^@(\S+)\s+(.+)', txt)
            if m and not m.group(1):
                QMessageBox.warning(self, "错误", "必须指定接收者")
                return
                
            # 发送消息
            content = m.group(2) if m else txt
            msg_data = {'content': content}
                
            self.ws.send('private_message' if m else 'message',
                        {'target': m.group(1), **msg_data} if m else msg_data)
            
            self.input.clear()
            
        except Exception as e:
            QMessageBox.warning(self, "发送失败", f"发送消息时出错: {str(e)}")
            logging.error(f"发送消息失败: {e}")

    def kick_user(self):
        # 创建选择用户对话框
        dlg = QDialog(self)
        dlg.setWindowTitle("选择要踢出的用户")
        dlg.setMinimumSize(300, 400)
        
        lay = QVBoxLayout(dlg)
        
        # 在线用户列表
        lay.addWidget(QLabel("在线用户:"))
        user_list_widget = QListWidget()
        
        # 获取当前房主信息
        current_owner = None
        for i in range(1, self.user_list.count()):  # 跳过标题项
            item = self.user_list.item(i)
            # 房主名字颜色为白色
            if item.foreground() == QColor(Qt.white):
                current_owner = item.text()
                break
        
        # 填充用户列表，排除自己和其他房主
        for i in range(1, self.user_list.count()):  # 跳过标题项
            item = self.user_list.item(i)
            username = item.text()
            # 不能踢自己，也不能踢其他房主
            if username != self.name and username != current_owner:
                user_list_widget.addItem(username)
        
        lay.addWidget(user_list_widget)
        
        # 选择按钮
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("选择")
        cancel_btn = QPushButton("取消")
        
        select_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        
        btn_layout.addWidget(select_btn)
        btn_layout.addWidget(cancel_btn)
        lay.addLayout(btn_layout)
        
        # 显示对话框并获取结果
        if dlg.exec():
            selected_items = user_list_widget.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "无法踢人", "请选择一个用户")
                return
            
            username = selected_items[0].text()
            if QMessageBox.question(self, "确认踢人", f"确定要将 {username} 踢出聊天室吗？") == QMessageBox.Yes:
                self.ws.send('kick_user', {'target': username})
                # 直接添加或更新到踢出列表，不检查是否已存在
                if username in self.kicked_users_list:
                    # 如果用户已在列表中，移除后重新添加（这样可以更新顺序）
                    self.kicked_users_list.remove(username)
                self.kicked_users_list.append(username)
                # 显示系统消息
                self.add_sys(f"已将 {username} 踢出聊天室")

    def mute_user(self):
        # 创建选择用户对话框
        dlg = QDialog(self)
        dlg.setWindowTitle("选择要禁言的用户")
        dlg.setMinimumSize(300, 400)
        
        lay = QVBoxLayout(dlg)
        
        # 在线用户列表
        lay.addWidget(QLabel("在线用户:"))
        user_list_widget = QListWidget()
        
        # 获取当前房主信息
        current_owner = None
        for i in range(1, self.user_list.count()):  # 跳过标题项
            item = self.user_list.item(i)
            # 房主名字颜色为白色
            if item.foreground() == QColor(Qt.white):
                current_owner = item.text()
                break
        
        # 填充用户列表，排除自己、其他房主和已被禁言的用户
        for i in range(1, self.user_list.count()):  # 跳过标题项
            item = self.user_list.item(i)
            username = item.text()
            # 不能禁言自己，不能禁言其他房主，且排除已被禁言的用户
            if username != self.name and username != current_owner and username not in self.muted_users_list:
                user_list_widget.addItem(username)
        
        lay.addWidget(user_list_widget)
        
        # 选择按钮
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("选择")
        cancel_btn = QPushButton("取消")
        
        select_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        
        btn_layout.addWidget(select_btn)
        btn_layout.addWidget(cancel_btn)
        lay.addLayout(btn_layout)
        
        # 显示对话框并获取结果
        if dlg.exec():
            selected_items = user_list_widget.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "无法禁言", "请选择一个用户")
                return
            
            username = selected_items[0].text()
            if QMessageBox.question(self, "确认禁言", f"确定要禁言 {username} 吗？") == QMessageBox.Yes:
                self.ws.send('mute_user', {'target': username})
                # 添加到禁言列表
                if username not in self.muted_users_list:
                    self.muted_users_list.append(username)
                # 显示系统消息
                self.add_sys(f"已禁言 {username}")

    def unmute_user(self):
        # 创建选择用户对话框
        dlg = QDialog(self)
        dlg.setWindowTitle("选择要解除禁言的用户")
        dlg.setMinimumSize(300, 400)
        
        lay = QVBoxLayout(dlg)
        
        # 被禁言用户列表
        lay.addWidget(QLabel("被禁言用户:"))
        muted_list_widget = QListWidget()
        
        # 检查禁言列表是否为空
        if not self.muted_users_list:
            QMessageBox.information(self, "无法解除禁言", "当前没有被禁言的用户")
            return
            
        # 填充禁言列表
        for username in self.muted_users_list:
            muted_list_widget.addItem(username)
        
        lay.addWidget(muted_list_widget)
        
        # 选择按钮
        btn_layout = QHBoxLayout()
        select_btn = QPushButton("选择")
        cancel_btn = QPushButton("取消")
        
        select_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        
        btn_layout.addWidget(select_btn)
        btn_layout.addWidget(cancel_btn)
        lay.addLayout(btn_layout)
        
        # 显示对话框并获取结果
        if dlg.exec():
            selected_items = muted_list_widget.selectedItems()
            if not selected_items:
                QMessageBox.warning(self, "无法解除禁言", "请选择一个用户")
                return
            
            username = selected_items[0].text()
            if QMessageBox.question(self, "确认解除禁言", f"确定要解除 {username} 的禁言吗？") == QMessageBox.Yes:
                self.ws.send('unmute_user', {'target': username})
                # 从禁言列表中移除
                if username in self.muted_users_list:
                    self.muted_users_list.remove(username)
                # 显示系统消息
                self.add_sys(f"已解除 {username} 的禁言")

    def show_muted_users(self):
        # 显示被禁言用户列表
        dlg = QDialog(self)
        dlg.setWindowTitle("被禁言用户")
        dlg.setMinimumSize(300, 400)
        
        lay = QVBoxLayout(dlg)
        
        if not self.muted_users_list:
            lay.addWidget(QLabel("当前没有被禁言的用户"))
        else:
            lay.addWidget(QLabel("被禁言用户列表:"))
            list_widget = QListWidget()
            for username in self.muted_users_list:
                list_widget.addItem(username)
            lay.addWidget(list_widget)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(dlg.accept)
        lay.addWidget(ok_btn)
        
        dlg.exec()
        
    def show_kicked_users(self):
        # 显示被踢出用户列表
        dlg = QDialog(self)
        dlg.setWindowTitle("被踢出用户")
        dlg.setMinimumSize(300, 400)
        
        lay = QVBoxLayout(dlg)
        
        if not self.kicked_users_list:
            lay.addWidget(QLabel("当前没有被踢出的用户"))
        else:
            lay.addWidget(QLabel("被踢出用户列表:"))
            list_widget = QListWidget()
            for username in self.kicked_users_list:
                list_widget.addItem(username)
            lay.addWidget(list_widget)
        
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(dlg.accept)
        lay.addWidget(ok_btn)
        
        dlg.exec()
        
    def close_room(self):
        # 检查是否为全局房间
        if self.current_room == "global":
            QMessageBox.warning(self, "操作失败", "不能关闭全局房间")
            return
            
        # 显示确认对话框
        reply = QMessageBox.question(
            self, 
            "确认关闭房间", 
            f"确定要关闭房间 {self.room_list.get(self.current_room, self.current_room)} 吗？\n关闭后房间内所有成员将被移至全局聊天室。",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            # 发送关闭房间请求
            self.ws.send('close_room', {'room_id': self.current_room})
        
    def manage_banned_words(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("屏蔽词管理")
        lay = QVBoxLayout(dlg)
        
        # 屏蔽词列表
        self.banned_words_list = QListWidget()
        for word in self.banned_words:
            self.banned_words_list.addItem(word)
        lay.addWidget(self.banned_words_list)
        
        # 添加屏蔽词
        add_layout = QHBoxLayout()
        self.new_banned_word = QLineEdit()
        add_layout.addWidget(self.new_banned_word)
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self.add_banned_word)
        add_layout.addWidget(add_btn)
        lay.addLayout(add_layout)
        
        # 移除屏蔽词
        remove_btn = QPushButton("移除选中的屏蔽词")
        remove_btn.clicked.connect(self.remove_banned_word)
        lay.addWidget(remove_btn)
        
        dlg.exec()

    def add_banned_word(self):
        word = self.new_banned_word.text().strip()
        if word and word not in self.banned_words:
            self.ws.send('add_banned_word', {'word': word})
            self.banned_words.append(word)
            self.banned_words_list.addItem(word)
            self.new_banned_word.clear()
        elif not word:
            QMessageBox.warning(self, "错误", "屏蔽词不能为空")
        else:
            QMessageBox.warning(self, "错误", "该屏蔽词已存在")

    def remove_banned_word(self):
        current_item = self.banned_words_list.currentItem()
        if current_item:
            word = current_item.text()
            self.ws.send('remove_banned_word', {'word': word})
            self.banned_words.remove(word)
            self.banned_words_list.takeItem(self.banned_words_list.row(current_item))
        else:
            QMessageBox.warning(self, "错误", "请先选择要移除的屏蔽词")

    def owner_broadcast(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("房主广播")
        lay = QVBoxLayout(dlg)
        
        broadcast_input = QTextEdit()
        broadcast_input.setPlaceholderText("输入广播内容...")
        lay.addWidget(broadcast_input)
        
        send_btn = QPushButton("发送广播")
        send_btn.clicked.connect(lambda: self.send_broadcast(broadcast_input.toPlainText(), dlg))
        lay.addWidget(send_btn)
        
        dlg.exec()

    def send_broadcast(self, content, dlg):
        if content.strip():
            self.ws.send('owner_broadcast', {'content': content})
            dlg.close()
        else:
            QMessageBox.warning(self, "错误", "广播内容不能为空")

    def upload_file(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "选择文件")
            if not path:
                return
                
            file_size = os.path.getsize(path)
            if file_size > 100 * 1024 * 1024:
                QMessageBox.warning(self, "文件过大", f"文件大小 {file_size/1024/1024:.2f} MB 超过100MB限制")
                return
                
            self.progress.setVisible(True)
            self.progress.setValue(0)

            def run():
                try:
                    with open(path, 'rb') as f:
                        content = f.read().hex()
                    self.ws.send('file_upload', {
                        'filename': os.path.basename(path), 
                        'content': content,
                        'size': file_size
                    })
                except Exception as e:
                    self.progress.setVisible(False)
                    QMessageBox.warning(self, "上传失败", f"上传文件时出错: {str(e)}")
                    logging.error(f"文件上传失败: {e}")

            threading.Thread(target=run, daemon=True).start()
            
        except Exception as e:
            self.progress.setVisible(False)
            QMessageBox.warning(self, "错误", f"选择文件时出错: {str(e)}")
            logging.error(f"文件选择失败: {e}")

    def closeEvent(self, e):
        if QMessageBox.question(self, "退出", "确认退出？") == QMessageBox.Yes:
            # 先移除窗口置顶标志，确保窗口可以正常关闭
            if self.stay_on_top_action.isChecked():
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
                self.show()
            
            self.ws.running = False
            e.accept()
        else:
            e.ignore()
            
    def export_chat(self, fmt):
        file, _ = QFileDialog.getSaveFileName(self, "保存聊天记录", "", f"{fmt.upper()} (*.{fmt})")
        if not file:
            return
        try:
            text = self.chat.toPlainText() if fmt == "txt" else self.chat.toHtml()
            if fmt == "md":
                text = self.chat.toPlainText()
            with open(file, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, "导出成功", f"已保存为 {fmt.upper()}")
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))


class LoginDlg(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("登录")
        lay = QFormLayout(self)
        
        # 昵称输入
        self.name = QLineEdit()
        lay.addRow("昵称:", self.name)
        
        # 服务器配置输入
        self.host = QLineEdit()
        self.host.setPlaceholderText("Your IP")
        self.port = QLineEdit()
        self.port.setPlaceholderText("Your Port")
        self.port.setValidator(QIntValidator(1, 65535))
        
        # 尝试加载现有配置
        cfg = configparser.ConfigParser()
        cfg["SERVER"] = {"host": "localhost", "port": "8765"}
        if INI_PATH.exists():
            cfg.read(INI_PATH, encoding="utf-8")
            self.host.setText(cfg["SERVER"]["host"])
            self.port.setText(cfg["SERVER"]["port"])
        
        lay.addRow("服务器地址:", self.host)
        lay.addRow("服务器端口:", self.port)
        
        btn = QPushButton("连接")
        btn.clicked.connect(self.accept)
        lay.addWidget(btn)
        self.name.setFocus()

    def cred(self):
        host = self.host.text().strip() or "localhost"
        port = self.port.text().strip() or "8765"
        
        # 验证IP地址
        try:
            import socket
            socket.inet_aton(host)
        except socket.error:
            QMessageBox.warning(self, "无效地址", f"无效的IP地址 {host}")
            return None
        
        # 保存配置
        cfg = configparser.ConfigParser()
        cfg["SERVER"] = {"host": host, "port": port}
        try:
            with open(INI_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)
        except Exception as e:
            logging.error(f"保存配置失败: {e}")
        
        return {'name': self.name.text().strip(), 'url': f"{host}:{port}"}


if __name__ == '__main__':
    app = QApplication(sys.argv)
    apply_stylesheet(app, 'dark_teal.xml')
    dlg = LoginDlg()
    if dlg.exec():
        c = dlg.cred()
        if c:  # 只有配置有效时才继续
            w = ChatWindow(c['name'], c['url'])
            w.show()
            sys.exit(app.exec())
