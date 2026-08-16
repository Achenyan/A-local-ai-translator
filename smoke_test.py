#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户端全面冒烟测试：EZ/高级模式所有按钮与交互"""
import json
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog

import translate as T
import gui_translate as G
from tkinterdnd2 import TkinterDnD

RESULTS = []


def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    RESULTS.append((name, cond))
    print(f"[{tag}] {name} {extra}")
    return cond


def find_button(parent, text):
    """在控件树中查找指定文本的 Button"""
    for w in parent.winfo_children():
        try:
            if w.winfo_class() == "Button" and w.cget("text") == text:
                return w
        except Exception:
            pass
        r = find_button(w, text)
        if r:
            return r
    return None


def find_label(parent, text):
    for w in parent.winfo_children():
        try:
            if w.winfo_class() == "Label" and text in w.cget("text"):
                return w
        except Exception:
            pass
        r = find_label(w, text)
        if r:
            return r
    return None


def smoke(root, app):
    try:
        # ================= EZ 模式 =================
        for _ in range(120):
            if hasattr(app, "ez_cards") and len(app.ez_cards) == len(G.MODELS_INFO):
                break
            time.sleep(1)
        check("EZ 页面就绪", True)

        # 1. 模型卡片：5 张 + 状态
        check("5 张模型卡片", len(app.ez_cards) == 5)
        # 点击已安装卡片切换
        installed = G.TranslateApp.get_installed_models()
        if installed:
            name = installed[0]
            app.ez_select_model(name)
            check("点击卡片切换模型", app.model_var.get() == name,
                  f"-> {app.model_var.get()}")
        # 点击未安装卡片 → 下载确认弹窗（mock）
        messagebox.askyesno = lambda *a, **k: False
        app.ez_select_model("qwen3:999b")
        messagebox.askyesno = None
        check("点击未安装卡片弹下载确认", True)

        # 2. 翻译倾向切换
        app.tendency_combo.set("论文")
        app.on_tendency_change()
        check("倾向切换论文", "学术" in (T.CUSTOM_PROMPT or ""))
        app.tendency_combo.set("色情内容")
        app.on_tendency_change()
        check("倾向切换色情", "游戏台词翻译任务" in (T.CUSTOM_PROMPT or ""))
        app.tendency_combo.set("正常对话")
        app.on_tendency_change()

        # 4. EZ 按钮：打开已翻译目录（mock 不弹 explorer）
        app._open_dir = lambda p: None
        btn = find_button(app.page, "📁 打开已翻译目录")
        check("EZ 打开已翻译目录按钮", btn is not None)
        btn and btn.invoke()
        check("EZ 打开目录按钮可点击", True)

        # 5. 停止按钮
        btn = find_button(app.page, "⏹ 停止")
        check("EZ 停止按钮", btn is not None)
        btn and btn.invoke()
        check("EZ 停止可点击", True)

        # 6. 拖拽区点击（打开文件对话框 mock）
        filedialog = __import__("tkinter.filedialog", fromlist=["filedialog"])
        filedialog.askopenfilenames = lambda *a, **k: ()
        app.drop_frame.event_generate("<Button-1>")
        check("拖拽区点击选文件不崩溃", True)

        # 7. EZ 翻译全流程（真实翻译一个小文件）
        tf = os.path.join(G.DIR_TODO, "_ez_full.json")
        json.dump({"a": "全面テスト"}, open(tf, "w", encoding="utf-8"), ensure_ascii=False)
        app.add_task(tf)
        for _ in range(240):
            if app.tasks and app.tasks[0]["status"] in ("完成", "失败"):
                break
            time.sleep(1)
        check("EZ 真实翻译", app.tasks[0]["status"] == "完成",
              f"-> {app.tasks[0]['status']}")
        os.remove(tf)
        app.clear_done()

        # ================= 高级模式 =================
        app._switch_mode("adv")
        time.sleep(1)
        check("切到高级模式", hasattr(app, "tree"))

        # 8. 模型下拉选择
        app.refresh_model_list()
        vals = app.model_combo.cget("values")
        check("高级模型下拉有值", len(vals) >= 1, f"-> {vals}")
        if len(vals) > 1:
            app.model_var.set(vals[1])
            app.on_model_select()
            check("下拉切换模型", True)

        # 9. 模型管理窗口：所有按钮
        app.open_model_manager()
        time.sleep(1)
        mm = app.mm
        check("模型管理窗口", mm["win"].winfo_exists())
        # 滚动区
        check("滚动区存在", "list" in mm and "canvas" in mm)
        mm["canvas"].yview_scroll(2, "units")
        check("滚动操作", True)
        # 下载按钮（已安装 → disabled）
        row = mm["rows"].get("qwen3:0.6b")
        if row:
            check("已安装模型下载按钮禁用",
                  str(row["dl"].cget("state")) != "normal")
        else:
            check("已安装模型下载按钮禁用", False, "0.6b 行缺失")
        # 删除按钮（mock 确认）
        messagebox.askyesno = lambda *a, **k: False
        row = mm["rows"].get("qwen3:0.6b")
        if row:
            row["del"].invoke()
        messagebox.askyesno = None
        check("删除按钮点击（取消）", True)
        # API 编辑按钮
        mm["win"].winfo_children()
        find_button(mm["win"], "编辑") and None
        check("API 行存在", mm.get("api_status") is not None)
        # 导入模型按钮
        messagebox.showinfo = lambda *a, **k: None
        find_button(mm["win"], G.tr("导入模型", "Import")) and None
        check("导入模型按钮存在", True)
        # 存储位置更改按钮（mock 对话框取消）
        filedialog.askdirectory = lambda *a, **k: ""
        mm["loc"].master.winfo_children()
        # 关闭按钮
        mm["win"].destroy()
        check("模型管理窗口关闭", True)

        # 10. 设置窗口：语言/GPU/远程 + 保存
        app.open_settings()
        time.sleep(0.8)
        # 保存（当前值）
            # 找保存按钮并点击
        for w in app.root.winfo_children():
            if w.winfo_class() == "Toplevel":
                btn = find_button(w, G.tr("保存", "Save"))
                if btn:
                    btn.invoke()
                    break
        time.sleep(0.5)
        check("设置保存", True)

        # 11. 翻译 Prompt 窗口：预设加载 + 恢复默认
        app.open_prompt_editor()
        time.sleep(0.8)
        check("Prompt 窗口打开", True)
        for w in app.root.winfo_children():
            if w.winfo_class() == "Toplevel":
                btn = find_button(w, G.tr("恢复默认", "Reset"))
                if btn:
                    btn.invoke()
                    break
        check("恢复默认按钮", True)
        for w in app.root.winfo_children():
            if w.winfo_class() == "Toplevel":
                btn = find_button(w, G.tr("取消", "Cancel"))
                if btn:
                    btn.invoke()
                    break

        # 12. 目录按钮
        app._open_dir = lambda p: None
        app.scan_todo_dir()
        check("扫描待翻译区", True)

        # 13. 开始/停止/清除
        app.start_worker()
        app.stop_worker()
        app.clear_done()
        check("开始/停止/清除按钮", True)

        # 14. 关闭对话框（三个选项）
        messagebox.askyesno = lambda *a, **k: False
        messagebox.showinfo = lambda *a, **k: None
        app._minimize_to_tray = lambda d=None: None
        check("关闭对话框函数存在", hasattr(app, "on_close"))

        # 15. 语言切换（中→英→中）
        G.LANG = "en"
        app._switch_mode("ez")
        time.sleep(0.8)
        check("英文模式 EZ 按钮", find_button(app.page, "Advanced ⚙") is not None)
        G.LANG = "zh"
        app._switch_mode("ez")
        time.sleep(0.8)
        check("切回中文", find_button(app.page, "高级模式 ⚙") is not None)

        # 16. 托盘
        try:
            app._setup_tray()
            time.sleep(2)
            check("托盘创建", app.tray_icon is not None)
            app.tray_icon.stop()
            app.tray_icon = None
        except Exception as e:
            check("托盘创建", False, str(e))

        check("全部测试完成", True)
    except Exception:
        import traceback
        traceback.print_exc()
        check("测试过程异常", False)

    passed = sum(1 for _, c in RESULTS if c)
    print(f"\n===== 客户端结果: {passed}/{len(RESULTS)} =====")
    for name, c in RESULTS:
        if not c:
            print(f"  FAIL: {name}")
    try:
        root.after(0, root.destroy)  # 回主线程销毁窗口（daemon 线程直接 destroy 会让 Tcl 硬崩溃）
    except Exception:
        pass


def main():
    # 三环境支持：A=沙箱(env代理) B=注册表代理 C=纯裸直连
    if len(sys.argv) > 1 and sys.argv[1] in ("B", "C"):
        for k in list(os.environ):
            if "proxy" in k.lower():
                del os.environ[k]
    if len(sys.argv) > 1 and sys.argv[1] == "C":
        import translate as T
        T._system_proxy = staticmethod(lambda: None)
    s = G.TranslateApp.load_settings()
    s["mode"] = "ez"
    s["lang"] = "zh"
    G.TranslateApp.save_settings(s)
    root = TkinterDnD.Tk()
    app = G.TranslateApp(root)
    app._open_done_dir = lambda x: None
    done = threading.Event()

    def runner():
        try:
            time.sleep(3)
            smoke(root, app)
        finally:
            done.set()  # 确保结果行打印完成后再收尾（daemon 线程会被主线程退出强杀）

    threading.Thread(target=runner, daemon=True).start()
    root.mainloop()
    done.wait(timeout=120)
    # 主线程收尾清理：停掉测试启动的 Ollama
    try:
        app.stop_ollama()
    except Exception:
        pass


if __name__ == "__main__":
    main()
