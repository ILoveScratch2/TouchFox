# region COPYRIGHT

# Copyright © 2025 [MinerMouse]
# Luogu UID:1203704
# 本软件著作权归作者所有，代发布者仅协助发布，除经过授权，不享有任何著作权。

# endregion

# client.py

import sys, os, json, asyncio, websockets, threading, queue, datetime, re, logging
from pathlib import Path
from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QThread, Signal, QEvent
from PySide6.QtGui import QFont, QIntValidator
import markdown
from qt_material import apply_stylesheet, list_themes
import configparser

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
        self.setWindowTitle(f"TouchMouse V1.0 - {name}")
        self.resize(800, 600)

        central = QWidget()
        lay = QVBoxLayout(central)

        # 上：左侧在线列表 + 右侧聊天
        top = QHBoxLayout()
        self.user_list = QListWidget()
        self.user_list.addItem("在线用户")
        self.user_list.setFixedWidth(180)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        top.addWidget(self.user_list)
        top.addWidget(self.chat, 1)
        lay.addLayout(top, 1)

        # 下：输入 + 按钮 + 进度
        self.input = QTextEdit()
        self.input.setMaximumHeight(80)
        self.input.textChanged.connect(self.update_preview)

        self.preview = QTextEdit()
        self.preview.setMaximumHeight(100)
        self.preview.setReadOnly(True)
        self.preview.setVisible(False)

        btn_lay = QHBoxLayout()
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self.send_msg)
        self.preview_btn = QPushButton("预览")
        self.preview_btn.clicked.connect(self.toggle_preview)
        self.file_btn = QPushButton("发送文件")
        self.file_btn.clicked.connect(self.upload_file)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        btn_lay.addWidget(self.input)
        btn_lay.addWidget(self.send_btn)
        btn_lay.addWidget(self.preview_btn)
        btn_lay.addWidget(self.file_btn)

        lay.addWidget(self.preview)
        lay.addLayout(btn_lay)
        lay.addWidget(self.progress)

        self.setCentralWidget(central)

        # WebSocket
        self.ws = WS(url, name)
        self.ws.msg.connect(self.handle)
        self.ws.error.connect(self.on_error)
        self.ws.start()
        menubar = self.menuBar()

        theme_menu = menubar.addMenu("主题")
        for t in list_themes():
            theme_menu.addAction(t, lambda t=t: apply_stylesheet(QApplication.instance(), t))

        menubar.addAction("字体", self.change_font)

        menubar.addAction("关于", self.show_about)

        export_menu = menubar.addMenu("导出")
        export_menu.addAction("导出 TXT", lambda: self.export_chat("txt"))
        export_menu.addAction("导出 MD", lambda: self.export_chat("md"))
        export_menu.addAction("导出 HTML", lambda: self.export_chat("html"))

    # ---------- 消息 ----------
    def handle(self, data):
        t = data.get('type')
        if t == 'user_list':
            self.user_list.clear()
            self.user_list.addItem("在线用户")
            for user in data['users']:
                self.user_list.addItem(user)
        elif t == 'message':
            self.add(data['username'], data['content'], data['timestamp'])
        elif t == 'user_joined':
            self.add_sys(f"{data['username']} 加入了聊天")
            self.user_list.addItem(data['username'])
        elif t == 'user_left':
            self.add_sys(f"{data['username']} 加入了聊天")
            items = self.user_list.findItems(data['username'], Qt.MatchExactly)
            for item in items:
                self.user_list.takeItem(self.user_list.row(item))
        elif t == 'private_message':
            self.add_priv(data['from'] + " → 我", data['content'], data['timestamp'])
        elif t == 'private_message_sent':
            self.add_priv("我 → " + data['to'], data['content'], data['timestamp'])
        elif t == 'file_shared':
            self.add_sys(f"{data['username']} 分享了文件 {data['filename']}")
        elif t == 'file_progress':
            self.progress.setValue(data['progress'])
            self.progress.setVisible(data['progress'] < 100)
        elif t == 'file_error':
            QMessageBox.warning(self, "文件错误", data['message'])
            self.progress.setVisible(False)

    def on_error(self, msg):
        QMessageBox.warning(self, "连接失败", f"无法连接到服务器：{msg}")
        self.close()

    # ---------- 渲染 ----------
    def add(self, user, content, ts):
        dt = datetime.datetime.fromisoformat(ts).strftime('%H:%M')
        html = markdown.markdown(content, extensions=['nl2br'])
        self.chat.append(f'<div><b>[{dt}] {user}</b><br>{html}</div>')

    def add_sys(self, txt):
        self.chat.append(f'<div style="color:#757575;text-align:center;">{txt}</div>')

    def add_priv(self, title, content, ts):
        dt = datetime.datetime.fromisoformat(ts).strftime('%H:%M')
        html = markdown.markdown(content, extensions=['nl2br'])
        self.chat.append(f'<div style="color:#ff7043;"><b>[私聊] {title}</b><br>{html}</div>')

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
                          "TouchMouse Version 1.0\n"
                          "Made by minermouse\n"
                          "联系邮箱: mouse_m@qq.com")

    def send_msg(self):
        txt = self.input.toPlainText().strip()
        if not txt: return
        m = re.match(r'^@(\S+)\s+(.+)', txt)
        self.ws.send('private_message' if m else 'message',
                     {'target': m.group(1), 'content': m.group(2)} if m else {'content': txt})
        self.input.clear()

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if not path or os.path.getsize(path) > 100 * 1024 * 1024:
            QMessageBox.warning(self, "文件过大", "不能超过 100 MB")
            return
        self.progress.setVisible(True)
        self.progress.setValue(0)

        def run():
            try:
                with open(path, 'rb') as f:
                    content = f.read().hex()
                self.ws.send('file_upload', {'filename': os.path.basename(path), 'content': content})
            except Exception as e:
                QMessageBox.warning(self, "上传失败", str(e))
                self.progress.setVisible(False)
        threading.Thread(target=run, daemon=True).start()

    def closeEvent(self, e):
        if QMessageBox.question(self, "退出", "确认退出？") == QMessageBox.Yes:
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
