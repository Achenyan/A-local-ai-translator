#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地批量翻译脚本 —— 基于 Ollama + Qwen3
支持：.txt / .md / .srt / .json 文件，自动识别英/日文并翻译成简体中文
（.json 只翻译字符串值，key 和结构原样保留；适配 RPG Maker 翻译文件：
  纯 ASCII 值自动跳过，专有名词生成统一译名，特殊符号/换行保留）

用法：
    python translate.py 文件1 [文件2 ...]          # 翻译一个或多个文件
    python translate.py --model qwen3:30b 文件.txt  # 指定其他模型
    python translate.py --test                      # 快速自检（不翻译文件）
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

API_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3:8b"
BLOCK_CHARS = 1200          # 每块最大字符数（避免超上下文）
TEMPERATURE = 0.2           # 翻译用低温度，保证忠实
NUM_CTX = 4096              # 上下文长度（翻译任务足够，8GB 显存更稳）
REQUEST_TIMEOUT = 180       # 单次请求超时（秒），超过则重试/重启 Ollama
FAIL_LIMIT = 2              # 连续失败多少次后重启 Ollama

# 翻译引擎配置（GUI 可通过修改这些模块级变量切换后端）
ENGINE = "ollama"           # "ollama"=本地 | "api"=外部 OpenAI 兼容 API
API_BASE = ""               # 如 https://api.deepseek.com/v1
API_KEY = ""
API_MODEL = ""
CUSTOM_PROMPT = None        # 自定义翻译 prompt 模板（{text} 为待翻译文本占位符）
GPU_VISIBLE = None          # 翻译专用显卡（CUDA_VISIBLE_DEVICES 值，None=自动/全部）
def log_file(msg, path, trace=None):
    """追加一行到日志文件（UTF-8，人类可读；超过 2MB 自动轮转保留 .old）
    trace 非空时附带异常堆栈（用户反馈问题时可整体发给作者）"""
    try:
        MAX = 2 * 1024 * 1024
        if os.path.exists(path) and os.path.getsize(path) > MAX:
            try:
                os.replace(path, path + ".old")
            except Exception:
                pass
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            if trace:
                f.write(f"[{ts}]    → {trace}\n")
    except Exception:
        pass


# 日文假名区间（平假名 + 片假名 + 半角片假名），用于英/日语言判断
JAPANESE_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff61-\uff9f]")
# 片假名词组（含半角），用于提取专有名词
KATA_RE = re.compile(r"[\u3040-\u309f\u30a0-\u30ff\uff61-\uff9f]{2,}")


def detect_lang(text):
    """粗略判断：含日文假名 → ja，否则按英文处理"""
    return "ja" if JAPANESE_RE.search(text) else "en"


KEEP_ALIVE = None  # None=Ollama 默认(5分钟)；-1=常驻显存（长线翻译模式）


def warm_model(model):
    """把模型加载进显存（点击开始翻译后调用；已加载时秒回复用）"""
    try:
        payload = {"model": model,
                   "messages": [{"role": "user", "content": "/no_think\nhi"}],
                   "stream": False,
                   "options": {"num_predict": 1, "num_ctx": 2048}}
        if KEEP_ALIVE:
            payload["keep_alive"] = KEEP_ALIVE
        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=120).read()
        return True
    except Exception:
        return False


def unload_model(model):
    """卸载指定模型（keep_alive=0），立即释放显存"""
    try:
        payload = {"model": model, "keep_alive": 0}
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception:
        return False


def chat_ollama(model, content):
    """调用本地 Ollama API 生成一次回复（system 指令关闭思考模式，翻译无需推理）
    num_predict 限制生成长度，防止模型病态重复生成导致卡死"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "/no_think"},
            {"role": "user", "content": content},
        ],
        "stream": False,
        "options": {"temperature": TEMPERATURE, "num_ctx": NUM_CTX,
                    "num_predict": 2048},
    }
    if KEEP_ALIVE:
        payload["keep_alive"] = KEEP_ALIVE  # 长线模式：模型常驻显存
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["message"]["content"].strip()


def chat_api(content):
    """调用外部 OpenAI 兼容 API（DeepSeek/通义/Kimi/OpenAI 等）"""
    url = API_BASE.rstrip("/") + "/chat/completions"
    payload = {
        "model": API_MODEL,
        "messages": [
            # Qwen 系模型：system 里的 /no_think 指令关闭思考模式（减少 token 消耗）
            {"role": "system", "content": "/no_think"},
            {"role": "user", "content": content},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": 2048,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = "Bearer " + API_KEY
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    msg = data["choices"][0]["message"]
    # Qwen 系思考内容在 reasoning 字段；正常取 content，为空时兜底
    content_out = (msg.get("content") or "").strip()
    if not content_out:
        content_out = (msg.get("reasoning") or "").strip()
    return content_out


def chat(model, content):
    """统一入口：按 ENGINE 选择本地 Ollama 或外部 API"""
    if ENGINE == "api":
        return chat_api(content)
    return chat_ollama(model, content)


def make_prompt(fallback, *args, **kw):
    """统一 prompt 构造：设置自定义模板时优先使用（{text} 替换为待翻译文本）"""
    if CUSTOM_PROMPT:
        text = args[0] if args else kw.get("text", "")
        if "{text}" in CUSTOM_PROMPT:
            return CUSTOM_PROMPT.replace("{text}", text)
        return f"{CUSTOM_PROMPT}\n\n{text}"
    return fallback(*args, **kw)


# 供 GUI 设置界面展示的默认逐行翻译模板
DEFAULT_TRANSLATE_PROMPT = (
    "你是专业的游戏本地化翻译。请把下面的日文逐行翻译成简体中文，每行对应一行译文。\n"
    "要求：\n"
    "1. 译文准确、自然，符合游戏口语风格\n"
    "2. 专有名词（人名/地名）音译并保持全文一致\n"
    "3. 保留原文中的换行和特殊符号（♥ ｗ ！？ …… ゛ 等）\n"
    "4. 技能名、物品名简短通顺\n"
    "5. 只输出译文，不要行号、编号或解释\n\n"
    "原文：\n{text}"
)


def restart_ollama():
    """llama-server 卡死时重启 Ollama（Windows），返回是否成功"""
    print("  (重启 Ollama 服务...)", flush=True)
    subprocess.run(["taskkill", "/f", "/im", "ollama app.exe"],
                   capture_output=True, shell=False,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run(["taskkill", "/f", "/im", "llama-server.exe"],
                   capture_output=True, shell=False,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                   capture_output=True, shell=False,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(3)
    # serve 模式启动：无控制台窗口、无托盘图标、无 app 守护
    ollama_exe = os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")
    env = os.environ.copy()
    env["OLLAMA_NO_TRAY"] = "1"
    if not env.get("OLLAMA_MODELS") and os.path.isdir(r"E:\ollama-models"):
        env["OLLAMA_MODELS"] = r"E:\ollama-models"
    if GPU_VISIBLE is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(GPU_VISIBLE)
    subprocess.Popen([ollama_exe, "serve"],
                     creationflags=subprocess.CREATE_NO_WINDOW, env=env)
    time.sleep(10)
    try:
        urllib.request.urlopen("http://localhost:11434/", timeout=5)
        return True
    except Exception:
        return False


def build_prompt(lang, text):
    src = "日文" if lang == "ja" else "英文"
    return (
        f"你是专业翻译。请把下面的{src}翻译成简体中文。\n"
        "要求：准确忠实、通顺自然；人名地名保留原文或按通用译法；"
        "代码、网址、数字、文件名保持原样；保持原文的段落结构；"
        "只输出译文，不要任何解释或额外内容。\n\n"
        f"原文：\n{text}"
    )


def build_prompt_mixed(text):
    """通用翻译 prompt（用于内容可能混合英/日文的场景，如 JSON）"""
    return (
        "你是专业翻译。请把下面的内容逐行翻译成简体中文，每行对应一行译文。\n"
        "要求：准确忠实、通顺自然；人名地名保留原文或按通用译法；"
        "代码、网址、数字、文件名保持原样；不要添加行号或编号；"
        "只输出译文，不要任何解释或额外内容。\n\n"
        f"原文：\n{text}"
    )


def build_prompt_glossary(text, glossary):
    """游戏文本翻译 prompt：带统一译名词典，适合 RPG Maker 翻译文件"""
    gloss_lines = "、".join(f"{ja}={zh}" for ja, zh in glossary.items())
    return (
        "你是专业的游戏本地化翻译。请把下面的日文逐行翻译成简体中文，每行对应一行译文。\n"
        "要求：\n"
        "1. 译文准确、自然，符合游戏口语风格\n"
        "2. 专有名词必须使用以下统一译名，不得另行翻译：\n"
        f"   {gloss_lines}\n"
        "3. 保留原文中的换行和特殊符号（♥ ｗ ！？ …… ゛ 等）\n"
        "4. 技能名、物品名简短通顺\n"
        "5. 只输出译文，不要行号、编号或解释\n\n"
        f"原文：\n{text}"
    )


def build_glossary_prompt(text):
    """让模型为专有名词生成统一译名（只保留人名/地名等，过滤语气词/语法词）"""
    return (
        "你是专业的游戏本地化翻译。以下是游戏中出现频率较高的候选词，"
        "请从中选出人名、地名、组织名、怪物名等【专有名词】，"
        "为它们生成简体中文译名，格式每行：\"序号. 原文=译文\"。\n"
        "要求：\n"
        "1. 专有名词音译，符合游戏常见译法（如 シエラ=希拉、ルミナス町=卢米纳斯镇）\n"
        "2. 语气词（はぁ、んっ、おぉ 等）、助词（この、です、もっと 等）、"
        "普通名词（おっぱい 等）【不要输出】\n"
        "3. 只输出译文行，不要解释。\n\n"
        f"候选词：\n{text}"
    )


def is_translatable(s):
    """判断字符串值是否需要翻译：空串或纯 ASCII（标识符/数字/代码/插件名）跳过"""
    if not s:
        return False
    return any(ord(ch) >= 0x2E80 for ch in s)  # 含 CJK/假名等非 ASCII 字符才翻译


def model_skip_glossary(model):
    """小模型（<2B）术语表任务质量差且耗时，直接跳过"""
    return any(t in model for t in ("0.6b", "1.7b"))


def extract_glossary(strings, top_n=25):
    """提取出现频率最高的片假名词组，作为专有名词候选"""
    counts = {}
    for s in strings:
        for m in KATA_RE.finditer(s):
            w = m.group()
            counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda x: -x[1])
            if len(w) >= 2][:top_n]


def parse_glossary(out):
    """解析模型输出的译名表（格式：序号. 原文=译文）"""
    gloss = {}
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^\d+\.\s*(.+?)[=＝→](.+)$", line) or re.match(r"^(.+?)[=＝→](.+)$", line)
        if m:
            gloss[m.group(1).strip()] = m.group(2).strip()
    return gloss


def translate_text(model, text):
    """普通文本（txt/md）：按段落分块，逐块翻译后拼接
    （单换行的大文件也会按行二次拆分，避免超长单块被截断）"""
    lang = detect_lang(text)
    paras = text.split("\n\n")  # 以空行分段

    blocks, cur, cur_len = [], [], 0
    for p in paras:
        n = len(p)
        if cur_len + n + 1 > BLOCK_CHARS and cur:
            blocks.append("\n\n".join(cur))
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += n + 1
    if cur:
        blocks.append("\n\n".join(cur))

    # 超长块（如整个文件都是单换行）按行二次拆分，防止单块超上下文被截断
    final = []
    for b in blocks:
        if len(b) <= BLOCK_CHARS:
            final.append(b)
            continue
        lines = b.split("\n")
        sub, sub_len = [], 0
        for ln in lines:
            if sub_len + len(ln) + 1 > BLOCK_CHARS and sub:
                final.append("\n".join(sub))
                sub, sub_len = [], 0
            sub.append(ln)
            sub_len += len(ln) + 1
        if sub:
            final.append("\n".join(sub))
    blocks = final

    parts = []
    total = len(blocks)
    for i, block in enumerate(blocks, 1):
        print(f"  [{i}/{total}] 翻译中...", flush=True)
        parts.append(chat(model, make_prompt(lambda t: build_prompt(lang, t), block)))
    return "\n\n".join(parts)


def translate_srt(model, content):
    """字幕文件：解析字幕块，只翻译文本行；按行合并翻译，保持行数"""
    # 解析：[(序号, 时间戳, [文本行...]), ...]
    blocks, cur = [], {}
    for line in content.splitlines():
        if line.strip() == "":
            if cur.get("idx") is not None:
                blocks.append((cur["idx"], cur["ts"], cur["text"]))
            cur = {}
            continue
        if "idx" not in cur:
            try:
                int(line.strip())
                cur["idx"] = line.strip()
                continue
            except ValueError:
                pass
        if "ts" not in cur and "-->" in line:
            cur["ts"] = line
            continue
        cur.setdefault("text", []).append(line)
    if cur.get("idx") is not None:
        blocks.append((cur["idx"], cur["ts"], cur["text"]))

    lang = detect_lang(" ".join(l for _, _, lines in blocks for l in lines))

    # 按字符数分批，批次内的文本行合并成一次请求
    batches = []  # [(start, end, [文本行...]), ...]
    buf, buf_len, start = [], 0, 0
    for i, (_, _, text_lines) in enumerate(blocks):
        n = sum(len(t) for t in text_lines)
        if buf_len + n > BLOCK_CHARS and buf:
            batches.append((start, i, buf))
            buf, buf_len = [], 0
            start = i
        buf.extend(text_lines)
        buf_len += n
    if buf:
        batches.append((start, len(blocks), buf))

    translated = {}  # 翻译结果按 (block_idx, line_idx) 存储
    total = len(batches)
    for bi, (s, e, text_lines) in enumerate(batches, 1):
        print(f"  [{bi}/{total}] 翻译中...", flush=True)
        out = chat(model, make_prompt(lambda t: build_prompt(lang, t), "\n".join(text_lines)))
        out_lines = [l for l in out.splitlines() if l.strip()]
        if len(out_lines) == len(text_lines):
            for j, (block_idx, line_idx) in enumerate(
                (idx, k) for idx in range(s, e) for k in range(len(blocks[idx][2]))
            ):
                translated[(block_idx, line_idx)] = out_lines[j]
        else:
            print(f"  警告：第 {bi} 批翻译行数不一致，保留原文", flush=True)

    # 重建 srt
    out_lines = []
    for idx, (num, ts, text_lines) in enumerate(blocks):
        out_lines.append(num)
        out_lines.append(ts)
        for k, line in enumerate(text_lines):
            out_lines.append(translated.get((idx, k), line))
        out_lines.append("")
    return "\n".join(out_lines)


def translate_json(model, content, progress=None):
    """JSON 文件：解析后只翻译字符串值，key、结构、数字等原样保留。
    适配 RPG Maker 翻译文件：纯 ASCII 值跳过、专有名词统一译名。
    progress 为可选回调 progress(stage, cur, total, msg)，用于 GUI 实时进度。
    解析失败返回 None（由调用方按普通文本处理）。"""
    def report(stage, cur=0, total=0, msg=""):
        if progress:
            progress(stage, cur, total, msg)

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return None

    # 深度优先收集所有需要翻译的字符串值（与回填顺序保持一致）
    strings = []
    def collect(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                collect(v)
        elif isinstance(obj, list):
            for v in obj:
                collect(v)
        elif isinstance(obj, str) and is_translatable(obj):
            strings.append(obj)

    collect(data)
    if not strings:
        print("  (没有需要翻译的字符串)")
        return json.dumps(data, ensure_ascii=False, indent=2)

    print(f"  (共 {len(strings)} 条文本待翻译)")
    report("scan", 0, len(strings), f"共 {len(strings)} 条文本待翻译")

    # 生成专有名词统一译名（术语表），失败或质量差则跳过（仅影响译名一致性）
    glossary = {}
    words = extract_glossary(strings)
    if words and not model_skip_glossary(model):
        print(f"  (识别到 {len(words)} 个高频专有名词，生成统一译名...)", flush=True)
        report("glossary", 0, len(words), f"识别到 {len(words)} 个专有名词，生成统一译名...")
        try:
            gtext = "\n".join(f"{i + 1}. {w}" for i, w in enumerate(words))
            glossary = parse_glossary(chat(model, build_glossary_prompt(gtext)))
            # 质量校验：过滤自映射/垃圾条目，剩余太少则弃用术语表
            glossary = {k: v for k, v in glossary.items()
                        if k != v and len(k) <= 20 and len(v) <= 20
                        and "序号" not in k and "原文" not in k and "译文" not in k}
            if len(glossary) < 3:
                glossary = {}
            print(f"  (术语表 {len(glossary)} 条：{list(glossary.items())[:5]} ...)", flush=True)
            report("glossary", len(glossary), len(words), f"术语表 {len(glossary)} 条")
        except Exception as e:
            print(f"  ⚠ 术语表生成失败（{e}），继续翻译", flush=True)
            report("glossary", 0, 0, f"术语表生成失败：{e}")

    # 字符串内的换行会破坏逐行对齐，先用罕见字符占位，翻完再换回
    for i, s in enumerate(strings):
        strings[i] = s.replace("\n", "␤").replace("\r", "␝")

    # 分批：每批最多 20 条 或 1200 字符（先到先切，保证行数对齐可靠）
    batches, cur, cur_len = [], [], 0
    for s in strings:
        n = len(s)
        if (cur_len + n + 1 > BLOCK_CHARS or len(cur) >= 20) and cur:
            batches.append(cur)
            cur, cur_len = [], 0
        cur.append(s)
        cur_len += n + 1
    if cur:
        batches.append(cur)

    use_glossary = bool(glossary)
    # 逐批翻译，按行对齐回填；行数不一致或失败时该批保留原文
    translated = []
    total = len(batches)
    fail_count = 0
    for i, batch in enumerate(batches, 1):
        print(f"  [{i}/{total}] 翻译中...", flush=True)
        report("batch", i, total, f"共 {total} 批")
        out = None
        for attempt in range(3):  # 失败重试；连续失败达到阈值时重启 Ollama 自愈
            try:
                if use_glossary:
                    out = chat(model, make_prompt(build_prompt_glossary,
                                                  "\n".join(batch), glossary))
                else:
                    out = chat(model, make_prompt(build_prompt_mixed, "\n".join(batch)))
                fail_count = 0
                break
            except Exception as e:
                fail_count += 1
                print(f"    第 {attempt + 1} 次失败：{e}", flush=True)
                if fail_count >= FAIL_LIMIT:
                    restart_ollama()
                    fail_count = 0
        if out is None:
            print(f"  警告：第 {i} 批翻译失败，保留原文", flush=True)
            report("warn", i, total, f"第 {i} 批失败，保留原文")
            translated.extend(batch)
            continue
        out_lines = [l for l in out.splitlines() if l.strip()]
        if len(out_lines) == len(batch):
            translated.extend(out_lines)
        else:
            print(f"  警告：第 {i} 批行数不一致（{len(out_lines)}/{len(batch)}），保留原文", flush=True)
            report("warn", i, total, f"第 {i} 批行数不一致，保留原文")
            translated.extend(batch)

    # 按收集顺序回填译文
    it = iter(translated)
    def fill(obj):
        if isinstance(obj, dict):
            for k in obj:
                obj[k] = fill(obj[k])
            return obj
        if isinstance(obj, list):
            return [fill(v) for v in obj]
        if isinstance(obj, str):
            if is_translatable(obj):
                return next(it).replace("␤", "\n").replace("␝", "\r")
            return obj  # 不可翻译的值原样保留
        return obj

    fill(data)
    return json.dumps(data, ensure_ascii=False, indent=2)


def translate_file(model, path):
    ext = os.path.splitext(path)[1].lower()
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        print(f"跳过空文件：{path}")
        return

    print(f"翻译 {path} ...")
    if ext == ".srt":
        out = translate_srt(model, content)
        out_path = os.path.splitext(path)[0] + ".zh.srt"
    elif ext == ".json":
        stem, e = os.path.splitext(path)
        out_path = stem + ".zh" + (e or ".txt")
        out = translate_json(model, content)
        if out is None:
            print("  ⚠ JSON 解析失败，按普通文本翻译（结构可能被破坏）")
            out = translate_text(model, content)
    else:
        out = translate_text(model, content)
        stem, e = os.path.splitext(path)
        out_path = stem + ".zh" + (e or ".txt")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"✔ 完成 -> {out_path}\n")


def check_ollama():
    """确认 Ollama 服务可用"""
    try:
        urllib.request.urlopen("http://localhost:11434/", timeout=3)
        return True
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="本地批量翻译（Ollama + Qwen3）")
    parser.add_argument("files", nargs="*", help="要翻译的文件（支持 .txt/.md/.srt）")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"模型名（默认 {DEFAULT_MODEL}）")
    parser.add_argument("--test", action="store_true", help="快速自检翻译效果")
    args = parser.parse_args()

    if not check_ollama():
        print("❌ 无法连接 Ollama（localhost:11434）。请先启动 Ollama 并下载模型。")
        sys.exit(1)

    if args.test:
        tests = [
            ("英文示例", "The quick brown fox jumps over the lazy dog. Local AI models run privately on your own hardware."),
            ("日文示例", "今日はとても良い天気です。公園で散歩しながら桜を楽しみました。"),
        ]
        for name, text in tests:
            lang = detect_lang(text)
            print(f"\n--- {name}（识别为 {'日文' if lang == 'ja' else '英文'}）---")
            print("原文：", text)
            print("译文：", chat(args.model, build_prompt(lang, text)))
        return

    if not args.files:
        parser.print_help()
        return

    for path in args.files:
        if not os.path.isfile(path):
            print(f"❌ 文件不存在：{path}")
            continue
        translate_file(args.model, path)


if __name__ == "__main__":
    main()
