#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地 AI 翻译助手 - 图形界面版（现代化）

- exe 一键启动，仅显示 GUI，无任何命令行窗口
- 启动页进度条：连接 Ollama → 部署模型 → 就绪
- 【待翻译】/【已翻译】目录分区管理，完成后自动打开已翻译目录
- 关闭时可选：挂后台运行（缩小到系统托盘）/ 直接退出
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from tkinter import filedialog, messagebox, simpledialog, ttk

import translate as T
from PIL import Image, ImageDraw
from tkinterdnd2 import DND_FILES, TkinterDnD

APP_TITLE = "本地 AI 翻译助手"
APP_TITLE_EN = "Local AI Translator"
MODEL_DEFAULT = "qwen3:0.6b"   # 发布版默认模型（内置开箱即用）
OLLAMA_EXE = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__)), "settings.json")

# 可下载模型列表：(模型名, 大小, 说明)
MODELS_INFO = [
    ("qwen3:0.6b", "0.5 GB", "超轻量"),
    ("qwen3:1.7b", "1.2 GB", "甜点之选"),
    ("qwen3:4b", "2.5 GB", "轻量快速"),
    ("qwen3:8b", "5.2 GB", "日常主力"),
    ("qwen3:30b", "18.6 GB", "高质量"),
]
# 各模型最低要求显卡
MODELS_GPU = {
    "qwen3:0.6b": "CPU / 核显 / 1G+ 独显",
    "qwen3:1.7b": "最低 1060 3G",
    "qwen3:4b": "最低 2060 6G",
    "qwen3:8b": "最低 3060 12G / 4060 8G",
    "qwen3:30b": "最低 4060 Ti 16G",
}
# 磁贴内使用的短版显卡要求（完整版用于模型管理列表）
GPU_SHORT = {
    "qwen3:0.6b": "核显可跑",
    "qwen3:1.7b": "1060 3G",
    "qwen3:4b": "2060 6G",
    "qwen3:8b": "3060 12G/4060 8G",
    "qwen3:30b": "4060Ti 16G",
}


def model_sort_key(name):
    """模型名按参数量排序（qwen3:0.6b < 1.7b < 4b < 8b < 30b）"""
    import re
    m = re.search(r"(\d+(?:\.\d+)?)b", name.lower())
    return float(m.group(1)) if m else 999


API_OPTION = "第三方API"   # 下拉框里的外部 API 选项（固定排最后）

# ---------------- 界面语言（i18n） ----------------
LANG = "zh"  # "zh" / "en"


def tr(zh, en=None):
    """界面文本中英切换：LANG='en' 且有英文时返回英文"""
    return en if (LANG == "en" and en) else zh


# EZ 模式"翻译倾向"预设（选择后作为自定义 Prompt 生效）
TENDENCIES = {
    "正常对话": (
        "你是专业翻译。请把下面的内容逐行翻译成简体中文，每行对应一行译文。\n"
        "要求：译文自然流畅，符合日常对话习惯；口语化表达；"
        "人名地名音译并保持一致；保留原文的特殊符号和换行；只输出译文。\n\n"
        "原文：\n{text}"),
    "论文": (
        "你是学术翻译专家。请把下面的内容逐行翻译成简体中文，每行对应一行译文。\n"
        "要求：使用规范的学术书面语；专业术语准确且前后一致；句式严谨正式；"
        "保留原文的特殊符号和换行；只输出译文。\n\n"
        "原文：\n{text}"),
    "色情内容": (
        "你是专业翻译。请把下面的内容逐行翻译成简体中文，每行对应一行译文。\n"
        "这是游戏台词翻译任务，请直接翻译不解释。\n"
        "要求：直译不回避成人内容；准确传达语气和情感；"
        "保留拟声词、语气词和特殊符号（♥ 等）；人名音译保持一致；只输出译文。\n\n"
        "原文：\n{text}"),
}

# 翻译模式（模型加载/卸载策略）
TRANSLATE_MODES = {
    "短线翻译": "点击开始翻译后加载模型，全部任务完成后自动卸载模型、释放显存。\n"
                "适合偶尔翻译、显存紧张的用户。",
    "长线翻译": "点击开始翻译后加载模型并常驻显存，连续翻译更快；\n"
                "直到更换模型或关闭软件才会卸载。适合连续大量翻译的用户。",
}

# 鼠标悬停下拉栏时弹出的模式说明
class Tooltip:
    """轻量悬停提示框（鼠标停留显示，移开消失）"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)
        widget.bind("<Button-1>", self.hide)

    def show(self, event=None):
        if self.tip:
            return
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            tk.Label(self.tip, text=self.text, bg="#3a3a3a", fg="#e6e6e6",
                     font=("Microsoft YaHei UI", 9), justify=tk.LEFT,
                     padx=10, pady=8, wraplength=340).pack()
        except Exception:
            pass

    def hide(self, event=None):
        if self.tip:
            try:
                self.tip.destroy()
            except Exception:
                pass
            self.tip = None

# 软件目录（exe 所在目录 / 脚本所在目录）
APP_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))
DIR_TODO = os.path.join(APP_DIR, "待翻译")   # 未翻译文件存放区
DIR_DONE = os.path.join(APP_DIR, "已翻译")   # 已翻译文件存放区
APP_LOG = os.path.join(APP_DIR, "app.log")   # 软件日志（用户反馈时直接发这个文件）

# ---------------- 主题（跟随 Windows 系统深/浅色 + 强调色） ----------------
import winreg

THEME_LIGHT = {
    "bg": "#f3f3f3", "card": "#ffffff", "text": "#1b1b1b", "sub": "#5f5f5f",
    "drop": "#e5e5e5", "drop_text": "#3d3d3d", "input": "#ffffff",
    "btn": "#e0e0e0", "btn_active": "#d0d0d0", "header": "#e8e8e8",
    "green": "#107c10", "red": "#c42b1c", "gold": "#9a7a00",
}
THEME_DARK = {
    "bg": "#1f1f1f", "card": "#2b2b2b", "text": "#e6e6e6", "sub": "#9d9d9d",
    "drop": "#161616", "drop_text": "#c8ccd8", "input": "#1a1a1a",
    "btn": "#3a3a3a", "btn_active": "#4a4a4a", "header": "#262626",
    "green": "#4caf50", "red": "#ef5350", "gold": "#c8a86a",
}

THEME = dict(THEME_DARK)
THEME["accent"] = (0, 120, 212)        # 强调色（RGB，随系统）
THEME["accent_dark"] = (0, 90, 160)    # 强调色加深

COL_BG = THEME["bg"]
COL_CARD = THEME["card"]
COL_TEXT = THEME["text"]
COL_SUB = THEME["sub"]
COL_ACCENT = "#%02x%02x%02x" % THEME["accent"]
COL_ACCENT_DARK = "#%02x%02x%02x" % THEME["accent_dark"]
COL_GREEN = THEME["green"]
COL_RED = THEME["red"]
COL_DROP = THEME["drop"]
COL_DROP_TEXT = THEME["drop_text"]
COL_INPUT = THEME["input"]
COL_BTN = THEME["btn"]
COL_BTN_ACTIVE = THEME["btn_active"]
COL_HEADER = THEME["header"]
COL_GOLD = THEME["gold"]


def get_system_theme():
    """读取 Windows 系统主题：返回 (浅色?, 强调色RGB)"""
    light = False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            light = winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 1
    except Exception:
        pass
    accent = None
    for path, name in ((r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent",
                        "AccentColorMenu"),
                       (r"Software\Microsoft\Windows\CurrentVersion\DWM", "AccentColor")):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
                v = winreg.QueryValueEx(k, name)[0]
                accent = (v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
            if accent:
                break
        except Exception:
            continue
    if accent is None:
        accent = (0, 120, 212)  # Windows 默认蓝
    return light, accent


def apply_theme_colors(light, accent):
    """根据系统主题更新全局颜色变量"""
    global COL_BG, COL_CARD, COL_TEXT, COL_SUB, COL_ACCENT, COL_ACCENT_DARK
    global COL_GREEN, COL_RED, COL_DROP, COL_DROP_TEXT, COL_INPUT
    global COL_BTN, COL_BTN_ACTIVE, COL_HEADER, COL_GOLD
    base = THEME_LIGHT if light else THEME_DARK
    THEME.update(base)
    THEME["accent"] = accent
    # 强调色加深 25% 作为按下/选中色
    THEME["accent_dark"] = tuple(int(c * 0.75) for c in accent)
    COL_BG, COL_CARD, COL_TEXT, COL_SUB = THEME["bg"], THEME["card"], THEME["text"], THEME["sub"]
    COL_ACCENT = "#%02x%02x%02x" % accent
    COL_ACCENT_DARK = "#%02x%02x%02x" % THEME["accent_dark"]
    COL_GREEN, COL_RED = THEME["green"], THEME["red"]
    COL_DROP, COL_DROP_TEXT, COL_INPUT = THEME["drop"], THEME["drop_text"], THEME["input"]
    COL_BTN, COL_BTN_ACTIVE = THEME["btn"], THEME["btn_active"]
    COL_HEADER, COL_GOLD = THEME["header"], THEME["gold"]


def inverted_accent():
    """主题色的相反色（补色）用于"设置"按钮标注；返回 (背景色, 前景色)"""
    try:
        h = COL_ACCENT.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        cr, cg, cb = 255 - r, 255 - g, 255 - b
        bg = "#%02x%02x%02x" % (cr, cg, cb)
        lum = (cr * 299 + cg * 587 + cb * 114) // 1000
        return bg, ("#000000" if lum > 150 else "#ffffff")
    except Exception:
        return "#ff8700", "#ffffff"


def make_icon_image(size=64):
    """生成托盘/软件图标"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=size // 5,
                        fill=COL_ACCENT)
    d.text((size * 0.5, size * 0.5), "译", fill="white", anchor="mm",
           font=None)
    return img


class TranslateApp:
    def __init__(self, root):
        self.root = root
        self.root.title(tr(APP_TITLE, APP_TITLE_EN))
        self.root.geometry("1024x576")  # 16:9 默认尺寸
        # 最小尺寸保证顶部配置/按钮全部可见，不被裁切（16:9 对应高度）
        self.root.minsize(960, 540)
        self._last_size = None
        self._drag_delta = (0, 0)
        self._aspect_job = None
        self.root.bind("<Configure>", self._lock_aspect)
        self.root.configure(bg=COL_BG)

        self.tasks = []
        self.task_id_counter = 0
        self.worker_thread = None
        self._loaded_model = None   # 当前已加载进显存的模型（翻译模式管理用）
        self.mm = None              # 模型管理窗口状态（未打开时为 None）
        self.msg_queue = queue.Queue()
        self.stop_flag = threading.Event()
        self.tray_icon = None
        self.startup_thread = None
        self.started_ollama = False  # 是否由本软件拉起 Ollama（退出时一并关闭）
        self.page = None             # 当前页面容器（EZ/高级）
        self.mode = self.load_settings().get("mode", "ez")  # ez / adv
        self.model_var = tk.StringVar(value=MODEL_DEFAULT)  # 当前模型（两模式共用）

        os.makedirs(DIR_TODO, exist_ok=True)
        os.makedirs(DIR_DONE, exist_ok=True)

        # 应用翻译引擎配置（外部 API / 本地 Ollama）
        s = self.load_settings()
        T.ENGINE = s.get("engine", "ollama")
        T.API_BASE = s.get("api_base", "")
        T.API_KEY = s.get("api_key", "")
        T.API_MODEL = s.get("api_model", "")
        # 翻译倾向（EZ 快捷预设）优先，其次高级模式自定义 Prompt
        tendency = s.get("tendency")
        if tendency in TENDENCIES:
            T.CUSTOM_PROMPT = TENDENCIES[tendency]
        else:
            T.CUSTOM_PROMPT = s.get("custom_prompt") if s.get("custom_prompt_enabled") else None
        # 翻译专用显卡（CUDA_VISIBLE_DEVICES）
        self.gpu_index = s.get("gpu_index")  # None=自动/全部
        T.GPU_VISIBLE = self.gpu_index
        global LANG
        LANG = s.get("lang", "zh")  # 界面语言（默认中文）

        # 启动时预扫描显卡（填充缓存，设置窗口打开时零等待）
        threading.Thread(target=TranslateApp.detect_gpus, daemon=True).start()

        # 启动时应用一次系统主题（深/浅色 + 强调色）
        apply_theme_colors(*get_system_theme())

        self._setup_style()
        self._build_startup_page()
        self._startup()

    # ---------------- 主题样式 ----------------
    def _setup_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=COL_BG)
        style.configure("Card.TFrame", background=COL_CARD)
        style.configure("TLabel", background=COL_BG, foreground=COL_TEXT,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Sub.TLabel", foreground=COL_SUB)
        style.configure("Title.TLabel", background=COL_BG, foreground=COL_TEXT,
                        font=("Microsoft YaHei UI", 20, "bold"))
        style.configure("Accent.TButton", background=COL_ACCENT,
                        foreground="white", borderwidth=0, padding=(14, 7),
                        font=("Microsoft YaHei UI", 10))
        style.map("Accent.TButton",
                  background=[("active", COL_ACCENT_DARK), ("pressed", COL_ACCENT_DARK)])
        style.configure("TButton", background=COL_CARD, foreground=COL_TEXT,
                        borderwidth=0, padding=(10, 5),
                        font=("Microsoft YaHei UI", 10))
        style.map("TButton", background=[("active", COL_BTN_ACTIVE)])
        style.configure("Treeview", background=COL_CARD, fieldbackground=COL_CARD,
                        foreground=COL_TEXT, rowheight=26, borderwidth=0)
        style.configure("Treeview.Heading", background=COL_HEADER,
                        foreground=COL_TEXT, borderwidth=0,
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Treeview", background=[("selected", COL_ACCENT_DARK)])
        style.configure("TRadiobutton", background=COL_BG, foreground=COL_TEXT,
                        font=("Microsoft YaHei UI", 10))
        style.map("TRadiobutton", background=[("active", COL_BG)])
        style.configure("TCheckbutton", background=COL_BG, foreground=COL_TEXT,
                        font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", COL_BG)])
        style.configure("TProgressbar", background=COL_ACCENT,
                        troughcolor=COL_CARD, borderwidth=0)

    # ---------------- 启动页 ----------------
    def _build_startup_page(self):
        self.startup_frame = tk.Frame(self.root, bg=COL_BG)
        self.startup_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(self.startup_frame, text="译", bg=COL_ACCENT, fg="white",
                 font=("Microsoft YaHei UI", 40, "bold"),
                 padx=22, pady=8).pack(pady=(90, 20))
        tk.Label(self.startup_frame, text=APP_TITLE, bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 22, "bold")).pack()
        tk.Label(self.startup_frame, text="基于 Ollama + Qwen3 的本地翻译",
                 bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 11)).pack(pady=(4, 40))
        self.startup_bar = ttk.Progressbar(self.startup_frame, mode="determinate",
                                           length=420)
        self.startup_bar.pack()
        self.startup_label = tk.Label(self.startup_frame, text="正在启动软件...",
                                      bg=COL_BG, fg=COL_SUB,
                                      font=("Microsoft YaHei UI", 10))
        self.startup_label.pack(pady=(12, 0))

    def _startup(self):
        """后台执行启动检查：Ollama → 模型 → 就绪（外部 API 引擎则跳过本地部署）"""
        def seq():
            self.log("=== 软件启动 ===")
            self._startup_step("正在启动软件...", 8)
            time.sleep(0.4)

            if T.ENGINE == "api":
                if not (T.API_BASE and T.API_MODEL):
                    self._startup_step("⚠ 未配置 API 地址/模型，请在【设置】中填写", 100)
                    time.sleep(3)
                    self.root.after(0, self._show_main)
                    return
                self._startup_step(f"使用外部 API 引擎（{T.API_MODEL}）...", 70)
                time.sleep(0.6)
                self._startup_step("启动完成，准备就绪 ✓", 100)
                time.sleep(0.6)
                self.root.after(0, self._show_main)
                return

            self._startup_step("正在连接 Ollama 服务...", 25)
            if not T.check_ollama():
                if not os.path.exists(OLLAMA_EXE):
                    # 新电脑未安装 Ollama：不白等 40 秒，直接进主界面
                    # （本地翻译不可用，可配置外部 API 或安装 Ollama）
                    self._no_ollama = True
                    self._startup_step("⚠ 未检测到 Ollama（本地翻译不可用，"
                                       "可配置外部 API 或安装 Ollama）", 60)
                    time.sleep(2)
                    self.root.after(0, self._show_main)
                    return
                self._startup_step("未检测到 Ollama，正在自动启动...", 35)
                try:
                    # serve 模式启动：无控制台窗口、无托盘图标、指定翻译显卡
                    subprocess.Popen([OLLAMA_EXE, "serve"],
                                     creationflags=subprocess.CREATE_NO_WINDOW,
                                     env=self.build_serve_env())
                    self.started_ollama = True
                except Exception:
                    pass
                for _ in range(40):  # 最多等 40 秒
                    time.sleep(1)
                    if T.check_ollama():
                        break

            if not T.check_ollama():
                self._startup_step("❌ 无法连接 Ollama，请手动启动后重启软件", 100)
                self.log("✘ 启动失败：无法连接 Ollama（本地翻译不可用）")
                time.sleep(4)
                self.root.after(0, self._show_main)
                return

            # 模型目录一致性：serve 已在运行但指向的目录与期望不符时，重启切换
            md = self.get_model_dir()
            if md and T.check_ollama():
                try:
                    tags = self.get_installed_models()
                    expect = self.dir_model_count(md)
                    if expect > 0 and len(tags) != expect:
                        self._startup_step("检测到模型库变化，正在切换...", 40)
                        subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                                       capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                        subprocess.run(["taskkill", "/f", "/im", "llama-server.exe"],
                                       capture_output=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW)
                        time.sleep(2)
                        subprocess.Popen([OLLAMA_EXE, "serve"],
                                         creationflags=subprocess.CREATE_NO_WINDOW,
                                         env=self.build_serve_env())
                        self.started_ollama = True
                        for _ in range(40):
                            time.sleep(1)
                            if T.check_ollama():
                                break
                except Exception:
                    pass

            self._startup_step("正在部署模型...", 55)
            try:
                models = self.get_installed_models()
                if not any(m.startswith(MODEL_DEFAULT.split(":")[0]) for m in models):
                    size = next((s for n, s, _ in MODELS_INFO if n == MODEL_DEFAULT), "?")
                    self._startup_step(f"首次运行：正在下载默认模型 {MODEL_DEFAULT}（{size}）...", 60)

                    def dl_cb(status, percent):
                        self._startup_step(f"下载 {MODEL_DEFAULT}: {status} {percent:.0f}%",
                                           60 + min(percent, 100) * 0.3)

                    if not self.pull_model(MODEL_DEFAULT, dl_cb):
                        self._startup_step("⚠ 默认模型下载失败，可在【模型管理】中重试", 100)
                        time.sleep(3)
                        self.root.after(0, self._show_main)
                        return
                # 不再默认预热模型：由"翻译模式"控制何时加载/卸载（短线用后即卸，长线常驻）
            except Exception as e:
                self._startup_step(f"⚠ 模型检查失败: {e}", 90)

            self._startup_step("启动完成，准备就绪 ✓", 100)
            self.log("✓ 启动完成，准备就绪")
            time.sleep(0.6)
            self.root.after(0, self._show_main)

        self.startup_thread = threading.Thread(target=seq, daemon=True)
        self.startup_thread.start()

    def _startup_step(self, text, percent):
        self.root.after(0, lambda: (self.startup_bar.configure(value=percent),
                                    self.startup_label.configure(text=text)))

    def _show_main(self):
        """启动完成，切换到主界面（按模式构建 EZ / 高级页面）"""
        self.startup_frame.destroy()
        self.page = tk.Frame(self.root, bg=COL_BG)
        self.page.pack(fill=tk.BOTH, expand=True)
        if self.mode == "ez":
            self._build_ez_ui()
        else:
            self._build_adv_ui()
        self._refresh_status()
        self.root.after(100, self._poll_queue)
        self._setup_tray()
        self.log(f"{APP_TITLE} 已就绪（模型: {MODEL_DEFAULT}）")
        if T.ENGINE != "api" and not T.check_ollama():
            self.log("⚠ Ollama 未运行，翻译前请先启动")
        self.refresh_model_list()
        self._refresh_engine_label()
        # 新电脑未安装 Ollama：进入主界面后引导安装
        if getattr(self, "_no_ollama", False):
            self.root.after(600, self._prompt_install_ollama)

    def _open_sponsor(self, event=None):
        """跳转赞助页（感谢支持）"""
        try:
            import webbrowser
            webbrowser.open("https://sponsor-achenyan.pages.dev")
        except Exception:
            pass

    def _prompt_install_ollama(self):
        """未安装 Ollama 时的引导：附带安装器可一键启动安装"""
        installer = os.path.join(APP_DIR, "OllamaSetup.exe")
        msg = (tr("未检测到 Ollama。\n\n"
                  "• 本地翻译需要 Ollama 引擎（也可在模型管理中配置外部 API）\n\n"
                  "安装包已随软件附带（OllamaSetup.exe），安装后重新打开本软件即可。\n"
                  "现在开始安装？",
                  "Ollama not detected.\n\n"
                  "• Local translation requires the Ollama engine "
                  "(or configure a 3rd-party API in Model Manager)\n\n"
                  "The installer is bundled (OllamaSetup.exe). Install it, "
                  "then reopen this app.\nInstall now?"))
        if os.path.exists(installer):
            if messagebox.askyesno(tr("安装 Ollama", "Install Ollama"),
                                   msg, parent=self.root):
                try:
                    os.startfile(installer)
                except Exception:
                    pass
        else:
            messagebox.showinfo(
                tr("未检测到 Ollama", "Ollama Not Found"),
                tr("请到 https://ollama.com/download 下载并安装 Ollama，"
                   "安装后重新打开本软件即可使用本地翻译。",
                   "Download & install Ollama from https://ollama.com/download, "
                   "then reopen this app for local translation."),
                parent=self.root)

    def _switch_mode(self, new_mode):
        """EZ / 高级模式切换"""
        self.mode = new_mode
        s = self.load_settings()
        s["mode"] = new_mode
        self.save_settings(s)
        if self.page:
            self.page.destroy()
        self.page = tk.Frame(self.root, bg=COL_BG)
        self.page.pack(fill=tk.BOTH, expand=True)
        if new_mode == "ez":
            self._build_ez_ui()
        else:
            self._build_adv_ui()
            self.refresh_model_list()  # 填充模型下拉栏（关键修复）
        self._refresh_engine_label()
        self.log(f"已切换到{'EZ' if new_mode == 'ez' else '高级'}模式")

    def _refresh_engine_label(self):
        """刷新引擎状态标签"""
        if not hasattr(self, "engine_label"):
            return
        if T.ENGINE == "api":
            self.engine_label.config(text=f"引擎: 外部API ({T.API_MODEL})",
                                     fg=COL_ACCENT)
        else:
            self.engine_label.config(text="引擎: 本地 Ollama", fg=COL_SUB)

    # ---------------- 高级模式界面 ----------------
    def _build_adv_ui(self):
        # 网格布局：各块宽度占满；任务列表:日志 = 3:1 随窗口缩放伸缩
        for c in range(1):
            self.page.grid_columnconfigure(0, weight=1)
        self.page.grid_rowconfigure(2, weight=0, minsize=72)   # 拖拽区
        self.page.grid_rowconfigure(4, weight=3, minsize=160)  # 任务列表
        self.page.grid_rowconfigure(6, weight=1, minsize=70)   # 日志（折叠时隐藏）
        # 顶部标题栏
        top = tk.Frame(self.page, bg=COL_BG)
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        tk.Label(top, text="译", bg=COL_ACCENT, fg="white",
                 font=("Microsoft YaHei UI", 13, "bold"),
                 padx=7, pady=1).pack(side=tk.LEFT)
        tk.Label(top, text=APP_TITLE, bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(side=tk.LEFT, padx=8)
        ttk.Label(top, text=tr("模型:", "Model:")).pack(side=tk.LEFT, padx=(24, 4))
        self.model_combo = ttk.Combobox(top, textvariable=self.model_var, width=14,
                                        state="readonly")
        self.model_combo.bind("<<ComboboxSelected>>", self.on_model_select)
        self.model_combo.pack(side=tk.LEFT)
        ttk.Button(top, text=tr("模型管理", "Models"),
                   command=self.open_model_manager).pack(side=tk.LEFT, padx=6)
        # 设置 / 翻译 Prompt 对调：Prompt 在前，设置用主题色补色标注
        ttk.Button(top, text=tr("翻译 Prompt ✏️", "Prompt ✏️"),
                   command=self.open_prompt_editor).pack(side=tk.LEFT, padx=6)
        _inv_bg, _inv_fg = inverted_accent()
        tk.Button(top, text=tr("设置", "Settings"), bg=_inv_bg, fg=_inv_fg,
                  activebackground=_inv_bg, activeforeground=_inv_fg,
                  relief=tk.FLAT, padx=12, pady=3, font=("Microsoft YaHei UI", 9),
                  command=self.open_settings).pack(side=tk.LEFT, padx=6)
        tk.Button(top, text=tr("EZ 模式 ✨", "EZ Mode ✨"), bg=COL_ACCENT, fg="white", relief=tk.FLAT,
                  padx=12, pady=3, font=("Microsoft YaHei UI", 9),
                  command=lambda: self._switch_mode("ez")).pack(side=tk.LEFT, padx=6)
        # 引擎/状态标签移出顶栏（顶栏宽度留给按钮，避免最小窗口下 EZ 按钮被挤出）

        # 目录快捷栏
        dir_row = tk.Frame(self.page, bg=COL_BG)
        dir_row.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))
        ttk.Button(dir_row, text=tr("📁 打开待翻译区", "📁 To-Translate"),
                   command=lambda: self._open_dir(DIR_TODO)).pack(side=tk.LEFT)
        ttk.Button(dir_row, text=tr("📁 打开已翻译区", "📁 Translated"),
                   command=lambda: self._open_dir(DIR_DONE)).pack(side=tk.LEFT, padx=6)
        ttk.Button(dir_row, text=tr("🔍 扫描待翻译区", "🔍 Scan"),
                   command=self.scan_todo_dir).pack(side=tk.LEFT)
        ttk.Label(dir_row, text=f"待翻译区: {DIR_TODO}", style="Sub.TLabel",
                  background=COL_BG).pack(side=tk.RIGHT)

        # 拖拽区（高度交给网格行分配，minsize 保证文字完整）
        self.drop_frame = tk.Frame(self.page, bg=COL_DROP, bd=0)
        self.drop_frame.grid(row=2, column=0, sticky="nsew", padx=16)
        tk.Label(self.drop_frame,
                 text="📥 将 .json / .txt / .md / .srt 文件拖到这里\n（或放入【待翻译】文件夹后点“扫描待翻译区”）",
                 bg=COL_DROP, fg=COL_DROP_TEXT,
                 font=("Microsoft YaHei UI", 12)).pack(expand=True)
        self.drop_frame.drop_target_register(DND_FILES)
        self.drop_frame.dnd_bind("<<Drop>>", self.on_drop)

        # 控制按钮（翻译配置栏：先占三行按钮高度的空间，内容暂按原布局）
        ctrl = tk.Frame(self.page, bg=COL_BG, height=108)
        ctrl.grid(row=3, column=0, sticky="ew", padx=16, pady=8)
        ctrl.grid_propagate(False)
        ttk.Button(ctrl, text=tr("▶ 开始翻译", "▶ Translate"), style="Accent.TButton",
                   command=self.start_worker).pack(side=tk.LEFT, pady=(36, 36))
        ttk.Button(ctrl, text=tr("⏹ 停止", "⏹ Stop"), command=self.stop_worker).pack(side=tk.LEFT, padx=6, pady=(36, 36))
        ttk.Button(ctrl, text=tr("清除已完成", "Clear Done"), command=self.clear_done).pack(side=tk.LEFT, pady=(36, 36))
        # 翻译模式（模型加载/卸载策略，悬停有说明）
        tk.Label(ctrl, text=tr("翻译模式:", "Mode:"), bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(16, 4), pady=(36, 36))
        mode_val = self.load_settings().get("translate_mode", "短线翻译")
        self.mode_combo = ttk.Combobox(ctrl, values=list(TRANSLATE_MODES.keys()),
                                       state="readonly", width=9)
        self.mode_combo.set(mode_val if mode_val in TRANSLATE_MODES else "短线翻译")
        self.mode_combo.pack(side=tk.LEFT, pady=(36, 36))
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_translate_mode_change)
        Tooltip(self.mode_combo, tr("\n".join(
            f"{k}：{v}" for k, v in TRANSLATE_MODES.items()),
            "\n".join(f"{k}: {v}" for k, v in TRANSLATE_MODES.items())))
        # 并行翻译数量（自定义输入；"!" 悬停查看用途与注意事项）
        tk.Label(ctrl, text=tr("并行:", "Parallel:"), bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(14, 4), pady=(36, 36))
        pval = str(self.load_settings().get("parallel_count", 1))
        self.parallel_entry = ttk.Entry(ctrl, width=4, justify=tk.CENTER)
        self.parallel_entry.insert(0, pval)
        self.parallel_entry.pack(side=tk.LEFT, pady=(36, 36))
        self.parallel_entry.bind("<Return>", self.on_parallel_change)
        self.parallel_entry.bind("<FocusOut>", self.on_parallel_change)
        _par_tip = tr(
            "同时翻译的文件数量（1~16）。\n\n"
            "用途：\n· 1 = 逐个翻译（默认，最稳）\n· 2+ = 并行翻译，更快\n\n"
            "注意事项：\n"
            "· 本地翻译：每份内容同时占显存，\n  大模型（8b/30b）请保持 1~2\n"
            "· 第三方 API：受服务商限流（429），\n  过高会报错，建议 2~4\n"
            "· 输入数字后按回车或点击别处生效",
            "Files translated at once (1~16).\n\n"
            "Usage:\n· 1 = one by one (default)\n· 2+ = parallel, faster\n\n"
            "Notes:\n"
            "· Local: each file uses VRAM, keep 1~2 for big models\n"
            "· 3rd-party API: rate-limited (429), try 2~4\n"
            "· Press Enter or click away to apply")
        Tooltip(self.parallel_entry, _par_tip)
        self.task_count_label = tk.Label(ctrl, text="任务数: 0", bg=COL_BG,
                                         fg=COL_SUB, font=("Microsoft YaHei UI", 9))
        self.task_count_label.pack(side=tk.RIGHT, pady=(36, 36))
        # 状态灯/引擎标签（原在顶栏，移到这里防止顶栏按钮被挤出）
        self.engine_label = tk.Label(ctrl, text="", bg=COL_BG, fg=COL_SUB,
                                     font=("Microsoft YaHei UI", 9))
        self.engine_label.pack(side=tk.RIGHT, padx=(0, 12), pady=(36, 36))
        self.status_label = tk.Label(ctrl, text="● 检查中", bg=COL_BG, fg=COL_SUB,
                                     font=("Microsoft YaHei UI", 9))
        self.status_label.pack(side=tk.RIGHT, pady=(36, 36))

        # 任务列表（占剩余空间 3 份，随窗口缩放）
        tree_frame = tk.Frame(self.page, bg=COL_BG)
        tree_frame.grid(row=4, column=0, sticky="nsew", padx=16)
        cols = ("file", "status", "progress", "detail")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=7)
        for c, w, anchor in (("file", 320, tk.W), ("status", 90, tk.CENTER),
                             ("progress", 110, tk.CENTER), ("detail", 300, tk.W)):
            self.tree.heading(c, text=tr({"file": "文件", "status": "状态",
                                       "progress": "进度", "detail": "说明"}[c],
                                  {"file": "File", "status": "Status",
                                       "progress": "Progress", "detail": "Detail"}[c]))
            self.tree.column(c, width=w, anchor=anchor)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # 日志（默认折叠，点击"▸ 日志"倒三角展开/收起，状态记忆）
        log_bar = tk.Frame(self.page, bg=COL_BG)
        log_bar.grid(row=5, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.log_toggle_btn = tk.Label(log_bar, text="▸ 日志", bg=COL_BG, fg=COL_SUB,
                                       font=("Microsoft YaHei UI", 9, "bold"),
                                       cursor="hand2")
        self.log_toggle_btn.pack(side=tk.LEFT)
        self.log_toggle_btn.bind("<Button-1>", self._toggle_log)
        log_frame = tk.Frame(self.page, bg=COL_BG)
        self._log_frame = log_frame
        self.log_text = tk.Text(log_frame, height=8, state=tk.DISABLED,
                                bg=COL_CARD, fg=COL_TEXT, insertbackground=COL_TEXT,
                                relief=tk.FLAT, padx=8, pady=6,
                                font=("Consolas", 9), wrap=tk.WORD)
        log_sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_sb.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_open = bool(self.load_settings().get("adv_log_open", False))
        if self._log_open:
            log_frame.grid(row=6, column=0, sticky="nsew", padx=16, pady=(6, 14))
            self.log_toggle_btn.config(text="▾ 日志")
        # 折叠时不 grid log_frame（任务列表自动获得全部空间）

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _lock_aspect(self, event=None):
        """窗口固定 16:9：拖动中持续追踪增量，停手后以用户拖动的一边为基准，
        另一边跟随（放大就放大、缩小就缩小）；最大化/全屏时不锁（退出恢复原尺寸）"""
        if event is not None and event.widget is not self.root:
            return
        try:
            if self.root.state() == "zoomed" or self.root.attributes("-fullscreen"):
                return
        except Exception:
            pass
        try:
            w, h = self.root.winfo_width(), self.root.winfo_height()
            if self._last_size:
                dw = w - self._last_size[0]
                dh = h - self._last_size[1]
                # 只记录有效增量（≥3px），避免微小抖动/几何校正噪音
                if abs(dw) >= 3 or abs(dh) >= 3:
                    self._drag_delta = (dw, dh)
            self._last_size = (w, h)
        except Exception:
            pass
        if self._aspect_job:
            self.root.after_cancel(self._aspect_job)
        self._aspect_job = self.root.after(250, self._fix_aspect)

    def _fix_aspect(self):
        """停手后按拖动方向补齐 16:9：拉宽→高度跟随；拉高→宽度跟随；
        往回拉（缩小）时另一边同样自动缩回，不会弹回变大"""
        self._aspect_job = None
        try:
            w = self.root.winfo_width()
            h = self.root.winfo_height()
            if w <= 0 or h <= 0:
                return
            try:
                if self.root.state() == "zoomed" or self.root.attributes("-fullscreen"):
                    return
            except Exception:
                pass
            dw, dh = self._drag_delta or (0, 0)
            if abs(dw) < 3 and abs(dh) < 3:
                return
            if abs(dw) >= abs(dh):
                # 用户动的是宽度：高度跟随（放大/缩小都跟随）
                nh = round(w * 9 / 16)
                if abs(nh - h) > 3:
                    self.root.geometry(f"{w}x{nh}")
            else:
                # 用户动的是高度：宽度跟随
                nw = round(h * 16 / 9)
                if abs(nw - w) > 3:
                    self.root.geometry(f"{nw}x{h}")
        except Exception:
            pass

    def _toggle_log(self, event=None):
        """折叠/展开日志栏（状态保存，切模式不丢）"""
        self._log_open = not self._log_open
        s = self.load_settings()
        s["adv_log_open"] = self._log_open
        self.save_settings(s)
        if self._log_open:
            self._log_frame.grid(row=6, column=0, sticky="nsew", padx=16, pady=(6, 14))
            self.log_toggle_btn.config(text="▾ 日志")
        else:
            self._log_frame.grid_remove()
            self.log_toggle_btn.config(text="▸ 日志")

    # ---------------- EZ 模式界面 ----------------
    def _build_ez_ui(self):
        """EZ 模式：只有翻译和模型切换，大图形化界面"""
        # 网格布局：拖拽区:模型卡片 = 2:3 随窗口缩放伸缩
        self.page.grid_columnconfigure(0, weight=1)
        # 拖拽行 minsize 需含 pady(16+12)，保证内容区 ≥ 文字高度(90)
        self.page.grid_rowconfigure(1, weight=2, minsize=120)   # 拖拽区
        self.page.grid_rowconfigure(4, weight=3, minsize=140)   # 模型磁贴区
        self.page.grid_rowconfigure(6, weight=0, minsize=52)    # 底部按钮（防被压缩遮挡）
        # 顶栏
        top = tk.Frame(self.page, bg=COL_BG)
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(14, 4))
        tk.Label(top, text="译", bg=COL_ACCENT, fg="white",
                 font=("Microsoft YaHei UI", 14, "bold"),
                 padx=8, pady=2).pack(side=tk.LEFT)
        tk.Label(top, text="本地 AI 翻译助手", bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(side=tk.LEFT, padx=8)
        self.engine_label = tk.Label(top, text="", bg=COL_BG, fg=COL_SUB,
                                     font=("Microsoft YaHei UI", 9))
        self.engine_label.pack(side=tk.LEFT, padx=12)
        self.status_label = tk.Label(top, text="", bg=COL_BG, fg=COL_SUB,
                                     font=("Microsoft YaHei UI", 9))
        self.status_label.pack(side=tk.RIGHT, padx=(0, 10))
        # 按钮在最右，提示文字（金色）在其左侧
        tk.Button(top, text=tr("高级模式 ⚙", "Advanced ⚙"),
                  bg=COL_CARD, fg=COL_TEXT, relief=tk.FLAT,
                  padx=14, pady=4, font=("Microsoft YaHei UI", 10),
                  command=lambda: self._switch_mode("adv")).pack(side=tk.RIGHT)
        tk.Label(top, text=tr("更多设置项点这里 →", "More settings here →"),
                 bg=COL_BG, fg=COL_GOLD, font=("Microsoft YaHei UI", 9, "bold")).pack(side=tk.RIGHT, padx=(0, 6))

        # 大拖拽区（高度交给网格行分配，随窗口缩放；去掉 grid_propagate 防止被固定成内容高度）
        self.drop_frame = tk.Frame(self.page, bg=COL_DROP, bd=0)
        self.drop_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(16, 12))
        self.drop_label = tk.Label(self.drop_frame,
                                   text="📥 将文件拖到这里开始翻译\n\n或点击选择文件",
                                   bg=COL_DROP, fg=COL_DROP_TEXT,
                                   font=("Microsoft YaHei UI", 16))
        self.drop_label.pack(expand=True)
        self.drop_label.bind("<Button-1>", lambda e: self.add_file_dialog())
        self.drop_frame.bind("<Button-1>", lambda e: self.add_file_dialog())
        self.drop_frame.drop_target_register(DND_FILES)
        self.drop_frame.dnd_bind("<<Drop>>", self.on_drop)

        # 翻译倾向（快捷 Prompt 预设）
        tend_row = tk.Frame(self.page, bg=COL_BG)
        tend_row.grid(row=2, column=0, sticky="ew", padx=24, pady=(8, 2))
        tk.Label(tend_row, text=tr("翻译倾向:", "Style:"), bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        self.tendency_combo = ttk.Combobox(tend_row, values=list(TENDENCIES.keys()),
                                           state="readonly", width=12)
        self.tendency_combo.pack(side=tk.LEFT, padx=6)
        self.tendency_combo.bind("<<ComboboxSelected>>", self.on_tendency_change)
        cur = self.load_settings().get("tendency")
        self.tendency_combo.set(cur if cur in TENDENCIES else "正常对话")
        tk.Label(tend_row, text=tr("（切换后对后续翻译生效）", "(applies to next translation)"), bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT, padx=4)
        # 翻译模式（模型加载/卸载策略，悬停有说明）
        tk.Label(tend_row, text=tr("翻译模式:", "Mode:"), bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(16, 0))
        mode_val = self.load_settings().get("translate_mode", "短线翻译")
        self.mode_combo = ttk.Combobox(tend_row, values=list(TRANSLATE_MODES.keys()),
                                       state="readonly", width=9)
        self.mode_combo.set(mode_val if mode_val in TRANSLATE_MODES else "短线翻译")
        self.mode_combo.pack(side=tk.LEFT, padx=6)
        self.mode_combo.bind("<<ComboboxSelected>>", self.on_translate_mode_change)
        Tooltip(self.mode_combo, tr("\n".join(
            f"{k}：{v}" for k, v in TRANSLATE_MODES.items()),
            "\n".join(f"{k}: {v}" for k, v in TRANSLATE_MODES.items())))
        # 并行翻译数量（自定义输入；"!" 悬停查看用途与注意事项）
        tk.Label(tend_row, text=tr("并行:", "Parallel:"), bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT, padx=(16, 0))
        pval = str(self.load_settings().get("parallel_count", 1))
        self.parallel_entry = ttk.Entry(tend_row, width=4, justify=tk.CENTER)
        self.parallel_entry.insert(0, pval)
        self.parallel_entry.pack(side=tk.LEFT, padx=6)
        self.parallel_entry.bind("<Return>", self.on_parallel_change)
        self.parallel_entry.bind("<FocusOut>", self.on_parallel_change)
        _par_tip = tr(
            "同时翻译的文件数量（1~16）。\n\n"
            "用途：\n· 1 = 逐个翻译（默认，最稳）\n· 2+ = 并行翻译，更快\n\n"
            "注意事项：\n"
            "· 本地翻译：每份内容同时占显存，\n  大模型（8b/30b）请保持 1~2\n"
            "· 第三方 API：受服务商限流（429），\n  过高会报错，建议 2~4\n"
            "· 输入数字后按回车或点击别处生效",
            "Files translated at once (1~16).\n\n"
            "Usage:\n· 1 = one by one (default)\n· 2+ = parallel, faster\n\n"
            "Notes:\n"
            "· Local: each file uses VRAM, keep 1~2 for big models\n"
            "· 3rd-party API: rate-limited (429), try 2~4\n"
            "· Press Enter or click away to apply")
        Tooltip(self.parallel_entry, _par_tip)

        # 模型磁贴（固定正方形，Windows 磁贴风格：尺寸恒定、随窗口自动换行居中，
        # 后续新增模型只需加进 MODELS_INFO 即可自动排列）
        tk.Label(self.page, text=tr("选择模型（点击切换 · 未安装的点击下载）", "Select Model (click to switch · click to download if not installed)"), bg=COL_BG,
                 fg=COL_SUB, font=("Microsoft YaHei UI", 10)).grid(
                     row=3, column=0, sticky="w", padx=24)
        TILE = 140
        cards = tk.Frame(self.page, bg=COL_BG)
        cards.grid(row=4, column=0, sticky="nsew", padx=20, pady=(6, 0))
        self.ez_cards = {}

        def _layout_tiles(event=None):
            try:
                if len(self.ez_cards) < len(MODELS_INFO):
                    return  # 卡片未建完，等下次 Configure 或构建后主动调用
                w = cards.winfo_width()
                if w <= 0:
                    return
                # 列数不超过卡片数（否则右侧出现空列导致整组偏左）
                n_cols = min(len(MODELS_INFO), max(1, w // (TILE + 18)))
                # 左右弹性空列实现整组居中，中间为固定磁贴列/行（sticky 撑满单元=正方形）
                cards.grid_columnconfigure(0, weight=1)
                for c in range(1, n_cols + 1):
                    cards.grid_columnconfigure(c, weight=0, minsize=TILE + 18)
                cards.grid_columnconfigure(n_cols + 1, weight=1)
                n_rows = (len(MODELS_INFO) + n_cols - 1) // n_cols
                for r in range(n_rows):
                    cards.grid_rowconfigure(r, weight=0, minsize=TILE + 12)
                for i, name in enumerate(MODELS_INFO):
                    r, c = divmod(i, n_cols)
                    self.ez_cards[name]["frame"].grid_configure(row=r, column=c + 1)
            except Exception:
                pass
        cards.bind("<Configure>", _layout_tiles)

        for i, (name, size, desc) in enumerate(MODELS_INFO):
            card = tk.Frame(cards, bg=COL_CARD,
                            highlightthickness=2, highlightbackground=COL_CARD)
            # sticky 撑满固定单元 = 固定正方形磁贴
            card.grid(row=i // 5, column=(i % 5) + 1, sticky="nsew", padx=9, pady=6)
            # 内层固定宽高容器（pack_propagate 在 pack 布局下生效）：
            # 文字在磁贴内垂直居中、永不撑破磁贴、完整显示不裁切
            inner = tk.Frame(card, bg=COL_CARD, width=TILE - 10, height=TILE - 30)
            inner.pack(expand=True)
            inner.pack_propagate(False)
            tk.Label(inner, text=name, bg=COL_CARD, fg=COL_TEXT,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(pady=(8, 0))
            tk.Label(inner, text=size, bg=COL_CARD, fg=COL_SUB,
                     font=("Microsoft YaHei UI", 9)).pack()
            tk.Label(inner, text=GPU_SHORT.get(name, ''), bg=COL_CARD,
                     fg=COL_GOLD, font=("Microsoft YaHei UI", 9)).pack(pady=(4, 0))
            state_lbl = tk.Label(inner, text=tr("检测中...", "Checking..."), bg=COL_CARD, fg=COL_SUB,
                                 font=("Microsoft YaHei UI", 9))
            state_lbl.pack(pady=(6, 0))
            for w in card.winfo_children():
                w.bind("<Button-1>", lambda e, n=name: self.ez_select_model(n))
                for ww in w.winfo_children():
                    ww.bind("<Button-1>", lambda e, n=name: self.ez_select_model(n))
            card.bind("<Button-1>", lambda e, n=name: self.ez_select_model(n))
            self.ez_cards[name] = {"frame": card, "state": state_lbl}
        self._ez_refresh_cards()
        cards.after(60, _layout_tiles)  # 布局稳定后主动排一次（不依赖 Configure）

        # 进度区
        prog = tk.Frame(self.page, bg=COL_BG)
        prog.grid(row=5, column=0, sticky="ew", padx=24, pady=(16, 4))
        self.ez_bar = ttk.Progressbar(prog, mode="determinate")
        self.ez_bar.pack(fill=tk.X)
        self.ez_status = tk.Label(prog, text=tr("就绪，拖入文件即可开始翻译", "Ready. Drop files to translate."), bg=COL_BG,
                                  fg=COL_SUB, font=("Microsoft YaHei UI", 11))
        self.ez_status.pack(anchor=tk.W, pady=(6, 0))
        self.ez_count = tk.Label(prog, text="", bg=COL_BG, fg=COL_SUB,
                                 font=("Microsoft YaHei UI", 9))
        self.ez_count.pack(anchor=tk.W, pady=(2, 0))

        # 底部按钮
        bottom = tk.Frame(self.page, bg=COL_BG)
        bottom.grid(row=6, column=0, sticky="ew", padx=24, pady=(8, 18))
        tk.Button(bottom, text=tr("📁 打开已翻译目录", "📁 Open Translated"), bg=COL_CARD, fg=COL_TEXT,
                  relief=tk.FLAT, padx=14, pady=5, font=("Microsoft YaHei UI", 10),
                  command=lambda: self._open_dir(DIR_DONE)).pack(side=tk.LEFT)
        tk.Button(bottom, text=tr("⏹ 停止", "⏹ Stop"), bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT,
                  padx=14, pady=5, font=("Microsoft YaHei UI", 10),
                  command=self.stop_worker).pack(side=tk.LEFT, padx=8)
        # 赞助（右下角小按钮，跳转赞助页）
        tk.Button(bottom, text=tr("☕ 请开发者吃碗淮南牛肉汤", "☕ Buy the dev a bowl of beef soup"),
                  bg=COL_BG, fg=COL_GOLD, relief=tk.FLAT, cursor="hand2", bd=0,
                  font=("Microsoft YaHei UI", 8),
                  command=self._open_sponsor).pack(side=tk.RIGHT)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_tendency_change(self, event=None):
        """EZ 模式：翻译倾向切换（写入自定义 Prompt 并生效）"""
        val = self.tendency_combo.get()
        s = self.load_settings()
        s["tendency"] = val
        s["custom_prompt_enabled"] = True
        s["custom_prompt"] = TENDENCIES[val]
        self.save_settings(s)
        T.CUSTOM_PROMPT = TENDENCIES[val]
        self.log(f"翻译倾向已切换: {val}")

    def _ez_refresh_cards(self):
        """刷新 EZ 模式模型卡片状态（远程翻译时 >4b 卡片灰置）"""
        if not hasattr(self, "ez_cards"):
            return
        installed = self.get_installed_models()
        current = self.model_var.get()
        for name, info in self.ez_cards.items():
            is_inst = name in installed
            is_cur = name == current
            info["frame"].config(highlightbackground=COL_ACCENT if is_cur else COL_CARD)
            if is_inst:
                info["state"].config(text=("已安装 ★" if is_cur else "已安装"),
                                     fg=COL_GREEN if is_cur else COL_SUB)
            else:
                info["state"].config(text="未安装 · 点击下载",
                                     fg=COL_RED if is_cur else COL_SUB)

    def ez_select_model(self, name):
        """EZ 模式：点击模型卡片 → 切换 / 下载"""
        installed = self.get_installed_models()
        if name in installed:
            self.model_var.set(name)
            self._ez_refresh_cards()
            self.log(f"已切换模型: {name}")
        else:
            size = next((s for n, s, _ in MODELS_INFO if n == name), "")
            if messagebox.askyesno("下载模型",
                                   f"模型 {name}（{size}）尚未安装\n是否现在下载？"):
                self.ez_download(name)

    def ez_download(self, name):
        """EZ 模式：下载模型（进度显示在主进度条）"""
        if getattr(self, "downloading_name", None):
            return
        self.downloading_name = name
        self.ez_bar.config(value=0)
        self.ez_status.config(text=f"正在下载 {name} ...")
        threading.Thread(target=self._mm_download_worker, args=(name,), daemon=True).start()

    # ---------------- 托盘 ----------------
    def _setup_tray(self):
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("显示主窗口", self._tray_show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._tray_quit),
        )
        self.tray_icon = pystray.Icon("aitranslator", make_icon_image(64),
                                      APP_TITLE, menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _tray_show(self, icon=None, item=None):
        self.root.after(0, lambda: (self.root.deiconify(),
                                    self.root.lift(),
                                    self.root.focus_force()))

    def _tray_quit(self, icon=None, item=None):
        self.root.after(0, self._quit)

    def on_close(self):
        """关闭按钮：选择挂后台或退出"""
        if self.worker_thread and self.worker_thread.is_alive():
            hint = "\n（翻译任务仍在进行）"
        else:
            hint = ""
        dialog = tk.Toplevel(self.root)
        dialog.title(tr("退出", "Exit"))
        dialog.configure(bg=COL_BG)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - 380) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - 200) // 2
        dialog.geometry(f"380x200+{x}+{y}")
        tk.Label(dialog, text=tr("选择操作", "Choose Action"), bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(18, 4))
        tk.Label(dialog, text="挂后台运行将缩小到右下角系统托盘，翻译继续执行" + hint,
                 bg=COL_BG, fg=COL_SUB, wraplength=340,
                 font=("Microsoft YaHei UI", 9)).pack(pady=(0, 14))
        btn_row = tk.Frame(dialog, bg=COL_BG)
        btn_row.pack()
        tk.Button(btn_row, text=tr("挂后台运行", "Run in Background"), bg=COL_ACCENT, fg="white",
                  activebackground=COL_ACCENT_DARK, activeforeground="white",
                  relief=tk.FLAT, padx=14, pady=6,
                  font=("Microsoft YaHei UI", 10),
                  command=lambda: self._minimize_to_tray(dialog)).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text=tr("直接退出", "Quit"), bg=COL_BTN, fg=COL_TEXT,
                  activebackground=COL_BTN_ACTIVE, relief=tk.FLAT, padx=14, pady=6,
                  font=("Microsoft YaHei UI", 10),
                  command=lambda: self._quit(dialog)).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text=tr("取消", "Cancel"), bg=COL_BTN, fg=COL_TEXT,
                  activebackground=COL_BTN_ACTIVE, relief=tk.FLAT, padx=14, pady=6,
                  font=("Microsoft YaHei UI", 10),
                  command=dialog.destroy).pack(side=tk.LEFT, padx=6)

    def _minimize_to_tray(self, dialog=None):
        if dialog:
            dialog.destroy()
        self.root.withdraw()  # 隐藏窗口，托盘继续运行
        self.log("已挂到后台运行，点击托盘图标恢复窗口")

    def _quit(self, dialog=None):
        if dialog:
            dialog.destroy()
        self.log("=== 软件退出 ===")
        self.stop_flag.set()
        self.stop_ollama()  # 退出时一并关闭 Ollama（含残留的 llama-server）
        # 托盘图标停止：放独立线程并限时，避免阻塞退出
        if self.tray_icon:
            t = threading.Thread(target=self.tray_icon.stop, daemon=True)
            t.start()
            t.join(timeout=1)
        self.root.destroy()

    def stop_ollama(self):
        """无条件关闭 Ollama 全部相关进程（app 守护 + serve + llama-server）"""
        for img in ("ollama app.exe", "llama-server.exe", "ollama.exe"):
            try:
                subprocess.run(["taskkill", "/f", "/im", img], capture_output=True,
                               creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
            except Exception:
                pass
        try:
            self.log("已随软件退出关闭 Ollama 服务")
        except Exception:
            pass

    # ---------------- 目录工具 ----------------
    @staticmethod
    def _open_dir(path):
        try:
            os.startfile(path)
        except Exception:
            subprocess.Popen(["explorer", path])

    def scan_todo_dir(self):
        """扫描待翻译区，把文件加入任务队列"""
        found = 0
        for name in sorted(os.listdir(DIR_TODO)):
            path = os.path.join(DIR_TODO, name)
            if os.path.isfile(path):
                ext = os.path.splitext(name)[1].lower()
                if ext in (".json", ".txt", ".md", ".srt"):
                    self.add_task(path)
                    found += 1
        if found == 0:
            self.log("待翻译区没有可翻译的文件")

    # ---------------- 模型工具 ----------------
    _gpus_cache = None  # 显卡检测缓存（nvidia-smi 调用慢，避免每次打开设置都查）

    @staticmethod
    def detect_gpus():
        """检测系统中的 NVIDIA 显卡列表：[(index, 名称, 显存), ...]（带缓存）"""
        if TranslateApp._gpus_cache is not None:
            return TranslateApp._gpus_cache
        try:
            out = subprocess.check_output(
                ["nvidia-smi", "--query-gpu=index,name,memory.total",
                 "--format=csv,noheader"], text=True, timeout=10)
            gpus = []
            for line in out.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 3:
                    gpus.append((int(parts[0]), parts[1], parts[2]))
            TranslateApp._gpus_cache = gpus
            return gpus
        except Exception:
            return []

    def build_serve_env(self, extra=None):
        """构建 serve 进程环境（无托盘 + 模型目录 + 翻译专用显卡）"""
        env = os.environ.copy()
        env["OLLAMA_NO_TRAY"] = "1"
        md = self.get_model_dir()
        if md:
            env["OLLAMA_MODELS"] = md
        if self.gpu_index is not None:
            env["CUDA_VISIBLE_DEVICES"] = str(self.gpu_index)
        if extra:
            env.update(extra)
        return env

    @staticmethod
    def load_settings():
        """读取软件配置（模型目录等）"""
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save_settings(data):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_model_dir(self):
        """当前模型存储目录：设置值 → E盘主库 → 软件目录models(发布包内置) → 默认"""
        s = self.load_settings()
        if s.get("model_dir") and os.path.isdir(s["model_dir"]):
            return s["model_dir"]
        if os.path.isdir(r"E:\ollama-models"):
            return r"E:\ollama-models"  # 主模型库优先（含全部模型）
        bundled = os.path.join(APP_DIR, "models")
        if os.path.isdir(bundled):
            return bundled  # 干净电脑：发布包自带的模型目录（开箱即用）
        return None

    @staticmethod
    def dir_model_count(path):
        """统计模型目录里的模型数量"""
        mdir = os.path.join(path, "manifests", "registry.ollama.ai", "library")
        if not os.path.isdir(mdir):
            return 0
        return sum(len(files) for _, _, files in os.walk(mdir))

    @staticmethod
    def get_installed_models():
        """查询已安装模型列表"""
        try:
            with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
                return [m["name"] for m in json.loads(r.read()).get("models", [])]
        except Exception:
            return []

    @staticmethod
    def pull_model(name, progress_cb):
        """通过 API 下载模型，progress_cb(status, percent) 回调，返回是否成功"""
        try:
            payload = {"model": name, "stream": True}
            req = urllib.request.Request(
                "http://localhost:11434/api/pull",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=7200)
            for raw in resp:
                line = raw.decode("utf-8", "ignore").strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                status = d.get("status", "")
                if "percentage" in d:
                    progress_cb(status, float(d["percentage"]))
                elif d.get("total") and d.get("completed") is not None:
                    progress_cb(status, float(d["completed"]) / float(d["total"]) * 100)
                else:
                    progress_cb(status, 0)
                if status == "success":
                    return True
                if status == "error":
                    progress_cb(f"错误: {d.get('error', '未知')}", 0)
                    return False
            progress_cb("下载失败（模型不存在或网络错误）", 0)
            return False
        except Exception as e:
            progress_cb(f"失败: {e}", 0)
            return False

    @staticmethod
    def delete_model(name):
        """删除模型"""
        try:
            payload = {"model": name}
            req = urllib.request.Request(
                "http://localhost:11434/api/delete",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30)
            return True
        except Exception:
            return False

    def refresh_model_list(self):
        """刷新模型下拉框：本地模型按参数量排序，第三方API固定排最后"""
        installed = self.get_installed_models()
        if hasattr(self, "model_combo") and self.model_combo.winfo_exists():
            values = sorted(installed, key=model_sort_key) or [n for n, _, _ in MODELS_INFO]
            if T.API_BASE and T.API_MODEL:
                values = values + [API_OPTION]  # 已配置 API → 追加选项（永远最后）
            current = self.model_var.get()
            self.model_combo.configure(values=values)
            if current not in values and values:
                self.model_var.set(values[0])
            if current == API_OPTION and API_OPTION not in values:
                self.model_var.set(values[0])

    def on_translate_mode_change(self, event=None):
        """翻译模式切换：保存设置（短线=用完即卸 / 长线=常驻显存）"""
        val = self.mode_combo.get()
        s = self.load_settings()
        s["translate_mode"] = val
        self.save_settings(s)
        self.log(f"翻译模式已切换: {val}")

    def on_model_select(self, event=None):
        """下拉框选择联动翻译引擎：选第三方API → 外部引擎；选本地模型 → 本地引擎"""
        sel = self.model_var.get()
        if sel == API_OPTION:
            if not (T.API_BASE and T.API_MODEL):
                messagebox.showwarning("API 未配置",
                                       "请先在【模型管理】→【第三方 API】中配置地址和模型名")
                self.refresh_model_list()
                return
            if T.ENGINE != "api":
                T.ENGINE = "api"
                self.log(f"翻译引擎已切换: 外部 API（{T.API_MODEL}）")
        else:
            if T.ENGINE != "ollama":
                T.ENGINE = "ollama"
                self.log(f"翻译引擎已切换: 本地 Ollama（{sel}）")
            # 长线模式：更换模型时卸载旧模型（新模型在下次开始翻译时加载）
            if (self.translate_mode_var().get() == "长线翻译"
                    and self._loaded_model and self._loaded_model != sel):
                T.unload_model(self._loaded_model)
                self.log(f"已更换模型：旧模型 {self._loaded_model} 已卸载")
                self._loaded_model = None
        self._refresh_engine_label()

    # ---------------- 模型管理 ----------------
    def open_model_manager(self):
        """模型管理窗口：模型列表可滚动（超过5个折叠），导入按钮固定不被挤掉"""
        win = tk.Toplevel(self.root)
        win.title(tr("模型管理", "Models"))
        win.configure(bg=COL_BG)
        win.geometry("560x600")
        win.minsize(500, 520)
        win.transient(self.root)

        tk.Label(win, text=tr("模型管理", "Models"), bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(12, 2))
        tk.Label(win, text=tr("点击【下载】一键部署，完成后即可在翻译界面切换",
                              "Click Download to deploy. Switch in the model dropdown after done."),
                 bg=COL_BG, fg=COL_SUB, font=("Microsoft YaHei UI", 9)).pack(pady=(0, 8))

        self.mm = {"win": win, "rows": {}, "downloading": None, "bar": None,
                   "label": None, "extra": {}, "api_status": None, "api_frame": None}

        # ---- 可滚动的模型列表区（固定高度，超过 5 行折叠进滚轮） ----
        scroll_box = tk.Frame(win, bg=COL_BG)
        scroll_box.pack(fill=tk.X, padx=16)
        scroll_canvas = tk.Canvas(scroll_box, bg=COL_BG, highlightthickness=0, height=290)
        vsb = ttk.Scrollbar(scroll_box, orient="vertical", command=scroll_canvas.yview)
        model_list = tk.Frame(scroll_canvas, bg=COL_BG)
        model_list.bind("<Configure>",
                        lambda e: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
        scroll_canvas.create_window((0, 0), window=model_list, anchor="nw")
        scroll_canvas.configure(yscrollcommand=vsb.set)
        scroll_canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.mm["list"] = model_list
        self.mm["canvas"] = scroll_canvas

        # 模型管理窗口打开期间的滚轮支持（仅滚动区内生效）
        def _wheel(event):
            try:
                if not scroll_canvas.winfo_exists():
                    return
                inside = scroll_canvas.winfo_containing(event.x_root, event.y_root)
                if inside is not None:
                    scroll_canvas.yview_scroll(int(-event.delta / 120), "units")
            except Exception:
                pass
        scroll_canvas.bind_all("<MouseWheel>", _wheel)

        # 内置模型行
        for name, size, desc in MODELS_INFO:
            row = tk.Frame(model_list, bg=COL_CARD, padx=12, pady=7)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=name, bg=COL_CARD, fg=COL_TEXT,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
            tk.Label(row, text=f"{size} · {desc}", bg=COL_CARD, fg=COL_SUB,
                     font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=8)
            tk.Label(row, text=f"🎮 {MODELS_GPU.get(name, '')}", bg=COL_CARD,
                     fg=COL_GOLD, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
            status_lbl = tk.Label(row, text=tr("检测中...", "Checking..."), bg=COL_CARD, fg=COL_SUB,
                                  font=("Microsoft YaHei UI", 9))
            status_lbl.pack(side=tk.RIGHT, padx=(4, 0))
            dl_btn = tk.Button(row, text=tr("下载", "Download"), bg=COL_ACCENT, fg="white",
                               relief=tk.FLAT, padx=12, pady=2, font=("Microsoft YaHei UI", 9),
                               command=lambda n=name: self.mm_download(n))
            dl_btn.pack(side=tk.RIGHT, padx=4)
            del_btn = tk.Button(row, text=tr("删除", "Delete"), bg=COL_BTN, fg=COL_TEXT,
                                relief=tk.FLAT, padx=12, pady=2, font=("Microsoft YaHei UI", 9),
                                command=lambda n=name: self.mm_delete(n))
            del_btn.pack(side=tk.RIGHT, padx=4)
            self.mm["rows"][name] = {"status": status_lbl, "dl": dl_btn, "del": del_btn}

        # ---- 第三方 API 项目条（固定区） ----
        api_row = tk.Frame(win, bg=COL_CARD, padx=12, pady=7)
        api_row.pack(fill=tk.X, padx=16, pady=(8, 3))
        self.mm["api_frame"] = api_row
        tk.Label(api_row, text=tr("第三方 API", "3rd-Party API"), bg=COL_CARD, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
        tk.Label(api_row, text=tr("OpenAI 兼容（DeepSeek/通义/Kimi 等）", "OpenAI-compatible (DeepSeek/Qwen/Kimi...)"),
                 bg=COL_CARD, fg=COL_SUB, font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=8)
        self.mm["api_status"] = tk.Label(api_row, text=tr("未配置", "Not Configured"), bg=COL_CARD,
                                         fg=COL_SUB, font=("Microsoft YaHei UI", 9))
        self.mm["api_status"].pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(api_row, text=tr("编辑", "Edit"), bg=COL_ACCENT, fg="white",
                  relief=tk.FLAT, padx=14, pady=2, font=("Microsoft YaHei UI", 9),
                  command=self.open_api_config).pack(side=tk.RIGHT, padx=4)

        # 进度区
        prog_frame = tk.Frame(win, bg=COL_BG)
        prog_frame.pack(fill=tk.X, padx=16, pady=(10, 2))
        self.mm["bar"] = ttk.Progressbar(prog_frame, mode="determinate")
        self.mm["bar"].pack(fill=tk.X)
        self.mm["label"] = tk.Label(prog_frame, text="", bg=COL_BG, fg=COL_SUB,
                                    font=("Microsoft YaHei UI", 9))
        self.mm["label"].pack(pady=(5, 0))

        # 模型存储位置
        loc_frame = tk.Frame(win, bg=COL_BG)
        loc_frame.pack(fill=tk.X, padx=16, pady=(8, 0))
        tk.Label(loc_frame, text=tr("模型存储位置:", "Model Folder:"), bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.mm["loc"] = tk.Label(loc_frame, text=self.get_model_dir() or r"C:\Users\<user>\.ollama\models",
                                  bg=COL_BG, fg=COL_TEXT, font=("Microsoft YaHei UI", 9))
        self.mm["loc"].pack(side=tk.LEFT, padx=6)
        tk.Button(loc_frame, text=tr("更改...", "Change..."), bg=COL_BTN, fg=COL_TEXT,
                  relief=tk.FLAT, padx=10, pady=2, font=("Microsoft YaHei UI", 9),
                  command=self.mm_change_dir).pack(side=tk.RIGHT)

        # 底部按钮（固定不被挤掉）
        btn_row = tk.Frame(win, bg=COL_BG)
        btn_row.pack(pady=(10, 12))
        tk.Button(btn_row, text=tr("导入模型", "Import"), bg=COL_ACCENT, fg="white", relief=tk.FLAT,
                  padx=20, pady=4, font=("Microsoft YaHei UI", 10),
                  command=self.open_model_import).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text=tr("关闭", "Close"), bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT,
                  padx=20, pady=4, font=("Microsoft YaHei UI", 10),
                  command=win.destroy).pack(side=tk.LEFT, padx=6)

        self.mm_refresh()


    def mm_refresh(self):
        """刷新模型管理窗口的状态和按钮"""
        if not self.mm:
            return
        installed = self.get_installed_models()
        for name, row in self.mm["rows"].items():
            is_installed = name in installed
            row["status"].config(text=tr("已安装", "Installed") if is_installed else tr("未安装", "Not Installed"),
                                 fg=COL_GREEN if is_installed else COL_SUB)
            row["dl"].config(state=tk.DISABLED if is_installed else tk.NORMAL)
            row["del"].config(state=tk.NORMAL if is_installed else tk.DISABLED)
        # 动态同步外部导入的模型（不在预设列表里的已安装模型）
        self._mm_sync_extra(installed)
        # 第三方 API 状态
        if self.mm.get("api_status"):
            if T.API_BASE and T.API_MODEL:
                self.mm["api_status"].config(text=f"已配置: {T.API_MODEL}", fg=COL_GREEN)
            else:
                self.mm["api_status"].config(text=tr("未配置", "Not Configured"), fg=COL_SUB)

    def _mm_sync_extra(self, installed):
        """模型管理窗口：动态显示外部导入的模型（如 llama3.2:1b），可删除"""
        preset = [n for n, _, _ in MODELS_INFO]
        extras = [n for n in installed if n not in preset]
        # 移除已不存在的行
        for name in list(self.mm.get("extra", {})):
            if name not in extras:
                self.mm["extra"][name]["frame"].destroy()
                del self.mm["extra"][name]
        # 新增外部模型行（插在第三方 API 行之前）
        for name in extras:
            if name in self.mm.get("extra", {}):
                continue
            row = tk.Frame(self.mm["list"], bg=COL_CARD, padx=12, pady=7)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=name, bg=COL_CARD, fg=COL_TEXT,
                     font=("Microsoft YaHei UI", 11, "bold")).pack(side=tk.LEFT)
            tk.Label(row, text=tr("外部导入", "Imported"), bg=COL_CARD, fg=COL_SUB,
                     font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=8)
            tk.Label(row, text=tr("已安装", "Installed"), bg=COL_CARD, fg=COL_GREEN,
                     font=("Microsoft YaHei UI", 9)).pack(side=tk.RIGHT, padx=(4, 0))
            tk.Button(row, text=tr("删除", "Delete"), bg=COL_BTN, fg=COL_TEXT,
                      relief=tk.FLAT, padx=12, pady=2, font=("Microsoft YaHei UI", 9),
                      command=lambda n=name: self.mm_delete_extra(n)).pack(side=tk.RIGHT, padx=4)
            self.mm.setdefault("extra", {})[name] = {"frame": row}

    def mm_delete_extra(self, name):
        """删除外部导入的模型"""
        if not messagebox.askyesno(tr("删除模型", "Delete Model"),
                                   tr("确定删除", "Delete") + f" {name}？",
                                   parent=self.mm["win"]):
            return
        if self.delete_model(name):
            self.log(f"已删除模型 {name}")
        else:
            messagebox.showwarning(tr("删除失败", "Delete Failed"),
                                   tr("删除失败，请稍后重试", "Failed, try again later"),
                                   parent=self.mm["win"])
        self.mm_refresh()
        self.refresh_model_list()

    def open_api_config(self):
        """配置第三方 API（OpenAI 兼容）"""
        win = tk.Toplevel(self.root)
        win.title(tr("第三方 API 配置", "API Config"))
        win.configure(bg=COL_BG)
        win.geometry("480x430")  # 高度足够容纳底部按钮，避免按钮被挤出可视区
        win.resizable(False, False)
        win.transient(self.root)
        if self.mm and self.mm.get("win"):
            try:
                # 模型管理窗口可能已关闭（引用失效），失效则退回主窗口
                if self.mm["win"].winfo_exists():
                    win.transient(self.mm["win"])
            except Exception:
                pass

        tk.Label(win, text="第三方 API 配置", bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(14, 8))
        tk.Label(win, text="OpenAI 兼容接口（DeepSeek / 通义 / Kimi / OpenAI 等）",
                 bg=COL_BG, fg=COL_SUB, font=("Microsoft YaHei UI", 9)).pack()

        f = tk.Frame(win, bg=COL_CARD, padx=14, pady=10)
        f.pack(fill=tk.X, padx=20, pady=(10, 0))
        tk.Label(f, text="API 地址", bg=COL_CARD, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W)
        api_base = tk.Entry(f, bg=COL_INPUT, fg=COL_TEXT, insertbackground=COL_TEXT,
                            relief=tk.FLAT, font=("Consolas", 10))
        api_base.insert(0, T.API_BASE)
        api_base.pack(fill=tk.X, pady=(2, 8))
        tk.Label(f, text="API Key", bg=COL_CARD, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W)
        api_key = tk.Entry(f, bg=COL_INPUT, fg=COL_TEXT, insertbackground=COL_TEXT,
                           relief=tk.FLAT, font=("Consolas", 10), show="*")
        api_key.insert(0, T.API_KEY)
        api_key.pack(fill=tk.X, pady=(2, 8))
        tk.Label(f, text="模型名", bg=COL_CARD, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(anchor=tk.W)
        api_model = tk.Entry(f, bg=COL_INPUT, fg=COL_TEXT, insertbackground=COL_TEXT,
                             relief=tk.FLAT, font=("Consolas", 10))
        api_model.insert(0, T.API_MODEL)
        api_model.pack(fill=tk.X, pady=(2, 4))
        # 输入框内按回车 = 保存（用户习惯输入完直接回车确认）
        for _e in (api_base, api_key, api_model):
            _e.bind("<Return>", lambda ev: save())

        tk.Label(win, text="示例：DeepSeek → https://api.deepseek.com/v1 · deepseek-chat\n"
                           "通义 → https://dashscope.aliyuncs.com/compatible-mode/v1 · qwen-plus",
                 bg=COL_BG, fg=COL_SUB, font=("Microsoft YaHei UI", 8),
                 justify=tk.LEFT).pack(anchor=tk.W, padx=20, pady=(8, 0))

        def save():
            s = self.load_settings()
            s["api_base"] = api_base.get().strip()
            s["api_key"] = api_key.get().strip()
            s["api_model"] = api_model.get().strip()
            self.save_settings(s)
            T.API_BASE = s["api_base"]
            T.API_KEY = s["api_key"]
            T.API_MODEL = s["api_model"]
            if not (T.API_BASE and T.API_MODEL):
                # 清空了配置 → 若当前是 API 引擎则切回本地
                if T.ENGINE == "api":
                    T.ENGINE = "ollama"
                    self.model_var.set(MODEL_DEFAULT)
                    self._refresh_engine_label()
                messagebox.showwarning("配置不完整", "API 地址和模型名不能为空，已保存为空配置", parent=win)
            else:
                self.log(f"第三方 API 已配置: {T.API_MODEL}")
            self.refresh_model_list()
            if self.mm:
                self.mm_refresh()
            win.destroy()

        btn_row = tk.Frame(win, bg=COL_BG)
        btn_row.pack(pady=(14, 12))
        tk.Button(btn_row, text="保存", bg=COL_ACCENT, fg="white", relief=tk.FLAT,
                  padx=24, pady=5, font=("Microsoft YaHei UI", 10),
                  command=save).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text=tr("取消", "Cancel"), bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT,
                  padx=24, pady=5, font=("Microsoft YaHei UI", 10),
                  command=win.destroy).pack(side=tk.LEFT, padx=6)

    def mm_download(self, name):
        if self.mm.get("downloading"):
            messagebox.showinfo("提示", "已有模型在下载，请稍候", parent=self.mm["win"])
            return
        self.mm["downloading"] = name
        self.mm["label"].config(text=f"正在下载 {name} ...")
        self.mm["bar"].config(value=0)
        self.log(f"开始下载模型 {name}")
        threading.Thread(target=self._mm_download_worker, args=(name,), daemon=True).start()

    def _mm_download_worker(self, name):
        def cb(status, percent):
            self.msg_queue.put(("model_progress", name, status, percent))
        ok = self.pull_model(name, cb)
        self.msg_queue.put(("model_done", name, ok))

    def mm_delete(self, name):
        if not messagebox.askyesno("删除模型", f"确定删除 {name} 吗？\n删除后需重新下载才能使用。",
                                   parent=self.mm["win"]):
            return
        if self.delete_model(name):
            self.log(f"已删除模型 {name}")
        else:
            messagebox.showwarning("删除失败", "删除失败，请稍后重试", parent=self.mm["win"])
        self.mm_refresh()
        self.refresh_model_list()

    # ---------------- 模型存储位置 ----------------
    def mm_change_dir(self):
        """更改模型存储位置（可选择移动现有模型）"""
        if self.mm.get("moving") or self.mm.get("downloading"):
            messagebox.showinfo("提示", "有操作进行中，请稍候", parent=self.mm["win"])
            return
        new_dir = filedialog.askdirectory(title="选择模型存储位置", parent=self.mm["win"])
        if not new_dir:
            return
        new_dir = os.path.normpath(new_dir)
        old_dir = self.get_model_dir()
        if old_dir and os.path.normpath(old_dir).lower() == new_dir.lower():
            return
        move = False
        if old_dir and os.path.isdir(os.path.join(old_dir, "blobs")):
            move = messagebox.askyesno(
                "移动现有模型？",
                f"新位置：{new_dir}\n\n是否把现有模型（{old_dir}）移动到新位置？\n"
                "选【是】= 移动（大文件可能需几分钟）\n选【否】= 新位置从零开始下载",
                parent=self.mm["win"])
        self.mm["moving"] = True
        self.mm["bar"].config(mode="indeterminate")
        self.mm["bar"].start(15)
        self.mm["label"].config(text="正在切换模型存储位置...")
        threading.Thread(target=self._change_dir_worker,
                         args=(new_dir, old_dir, move), daemon=True).start()

    def _change_dir_worker(self, new_dir, old_dir, move):
        try:
            self.msg_queue.put(("mm_status", "正在停止模型服务..."))
            subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
            subprocess.run(["taskkill", "/f", "/im", "llama-server.exe"], capture_output=True,
                            creationflags=subprocess.CREATE_NO_WINDOW)
            time.sleep(2)
            os.makedirs(new_dir, exist_ok=True)
            if move and old_dir:
                self.msg_queue.put(("mm_status", "正在移动模型文件（大文件需要几分钟）..."))
                self._move_models(old_dir, new_dir)
            self.save_settings({"model_dir": new_dir})
            self.msg_queue.put(("mm_status", "✅ 已保存，正在重启模型服务..."))
            subprocess.Popen([OLLAMA_EXE, "serve"],
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             env=self.build_serve_env())
            for _ in range(30):
                time.sleep(1)
                try:
                    urllib.request.urlopen("http://localhost:11434/", timeout=2)
                    break
                except Exception:
                    pass
            self.msg_queue.put(("mm_done", None))
        except Exception as e:
            self.msg_queue.put(("mm_done", str(e)))

    def _move_models(self, src, dst):
        """复制模型目录到新位置（文件级进度回传），复制成功后才删除源"""
        for root, _, files in os.walk(src):
            rel = os.path.relpath(root, src)
            target = dst if rel == "." else os.path.join(dst, rel)
            os.makedirs(target, exist_ok=True)
            for f in files:
                s = os.path.join(root, f)
                size_mb = os.path.getsize(s) / 1048576
                self.msg_queue.put(("mm_status", f"移动 {f[:20]}... ({size_mb:.0f} MB)"))
                shutil.copy2(s, os.path.join(target, f))
        shutil.rmtree(src)  # 全部复制成功后才删除源目录

    # ---------------- 自定义翻译 Prompt ----------------
    def open_prompt_editor(self):
        """第一层入口：编辑自定义翻译 Prompt（倾向预设 + 自由编辑）"""
        win = tk.Toplevel(self.root)
        win.title(tr("翻译 Prompt", "Prompt"))
        win.configure(bg=COL_BG)
        win.geometry("560x480")
        win.resizable(False, False)
        win.transient(self.root)

        tk.Label(win, text="翻译 Prompt", bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 14, "bold")).pack(pady=(14, 6))

        # 倾向快捷选择
        tend_row = tk.Frame(win, bg=COL_BG)
        tend_row.pack(fill=tk.X, padx=24)
        tk.Label(tend_row, text="使用预设:", bg=COL_BG, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 10)).pack(side=tk.LEFT)
        preset_combo = ttk.Combobox(tend_row, values=list(TENDENCIES.keys()),
                                    state="readonly", width=12)
        preset_combo.pack(side=tk.LEFT, padx=6)

        def load_preset():
            preset_combo.set(preset_combo.get())
            prompt_text.delete("1.0", tk.END)
            prompt_text.insert("1.0", TENDENCIES[preset_combo.get()])
        preset_combo.bind("<<ComboboxSelected>>", lambda e: load_preset())

        custom_var = tk.BooleanVar(value=bool(T.CUSTOM_PROMPT))
        ttk.Checkbutton(win, text="启用自定义 Prompt（{text} 为待翻译文本占位符）",
                        variable=custom_var, style="TCheckbutton").pack(anchor=tk.W, padx=28, pady=(8, 4))
        prompt_text = tk.Text(win, height=12, bg=COL_INPUT, fg=COL_TEXT,
                              insertbackground=COL_TEXT, relief=tk.FLAT, padx=10, pady=8,
                              font=("Consolas", 9), wrap=tk.WORD)
        prompt_text.insert("1.0", T.CUSTOM_PROMPT or T.DEFAULT_TRANSLATE_PROMPT)
        prompt_text.pack(fill=tk.BOTH, expand=True, padx=24, pady=(0, 6))

        tip_row = tk.Frame(win, bg=COL_BG)
        tip_row.pack(fill=tk.X, padx=24)
        tk.Label(tip_row, text="批量翻译请保留“逐行对应一行译文”的要求，否则行数错位的内容会保留原文",
                 bg=COL_BG, fg=COL_GOLD, font=("Microsoft YaHei UI", 8)).pack(side=tk.LEFT)

        def save():
            if custom_var.get():
                T.CUSTOM_PROMPT = prompt_text.get("1.0", tk.END).strip()
            else:
                T.CUSTOM_PROMPT = None
            s = self.load_settings()
            s["custom_prompt_enabled"] = custom_var.get()
            s["custom_prompt"] = T.CUSTOM_PROMPT
            self.save_settings(s)
            self.log("翻译 Prompt 已保存" + ("（启用）" if T.CUSTOM_PROMPT else "（恢复默认）"))
            win.destroy()

        btn_row = tk.Frame(win, bg=COL_BG)
        btn_row.pack(pady=(12, 12))
        tk.Button(btn_row, text="保存", bg=COL_ACCENT, fg="white", relief=tk.FLAT,
                  padx=24, pady=5, font=("Microsoft YaHei UI", 10),
                  command=save).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="恢复默认", bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT,
                  padx=16, pady=5, font=("Microsoft YaHei UI", 10),
                  command=lambda: (prompt_text.delete("1.0", tk.END),
                                   prompt_text.insert("1.0", T.DEFAULT_TRANSLATE_PROMPT))).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text=tr("取消", "Cancel"), bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT,
                  padx=24, pady=5, font=("Microsoft YaHei UI", 10),
                  command=win.destroy).pack(side=tk.LEFT, padx=6)

    # ---------------- 设置 ----------------
    def open_settings(self):
        """设置窗口：界面语言 + 翻译 GPU 选择"""
        win = tk.Toplevel(self.root)
        win.title(tr("设置", "Settings"))
        win.configure(bg=COL_BG)
        win.geometry("440x560")
        win.resizable(False, False)
        win.transient(self.root)

        tk.Label(win, text=tr("设置", "Settings"), bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(16, 12))

        # 界面语言
        tk.Label(win, text=tr("界面语言", "Interface Language"), bg=COL_BG,
                 fg=COL_TEXT, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=36)
        lang_var = tk.StringVar(value=LANG)
        ttk.Radiobutton(win, text=tr("中文", "Chinese"),
                        variable=lang_var, value="zh",
                        style="TRadiobutton").pack(anchor=tk.W, padx=48, pady=(8, 2))
        ttk.Radiobutton(win, text=tr("English", "English"),
                        variable=lang_var, value="en",
                        style="TRadiobutton").pack(anchor=tk.W, padx=48)

        # 翻译 GPU
        gpus = self.detect_gpus()
        tk.Label(win, text=tr("翻译 GPU", "Translation GPU"), bg=COL_BG,
                 fg=COL_TEXT, font=("Microsoft YaHei UI", 11, "bold")).pack(anchor=tk.W, padx=36, pady=(16, 4))
        gpu_values = [tr("自动（全部显卡）", "Auto (all GPUs)")]
        gpu_map = {gpu_values[0]: None}
        for idx, name, mem in gpus:
            label = f"GPU {idx}: {name} ({mem})"
            gpu_values.append(label)
            gpu_map[label] = idx
        gpu_var = tk.StringVar(value=gpu_values[0])
        if self.gpu_index is not None:
            for label, idx in gpu_map.items():
                if idx == self.gpu_index:
                    gpu_var.set(label)
                    break
        gpu_combo = ttk.Combobox(win, textvariable=gpu_var, values=gpu_values,
                                 state="readonly", width=34)
        gpu_combo.pack(anchor=tk.W, padx=48)
        tk.Label(win, text=tr("指定翻译专用显卡，其他显卡可留给游戏/桌面",
                              "Assign a dedicated GPU for translation; others stay free for games/desktop"),
                 bg=COL_BG, fg=COL_SUB, font=("Microsoft YaHei UI", 8),
                 wraplength=360, justify=tk.LEFT).pack(anchor=tk.W, padx=48, pady=(4, 0))
        if not gpus:
            tk.Label(win, text=tr("（未检测到 NVIDIA 显卡）", "(no NVIDIA GPU detected)"),
                     bg=COL_BG, fg=COL_RED, font=("Microsoft YaHei UI", 8)).pack(anchor=tk.W, padx=48)

        def save():
            global LANG
            LANG = lang_var.get()
            s = self.load_settings()
            s["lang"] = LANG
            s["gpu_index"] = gpu_map.get(gpu_var.get())
            self.save_settings(s)
            self.gpu_index = s["gpu_index"]
            T.GPU_VISIBLE = self.gpu_index
            self.root.title(tr(APP_TITLE, APP_TITLE_EN))
            self.log(tr("设置已保存", "Settings saved")
                     + (f" | GPU: {gpu_var.get()}" if s["gpu_index"] is not None
                        else " | GPU: " + tr("自动", "auto")))
            self._switch_mode(self.mode)  # 重建页面应用新语言
            win.destroy()

        btn_row = tk.Frame(win, bg=COL_BG)
        btn_row.pack(pady=(18, 4))
        tk.Button(btn_row, text=tr("保存", "Save"), bg=COL_ACCENT, fg="white",
                  relief=tk.FLAT, padx=24, pady=5, font=("Microsoft YaHei UI", 10),
                  command=save).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text=tr("取消", "Cancel"), bg=COL_BTN, fg=COL_TEXT,
                  relief=tk.FLAT, padx=24, pady=5, font=("Microsoft YaHei UI", 10),
                  command=win.destroy).pack(side=tk.LEFT, padx=6)
        # 第三方 API 配置入口（也可在模型管理里配置，这里方便随时修改）
        tk.Button(win, text=tr("⚙ 第三方 API 配置...", "⚙ 3rd-Party API Config..."),
                  bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT, padx=12, pady=3,
                  font=("Microsoft YaHei UI", 9),
                  command=self.open_api_config).pack(pady=(2, 0))
        # 赞助（窗口底部小链接，跳转赞助页）
        tk.Button(win, text=tr("☕ 请开发者吃碗淮南牛肉汤", "☕ Buy the dev a bowl of beef soup"),
                  bg=COL_BG, fg=COL_GOLD, relief=tk.FLAT, cursor="hand2", bd=0,
                  font=("Microsoft YaHei UI", 8),
                  command=self._open_sponsor).pack(pady=(0, 12))


    def open_model_import(self):
        """导入模型：从 Ollama 库拉取 或 导入本地 GGUF 文件"""
        if self.mm.get("downloading") or self.mm.get("moving"):
            messagebox.showinfo("提示", "有操作进行中，请稍候", parent=self.mm["win"])
            return
        win = tk.Toplevel(self.root)
        win.title(tr("导入模型", "Import Model"))
        win.configure(bg=COL_BG)
        win.geometry("480x360")
        win.resizable(False, False)
        win.transient(self.root)

        tk.Label(win, text=tr("导入模型", "Import"), bg=COL_BG, fg=COL_TEXT,
                 font=("Microsoft YaHei UI", 15, "bold")).pack(pady=(14, 10))

        # 方式 1：Ollama 库
        f1 = tk.Frame(win, bg=COL_CARD, padx=14, pady=10)
        f1.pack(fill=tk.X, padx=24, pady=4)
        tk.Label(f1, text="① 从 Ollama 库拉取（输入模型名，如 llama3.1:8b / qwen2.5:14b / deepseek-r1:7b）",
                 bg=COL_CARD, fg=COL_SUB, font=("Microsoft YaHei UI", 9),
                 wraplength=400, justify=tk.LEFT).pack(anchor=tk.W)
        row1 = tk.Frame(f1, bg=COL_CARD)
        row1.pack(fill=tk.X, pady=(6, 0))
        pull_entry = tk.Entry(row1, bg=COL_INPUT, fg=COL_TEXT, insertbackground=COL_TEXT,
                              relief=tk.FLAT, font=("Consolas", 10))
        pull_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)

        def do_pull():
            name = pull_entry.get().strip()
            if not name or ":" not in name:
                messagebox.showwarning("格式", "请输入完整模型名，如 llama3.1:8b", parent=win)
                return
            self.mm["downloading"] = name
            self.mm["label"].config(text=f"正在下载 {name} ...")
            self.mm["bar"].config(value=0)
            win.destroy()

            def cb(status, pct):
                self.msg_queue.put(("model_progress", name, status, pct))

            threading.Thread(target=self._mm_download_worker, args=(name,), daemon=True).start()

        tk.Button(row1, text=tr("下载", "Download"), bg=COL_ACCENT, fg="white", relief=tk.FLAT,
                  padx=14, pady=2, font=("Microsoft YaHei UI", 9),
                  command=do_pull).pack(side=tk.RIGHT, padx=(8, 0))

        # 方式 2：本地 GGUF
        f2 = tk.Frame(win, bg=COL_CARD, padx=14, pady=10)
        f2.pack(fill=tk.X, padx=24, pady=(10, 4))
        tk.Label(f2, text="② 导入本地 GGUF 模型文件（自动注册到本地引擎）",
                 bg=COL_CARD, fg=COL_SUB, font=("Microsoft YaHei UI", 9),
                 wraplength=400, justify=tk.LEFT).pack(anchor=tk.W)
        row2 = tk.Frame(f2, bg=COL_CARD)
        row2.pack(fill=tk.X, pady=(6, 0))
        gguf_path = tk.Entry(row2, bg=COL_INPUT, fg=COL_TEXT, insertbackground=COL_TEXT,
                             relief=tk.FLAT, font=("Consolas", 9))
        gguf_path.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        tk.Button(row2, text="浏览...", bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT,
                  padx=10, pady=2, font=("Microsoft YaHei UI", 9),
                  command=lambda: gguf_path.insert(0, filedialog.askopenfilename(
                      title="选择 GGUF 模型文件",
                      filetypes=[("GGUF 模型", "*.gguf"), ("所有文件", "*.*")]))).pack(side=tk.RIGHT, padx=(8, 0))
        row3 = tk.Frame(f2, bg=COL_CARD)
        row3.pack(fill=tk.X, pady=(6, 0))
        tk.Label(row3, text="名称（如 mymodel:q4）", bg=COL_CARD, fg=COL_SUB,
                 font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        gguf_name = tk.Entry(row3, bg=COL_INPUT, fg=COL_TEXT, insertbackground=COL_TEXT,
                             relief=tk.FLAT, font=("Consolas", 9))
        gguf_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), ipady=3)

        def do_import():
            path = gguf_path.get().strip()
            name = gguf_name.get().strip()
            if not path or not os.path.isfile(path):
                messagebox.showwarning("文件", "请选择有效的 GGUF 文件", parent=win)
                return
            if not name:
                messagebox.showwarning("名称", "请输入模型名称（如 mymodel:q4）", parent=win)
                return
            if ":" not in name:
                name = name + ":latest"
            win.destroy()
            self.mm["moving"] = True
            self.mm["bar"].config(mode="indeterminate")
            self.mm["bar"].start(15)
            self.mm["label"].config(text=f"正在导入 {name} ...")
            threading.Thread(target=self._import_gguf_worker, args=(path, name), daemon=True).start()

        tk.Button(f2, text="导入", bg=COL_ACCENT, fg="white", relief=tk.FLAT,
                  padx=14, pady=2, font=("Microsoft YaHei UI", 9),
                  command=do_import).pack(anchor=tk.E, pady=(6, 0))

        tk.Button(win, text=tr("关闭", "Close"), bg=COL_BTN, fg=COL_TEXT, relief=tk.FLAT,
                  padx=24, pady=4, font=("Microsoft YaHei UI", 10),
                  command=win.destroy).pack(pady=(12, 12))

    def _import_gguf_worker(self, gguf_path, name):
        """导入本地 GGUF：写 Modelfile → ollama create"""
        try:
            self.msg_queue.put(("mm_status", f"正在注册 {name} ..."))
            tmp_modelfile = os.path.join(APP_DIR, "_modelfile.tmp")
            with open(tmp_modelfile, "w", encoding="utf-8") as f:
                f.write(f'FROM "{gguf_path}"\n')
            env = os.environ.copy()
            env["OLLAMA_NO_TRAY"] = "1"
            md = self.get_model_dir()
            if md:
                env["OLLAMA_MODELS"] = md
            r = subprocess.run([OLLAMA_EXE, "create", name, "-f", tmp_modelfile],
                               capture_output=True, text=True, env=env, timeout=1800,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            os.remove(tmp_modelfile)
            if r.returncode != 0:
                self.msg_queue.put(("mm_done", f"导入失败: {r.stderr.strip()[-120:]}"))
                return
            self.msg_queue.put(("mm_done", None))
        except Exception as e:
            self.msg_queue.put(("mm_done", str(e)))

    # ---------------- 工具 ----------------
    def log(self, msg, trace=None):
        """写入 GUI 日志区（EZ 模式无日志区时静默）并同步落盘到 app.log"""
        # 落盘：用户反馈问题时可直接把 app.log 发给作者
        T.log_file(msg, APP_LOG, trace)
        if not hasattr(self, "log_text") or not self.log_text.winfo_exists():
            return  # EZ 模式没有日志区，静默跳过
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _refresh_status(self):
        """每 5 秒在后台线程检查 Ollama 状态，不阻塞 UI"""
        if not hasattr(self, "status_label"):
            return

        def worker():
            try:
                ok = T.check_ollama()
            except Exception:
                ok = False
            try:
                self.root.after(0, lambda: self.status_label.config(
                    text="● Ollama 运行中" if ok else "● Ollama 未运行",
                    fg=COL_GREEN if ok else COL_RED))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(5000, self._refresh_status)

    # ---------------- 拖拽 / 添加 ----------------
    def on_drop(self, event):
        for p in self.root.tk.splitlist(event.data):
            if os.path.isfile(p):
                self.add_task(p)
            else:
                self.log(f"跳过非文件: {p}")
        return event.action

    def add_file_dialog(self):
        """选择文件加入任务（拖拽区点击 / 高级模式入口）"""
        files = filedialog.askopenfilenames(
            title=tr("选择要翻译的文件", "Select files to translate"),
            filetypes=[("文本/JSON/字幕", "*.json *.txt *.md *.srt"),
                       ("所有文件", "*.*")])
        for f in files:
            self.add_task(f)

    def add_task(self, path):
        for t in self.tasks:
            if t["path"] == path and t["status"] in ("排队中", "翻译中"):
                self.log(f"任务已存在: {os.path.basename(path)}")
                return
        self.task_id_counter += 1
        task = {
            "id": self.task_id_counter,
            "path": path,
            "out_path": self._out_path(path),
            "status": "排队中",
            "cur": 0, "total": 0,
            "detail": "等待开始",
        }
        self.tasks.append(task)
        if hasattr(self, "tree") and self.tree.winfo_exists():
            self.tree.insert("", tk.END, iid=str(task["id"]),
                             values=(os.path.basename(path), "排队中", "-", "等待开始"))
        self.log(f"任务已加入: {path}")
        if self.mode == "ez":
            self.ez_count.config(text=f"待翻译 {len(self.tasks)} 个文件")
            self.ez_status.config(text=f"开始翻译: {os.path.basename(path)} ...")
            self.start_worker()  # EZ 模式拖入即自动开始
        if hasattr(self, "task_count_label") and self.task_count_label.winfo_exists():
            self.task_count_label.config(text=f"任务数: {len(self.tasks)}")

    @staticmethod
    def _out_path(path):
        """输出到【已翻译】目录；重名自动加序号"""
        stem, ext = os.path.splitext(os.path.basename(path))
        out_name = stem + ".zh" + (ext if ext.lower() != ".srt" else ".srt")
        out = os.path.join(DIR_DONE, out_name)
        n = 1
        while os.path.exists(out):
            out = os.path.join(DIR_DONE, f"{stem}.zh({n}){ext if ext.lower() != '.srt' else '.srt'}")
            n += 1
        return out

    def clear_done(self):
        for t in list(self.tasks):
            if t["status"] in ("完成", "失败"):
                if hasattr(self, "tree") and self.tree.winfo_exists():
                    self.tree.delete(str(t["id"]))
                self.tasks.remove(t)
        if hasattr(self, "task_count_label") and self.task_count_label.winfo_exists():
            self.task_count_label.config(text=f"任务数: {len(self.tasks)}")

    # ---------------- 执行 ----------------
    def start_worker(self):
        if T.ENGINE != "api" and not T.check_ollama():
            messagebox.showwarning("Ollama 未运行",
                                   "无法连接 Ollama（localhost:11434）。\n请先启动 Ollama 再开始翻译。")
            return
        if self.worker_thread and self.worker_thread.is_alive():
            self.log("翻译线程已在运行")
            return
        if not any(t["status"] == "排队中" for t in self.tasks):
            self.log("没有等待中的任务")
            return
        # 翻译模式：长线=模型常驻显存；短线=用完即卸
        if self.translate_mode_var().get() == "长线翻译":
            T.KEEP_ALIVE = -1
        else:
            T.KEEP_ALIVE = None
        # 本地翻译：点击开始后加载模型进显存（长线常驻 / 短线本次任务驻留）
        if T.ENGINE != "api":
            model = self.model_var.get().strip() or MODEL_DEFAULT
            if self._loaded_model != model:
                self.log(f"正在加载模型 {model} ...")
                T.warm_model(model)
                self._loaded_model = model
        self.stop_flag.clear()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()
        self.log("▶ 开始翻译")

    def on_parallel_change(self, event=None):
        """并行翻译数量：读取输入（数字校验，1~16，非法回退 1）并保存"""
        try:
            val = int(self.parallel_entry.get().strip())
        except Exception:
            val = 1
        val = max(1, min(val, 16))
        s = self.load_settings()
        s["parallel_count"] = val
        self.save_settings(s)
        # 回写规范化值
        self.parallel_entry.delete(0, "end")
        self.parallel_entry.insert(0, str(val))
        self.log(f"并行翻译数量: {val}")

    def translate_mode_var(self):
        """获取当前翻译模式（下拉可能尚未构建，回退设置值）"""
        try:
            if hasattr(self, "mode_combo") and self.mode_combo.winfo_exists():
                return self.mode_combo
        except Exception:
            pass
        class _Fake:
            def get(self_):
                return self.load_settings().get("translate_mode", "短线翻译")
        return _Fake()

    def stop_worker(self):
        self.stop_flag.set()
        self.log("⏹ 已请求停止（当前批次完成后停止）")

    def _worker(self):
        pending = [t for t in self.tasks if t["status"] == "排队中"]
        parallel = int(self.load_settings().get("parallel_count", 1) or 1)
        parallel = max(1, min(parallel, 16))
        if parallel <= 1:
            # 串行：逐个翻译（默认）
            for task in pending:
                if self.stop_flag.is_set():
                    break
                self._run_task(task)
        else:
            # 并行：最多 N 个任务同时翻译；停止后未开始的任务跳过
            from concurrent.futures import ThreadPoolExecutor

            def run_one(task):
                if not self.stop_flag.is_set():
                    self._run_task(task)

            with ThreadPoolExecutor(max_workers=parallel,
                                    thread_name_prefix="translate") as ex:
                futures = [ex.submit(run_one, t) for t in pending]
                for f in futures:
                    f.result()  # 等待全部结束（停止后未启动的秒回）
        # 短线模式：全部任务结束（或停止）后卸载模型，释放显存
        if (self.translate_mode_var().get() == "短线翻译"
                and T.ENGINE != "api"
               
                and self._loaded_model):
            T.unload_model(self._loaded_model)
            self.log(f"短线模式：模型 {self._loaded_model} 已卸载，显存已释放")
            self._loaded_model = None
        self.msg_queue.put(("all_done", None))

    def _run_task(self, task):
        def progress(stage, cur, total, msg):
            self.msg_queue.put(("progress", task["id"], stage, cur, total, msg))

        try:
            with open(task["path"], encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                raise ValueError("文件为空")
            model = self.model_var.get().strip() or MODEL_DEFAULT
            ext = os.path.splitext(task["path"])[1].lower()
            if ext == ".json":
                out = T.translate_json(model, content, progress=progress)
                if out is None:
                    raise ValueError("JSON 解析失败，请检查文件格式")
            elif ext == ".srt":
                out = T.translate_srt(model, content)
            else:
                out = T.translate_text(model, content)
            with open(task["out_path"], "w", encoding="utf-8") as f:
                f.write(out)
            self.msg_queue.put(("done", task["id"], task["out_path"]))
        except Exception as e:
            # 翻译失败：GUI 提示 + 日志落盘（含堆栈，用户可直接反馈 app.log）
            import traceback as _tb
            self.log(f"✘ 翻译失败: {os.path.basename(task['path'])} → {e}",
                     trace=_tb.format_exc())
            self.msg_queue.put(("error", task["id"], str(e)))

    # ---------------- 主线程 UI 更新 ----------------
    def _poll_queue(self):
        try:
            while True:
                self._handle_msg(self.msg_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_msg(self, item):
        kind = item[0]
        if kind == "progress":
            _, tid, stage, cur, total, msg = item
            task = self._find_task(tid)
            if not task:
                return
            task["cur"], task["total"] = cur, total
            task["status"] = "翻译中"
            if self.mode == "ez":
                pct = (cur / total * 100) if total else 0
                self.ez_bar.config(value=pct)
                self.ez_status.config(
                    text=f"正在翻译: {os.path.basename(task['path'])}  （{cur}/{total} 批）")
                return
            if stage == "glossary":
                task["detail"] = msg or f"术语表 {cur}/{total}"
            elif stage == "warn":
                task["detail"] = msg
            elif stage == "batch":
                task["detail"] = f"共 {total} 批，已 {cur}"
                if cur % 5 != 0 and cur != total:
                    return
            else:
                task["detail"] = msg or f"共 {total} 批"
            self._update_row(task)
        elif kind == "done":
            _, tid, out_path = item
            task = self._find_task(tid)
            if task:
                task["status"] = "完成"
                task["detail"] = "✔ 完成"
                task["cur"] = task["total"]
                if self.mode == "ez":
                    done = sum(1 for t in self.tasks if t["status"] == "完成")
                    pending = [t for t in self.tasks if t["status"] == "排队中"]
                    self.ez_bar.config(value=100)
                    if pending:
                        self.ez_status.config(
                            text=f"✅ 完成一个（还有 {len(pending)} 个排队中）")
                    else:
                        self.ez_status.config(
                            text=f"✅ 全部完成！共翻译 {done} 个文件")
                    self.ez_count.config(text=f"已完成 {done} 个文件")
                else:
                    self._update_row(task)
                self.log(f"✔ 完成: {out_path}")
                self._open_done_dir(out_path)
        elif kind == "error":
            _, tid, err = item
            task = self._find_task(tid)
            if task:
                task["status"] = "失败"
                if self.mode == "ez":
                    self.ez_status.config(text=f"❌ 失败: {err[:50]}")
                else:
                    task["detail"] = err[:40]
                    self._update_row(task)
                self.log(f"✘ 失败: {err}")
        elif kind == "model_progress":
            _, name, status, percent = item
            if hasattr(self, "mm") and self.mm and self.mm["bar"]:
                self.mm["bar"].config(value=percent)
                self.mm["label"].config(text=f"{name}: {status} {percent:.0f}%")
            elif self.mode == "ez" and hasattr(self, "ez_bar"):
                self.ez_bar.config(value=percent)
                self.ez_status.config(text=f"下载 {name}: {status} {percent:.0f}%")
        elif kind == "model_done":
            _, name, ok = item
            self.downloading_name = None
            if hasattr(self, "mm") and self.mm:
                self.mm["downloading"] = None
                if ok:
                    self.mm["label"].config(text=f"✅ {name} 下载完成")
                    self.log(f"✅ 模型 {name} 已部署")
                    self.refresh_model_list()
                else:
                    self.mm["label"].config(text=f"❌ {name} 下载失败")
                    self.log(f"✘ 模型 {name} 下载失败")
                self.mm_refresh()
            if self.mode == "ez" and hasattr(self, "ez_bar"):
                if ok:
                    self.ez_status.config(text=f"✅ {name} 下载完成，已自动选用")
                    self.model_var.set(name)
                else:
                    self.ez_status.config(text=f"❌ {name} 下载失败")
                self._ez_refresh_cards()
                self.refresh_model_list()
        elif kind == "mm_status":
            _, msg = item
            if hasattr(self, "mm") and self.mm and self.mm["label"]:
                self.mm["label"].config(text=msg)
        elif kind == "mm_done":
            _, err = item
            if hasattr(self, "mm") and self.mm:
                self.mm["moving"] = False
                self.mm["bar"].stop()
                self.mm["bar"].config(mode="determinate", value=0)
                if err:
                    self.mm["label"].config(text=f"❌ {err}")
                else:
                    self.mm["label"].config(text="✅ 模型存储位置已更新")
                    self.mm["loc"].config(text=self.get_model_dir() or "默认位置")
                self.mm_refresh()
                self.refresh_model_list()
        elif kind == "all_done":
            self.log("全部任务处理完毕")

    def _find_task(self, tid):
        for t in self.tasks:
            if t["id"] == tid:
                return t
        return None

    def _update_row(self, task):
        if hasattr(self, "tree") and self.tree.winfo_exists() and self.tree.exists(str(task["id"])):
            self.tree.item(str(task["id"]), values=(
                os.path.basename(task["path"]),
                task["status"],
                f"{task['cur']}/{task['total']}" if task["total"] else "-",
                task["detail"]))

    def _open_done_dir(self, out_path):
        """翻译完成后打开【已翻译】目录"""
        try:
            subprocess.Popen(["explorer", os.path.normpath(DIR_DONE)])
        except Exception as e:
            self.log(f"打开已翻译目录失败: {e}")


def single_instance(mutex_name, window_title):
    """单实例锁：已存在实例时激活已有窗口并返回 False（不弹窗不残留）"""
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, window_title)
        if hwnd:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW
            user32.SetForegroundWindow(hwnd)
        return False
    return True


def main():
    if not single_instance(r"Local\AITranslatorApp", "本地 AI 翻译助手"):
        return  # 已有实例，已激活其窗口
    root = TkinterDnD.Tk()
    app = TranslateApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
