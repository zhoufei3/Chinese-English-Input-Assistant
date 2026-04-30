"""
中英文输入助手 v7.6.4 (多AI提供商预留 + 翻译成功日志 + MiMo速度优化 + 自定义拟态托盘菜单版)
- 支持自定义呼出/隐藏快捷键，默认 Ctrl+Shift+Z
- 记忆上次位置 / 光标上方
- 鼠标物理级强抢焦点
- 谷歌翻译接口
- 【升级】有道免 Key 网页翻译/词典接口
- 【保留】普通翻译接口支持 Auto / Google / Youdao 切换
- 注册表开机自启
- 【新增】DeepSeek AI润色候选：中文思考，英文地道表达
- 【保留】Google / MyMemory 普通翻译兜底，AI失败也能用
"""

import tkinter as tk
from tkinter import font as tkFont, simpledialog, messagebox
import threading
import time
import ctypes
import ctypes.wintypes
import sys
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import html
import hashlib
import uuid
import queue
import re
import winreg
import traceback

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception as _dep_error:
    pystray = None
    Image = None
    ImageDraw = None
    try:
        messagebox.showerror(
            "中英输入助手 - 缺少依赖",
            "启动失败：缺少 pystray 或 pillow。\n\n请双击 start_ai_deepseek.bat 启动，它会自动安装依赖。\n也可以手动运行：py -m pip install pystray pillow\n\n错误信息：" + str(_dep_error)
        )
    except Exception:
        print("缺少依赖：", _dep_error)
    sys.exit(1)

# ───────────────────────────────────────────────────────
#  Windows API
# ───────────────────────────────────────────────────────
user32  = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

def get_async_key(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)

def get_screen_size():
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

def send_string(text):
    """
    用 Windows SendInput API 直接输入文本。
    """
    try:
        user32.keybd_event(0x12, 0, 2, 0)  # Alt UP
        user32.keybd_event(0x10, 0, 2, 0)  # Shift UP
        user32.keybd_event(0x11, 0, 2, 0)  # Ctrl UP

        PUL = ctypes.POINTER(ctypes.c_ulong)
        class KeyBdInput(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                        ("dwExtraInfo", PUL)]
        class HardwareInput(ctypes.Structure):
            _fields_ = [("uMsg",ctypes.c_ulong),("wParamL",ctypes.c_short),("wParamH",ctypes.c_ushort)]
        class MouseInput(ctypes.Structure):
            _fields_ = [("dx",ctypes.c_long),("dy",ctypes.c_long),("mouseData",ctypes.c_ulong),
                        ("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),("dwExtraInfo",PUL)]
        class _INPUTunion(ctypes.Union):
            _fields_ = [("ki", KeyBdInput), ("mi", MouseInput), ("hi", HardwareInput)]
        class INPUT(ctypes.Structure):
            _fields_ = [("type", ctypes.c_ulong), ("ii", _INPUTunion)]

        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP   = 0x0002
        INPUT_KEYBOARD    = 1
        extra = ctypes.c_ulong(0)
        
        for ch in text:
            inputs = []
            code = ord(ch)
            ki_dn = KeyBdInput(0, code, KEYEVENTF_UNICODE, 0, ctypes.pointer(extra))
            inputs.append(INPUT(INPUT_KEYBOARD, _INPUTunion(ki=ki_dn)))
            ki_up = KeyBdInput(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, ctypes.pointer(extra))
            inputs.append(INPUT(INPUT_KEYBOARD, _INPUTunion(ki=ki_up)))

            arr = (INPUT * len(inputs))(*inputs)
            user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
            time.sleep(0.015) 

    except Exception as e:
        print(f"[输入错误] {e}")


# ───────────────────────────────────────────────────────
#  配置与位置记忆
# ───────────────────────────────────────────────────────
def get_app_dir():
    """
    获取程序目录。源码运行时使用脚本目录；打包成 exe 后使用 exe 所在目录。
    这样 deepseek_config.json 会和程序放在同一目录，方便用户直接编辑。
    """
    try:
        if getattr(sys, "frozen", False):
            return os.path.dirname(os.path.abspath(sys.executable))
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()

APP_DIR = get_app_dir()
SAVE_FILE = os.path.join(APP_DIR, "input_helper_pos.json")
CONFIG_FILE = os.path.join(APP_DIR, "deepseek_config.json")

DEFAULT_CONFIG = {
    "enable_ai_polish": True,
    "ai_provider": "deepseek",

    "deepseek_api_key": "在这里粘贴你的DeepSeek API Key",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",

    "kimi_api_key": "在这里粘贴你的Kimi API Key",
    "kimi_base_url": "https://api.moonshot.cn/v1",
    "kimi_model": "moonshot-v1-8k",

    "mimo_api_key": "在这里粘贴你的Xiaomi MiMo API Key",
    "mimo_base_url": "https://api.xiaomimimo.com/v1",
    "mimo_model": "mimo-v2.5-pro",
    "mimo_top_p": 0.95,
    "mimo_temperature": 1.0,
    "mimo_timeout_seconds": 180,
    "mimo_candidates": 3,
    "mimo_max_completion_tokens": 1024,
    "mimo_stream": True,
    "mimo_use_api_key_header": True,
    "mimo_speed_mode": True,
    "mimo_thinking_type": "disabled",
    "mimo_stream_early_stop": True,
    "mimo_fast_candidates": 2,
    "mimo_fast_max_completion_tokens": 512,
    "mimo_fast_temperature": 0.2,
    "mimo_fast_top_p": 0.8,

    "default_ai_style": "natural",
    "ai_timeout_seconds": 15,
    "ai_candidates": 5,
    "temperature": 0.45,
    "verbose_translation_log": True,

    "enable_two_stage_results": True,
    "machine_translate_delay": 0.25,
    "ai_polish_delay": 0.8,
    "translation_cache_enabled": True,
    "translation_cache_max_items": 500,

    "google_timeout_seconds": 2,
    "mymemory_timeout_seconds": 2,
    "mymemory_enabled": False,
    "auto_parallel_translate": True,

    "deepseek_speed_mode": True,
    "deepseek_candidates": 2,
    "deepseek_max_tokens": 180,
    "deepseek_timeout_seconds": 15,
    "deepseek_temperature": 0.2,

    "hotkey": "Ctrl+Shift+Z",
    "hotkey_note": "可在托盘菜单里修改。支持 Ctrl+Shift+Z、Ctrl+Alt+Q、Alt+Space、F8 等格式。建议至少带 Ctrl/Alt/Shift 中的一个，避免误触。",

    "translation_engine": "auto",
    "google_enabled": True,
    "mymemory_enabled": False,

    "youdao_enabled": True,
    "youdao_mode": "web_free",
    "youdao_use_free_translate_endpoint": False,
    "youdao_use_dict_web": True,
    "youdao_timeout_seconds": 2,
    "youdao_dict_url": "https://dict.youdao.com/w/{query}/",
    "youdao_note": "v7.2开始默认使用免Key有道网页方式，不需要有道appKey/appSecret。"
}

STYLE_MAP = {
    "natural": "natural, fluent, commonly used American English",
    "title": "catchy short-video or YouTube title style, attractive but not clickbait",
    "comment": "natural social media comment style",
    "prompt": "clear AI prompt style, specific and visually descriptive when useful",
    "business": "polite and professional business English",
    "casual": "casual spoken English used in everyday conversation",
}

PREFIX_STYLE_MAP = {
    "标题:": "title", "标题：": "title", "title:": "title", "Title:": "title",
    "评论:": "comment", "评论：": "comment", "comment:": "comment", "Comment:": "comment",
    "提示词:": "prompt", "提示词：": "prompt", "prompt:": "prompt", "Prompt:": "prompt",
    "商务:": "business", "商务：": "business", "business:": "business", "Business:": "business",
    "口语:": "casual", "口语：": "casual", "casual:": "casual", "Casual:": "casual",
    "自然:": "natural", "自然：": "natural", "natural:": "natural", "Natural:": "natural",
}


AI_PROVIDER_META = {
    "deepseek": {
        "label": "DeepSeek",
        "prefix": "deepseek",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "note": "当前默认可直接使用。走 OpenAI 兼容 /chat/completions。"
    },
    "kimi": {
        "label": "Kimi",
        "prefix": "kimi",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "note": "已预留 Kimi 接口位。填入 API Key / Base URL / Model 后即可切换。"
    },
    "mimo": {
        "label": "Xiaomi MiMo",
        "prefix": "mimo",
        "default_base_url": "https://api.xiaomimimo.com/v1",
        "default_model": "mimo-v2.5-pro",
        "note": "按小米 MiMo 官方 OpenAI 兼容格式调用：base_url=https://api.xiaomimimo.com/v1，model=mimo-v2.5-pro；v7.6.4 默认开启 stream 流式读取，并把 max_completion_tokens 提升到 1024，避免推理模型只输出 reasoning 没有 visible content。"
    }
}

AI_CACHE = {}
MACHINE_CACHE = {}

LAST_MACHINE_SOURCES = []


def _now_time_str():
    try:
        return time.strftime("%H:%M:%S")
    except Exception:
        return "--:--:--"


def _short_log_text(text, limit=42):
    text = " ".join(str(text or "").split())
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def translation_log(message):
    """控制台翻译日志。可在 deepseek_config.json 里把 verbose_translation_log 改成 false 关闭。"""
    try:
        cfg = load_app_config()
        if not bool(cfg.get("verbose_translation_log", True)):
            return
    except Exception:
        pass
    try:
        print(f"[{_now_time_str()}] {message}", flush=True)
    except Exception:
        print(message, flush=True)



def _cache_get(cache, key):
    try:
        cfg = load_app_config()
        if not cfg.get("translation_cache_enabled", True):
            return None
        val = cache.get(key)
        if val is not None:
            return list(val)
    except Exception:
        return None
    return None


def _cache_set(cache, key, value):
    try:
        cfg = load_app_config()
        if not cfg.get("translation_cache_enabled", True):
            return
        cache[key] = list(value or [])
        max_items = int(cfg.get("translation_cache_max_items", 500) or 500)
        while len(cache) > max_items:
            try:
                cache.pop(next(iter(cache)))
            except Exception:
                break
    except Exception:
        pass


def ensure_config_file():
    """首次运行时自动生成 deepseek_config.json。"""
    if os.path.exists(CONFIG_FILE):
        return
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[配置文件创建失败] {e}")


def load_app_config():
    ensure_config_file()
    cfg = DEFAULT_CONFIG.copy()
    try:
        # 用 utf-8-sig 读取，可以兼容 Windows 记事本保存出来的 UTF-8 BOM，避免反复报：Unexpected UTF-8 BOM
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            user_cfg = json.load(f)
        if isinstance(user_cfg, dict):
            cfg.update(user_cfg)
    except Exception as e:
        print(f"[配置文件读取失败] {e}")

    env_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        cfg["deepseek_api_key"] = env_key

    kimi_env_key = os.getenv("KIMI_API_KEY", "").strip() or os.getenv("MOONSHOT_API_KEY", "").strip()
    if kimi_env_key:
        cfg["kimi_api_key"] = kimi_env_key

    mimo_env_key = os.getenv("MIMO_API_KEY", "").strip() or os.getenv("XIAOMI_MIMO_API_KEY", "").strip()
    if mimo_env_key:
        cfg["mimo_api_key"] = mimo_env_key
    return cfg


def save_app_config(cfg):
    try:
        merged = DEFAULT_CONFIG.copy()
        merged.update(cfg or {})
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[配置文件保存失败] {e}")



def normalize_ai_provider(provider):
    provider = str(provider or "deepseek").strip().lower()
    return provider if provider in AI_PROVIDER_META else "deepseek"


def get_ai_provider_prefix(provider):
    provider = normalize_ai_provider(provider)
    return AI_PROVIDER_META.get(provider, AI_PROVIDER_META["deepseek"]).get("prefix", "deepseek")


def get_ai_provider_runtime(cfg=None, provider=None):
    cfg = cfg or load_app_config()
    provider = normalize_ai_provider(provider or cfg.get("ai_provider", "deepseek"))
    prefix = get_ai_provider_prefix(provider)
    meta = AI_PROVIDER_META.get(provider, AI_PROVIDER_META["deepseek"])
    api_key = str(cfg.get(f"{prefix}_api_key", "")).strip()
    base_url = str(cfg.get(f"{prefix}_base_url", meta.get("default_base_url", ""))).strip()
    model = str(cfg.get(f"{prefix}_model", meta.get("default_model", ""))).strip()

    # 兼容旧配置文件：如果旧版里还是“填写你自己的...”占位符，自动回退到当前默认值。
    placeholder_words = ("填写你自己的", "在这里", "粘贴", "YOUR", "your_")
    if (not base_url) or any(w.lower() in base_url.lower() for w in placeholder_words):
        base_url = meta.get("default_base_url", "")
    if (not model) or any(w.lower() in model.lower() for w in placeholder_words):
        model = meta.get("default_model", "")

    return {
        "provider": provider,
        "label": meta.get("label", provider),
        "prefix": prefix,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "note": meta.get("note", "")
    }


def has_valid_ai_key(cfg=None, provider=None):
    cfg = cfg or load_app_config()
    runtime = get_ai_provider_runtime(cfg, provider)
    key = str(runtime.get("api_key", "")).strip()
    if not key:
        return False
    bad_words = [
        "在这里", "粘贴", "你的", "your_api_key", "YOUR",
        "DeepSeek API Key", "Kimi API Key", "Xiaomi MiMo API Key",
        "填写你自己的", "sk-xxxx"
    ]
    if any(w.lower() in key.lower() for w in bad_words):
        return False
    return len(key) >= 10


def has_valid_deepseek_key(cfg=None):
    return has_valid_ai_key(cfg, "deepseek")


def has_valid_youdao_config(cfg=None):
    """判断有道免 Key 网页接口是否启用。

    v7.2 改为参考 VOCAB LAB 的实现思路：
    - 不再要求有道智云 appKey/appSecret
    - 桌面端 Python 不受浏览器 CORS 限制，可直接请求 dict.youdao.com
    """
    cfg = cfg or load_app_config()
    return bool(cfg.get("youdao_enabled", True)) and (
        bool(cfg.get("youdao_use_free_translate_endpoint", True)) or
        bool(cfg.get("youdao_use_dict_web", True))
    )


def normalize_translation_engine(engine):
    engine = str(engine or "auto").strip().lower()
    if engine not in ("auto", "google", "youdao"):
        return "auto"
    return engine


# ───────────────────────────────────────────────────────
#  自定义全局快捷键
# ───────────────────────────────────────────────────────
VK_CONTROL = 0x11
VK_SHIFT   = 0x10
VK_ALT     = 0x12
VK_LWIN    = 0x5B
VK_RWIN    = 0x5C

SPECIAL_KEY_MAP = {
    "SPACE": 0x20, "空格": 0x20,
    "TAB": 0x09,
    "ENTER": 0x0D, "RETURN": 0x0D, "回车": 0x0D,
    "ESC": 0x1B, "ESCAPE": 0x1B,
    "BACKSPACE": 0x08, "BKSP": 0x08,
    "DELETE": 0x2E, "DEL": 0x2E,
    "INSERT": 0x2D, "INS": 0x2D,
    "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PGUP": 0x21,
    "PAGEDOWN": 0x22, "PGDN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
}

for i in range(1, 25):
    SPECIAL_KEY_MAP[f"F{i}"] = 0x70 + i - 1


def _normalize_key_name(name):
    key = str(name or "").strip()
    aliases = {
        "CONTROL": "Ctrl", "CTRL": "Ctrl", "^": "Ctrl",
        "SHIFT": "Shift",
        "ALT": "Alt", "OPTION": "Alt",
        "WIN": "Win", "WINDOWS": "Win", "CMD": "Win", "COMMAND": "Win",
        "空格": "Space", "回车": "Enter",
    }
    upper = key.upper()
    if upper in aliases:
        return aliases[upper]
    if len(key) == 1:
        return key.upper()
    if upper.startswith("F") and upper[1:].isdigit():
        return upper
    pretty = {
        "SPACE": "Space", "TAB": "Tab", "ENTER": "Enter", "RETURN": "Enter",
        "ESC": "Esc", "ESCAPE": "Esc", "BACKSPACE": "Backspace", "BKSP": "Backspace",
        "DELETE": "Delete", "DEL": "Delete", "INSERT": "Insert", "INS": "Insert",
        "HOME": "Home", "END": "End", "PAGEUP": "PageUp", "PGUP": "PageUp",
        "PAGEDOWN": "PageDown", "PGDN": "PageDown", "UP": "Up", "DOWN": "Down",
        "LEFT": "Left", "RIGHT": "Right",
    }
    return pretty.get(upper, key)


def _main_key_to_vk(main_key):
    key = str(main_key or "").strip()
    upper = key.upper()
    if len(upper) == 1 and ("A" <= upper <= "Z" or "0" <= upper <= "9"):
        return ord(upper), upper
    if upper in SPECIAL_KEY_MAP:
        return SPECIAL_KEY_MAP[upper], _normalize_key_name(upper)
    raise ValueError(f"不支持的主按键：{main_key}")


def build_hotkey_spec(hotkey_str):
    """把 Ctrl+Shift+Z 这样的字符串解析成可轮询的 VK 组合。"""
    raw = str(hotkey_str or "").strip()
    if not raw:
        raise ValueError("快捷键不能为空")

    parts = [p.strip() for p in re.split(r"\s*\+\s*", raw) if p.strip()]
    if not parts:
        raise ValueError("快捷键格式不正确")

    mods = {"ctrl": False, "shift": False, "alt": False, "win": False}
    main_parts = []

    for part in parts:
        up = part.upper()
        if up in ("CTRL", "CONTROL", "^"):
            mods["ctrl"] = True
        elif up == "SHIFT":
            mods["shift"] = True
        elif up in ("ALT", "OPTION"):
            mods["alt"] = True
        elif up in ("WIN", "WINDOWS", "CMD", "COMMAND"):
            mods["win"] = True
        else:
            main_parts.append(part)

    if len(main_parts) != 1:
        raise ValueError("快捷键必须有且只能有一个主按键，例如 Ctrl+Shift+Z")

    vk, main_label = _main_key_to_vk(main_parts[0])

    has_modifier = any(mods.values())
    is_function_key = main_label.upper().startswith("F") and main_label[1:].isdigit()
    if not has_modifier and not is_function_key:
        raise ValueError("为避免误触，字母/数字快捷键请至少搭配 Ctrl、Alt 或 Shift，例如 Ctrl+Alt+Q")

    label_parts = []
    if mods["ctrl"]: label_parts.append("Ctrl")
    if mods["shift"]: label_parts.append("Shift")
    if mods["alt"]: label_parts.append("Alt")
    if mods["win"]: label_parts.append("Win")
    label_parts.append(main_label)

    return {
        "ctrl": mods["ctrl"],
        "shift": mods["shift"],
        "alt": mods["alt"],
        "win": mods["win"],
        "main_vk": vk,
        "main_label": main_label,
        "label": "+".join(label_parts),
    }


def parse_hotkey_config(hotkey_str):
    try:
        return build_hotkey_spec(hotkey_str)
    except Exception as e:
        print(f"[快捷键配置无效，已恢复默认 Ctrl+Shift+Z] {e}")
        return build_hotkey_spec("Ctrl+Shift+Z")


def is_hotkey_down(spec):
    try:
        if spec.get("ctrl") and not get_async_key(VK_CONTROL):
            return False
        if spec.get("shift") and not get_async_key(VK_SHIFT):
            return False
        if spec.get("alt") and not get_async_key(VK_ALT):
            return False
        if spec.get("win") and not (get_async_key(VK_LWIN) or get_async_key(VK_RWIN)):
            return False
        return get_async_key(int(spec.get("main_vk")))
    except Exception:
        return False


def load_settings(default_x, default_y):
    try:
        with open(SAVE_FILE, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
            return d.get("x", default_x), d.get("y", default_y), d.get("mode", "memory")
    except Exception:
        return default_x, default_y, "memory"


def save_settings(x, y, mode):
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump({"x": x, "y": y, "mode": mode}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ───────────────────────────────────────────────────────
#  本地词典
# ───────────────────────────────────────────────────────
LOCAL_DICT = {
    "你好": ["hello", "hi", "hey"],
    "谢谢": ["thank you", "thanks"],
    "再见": ["goodbye", "bye"],
    "是": ["yes", "correct"],
    "不": ["no", "not"],
    "好的": ["okay", "alright", "got it"],
    "可以": ["can", "possible"],
}

# ───────────────────────────────────────────────────────
#  翻译 + DeepSeek AI 润色逻辑
# ───────────────────────────────────────────────────────
def detect_ai_style(text):
    """
    支持前缀模式：
    标题: xxx   -> title
    评论: xxx   -> comment
    提示词: xxx -> prompt
    商务: xxx   -> business
    口语: xxx   -> casual
    """
    raw = text.strip()
    for prefix, style in PREFIX_STYLE_MAP.items():
        if raw.startswith(prefix):
            cleaned = raw[len(prefix):].strip()
            return cleaned or raw, style
    cfg = load_app_config()
    return raw, cfg.get("default_ai_style", "natural") or "natural"


def parse_ai_candidates(content):
    """兼容 JSON 数组、编号列表、普通换行列表。"""
    if not content:
        return []
    content = content.strip()

    # 优先解析 JSON 数组
    try:
        start = content.find("[")
        end = content.rfind("]")
        if start != -1 and end != -1 and end > start:
            arr = json.loads(content[start:end + 1])
            if isinstance(arr, list):
                return [str(x).strip().strip('"\'') for x in arr if str(x).strip()]
    except Exception:
        pass

    # 兜底：按行解析
    lines = []
    for line in content.splitlines():
        line = line.strip()
        line = re.sub(r"^[-*•\s]*", "", line)
        line = re.sub(r"^\d+[\.、\)\]]\s*", "", line)
        line = line.strip().strip('"\'')
        if line:
            lines.append(line)
    return lines






def _extract_text_field(value):
    """兼容 OpenAI content 字段可能是字符串或 content parts 列表。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts)
    return str(value)


def read_openai_stream_response(resp, provider_label="AI", early_stop_json=False):
    """读取 OpenAI 兼容 SSE 流式返回。

    v7.6.4 增强：
    - 兼容 choices[].delta.content / choices[].message.content
    - 记录 choices[].delta.reasoning_content，便于判断 MiMo 是否只输出了推理 token
    - 保存前几个原始事件预览，便于排查字段名变化
    """
    parts = []
    reasoning_parts = []
    raw_events = 0
    raw_preview = []
    early_stopped = False
    try:
        while True:
            line = resp.readline()
            if not line:
                break
            try:
                line = line.decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if not line:
                continue
            if line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw:
                continue
            if raw == "[DONE]":
                break
            raw_events += 1
            if len(raw_preview) < 3:
                raw_preview.append(raw[:500])
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            ch0 = choices[0] or {}
            delta = ch0.get("delta") or {}
            msg = ch0.get("message") or {}

            content = (
                _extract_text_field(delta.get("content"))
                or _extract_text_field(msg.get("content"))
                or _extract_text_field(ch0.get("text"))
            )
            reasoning = (
                _extract_text_field(delta.get("reasoning_content"))
                or _extract_text_field(delta.get("reasoning"))
                or _extract_text_field(msg.get("reasoning_content"))
                or _extract_text_field(msg.get("reasoning"))
            )
            if content:
                parts.append(content)
                if early_stop_json:
                    current_text = "".join(parts).strip()
                    # MiMo 速度模式：一旦可见内容已经形成可解析的 JSON 数组，就不再等待后续 token。
                    if "[" in current_text and "]" in current_text and parse_ai_candidates(current_text):
                        early_stopped = True
                        break
            if reasoning:
                reasoning_parts.append(reasoning)

        text_out = "".join(parts).strip()
        reasoning_text = "".join(reasoning_parts).strip()
        if text_out:
            translation_log(f"[AI流式读取成功] {provider_label} | events={raw_events} | content_chars={len(text_out)} | reasoning_chars={len(reasoning_text)} | early_stop={early_stopped}")
        else:
            preview = " || ".join(raw_preview).replace("\n", " ")[:1000]
            translation_log(f"[AI流式读取结束] {provider_label} | events={raw_events} | content=0 | reasoning_chars={len(reasoning_text)} | raw预览={preview}")
        return text_out
    except Exception as e:
        print(f"[{provider_label} 流式读取失败] {e}", flush=True)
        return "" 


def ai_provider_polish(text, base_candidates=None, style="natural"):
    """调用当前选中的 AI 提供商（DeepSeek / Kimi / MiMo），返回润色候选。"""
    text = text.strip()
    if not text:
        return []

    cfg = load_app_config()
    runtime = get_ai_provider_runtime(cfg)
    provider = runtime.get("provider")
    label = runtime.get("label", "AI")

    if not cfg.get("enable_ai_polish", True):
        translation_log(f"[AI跳过] AI 润色已关闭 | 输入=\"{_short_log_text(text)}\"")
        return []

    if not has_valid_ai_key(cfg, provider):
        translation_log(f"[AI跳过] {label} 缺少有效 API Key | 输入=\"{_short_log_text(text)}\"")
        return []

    base_candidates = base_candidates or []
    style = style or cfg.get("default_ai_style", "natural") or "natural"
    style_desc = STYLE_MAP.get(style, STYLE_MAP["natural"])

    cache_key = f"{provider}|{style}|{text}|{'|'.join(base_candidates[:3])}"
    if cache_key in AI_CACHE:
        cached = AI_CACHE[cache_key]
        if cached:
            translation_log(f"[AI缓存命中] {label} | 候选={len(cached)} | 输入=\"{_short_log_text(text)}\"")
        return cached

    base_url = str(runtime.get("base_url", "")).strip().rstrip("/")
    if not base_url:
        translation_log(f"[AI跳过] {label} Base URL 为空")
        return []
    if base_url.endswith("/chat/completions"):
        url = base_url
    else:
        url = f"{base_url}/chat/completions"

    max_items = int(cfg.get("ai_candidates", 5) or 5)
    max_items = max(2, min(max_items, 8))
    if provider == "deepseek" and bool(cfg.get("deepseek_speed_mode", True)):
        max_items = max(1, min(int(cfg.get("deepseek_candidates", 2) or 2), 3))
    if provider == "mimo":
        if bool(cfg.get("mimo_speed_mode", True)):
            max_items = max(1, min(int(cfg.get("mimo_fast_candidates", 2) or 2), 3))
        else:
            max_items = max(1, min(int(cfg.get("mimo_candidates", 3) or 3), 5))

    if (provider == "mimo" and bool(cfg.get("mimo_speed_mode", True))) or (provider == "deepseek" and bool(cfg.get("deepseek_speed_mode", True))):
        system_prompt = (
            "You are a fast translation engine. "
            "Do not think step by step. Do not output reasoning. "
            "Return final visible content immediately as a JSON array of English strings only."
        )
    else:
        system_prompt = (
            "You are a bilingual English writing assistant. "
            "Rewrite Chinese input into natural English. "
            "Return only a valid JSON array of English strings in the final assistant content. "
            "Do not explain. Do not output markdown."
        )

    # MiMo 速度模式：强制短 prompt + 关闭 thinking 参数，减少 reasoning token 带来的十几秒延迟。
    if provider == "mimo":
        if bool(cfg.get("mimo_speed_mode", True)):
            user_prompt = (
                f"Chinese: {text}\n"
                f"Task: Give exactly {max_items} natural English options.\n"
                "Rules: JSON array only. No explanation. No markdown. No Chinese. "
                "Example: [\"option one\", \"option two\"]"
            )
        else:
            user_prompt = (
                f"Translate and polish this Chinese into {max_items} natural English options. "
                f"Style: {style_desc}. Chinese: {text}. "
                "Put the final answer in visible content as a JSON array only. "
                "No markdown. No explanation. Example: [\"option one\", \"option two\"]"
            )
    else:
        user_prompt = f"""
Chinese input:
{text}

Machine translation reference:
{base_candidates}

Style:
{style_desc}

Requirements:
- Return {max_items} English options.
- Keep the original meaning faithful.
- Make the English natural and commonly used.
- Options should be practical for direct typing.
- Do not include Chinese.
- Do not include explanations.
- Return JSON array only.
""".strip()

    payload = {
        "model": runtime.get("model", ""),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False
    }

    if provider == "mimo":
        speed_mode = bool(cfg.get("mimo_speed_mode", True))
        if speed_mode:
            payload["max_completion_tokens"] = int(cfg.get("mimo_fast_max_completion_tokens", 512) or 512)
            payload["temperature"] = float(cfg.get("mimo_fast_temperature", 0.2) or 0.2)
            payload["top_p"] = float(cfg.get("mimo_fast_top_p", 0.8) or 0.8)
        else:
            payload["max_completion_tokens"] = int(cfg.get("mimo_max_completion_tokens", 1024) or 1024)
            payload["temperature"] = float(cfg.get("mimo_temperature", 1.0) or 1.0)
            payload["top_p"] = float(cfg.get("mimo_top_p", 0.95) or 0.95)
        thinking_type = str(cfg.get("mimo_thinking_type", "disabled") or "disabled").strip().lower()
        if thinking_type in ("disabled", "enabled", "auto"):
            payload["thinking"] = {"type": thinking_type}
        payload["stop"] = None
        payload["frequency_penalty"] = 0
        payload["presence_penalty"] = 0
        payload["stream"] = bool(cfg.get("mimo_stream", True))
    else:
        if provider == "deepseek" and bool(cfg.get("deepseek_speed_mode", True)):
            payload["temperature"] = float(cfg.get("deepseek_temperature", 0.2) or 0.2)
            payload["max_tokens"] = int(cfg.get("deepseek_max_tokens", 180) or 180)
        else:
            payload["temperature"] = float(cfg.get("temperature", 0.45) or 0.45)
            payload["max_tokens"] = 500

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {runtime['api_key']}",
        "Accept": "text/event-stream" if payload.get("stream") else "application/json",
        "User-Agent": f"ChineseInputHelper-{label}/7.6.2"
    }
    # MiMo 官方 OpenAI 示例用 OpenAI SDK 的 api_key；部分 MiMo 工具调用示例使用 api-key 头。
    # 同时发送两种头，通常兼容性更好。
    if provider == "mimo" and bool(cfg.get("mimo_use_api_key_header", True)):
        headers["api-key"] = runtime["api_key"]

    try:
        timeout = float(cfg.get("mimo_timeout_seconds", 180) or 180) if provider == "mimo" else float(cfg.get("ai_timeout_seconds", 15) or 15)
        translation_log(
            f"[AI请求] {label} | model={runtime.get('model','')} | stream={payload.get('stream')} | thinking={payload.get('thinking')} | max_completion_tokens={payload.get('max_completion_tokens')} | timeout={timeout}s | url={url} | 输入=\"{_short_log_text(text)}\""
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if payload.get("stream"):
                content = read_openai_stream_response(
                    resp,
                    provider_label=label,
                    early_stop_json=(provider == "mimo" and bool(cfg.get("mimo_stream_early_stop", True)))
                )
                data = None
            else:
                raw_body = resp.read().decode("utf-8", errors="ignore")
                data = json.loads(raw_body)
                choice0 = (data.get("choices") or [{}])[0] or {}
                msg = choice0.get("message") or {}
                content = _extract_text_field(msg.get("content")) or _extract_text_field(choice0.get("text"))
                reasoning_preview = _extract_text_field(msg.get("reasoning_content")) or _extract_text_field(msg.get("reasoning"))
                if not content and reasoning_preview:
                    translation_log(f"[AI非流式读取] {label} | content=0 | reasoning_chars={len(reasoning_preview)} | 可能是 max_completion_tokens 不足，推理模型只产生了 reasoning。")

        candidates = parse_ai_candidates(content)

        clean = []
        for item in candidates:
            item = " ".join(str(item).split()).strip()
            if not item:
                continue
            if any('一' <= ch <= '鿿' for ch in item):
                continue
            if len(item) > 180:
                continue
            if item.lower() == text.lower():
                continue
            if item not in clean:
                clean.append(item)

        final_clean = clean[:max_items]
        AI_CACHE[cache_key] = final_clean
        if final_clean:
            translation_log(f"[AI润色成功] {label} | model={runtime.get('model', '')} | 候选={len(final_clean)} | 输入=\"{_short_log_text(text)}\"")
        else:
            preview = (content or "")[:200].replace("\n", " ")
            translation_log(f"[AI润色失败] {label} 返回为空或无法解析 | content预览={preview} | 输入=\"{_short_log_text(text)}\"")
        return final_clean

    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="ignore")[:800]
            print(f"[{label} 润色失败] HTTP {e.code}: {body}", flush=True)
        except Exception:
            print(f"[{label} 润色失败] HTTP {e.code}", flush=True)
        return []
    except TimeoutError:
        print(f"[{label} 润色失败] 请求超时。当前超时设置：{timeout} 秒。可在配置里调高 {runtime.get('prefix', 'ai')}_timeout_seconds。", flush=True)
        return []
    except Exception as e:
        msg = str(e)
        if "timed out" in msg.lower():
            print(f"[{label} 润色失败] 请求超时。当前超时设置：{timeout} 秒。可在配置里调高 {runtime.get('prefix', 'ai')}_timeout_seconds。", flush=True)
        else:
            print(f"[{label} 润色失败] {e}", flush=True)
        return []


def deepseek_ai_polish(text, base_candidates=None, style="natural"):
    return ai_provider_polish(text, base_candidates=base_candidates, style=style)


def google_translate_zh_to_en(text):
    """Google 免费接口翻译。非官方公开接口，失败时返回空列表。"""
    text = text.strip()
    if not text:
        return []
    results = []
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=en&dt=t&q={urllib.parse.quote(text)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        cfg = load_app_config()
        with urllib.request.urlopen(req, timeout=float(cfg.get("google_timeout_seconds", 2) or 2)) as resp:
            data = json.loads(resp.read())
            parts = []
            for seg in data[0]:
                if seg and len(seg) > 0 and seg[0]:
                    parts.append(str(seg[0]))
            main_trans = "".join(parts).strip()
            if main_trans and main_trans.lower() != text.lower():
                results.append(main_trans)
    except Exception as e:
        print(f"[Google翻译失败] {e}", flush=True)
    final = results[:4]
    if final:
        translation_log(f"[普通翻译成功] Google | 候选={len(final)} | 输入=\"{_short_log_text(text)}\"")
    return final


def mymemory_translate_zh_to_en(text):
    """MyMemory 备用翻译接口。"""
    text = text.strip()
    if not text:
        return []
    results = []
    try:
        url = f"https://api.mymemory.translated.net/get?q={urllib.parse.quote(text)}&langpair=zh|en"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        cfg = load_app_config()
        with urllib.request.urlopen(req, timeout=float(cfg.get("mymemory_timeout_seconds", 2) or 2)) as resp:
            data = json.loads(resp.read())
            if data.get("responseStatus") == 200:
                main = data.get("responseData", {}).get("translatedText", "")
                if main and main != text and main not in results:
                    results.append(main)
                for m in data.get("matches", [])[:4]:
                    t = m.get("translation", "").strip()
                    if t and t not in results and t != text and len(t) < 120:
                        results.append(t)
    except Exception as e:
        print(f"[MyMemory翻译失败] {e}", flush=True)
    final = results[:5]
    if final:
        translation_log(f"[普通翻译成功] MyMemory | 候选={len(final)} | 输入=\"{_short_log_text(text)}\"")
    return final


def contains_cjk(text):
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def clean_html_text(raw):
    raw = re.sub(r"<script[\s\S]*?</script>", " ", raw, flags=re.I)
    raw = re.sub(r"<style[\s\S]*?</style>", " ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _split_youdao_candidate(raw):
    """把有道网页抓到的长串拆成更干净的候选。

    有道词典经常会把多个释义/短语混到同一个 li 里，例如：
    test; testing; checkout; measurement: a test in arithmetic, 算术测试 take a test; 参加测试
    这里先按明显分隔符拆开，避免整串出现在候选栏。
    """
    raw = clean_html_text(str(raw or ""))
    raw = raw.replace("｜", "|").replace("、", ";")
    pieces = re.split(r"[;；|]+", raw)
    out = []
    for p in pieces:
        p = p.strip(" \t\r\n\"'“”‘’·•-—")
        if p:
            out.append(p)
    return out or [raw]


def _clean_youdao_candidate_piece(piece, original):
    """过滤有道词典里不适合直接输入的候选。"""
    t = clean_html_text(str(piece or ""))
    t = t.strip(" \t\r\n\"'“”‘’·•-—")
    t = re.sub(r"\s+", " ", t)
    if not t:
        return ""

    # 去掉有道页面常见标签前缀。
    t = re.sub(r"^(短语|词组|网络释义|专业释义|例句|更多|柯林斯|英英释义|同近义词)\s*[:：]\s*", "", t, flags=re.I).strip()

    # 有道经常返回：measurement: a test in arithmetic, 算术测试 ...
    # 这类混合解释不是可直接输入的英文候选，直接丢弃。
    if contains_cjk(t):
        return ""

    # 原文是中文时，只保留英文候选，避免抓到数字、符号、网页噪音。
    if contains_cjk(original) and not re.search(r"[A-Za-z]", t):
        return ""

    # 去掉明显的网页/释义噪音。
    noise_patterns = [
        r"^\d+$",
        r"^查看更多",
        r"^展开",
        r"^收起",
        r"^登录",
        r"^发音",
        r"^相关词",
        r"^双语例句",
        r"^权威例句",
    ]
    if any(re.search(pat, t, flags=re.I) for pat in noise_patterns):
        return ""

    # 如果是“xxx: yyy”这种解释结构，通常不是候选词。保守过滤。
    # 允许 http(s) 之类 URL 外，普通翻译候选基本不需要冒号。
    if re.search(r"[：:]", t) and not re.match(r"https?://", t, flags=re.I):
        return ""

    # 过滤太长的词典解释。对有道候选做严格限制，AI/Google 不受这里影响。
    max_len = 60 if contains_cjk(original) else 100
    if len(t) > max_len:
        return ""

    # 短中文词查英文时，候选最好是词/短语，不要塞进长句。
    if contains_cjk(original) and len(original) <= 8:
        if len(t.split()) > 8:
            return ""

    if t.lower() == str(original).strip().lower():
        return ""
    return t


def add_candidate(results, candidate, original):
    """统一清洗候选词，避免重复、过长、中文原文回显。"""
    for piece in _split_youdao_candidate(candidate):
        t = _clean_youdao_candidate_piece(piece, original)
        if not t:
            continue
        if t not in results:
            results.append(t)


def youdao_free_json_translate(text, timeout=5):
    """
    有道免 Key 翻译端点。
    这个端点经常会返回空内容/HTML/被拦截页，所以这里做静默失败，避免控制台刷 Expected value。
    真正使用时会继续走 dict.youdao.com 词典网页，必要时再回退 Google。
    """
    results = []
    try:
        url = "https://fanyi.youdao.com/translate?doctype=json&type=AUTO&i=" + urllib.parse.quote(text, safe="")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://fanyi.youdao.com/",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore").strip()

        if not raw or raw[0] not in "[{":
            return []
        data = json.loads(raw)

        for group in data.get("translateResult", []) or []:
            for item in group or []:
                add_candidate(results, item.get("tgt", ""), text)
    except Exception:
        # 免 Key 端点不稳定，失败不视为程序错误。
        return []
    return results[:4]


def youdao_dict_web_translate(text, timeout=5):
    """
    有道词典网页抓取：参考 VOCAB LAB 的 dict.youdao.com 页面解析思路。
    VOCAB LAB 是浏览器端，所以用 api.codetabs.com 代理绕 CORS；
    本工具是 Python 桌面端，不需要代理，直接请求有道词典网页。
    """
    results = []
    try:
        cfg = load_app_config()
        tmpl = str(cfg.get("youdao_dict_url", "https://dict.youdao.com/w/{query}/") or "https://dict.youdao.com/w/{query}/")
        url = tmpl.replace("{query}", urllib.parse.quote(text))
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Referer": "https://dict.youdao.com/",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")

        # 1) VOCAB LAB 同款：.trans-container ul li
        blocks = re.findall(
            r'<div[^>]+class=["\'][^"\']*trans-container[^"\']*["\'][^>]*>([\s\S]*?)</div>',
            html_text,
            flags=re.I,
        )
        for block in blocks:
            for li in re.findall(r"<li[^>]*>([\s\S]*?)</li>", block, flags=re.I):
                add_candidate(results, li, text)
                if len(results) >= 6:
                    return results[:6]

        # 2) 有些页面的词组释义在 wordGroup / webPhrase 里，做一层兜底
        for pat in [
            r'<div[^>]+class=["\'][^"\']*wordGroup[^"\']*["\'][^>]*>([\s\S]*?)</div>',
            r'<div[^>]+id=["\']webPhrase["\'][^>]*>([\s\S]*?)</div>',
            r'<div[^>]+id=["\']tWebTrans["\'][^>]*>([\s\S]*?)</div>',
        ]:
            for block in re.findall(pat, html_text, flags=re.I):
                txt = clean_html_text(block)
                for part in re.split(r"[；;]| {2,}|\\n", txt):
                    add_candidate(results, part, text)
                    if len(results) >= 6:
                        return results[:6]

    except Exception as e:
        print(f"[有道词典网页抓取失败] {e}")
    return results[:6]


def youdao_translate_zh_to_en(text):
    """有道普通翻译。v7.2 起默认免 Key：有道翻译端点 + 有道词典网页解析。"""
    text = text.strip()
    if not text:
        return []

    cfg = load_app_config()
    if not cfg.get("youdao_enabled", True):
        return []

    timeout = float(cfg.get("youdao_timeout_seconds", 5) or 5)
    results = []

    def add_many(items):
        for item in items or []:
            add_candidate(results, item, text)

    if cfg.get("youdao_use_free_translate_endpoint", True):
        add_many(youdao_free_json_translate(text, timeout=timeout))

    # 翻译端点失败或候选太少，再走词典网页抓取。
    if cfg.get("youdao_use_dict_web", True) and len(results) < 2:
        add_many(youdao_dict_web_translate(text, timeout=timeout))

    final = results[:8]
    if final:
        translation_log(f"[普通翻译成功] 有道 | 候选={len(final)} | 输入=\"{_short_log_text(text)}\"")
    return final


def machine_translate_zh_to_en(text):
    """普通机器翻译：支持 auto / google / youdao。极速版带缓存，auto 模式可并发抢最快结果。"""
    global LAST_MACHINE_SOURCES
    LAST_MACHINE_SOURCES = []
    text = text.strip()
    if not text:
        return []

    local = LOCAL_DICT.get(text)
    if local:
        LAST_MACHINE_SOURCES = ["本地词典"]
        return local[:8]

    cfg = load_app_config()
    engine = normalize_translation_engine(cfg.get("translation_engine", "auto"))
    cache_key = f"machine|{engine}|{text}"
    cached = _cache_get(MACHINE_CACHE, cache_key)
    if cached is not None:
        LAST_MACHINE_SOURCES = ["缓存"]
        if cached:
            translation_log(f"[普通翻译缓存命中] 当前模式={engine} | 候选={len(cached)} | 输入=\"{_short_log_text(text)}\"")
        return cached[:8]

    results = []
    sources = []

    def add(items, source):
        added = 0
        for t in items or []:
            t = " ".join(str(t).split()).strip()
            if t and t != text and t not in results:
                results.append(t)
                added += 1
        if added and source not in sources:
            sources.append(source)
        return added

    def run_parallel_auto():
        q = queue.Queue()
        jobs = []
        if has_valid_youdao_config(cfg):
            jobs.append(("有道", youdao_translate_zh_to_en))
        if cfg.get("google_enabled", True):
            jobs.append(("Google", google_translate_zh_to_en))
        if not jobs:
            return False

        def worker(source, fn):
            try:
                q.put((source, fn(text)))
            except Exception as e:
                q.put((source, []))

        for source, fn in jobs:
            threading.Thread(target=worker, args=(source, fn), daemon=True).start()

        deadline = time.time() + max(float(cfg.get("google_timeout_seconds", 2) or 2), float(cfg.get("youdao_timeout_seconds", 2) or 2)) + 0.35
        got_any = False
        while time.time() < deadline and len(sources) < len(jobs):
            try:
                source, items = q.get(timeout=max(0.05, deadline - time.time()))
            except queue.Empty:
                break
            got_any = True
            if add(items, source):
                # 极速策略：auto 模式谁先返回可用候选，就先用谁，不等另一个慢接口。
                return True
        return got_any and bool(results)

    if engine == "youdao":
        add(youdao_translate_zh_to_en(text), "有道")
        if not results and cfg.get("google_enabled", True):
            add(google_translate_zh_to_en(text), "Google")
    elif engine == "google":
        if cfg.get("google_enabled", True):
            add(google_translate_zh_to_en(text), "Google")
    else:
        if cfg.get("auto_parallel_translate", True):
            run_parallel_auto()
        else:
            if has_valid_youdao_config(cfg):
                add(youdao_translate_zh_to_en(text), "有道")
            if not results and cfg.get("google_enabled", True):
                add(google_translate_zh_to_en(text), "Google")

    # 极速版默认不启用 MyMemory；只有用户显式开启，且前面结果很少时才兜底。
    if cfg.get("mymemory_enabled", False) and len(results) < 2:
        add(mymemory_translate_zh_to_en(text), "MyMemory")

    final = results[:8]
    LAST_MACHINE_SOURCES = sources
    _cache_set(MACHINE_CACHE, cache_key, final)
    if final:
        translation_log(f"[普通翻译最终成功] 接口={'+'.join(sources) if sources else '未知'} | 当前模式={engine} | 候选={len(final)} | 输入=\"{_short_log_text(text)}\"")
    else:
        translation_log(f"[普通翻译失败] 当前模式={engine} | 输入=\"{_short_log_text(text)}\"")
    return final


def translate_zh_to_en(text):
    """最终候选：AI润色优先，普通翻译兜底，并输出最终成功来源日志。"""
    text = text.strip()
    if not text:
        return []

    work_text, ai_style = detect_ai_style(text)

    # 本地词典优先，极短常用词不浪费 AI Token。
    local = LOCAL_DICT.get(work_text)
    if local:
        translation_log(f"[最终成功] 本地词典 | 候选={len(local[:8])} | 输入=\"{_short_log_text(work_text)}\"")
        return local[:8]

    normal_results = machine_translate_zh_to_en(work_text)
    machine_sources = list(LAST_MACHINE_SOURCES)
    ai_results = deepseek_ai_polish(work_text, base_candidates=normal_results, style=ai_style)

    merged = []
    for item in ai_results + normal_results:
        item = " ".join(str(item).split()).strip()
        if not item:
            continue
        if item.lower() == work_text.lower():
            continue
        if item not in merged:
            merged.append(item)

    if merged:
        if ai_results:
            runtime = get_ai_provider_runtime(load_app_config())
            ref = f"；参考普通翻译={'+'.join(machine_sources)}" if machine_sources else ""
            translation_log(f"[最终成功] {runtime.get('label', 'AI')} AI润色{ref} | 最终候选={len(merged[:8])} | 输入=\"{_short_log_text(work_text)}\"")
        else:
            translation_log(f"[最终成功] 普通翻译={'+'.join(machine_sources) if machine_sources else '未知'} | 最终候选={len(merged[:8])} | 输入=\"{_short_log_text(work_text)}\"")
        return merged[:8]

    translation_log(f"[最终失败] 所有翻译/AI 均未返回可用候选 | 输入=\"{_short_log_text(work_text)}\"")
    return [f"[{work_text}]"]


def merge_candidates(ai_results, normal_results, work_text):
    merged = []
    for item in (ai_results or []) + (normal_results or []):
        item = " ".join(str(item).split()).strip()
        if not item:
            continue
        if item.lower() == str(work_text).strip().lower():
            continue
        if item not in merged:
            merged.append(item)
    return merged[:8]


# ───────────────────────────────────────────────────────
#  主程序
# ───────────────────────────────────────────────────────
class InputHelper:
    BAR_H = 46   
    BAR_W = 700  

    # ==========================================
    # 动画设置项
    # ==========================================
    BREATH_INTERVAL = 150  # 托盘图标呼吸频率(毫秒)。默认 150。数值越大闪得越慢。

    # 拟态风格主色
    C_BG          = "#e9eef5"
    C_BORDER      = "#d1d9e6"
    C_INPUT       = "#556070"
    C_HINT        = "#97a2b1"
    C_ENTRY_BG    = "#eef3f8"
    C_CHIP_BORDER = "#d1d9e6"
    C_CHIP_TEXT   = "#6b7280"
    C_CHIP_BG     = "#eef3f8"
    C_CHIP_SEL_BG = "#7c9cff"
    C_CHIP_SEL_FG = "#ffffff"
    C_ACCENT      = "#7c9cff"
    C_NEU_LIGHT   = "#ffffff"
    C_NEU_DARK    = "#c9d3df"

    def __init__(self):
        self.enabled    = True
        self.visible    = False
        self.candidates = []
        self.sel_idx    = 0
        self.last_text  = ""
        self.tq         = queue.Queue()
        self.tq_running = True
        self.hotkey_running = True
        self.hotkey_spec = parse_hotkey_config(load_app_config().get("hotkey", "Ctrl+Shift+Z"))
        
        self.target_x = None
        self.target_y = None
        
        self.autostart_name = "ChineseInputHelper_App"

        self._build_ui()
        self._start_workers()

    def is_autostart_enabled(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
            winreg.QueryValueEx(key, self.autostart_name)
            winreg.CloseKey(key)
            return True
        except WindowsError:
            return False

    def toggle_autostart(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
            if self.is_autostart_enabled():
                winreg.DeleteValue(key, self.autostart_name)
            else:
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                else:
                    exe_path = os.path.abspath(sys.argv[0])
                winreg.SetValueEx(key, self.autostart_name, 0, winreg.REG_SZ, f'"{exe_path}"')
            winreg.CloseKey(key)
        except Exception as e:
            print(f"[设置自启失败] {e}")


    def get_ai_provider(self):
        try:
            return normalize_ai_provider(load_app_config().get("ai_provider", "deepseek"))
        except Exception:
            return "deepseek"

    def get_ai_provider_label(self):
        provider = self.get_ai_provider()
        return AI_PROVIDER_META.get(provider, AI_PROVIDER_META["deepseek"]).get("label", "DeepSeek")

    def set_ai_provider(self, provider):
        cfg = load_app_config()
        cfg["ai_provider"] = normalize_ai_provider(provider)
        save_app_config(cfg)
        self._refresh_status_dot()
        self.refresh_loading_label()
        self._update_tray_title()

    def _refresh_status_dot(self):
        try:
            if self.is_ai_ready():
                color = self.C_ACCENT
            elif self.is_ai_enabled():
                color = "#f0ad4e"
            elif has_valid_youdao_config(load_app_config()):
                color = "#7b8aa0"
            else:
                color = "#9dbf9e"
            self.status_dot.config(fg=color)
        except Exception:
            pass

    def _center_toplevel(self, win, width=760, height=640):
        try:
            sw, sh = get_screen_size()
            x = max(40, (sw - width) // 2)
            y = max(40, (sh - height) // 2)
            win.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            win.geometry(f"{width}x{height}")

    def open_settings_center(self):
        # 说明：系统托盘右键菜单是操作系统原生菜单，几乎无法做真正的拟态皮肤。
        # 所以这里新增一个自定义的“拟态设置中心”，把常用设置都集中到漂亮的窗口里。
        if getattr(self, "settings_win", None) is not None:
            try:
                if self.settings_win.winfo_exists():
                    self.settings_win.deiconify()
                    self.settings_win.lift()
                    self.settings_win.focus_force()
                    return
            except Exception:
                pass

        cfg = load_app_config()
        win = tk.Toplevel(self.root)
        self.settings_win = win
        win.title("中英输入助手 · 拟态设置中心")
        win.configure(bg=self.C_BG)
        win.resizable(False, False)
        win.transient(self.root)
        self._center_toplevel(win, 760, 680)

        outer = tk.Frame(win, bg=self.C_BG, padx=18, pady=18)
        outer.pack(fill="both", expand=True)

        def make_card(parent):
            shell = tk.Frame(parent, bg=self.C_NEU_DARK, padx=1, pady=1)
            inner = tk.Frame(shell, bg=self.C_ENTRY_BG, padx=16, pady=14)
            inner.pack(fill="both", expand=True)
            return shell, inner

        def title_label(parent, text, sub=None):
            tk.Label(parent, text=text, font=("Microsoft YaHei UI", 18, "bold"), bg=self.C_BG, fg=self.C_INPUT).pack(anchor="w")
            if sub:
                tk.Label(parent, text=sub, font=("Microsoft YaHei UI", 9), bg=self.C_BG, fg=self.C_HINT).pack(anchor="w", pady=(4, 10))

        def section_title(parent, text, sub=None):
            tk.Label(parent, text=text, font=("Microsoft YaHei UI", 11, "bold"), bg=self.C_ENTRY_BG, fg=self.C_INPUT).pack(anchor="w")
            if sub:
                tk.Label(parent, text=sub, font=("Microsoft YaHei UI", 9), bg=self.C_ENTRY_BG, fg=self.C_HINT, wraplength=660, justify="left").pack(anchor="w", pady=(2, 10))

        title_label(outer, "拟态设置中心", "AI 提供商、API Key、Base URL、Model、快捷键、普通翻译接口，都可以在这里直接修改。")

        provider_var = tk.StringVar(value=normalize_ai_provider(cfg.get("ai_provider", "deepseek")))
        enable_ai_var = tk.BooleanVar(value=bool(cfg.get("enable_ai_polish", True)))
        translation_var = tk.StringVar(value=normalize_translation_engine(cfg.get("translation_engine", "auto")))
        hotkey_var = tk.StringVar(value=self.get_hotkey_label())
        pos_var = tk.StringVar(value=self.pos_mode)

        provider_fields = {}
        for p, meta in AI_PROVIDER_META.items():
            prefix = meta.get("prefix", p)
            provider_fields[p] = {
                "api_key": tk.StringVar(value=str(cfg.get(f"{prefix}_api_key", ""))),
                "base_url": tk.StringVar(value=str(cfg.get(f"{prefix}_base_url", meta.get("default_base_url", "")))),
                "model": tk.StringVar(value=str(cfg.get(f"{prefix}_model", meta.get("default_model", ""))))
            }

        card1_shell, card1 = make_card(outer)
        card1.pack(fill="x", pady=(0, 12))
        section_title(card1, "AI 润色设置", "已预留 DeepSeek / Kimi / Xiaomi MiMo 三套接口位。Kimi 和 MiMo 后续只需要填入自己的 Key / Base URL / Model 即可切换。")

        top_line = tk.Frame(card1, bg=self.C_ENTRY_BG)
        top_line.pack(fill="x", pady=(0, 8))
        tk.Checkbutton(top_line, text="启用 AI 润色", variable=enable_ai_var, bg=self.C_ENTRY_BG, fg=self.C_INPUT,
                       activebackground=self.C_ENTRY_BG, activeforeground=self.C_INPUT, selectcolor=self.C_BG,
                       font=("Microsoft YaHei UI", 10)).pack(side="left")

        provider_btn_wrap = tk.Frame(card1, bg=self.C_ENTRY_BG)
        provider_btn_wrap.pack(fill="x", pady=(4, 10))
        provider_btns = {}
        provider_note = tk.Label(card1, text="", font=("Microsoft YaHei UI", 9), bg=self.C_ENTRY_BG, fg=self.C_HINT, wraplength=640, justify="left")
        provider_note.pack(anchor="w", pady=(0, 10))
        field_host = tk.Frame(card1, bg=self.C_ENTRY_BG)
        field_host.pack(fill="x")

        def refresh_provider_buttons():
            cur = provider_var.get()
            for p, btn in provider_btns.items():
                selected = (p == cur)
                btn.config(bg=self.C_ACCENT if selected else self.C_BG,
                           fg="#ffffff" if selected else self.C_INPUT,
                           relief="flat")

        def render_provider_fields(*args):
            for child in field_host.winfo_children():
                child.destroy()
            p = provider_var.get()
            meta = AI_PROVIDER_META.get(p, AI_PROVIDER_META["deepseek"])
            provider_note.config(text=f"当前提供商：{meta['label']}｜{meta.get('note', '')}")
            fields = provider_fields[p]
            for lab, key in (("API Key", "api_key"), ("Base URL", "base_url"), ("Model", "model")):
                tk.Label(field_host, text=lab, font=("Microsoft YaHei UI", 9, "bold"), bg=self.C_ENTRY_BG, fg=self.C_INPUT).pack(anchor="w")
                show = "•" if key == "api_key" else ""
                ent = tk.Entry(field_host, textvariable=fields[key], font=("Consolas", 10), show=show,
                               bg=self.C_BG, fg=self.C_INPUT, relief="flat", bd=0, insertbackground=self.C_ACCENT)
                ent.pack(fill="x", ipady=8, pady=(4, 8))
            tk.Label(field_host, text="提示：这三套字段都已写入配置文件结构。以后你想切到 Kimi 或 Xiaomi MiMo，只要在这里填好参数并切换提供商即可。",
                     font=("Microsoft YaHei UI", 8), bg=self.C_ENTRY_BG, fg=self.C_HINT, wraplength=640, justify="left").pack(anchor="w", pady=(4, 0))
            refresh_provider_buttons()

        for p, meta in AI_PROVIDER_META.items():
            btn = tk.Button(provider_btn_wrap, text=meta["label"], font=("Microsoft YaHei UI", 10, "bold"),
                            bg=self.C_BG, fg=self.C_INPUT, activebackground=self.C_ACCENT, activeforeground="#fff",
                            relief="flat", bd=0, padx=18, pady=10, cursor="hand2",
                            command=lambda v=p: (provider_var.set(v), render_provider_fields()))
            btn.pack(side="left", padx=(0, 10))
            provider_btns[p] = btn
        render_provider_fields()

        card2_shell, card2 = make_card(outer)
        card2.pack(fill="x", pady=(0, 12))
        section_title(card2, "普通翻译设置", "无 API Key 时，普通翻译仍可直接工作。")
        row2 = tk.Frame(card2, bg=self.C_ENTRY_BG)
        row2.pack(fill="x")
        for txt, val in (("自动（有道优先）", "auto"), ("Google", "google"), ("有道", "youdao")):
            tk.Radiobutton(row2, text=txt, value=val, variable=translation_var, bg=self.C_ENTRY_BG, fg=self.C_INPUT,
                           activebackground=self.C_ENTRY_BG, activeforeground=self.C_INPUT, selectcolor=self.C_BG,
                           font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 16))

        card3_shell, card3 = make_card(outer)
        card3.pack(fill="x", pady=(0, 12))
        section_title(card3, "快捷键与定位", "建议快捷键至少包含 Ctrl / Alt / Shift 其中之一，避免误触。")
        tk.Label(card3, text="呼出/隐藏快捷键", font=("Microsoft YaHei UI", 9, "bold"), bg=self.C_ENTRY_BG, fg=self.C_INPUT).pack(anchor="w")
        tk.Entry(card3, textvariable=hotkey_var, font=("Consolas", 11), bg=self.C_BG, fg=self.C_INPUT,
                 relief="flat", bd=0, insertbackground=self.C_ACCENT).pack(fill="x", ipady=8, pady=(4, 10))
        row3 = tk.Frame(card3, bg=self.C_ENTRY_BG)
        row3.pack(fill="x")
        for txt, val in (("记忆上次位置", "memory"), ("出现在光标上方", "cursor")):
            tk.Radiobutton(row3, text=txt, value=val, variable=pos_var, bg=self.C_ENTRY_BG, fg=self.C_INPUT,
                           activebackground=self.C_ENTRY_BG, activeforeground=self.C_INPUT, selectcolor=self.C_BG,
                           font=("Microsoft YaHei UI", 10)).pack(side="left", padx=(0, 18))

        bottom = tk.Frame(outer, bg=self.C_BG)
        bottom.pack(fill="x", pady=(6, 0))

        def save_settings_from_panel():
            try:
                spec = build_hotkey_spec(hotkey_var.get().strip())
            except Exception as e:
                messagebox.showerror("快捷键无效", str(e), parent=win)
                return

            latest = load_app_config()
            latest["enable_ai_polish"] = bool(enable_ai_var.get())
            latest["ai_provider"] = normalize_ai_provider(provider_var.get())
            latest["translation_engine"] = normalize_translation_engine(translation_var.get())
            latest["hotkey"] = spec["label"]
            for p, fields in provider_fields.items():
                prefix = AI_PROVIDER_META[p]["prefix"]
                latest[f"{prefix}_api_key"] = fields["api_key"].get().strip()
                latest[f"{prefix}_base_url"] = fields["base_url"].get().strip()
                latest[f"{prefix}_model"] = fields["model"].get().strip()
            save_app_config(latest)

            self.hotkey_spec = spec
            self.pos_mode = pos_var.get()
            save_settings(self.saved_x, self.saved_y, self.pos_mode)
            self._refresh_status_dot()
            self.refresh_loading_label()
            self._update_tray_title()
            messagebox.showinfo("已保存", "设置已保存并立即生效。", parent=win)

        tk.Button(bottom, text="保存设置", font=("Microsoft YaHei UI", 10, "bold"), bg=self.C_ACCENT, fg="#ffffff",
                  activebackground=self.C_ACCENT, activeforeground="#ffffff", relief="flat", bd=0, padx=18, pady=10,
                  cursor="hand2", command=save_settings_from_panel).pack(side="right")
        tk.Button(bottom, text="关闭", font=("Microsoft YaHei UI", 10), bg=self.C_BG, fg=self.C_INPUT,
                  activebackground=self.C_BG, activeforeground=self.C_INPUT, relief="flat", bd=0, padx=18, pady=10,
                  cursor="hand2", command=win.destroy).pack(side="right", padx=(0, 10))

        win.bind("<Escape>", lambda e: win.destroy())
        win.focus_force()

    def is_ai_enabled(self):
        try:
            return bool(load_app_config().get("enable_ai_polish", True))
        except Exception:
            return False

    def is_ai_ready(self):
        try:
            cfg = load_app_config()
            return bool(cfg.get("enable_ai_polish", True)) and has_valid_ai_key(cfg)
        except Exception:
            return False

    def toggle_ai_polish(self):
        cfg = load_app_config()
        cfg["enable_ai_polish"] = not bool(cfg.get("enable_ai_polish", True))
        save_app_config(cfg)
        self._update_tray_title()
        self._refresh_status_dot()
        self.refresh_loading_label()

    def open_config_file(self):
        ensure_config_file()
        try:
            os.startfile(CONFIG_FILE)
        except Exception as e:
            print(f"[打开配置文件失败] {e}")

    def get_hotkey_label(self):
        try:
            return self.hotkey_spec.get("label", "Ctrl+Shift+Z")
        except Exception:
            return "Ctrl+Shift+Z"



    def set_deepseek_api_key_dialog(self):
        cfg = load_app_config()
        provider = self.get_ai_provider()
        runtime = get_ai_provider_runtime(cfg, provider)
        prefix = runtime.get("prefix", provider)
        current = str(cfg.get(f"{prefix}_api_key", "")).strip()
        if not has_valid_ai_key(cfg, provider):
            current = ""
        msg = (
            f"当前 AI 提供商：{runtime['label']}\n\n"
            "请粘贴你的 API Key：\n\n"
            "保存后会写入本地 deepseek_config.json，自动使用 UTF-8 无 BOM 格式。"
        )
        key = simpledialog.askstring(
            f"设置 {runtime['label']} API Key",
            msg,
            initialvalue=current,
            parent=self.root
        )
        if key is None:
            return
        key = key.strip()
        cfg[f"{prefix}_api_key"] = key
        save_app_config(cfg)
        self._update_tray_title()
        self._refresh_status_dot()
        self.refresh_loading_label()
        if key:
            messagebox.showinfo("已保存", f"{runtime['label']} API Key 已保存。\n现在可以使用 AI 润色候选了。", parent=self.root)
        else:
            messagebox.showinfo("已清空", f"{runtime['label']} API Key 已清空。\n工具会继续使用普通翻译接口。", parent=self.root)

    def set_hotkey_dialog(self):

        current = self.get_hotkey_label()
        new_hotkey = simpledialog.askstring(
            "设置呼出/隐藏快捷键",
            "请输入新的快捷键：\n\n示例：Ctrl+Shift+Z、Ctrl+Alt+Q、Alt+Space、F8\n建议不要使用系统/软件常用快捷键。",
            initialvalue=current,
            parent=self.root
        )
        if new_hotkey is None:
            return
        try:
            spec = build_hotkey_spec(new_hotkey)
        except Exception as e:
            messagebox.showerror("快捷键无效", str(e), parent=self.root)
            return
        cfg = load_app_config()
        cfg["hotkey"] = spec["label"]
        save_app_config(cfg)
        self.hotkey_spec = spec
        self._update_tray_title()
        messagebox.showinfo("已保存", f"呼出/隐藏快捷键已改为：{spec['label']}\n立即生效。", parent=self.root)

    def get_translation_engine(self):
        try:
            return normalize_translation_engine(load_app_config().get("translation_engine", "auto"))
        except Exception:
            return "auto"

    def set_translation_engine(self, engine):
        cfg = load_app_config()
        cfg["translation_engine"] = normalize_translation_engine(engine)
        save_app_config(cfg)
        self._update_tray_title()
        self._refresh_status_dot()
        self.refresh_loading_label()

    def is_youdao_ready(self):
        try:
            return has_valid_youdao_config(load_app_config())
        except Exception:
            return False


    def get_loading_text(self):
        """根据当前真实配置显示加载提示，避免固定显示有道。"""
        try:
            cfg = load_app_config()
            if bool(cfg.get("enable_ai_polish", True)) and has_valid_ai_key(cfg):
                runtime = get_ai_provider_runtime(cfg)
                return f"{runtime.get('label', 'AI')} AI润色中..."

            engine = normalize_translation_engine(cfg.get("translation_engine", "auto"))
            if engine == "google":
                return "Google翻译中..."
            if engine == "youdao":
                return "有道翻译中..."
            # 自动模式不是固定有道，显示自动更准确
            return "自动翻译中..."
        except Exception:
            return "翻译中..."

    def refresh_loading_label(self):
        try:
            self.loading_lbl.config(text=self.get_loading_text())
        except Exception:
            pass


    def _build_ui(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        sw, sh = get_screen_size()

        self.popup = tk.Toplevel(self.root)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.attributes("-topmost", True)
        self.popup.attributes("-alpha", 0.985)
        self.popup.configure(bg=self.C_BORDER)
        self.popup.resizable(False, False)

        wrap = tk.Frame(self.popup, bg=self.C_BORDER, padx=1, pady=1)
        wrap.pack(fill="both", expand=True)

        row1 = tk.Frame(wrap, bg=self.C_BG, height=self.BAR_H)
        row1.pack(fill="x")
        row1.pack_propagate(False)

        drag_lbl = tk.Label(row1, text="≡", font=("Segoe UI", 11, "bold"), fg=self.C_HINT, bg=self.C_BG, cursor="fleur", padx=8)
        drag_lbl.pack(side="left")
        drag_lbl.bind("<ButtonPress-1>", self._drag_start)
        drag_lbl.bind("<B1-Motion>", self._drag_move)
        drag_lbl.bind("<ButtonRelease-1>", self._drag_end)

        tk.Frame(row1, bg=self.C_BG, width=4).pack(side="left")

        self.input_var = tk.StringVar()
        self.input_var.trace_add("write", self._on_input_change)
        self.entry = tk.Entry(row1, textvariable=self.input_var, font=("Microsoft YaHei UI", 13), bg=self.C_ENTRY_BG, fg=self.C_INPUT, insertbackground=self.C_ACCENT, relief="flat", bd=0, highlightthickness=0)
        self.entry.pack(side="left", fill="both", expand=True, padx=(8, 4))
        self.entry.bind("<Return>", lambda e: self._confirm() or "break")
        self.entry.bind("<Escape>", lambda e: self._hide())
        self.entry.bind("<Tab>",    lambda e: self._confirm() or "break")
        self.entry.bind("<space>",  lambda e: self._confirm_space(e))
        self.entry.bind("<Up>",     lambda e: self._move(-1) or "break")
        self.entry.bind("<Down>",   lambda e: self._move(1)  or "break")
        self.entry.bind("<Left>",   lambda e: self._move(-1) or "break")
        self.entry.bind("<Right>",  lambda e: self._move(1)  or "break")
        for i in range(1, 9):
            self.entry.bind(str(i), lambda e, idx=i-1: self._numkey_select(idx, e))

        dot_color = self.C_ACCENT if has_valid_ai_key() else ("#f0ad4e" if load_app_config().get("enable_ai_polish", True) else ("#7b8aa0" if has_valid_youdao_config() else "#9dbf9e"))
        self.status_dot = tk.Label(row1, text="●", font=("Consolas", 8), fg=dot_color, bg=self.C_BG)
        self.status_dot.pack(side="right", padx=(0,4))

        close_btn = tk.Label(row1, text="×", font=("Segoe UI", 14), fg=self.C_HINT, bg=self.C_BG, cursor="hand2", padx=10)
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._hide())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#ff6b6b"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg=self.C_HINT))

        self.cand_widgets = []
        self.cand_area = tk.Frame(row1, bg=self.C_BG)

        for i in range(8):
            outer = tk.Frame(self.cand_area, bg=self.C_CHIP_BORDER, padx=1, pady=1, cursor="hand2")
            inner = tk.Frame(outer, bg=self.C_CHIP_BG, cursor="hand2")
            inner.pack(fill="both", expand=True)
            txt = tk.Label(inner, text="", font=("Microsoft YaHei UI", 10), fg=self.C_CHIP_TEXT, bg=self.C_CHIP_BG, padx=12, pady=5, cursor="hand2")
            txt.pack()

            outer.bind("<Button-1>", lambda e, idx=i: self._select(idx))
            inner.bind("<Button-1>", lambda e, idx=i: self._select(idx))
            txt.bind( "<Button-1>", lambda e, idx=i: self._select(idx))
            outer.bind("<Enter>", lambda e, idx=i: self._hover(idx))
            inner.bind("<Enter>", lambda e, idx=i: self._hover(idx))
            txt.bind( "<Enter>", lambda e, idx=i: self._hover(idx))

            self.cand_widgets.append((outer, inner, txt))

        loading_text = self.get_loading_text()
        self.loading_lbl = tk.Label(self.cand_area, text=loading_text, font=("Microsoft YaHei UI", 9), fg=self.C_HINT, bg=self.C_BG, padx=8)

        self._breath_step  = 0
        self._breathing    = False
        self._chip_font = tkFont.Font(family="Microsoft YaHei UI", size=10)

        default_x = sw // 2 - self.BAR_W // 2
        default_y = sh // 2 - 40
        self.saved_x, self.saved_y, self.pos_mode = load_settings(default_x, default_y)
        self._tray = None
        self.settings_win = None
        self.neu_menu_win = None

    def _drag_start(self, e):
        self._dx = e.x_root - self.popup.winfo_x()
        self._dy = e.y_root - self.popup.winfo_y()

    def _drag_move(self, e):
        self.popup.geometry(f"+{e.x_root-self._dx}+{e.y_root-self._dy}")

    def _drag_end(self, e):
        self.saved_x = self.popup.winfo_x()
        self.saved_y = self.popup.winfo_y()
        save_settings(self.saved_x, self.saved_y, self.pos_mode)

    def set_pos_mode(self, mode):
        self.pos_mode = mode
        save_settings(self.saved_x, self.saved_y, mode)
        self._update_tray_title()

    def _calc_show_pos(self):
        sw, sh = get_screen_size()
        if self.pos_mode == "cursor":
            px = max(4, min(self.target_x, sw - self.BAR_W - 4)) if self.target_x else sw // 2
            py = max(4, min(self.target_y, sh - self.BAR_H - 4)) if self.target_y else sh // 2
            return px, py
        else:
            px = max(4, min(self.saved_x, sw - self.BAR_W - 4))
            py = max(4, min(self.saved_y, sh - self.BAR_H - 4))
            return px, py

    def _show(self):
        if not self.enabled:
            return

        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        self.target_x = pt.x
        self.target_y = pt.y

        px, py = self._calc_show_pos()
        self.popup.geometry(f"{self.BAR_W}x{self.BAR_H}+{px}+{py}")
        self.popup.deiconify()
        self.popup.update()

        try:
            hwnd = int(self.popup.frame(), 16)
            ctypes.windll.user32.ShowWindow(hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            ctypes.windll.user32.BringWindowToTop(hwnd)
        except Exception:
            self.popup.focus_force()

        self.entry.focus_set()
        self.visible = True
        self.input_var.set("")
        self.candidates = []
        self.sel_idx = 0
        self._redraw()

    def _hide(self):
        if self.visible:
            self.saved_x = self.popup.winfo_x()
            self.saved_y = self.popup.winfo_y()
            save_settings(self.saved_x, self.saved_y, self.pos_mode)
        self.popup.withdraw()
        self.visible    = False
        self.candidates = []
        self.sel_idx    = 0
        self.last_text  = ""
        self.cand_area.pack_forget()

    def toggle_popup(self):
        if self.visible:
            self._hide()
        else:
            self._show()


    # ───────────────────────────────────────────────────────
    #  自定义拟态托盘菜单：左键托盘图标弹出，右键仍保留系统备用菜单
    # ───────────────────────────────────────────────────────
    def _close_neu_menu(self):
        try:
            if getattr(self, "neu_menu_win", None) is not None and self.neu_menu_win.winfo_exists():
                self.neu_menu_win.destroy()
        except Exception:
            pass
        self.neu_menu_win = None

    def _neu_action(self, func, close=True):
        if close:
            self._close_neu_menu()
        try:
            func()
        finally:
            self._update_tray_title()
            self._refresh_status_dot()

    def _menu_pos_near_cursor(self, width=360, height=760):
        pt = ctypes.wintypes.POINT()
        try:
            user32.GetCursorPos(ctypes.byref(pt))
            x, y = pt.x, pt.y
        except Exception:
            sw, sh = get_screen_size()
            x, y = sw - width - 24, sh - height - 70
        sw, sh = get_screen_size()
        x = max(8, min(x - width + 14, sw - width - 8))
        y = max(8, min(y - 12, sh - height - 48))
        return x, y

    def _neu_card(self, parent, padx=12, pady=10):
        shadow = tk.Frame(parent, bg=self.C_NEU_DARK, padx=1, pady=1)
        inner = tk.Frame(shadow, bg=self.C_ENTRY_BG, padx=padx, pady=pady)
        inner.pack(fill="both", expand=True)
        return shadow, inner

    def _neu_label_row(self, parent, left, right="", icon="", fg=None):
        row = tk.Frame(parent, bg=self.C_ENTRY_BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=f"{icon} {left}" if icon else left,
                 font=("Microsoft YaHei UI", 9), bg=self.C_ENTRY_BG,
                 fg=fg or self.C_INPUT, anchor="w").pack(side="left")
        if right:
            tk.Label(row, text=right, font=("Microsoft YaHei UI", 9), bg=self.C_ENTRY_BG,
                     fg=self.C_HINT, anchor="e").pack(side="right")
        return row

    def _neu_button(self, parent, text, command, icon="", value_text=None, accent=False, danger=False):
        bg = self.C_ACCENT if accent else self.C_ENTRY_BG
        fg = "#ffffff" if accent else ("#e35b5b" if danger else self.C_INPUT)
        hover_bg = "#6f8fff" if accent else self.C_BG
        row = tk.Frame(parent, bg=bg, cursor="hand2")
        row.pack(fill="x", pady=3)
        label_text = f"{icon}  {text}" if icon else text
        left = tk.Label(row, text=label_text, font=("Microsoft YaHei UI", 10, "bold" if accent else "normal"),
                        bg=bg, fg=fg, anchor="w", padx=12, pady=8, cursor="hand2")
        left.pack(side="left", fill="x", expand=True)
        if value_text:
            right = tk.Label(row, text=value_text, font=("Microsoft YaHei UI", 9),
                             bg=bg, fg=("#ffffff" if accent else self.C_HINT), anchor="e", padx=10, cursor="hand2")
            right.pack(side="right")
        else:
            right = None

        def on_enter(_=None):
            row.config(bg=hover_bg)
            left.config(bg=hover_bg)
            if right: right.config(bg=hover_bg)
        def on_leave(_=None):
            row.config(bg=bg)
            left.config(bg=bg)
            if right: right.config(bg=bg)
        def on_click(_=None):
            command()
        for w in (row, left) + ((right,) if right else ()): 
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_click)
        return row

    def _neu_choice_button(self, parent, text, selected, command):
        bg = self.C_ACCENT if selected else self.C_BG
        fg = "#ffffff" if selected else self.C_INPUT
        btn = tk.Label(parent, text=text, font=("Microsoft YaHei UI", 9, "bold" if selected else "normal"),
                       bg=bg, fg=fg, padx=10, pady=7, cursor="hand2")
        btn.pack(side="left", padx=(0, 6), pady=3)
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.config(bg=("#6f8fff" if selected else "#dde6f1")))
        btn.bind("<Leave>", lambda e: btn.config(bg=bg))
        return btn

    def _refresh_neu_menu(self):
        """刷新拟态菜单状态，但保持窗口当前位置不变。"""
        fixed_pos = None
        try:
            if getattr(self, "neu_menu_win", None) is not None and self.neu_menu_win.winfo_exists():
                fixed_pos = (self.neu_menu_win.winfo_x(), self.neu_menu_win.winfo_y())
        except Exception:
            fixed_pos = None
        self._close_neu_menu()
        self.open_neu_tray_menu(fixed_pos=fixed_pos)

    def open_neu_tray_menu(self, fixed_pos=None):
        """左键托盘图标弹出的自定义拟态菜单。fixed_pos 用于刷新时固定位置，避免点击菜单项后窗口跳动。"""
        if getattr(self, "neu_menu_win", None) is not None:
            try:
                if self.neu_menu_win.winfo_exists():
                    self._close_neu_menu()
                    return
            except Exception:
                pass

        width, height = 360, min(760, max(620, get_screen_size()[1] - 70))
        if fixed_pos is not None:
            x, y = fixed_pos
            sw, sh = get_screen_size()
            x = max(8, min(int(x), sw - width - 8))
            y = max(8, min(int(y), sh - height - 48))
        else:
            x, y = self._menu_pos_near_cursor(width, height)
        win = tk.Toplevel(self.root)
        self.neu_menu_win = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=self.C_BG)
        win.geometry(f"{width}x{height}+{x}+{y}")
        try:
            win.attributes("-alpha", 0.985)
        except Exception:
            pass

        outer = tk.Frame(win, bg=self.C_BG, padx=12, pady=12)
        outer.pack(fill="both", expand=True)

        # 固定底部操作区：先 pack 到 bottom，避免被上方内容挤出窗口。
        footer_shadow, footer = self._neu_card(outer, padx=8, pady=7)
        footer_shadow.pack(side="bottom", fill="x", pady=(8, 0))
        footer_row = tk.Frame(footer, bg=self.C_ENTRY_BG)
        footer_row.pack(fill="x")

        def footer_btn(text, command, danger=False):
            bg = self.C_BG
            fg = "#d9534f" if danger else self.C_INPUT
            btn = tk.Label(
                footer_row,
                text=text,
                font=("Microsoft YaHei UI", 9, "bold" if danger else "normal"),
                bg=bg,
                fg=fg,
                padx=10,
                pady=7,
                cursor="hand2"
            )
            btn.pack(side="left", fill="x", expand=True, padx=3)
            btn.bind("<Enter>", lambda e: btn.config(bg="#dde6f1" if not danger else "#ffe6e6"))
            btn.bind("<Leave>", lambda e: btn.config(bg=bg))
            btn.bind("<Button-1>", lambda e: command())
            return btn

        footer_btn("⌨️ 快捷键", lambda: self._neu_action(self.set_hotkey_dialog))
        footer_btn("📂 配置", lambda: self._neu_action(self.open_config_file))
        footer_btn("🚪 退出", lambda: self._neu_action(self._quit), danger=True)

        # 顶部状态卡片
        head_shadow, head = self._neu_card(outer, padx=14, pady=12)
        head_shadow.pack(fill="x", pady=(0, 10))
        tk.Label(head, text="中英输入助手", font=("Microsoft YaHei UI", 14, "bold"),
                 bg=self.C_ENTRY_BG, fg=self.C_INPUT).pack(anchor="w")
        provider = self.get_ai_provider_label()
        engine = {"auto": "自动", "google": "Google", "youdao": "有道"}.get(self.get_translation_engine(), "自动")
        ai_state = "已开启" if self.is_ai_ready() else ("缺少 Key" if self.is_ai_enabled() else "已关闭")
        self._neu_label_row(head, "状态", "已启用" if self.enabled else "已停用", "●", fg=self.C_ACCENT if self.enabled else self.C_HINT)
        self._neu_label_row(head, "AI", f"{provider} · {ai_state}", "🤖")
        self._neu_label_row(head, "翻译", engine, "🌐")
        self._neu_label_row(head, "快捷键", self.get_hotkey_label(), "⌨️")

        # 快捷操作卡片
        c1_shadow, c1 = self._neu_card(outer)
        c1_shadow.pack(fill="x", pady=(0, 10))
        self._neu_button(c1, "呼出 / 隐藏输入条", lambda: self._neu_action(self.toggle_popup), icon="⚡", accent=True)
        self._neu_button(c1, "启用 / 停用", lambda: self._neu_action(self.toggle), icon="⏻", value_text=("已启用" if self.enabled else "已停用"))
        self._neu_button(c1, "开机自启", lambda: self._neu_action(self.toggle_autostart, close=False) or self._refresh_neu_menu(), icon="💻", value_text=("已开" if self.is_autostart_enabled() else "已关"))
        self._neu_button(c1, "AI 润色", lambda: self._neu_action(self.toggle_ai_polish, close=False) or self._refresh_neu_menu(), icon="✨", value_text=("已开" if self.is_ai_enabled() else "已关"))

        # AI 提供商
        c2_shadow, c2 = self._neu_card(outer)
        c2_shadow.pack(fill="x", pady=(0, 10))
        tk.Label(c2, text="AI 提供商", font=("Microsoft YaHei UI", 10, "bold"), bg=self.C_ENTRY_BG, fg=self.C_INPUT).pack(anchor="w", pady=(0, 5))
        row_provider = tk.Frame(c2, bg=self.C_ENTRY_BG)
        row_provider.pack(fill="x")
        cur_provider = self.get_ai_provider()
        self._neu_choice_button(row_provider, "DeepSeek", cur_provider == "deepseek", lambda: self._neu_action(lambda: self.set_ai_provider("deepseek"), close=False) or self._refresh_neu_menu())
        self._neu_choice_button(row_provider, "Kimi", cur_provider == "kimi", lambda: self._neu_action(lambda: self.set_ai_provider("kimi"), close=False) or self._refresh_neu_menu())
        self._neu_choice_button(row_provider, "MiMo", cur_provider == "mimo", lambda: self._neu_action(lambda: self.set_ai_provider("mimo"), close=False) or self._refresh_neu_menu())
        self._neu_button(c2, "设置当前 AI API Key", lambda: self._neu_action(self.set_deepseek_api_key_dialog), icon="🔐")

        # 翻译接口 + 定位
        c3_shadow, c3 = self._neu_card(outer)
        c3_shadow.pack(fill="x", pady=(0, 10))
        tk.Label(c3, text="普通翻译接口", font=("Microsoft YaHei UI", 10, "bold"), bg=self.C_ENTRY_BG, fg=self.C_INPUT).pack(anchor="w", pady=(0, 5))
        row_engine = tk.Frame(c3, bg=self.C_ENTRY_BG)
        row_engine.pack(fill="x")
        cur_engine = self.get_translation_engine()
        self._neu_choice_button(row_engine, "自动", cur_engine == "auto", lambda: self._neu_action(lambda: self.set_translation_engine("auto"), close=False) or self._refresh_neu_menu())
        self._neu_choice_button(row_engine, "Google", cur_engine == "google", lambda: self._neu_action(lambda: self.set_translation_engine("google"), close=False) or self._refresh_neu_menu())
        self._neu_choice_button(row_engine, "有道", cur_engine == "youdao", lambda: self._neu_action(lambda: self.set_translation_engine("youdao"), close=False) or self._refresh_neu_menu())

        tk.Label(c3, text="定位方式", font=("Microsoft YaHei UI", 10, "bold"), bg=self.C_ENTRY_BG, fg=self.C_INPUT).pack(anchor="w", pady=(8, 5))
        row_pos = tk.Frame(c3, bg=self.C_ENTRY_BG)
        row_pos.pack(fill="x")
        self._neu_choice_button(row_pos, "记忆位置", self.pos_mode == "memory", lambda: self._neu_action(lambda: self.set_pos_mode("memory"), close=False) or self._refresh_neu_menu())
        self._neu_choice_button(row_pos, "光标上方", self.pos_mode == "cursor", lambda: self._neu_action(lambda: self.set_pos_mode("cursor"), close=False) or self._refresh_neu_menu())

        # 自动关闭逻辑：失焦或 Esc 关闭。点击菜单内控件不会立刻失焦。
        win.bind("<Escape>", lambda e: self._close_neu_menu())
        win.bind("<FocusOut>", lambda e: win.after(180, lambda: None if win.focus_displayof() else self._close_neu_menu()))
        try:
            win.focus_force()
        except Exception:
            pass

    def _make_icon(self, active=True):
        size = 32
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if active:
            step = self._breath_step % len(self.BREATH_COLORS)
            hex_c = self.BREATH_COLORS[step]
            r = int(hex_c[1:3], 16)
            g = int(hex_c[3:5], 16)
            b = int(hex_c[5:7], 16)
        else:
            r, g, b = 160, 160, 160

        draw.rounded_rectangle([2, 2, 30, 30], radius=6, fill=(r, g, b, 255))
        draw.rectangle([9, 8, 12, 24], fill=(255, 255, 255, 255))
        draw.rectangle([12, 8, 23, 11], fill=(255, 255, 255, 255))
        draw.rectangle([12, 14, 21, 17], fill=(255, 255, 255, 255))
        draw.rectangle([12, 21, 23, 24], fill=(255, 255, 255, 255))

        return img

    def _update_tray_title(self):
        if not self._tray: return
        mode_str = "光标上方" if self.pos_mode == "cursor" else "记忆位置"
        state_str = "已启用" if self.enabled else "已停用"
        provider_name = self.get_ai_provider_label()
        if self.is_ai_ready():
            ai_str = f"AI润色：{provider_name} 已开启"
        elif self.is_ai_enabled():
            ai_str = f"AI润色：{provider_name} 未配置Key"
        else:
            ai_str = "AI润色：已关闭"
        engine = self.get_translation_engine()
        engine_name = {"auto": "自动", "google": "Google", "youdao": "有道"}.get(engine, "自动")
        youdao_str = "有道：免Key可用" if self.is_youdao_ready() else "有道：已关闭"
        self._tray.title = f"中英输入助手 {state_str}\n左键：拟态菜单\n{ai_str}\n翻译接口：{engine_name}（{youdao_str}）\n定位：{mode_str}\n{self.get_hotkey_label()} 呼出"


    def _build_tray(self):
        # 右键系统菜单保留为“备用菜单”。真正的拟态菜单通过左键托盘图标弹出。
        menu = pystray.Menu(
            pystray.MenuItem("打开拟态菜单", lambda: self.root.after(0, self.open_neu_tray_menu), default=True),
            pystray.MenuItem("呼出 / 隐藏输入条", lambda: self.root.after(0, self.toggle_popup)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda: self.root.after(0, self._quit)),
        )
        self._tray = pystray.Icon("中英助手", self._make_icon(active=False), f"中英输入助手\n左键打开拟态菜单\n{self.get_hotkey_label()} 呼出", menu)
        self._tray.default_action = lambda: self.root.after(0, self.open_neu_tray_menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _set_tray_icon(self, active=True):
        if self._tray:
            try: self._tray.icon = self._make_icon(active=active)
            except: pass

    def toggle(self):
        self.enabled = not self.enabled
        if self.enabled: self._start_breathing()
        else:
            self._stop_breathing()
            self._set_tray_icon(active=False)
            self._hide()
        self._update_tray_title()

    BREATH_COLORS = ["#aaaaaa","#9999bb","#8888cc","#7777dd","#6666ee","#5566ff","#4477ff","#3388ff","#2299ff","#11aaff","#00bbff","#11aaff","#2299ff","#3388ff","#4477ff","#5566ff","#6666ee","#7777dd","#8888cc","#9999bb","#aaaaaa","#aaaaaa"]

    def _start_breathing(self):
        self._breathing = True
        self._breath_step = 0
        self._breath_tick()

    def _stop_breathing(self):
        self._breathing = False

    def _breath_tick(self):
        if not self._breathing: return
        self._breath_step += 1
        self._set_tray_icon(active=True)
        # 使用 BREATH_INTERVAL 变量控制刷新频率
        self.root.after(self.BREATH_INTERVAL, self._breath_tick)

    def _on_input_change(self, *args):
        text = self.input_var.get().strip()
        if text == self.last_text: return
        self.last_text = text

        if not text:
            self.candidates = []
            self._redraw()
            return

        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text)
        has_style_prefix = any(text.startswith(p) for p in PREFIX_STYLE_MAP.keys())
        if not has_chinese and not has_style_prefix: return

        local = LOCAL_DICT.get(text)
        if local:
            self.candidates = local[:8]
            self.sel_idx = 0
            self._redraw()
        else:
            self.refresh_loading_label()
            self.cand_area.pack(side="left", fill="y", padx=(4,0))
            for outer, _, _ in self.cand_widgets: outer.pack_forget()
            self.loading_lbl.pack(side="left", padx=8)

        while not self.tq.empty():
            try: self.tq.get_nowait()
            except: pass
        self.tq.put(text)

    def _numkey_select(self, idx, event):
        if idx < len(self.candidates):
            self._select(idx)
            return "break"

    def _redraw(self):
        for outer, inner, txt in self.cand_widgets: outer.pack_forget()
        self.loading_lbl.pack_forget()

        if not self.candidates:
            self.cand_area.pack_forget()
            self._resize_bar(self.BAR_W)
            return

        self.cand_area.pack(side="left", fill="y", padx=(4, 0))

        for i, (outer, inner, txt) in enumerate(self.cand_widgets):
            if i < len(self.candidates):
                txt.config(text=self.candidates[i])
                sel = (i == self.sel_idx)
                outer.config(bg=self.C_CHIP_SEL_BG if sel else self.C_CHIP_BORDER)
                inner.config(bg=self.C_CHIP_SEL_BG if sel else self.C_CHIP_BG)
                txt.config(fg=self.C_CHIP_SEL_FG if sel else self.C_CHIP_TEXT, bg=self.C_CHIP_SEL_BG if sel else self.C_CHIP_BG)
                outer.pack(side="left", padx=4, pady=8)

        self.popup.after(1, self._resize_bar)

    def _resize_bar(self, fixed_w=None):
        sw, _ = get_screen_size()
        if fixed_w is not None:
            new_w = fixed_w
        else:
            ENTRY_ZONE, CLOSE_ZONE, CHIP_H_PAD = 220, 55, 30
            chips_w = sum(self._chip_font.measure(self.candidates[i]) + CHIP_H_PAD for i in range(len(self.candidates)))
            new_w = max(self.BAR_W, min(ENTRY_ZONE + chips_w + CLOSE_ZONE, sw - 20))

        cur_x, cur_y = self.popup.winfo_x(), self.popup.winfo_y()
        if cur_x + new_w > sw - 8: cur_x = max(4, sw - new_w - 8)
        self.popup.geometry(f"{new_w}x{self.BAR_H}+{cur_x}+{cur_y}")

    def _hover(self, idx):
        if idx < len(self.candidates): self.sel_idx = idx; self._redraw()

    def _move(self, d):
        if self.candidates:
            self.sel_idx = max(0, min(len(self.candidates)-1, self.sel_idx+d))
            self._redraw()

    def _select(self, idx):
        if idx < len(self.candidates):
            self.sel_idx = idx
            self._confirm()

    def _confirm_space(self, event):
        if self.candidates:
            self._confirm()
            return "break"
        return None

    def _confirm(self):
        if not self.candidates or self.sel_idx >= len(self.candidates):
            return
        chosen = self.candidates[self.sel_idx]
        self._hide()
        
        def delayed_type():
            time.sleep(0.15) 
            
            if self.target_x is not None and self.target_y is not None:
                user32.SetCursorPos(self.target_x, self.target_y)
                time.sleep(0.05) 
                user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
                user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
                time.sleep(0.05)
            
            send_string(chosen)
            
        threading.Thread(target=delayed_type, daemon=True).start()

    def _start_workers(self):
        threading.Thread(target=self._translate_worker, daemon=True).start()
        threading.Thread(target=self._hotkey_worker, daemon=True).start()
        self._build_tray()
        self.root.after(500, self._start_breathing)
        self.root.after(600, self._update_tray_title)

    def _translate_worker(self):
        while self.tq_running:
            try:
                text = self.tq.get(timeout=0.3)
                cfg = load_app_config()
                machine_delay = float(cfg.get("machine_translate_delay", 0.25) or 0.25)
                ai_delay = float(cfg.get("ai_polish_delay", 0.8) or 0.8)
                two_stage = bool(cfg.get("enable_two_stage_results", True))

                # 第一阶段：普通翻译更快，先显示，避免用户干等 AI。
                time.sleep(machine_delay)
                if not self.tq.empty() or text != self.last_text:
                    continue

                work_text, ai_style = detect_ai_style(text)
                local = LOCAL_DICT.get(work_text)
                if local:
                    if text == self.last_text:
                        self.candidates = local[:8]
                        self.sel_idx = 0
                        self.root.after(0, self._redraw)
                    continue

                normal_results = machine_translate_zh_to_en(work_text)
                machine_sources = list(LAST_MACHINE_SOURCES)

                if normal_results and text == self.last_text:
                    self.candidates = normal_results[:8]
                    self.sel_idx = 0
                    translation_log(f"[极速显示] 先显示普通翻译={'+'.join(machine_sources) if machine_sources else '未知'} | 候选={len(normal_results[:8])} | 输入=\"{_short_log_text(work_text)}\"")
                    self.root.after(0, self._redraw)

                if not two_stage:
                    results = translate_zh_to_en(text)
                    if text == self.last_text:
                        self.candidates = results
                        self.sel_idx = 0
                        self.root.after(0, self._redraw)
                    continue

                # 第二阶段：AI 后台补充/替换。等待更久一点，减少每个字都调用 AI。
                remain_delay = max(0.0, ai_delay - machine_delay)
                if remain_delay:
                    time.sleep(remain_delay)
                if not self.tq.empty() or text != self.last_text:
                    continue

                ai_results = deepseek_ai_polish(work_text, base_candidates=normal_results, style=ai_style)
                merged = merge_candidates(ai_results, normal_results, work_text)
                if not merged:
                    merged = normal_results[:8] if normal_results else [f"[{work_text}]"]

                if text == self.last_text:
                    self.candidates = merged[:8]
                    self.sel_idx = 0
                    if ai_results:
                        runtime = get_ai_provider_runtime(load_app_config())
                        translation_log(f"[极速补充] {runtime.get('label','AI')} AI润色已更新候选 | 最终候选={len(merged[:8])} | 输入=\"{_short_log_text(work_text)}\"")
                    self.root.after(0, self._redraw)
            except queue.Empty:
                pass
            except Exception as e:
                print(f"[翻译错误] {e}", flush=True)

    def _hotkey_worker(self):
        combo_prev = False
        last_label = self.get_hotkey_label()
        while self.hotkey_running:
            try:
                # 快捷键在托盘里修改后立即生效。
                spec = self.hotkey_spec
                label = spec.get("label", "")
                if label != last_label:
                    combo_prev = False
                    last_label = label

                combo = is_hotkey_down(spec)
                if combo and not combo_prev:
                    self.root.after(0, self.toggle_popup)
                combo_prev = combo
                time.sleep(0.03)
            except Exception:
                time.sleep(0.1)

    def _quit(self):
        self.tq_running = self.hotkey_running = self._breathing = False
        self._close_neu_menu()
        if self.visible: save_settings(self.popup.winfo_x(), self.popup.winfo_y(), self.pos_mode)
        if self._tray:
            try: self._tray.stop()
            except: pass
        try: self.root.quit(); self.root.destroy()
        except: pass
        sys.exit(0)

    def run(self):
        self.root.mainloop()


# ───────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        if sys.platform != "win32":
            print("Windows only.")
            sys.exit(1)
        print("=" * 40)
        cfg = load_app_config()
        hotkey_label = parse_hotkey_config(cfg.get("hotkey", "Ctrl+Shift+Z")).get("label", "Ctrl+Shift+Z")
        print("  中英输入助手 v7.6.4 多AI提供商预留 + 两段式极速响应版")
        print(f"  {hotkey_label} = 呼出 / 隐藏")
        print("=" * 40)
        InputHelper().run()
    except Exception as e:
        err_text = traceback.format_exc()
        try:
            log_path = os.path.join(get_app_dir(), "startup_error.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(err_text)
        except Exception:
            log_path = "startup_error.log"
        print(err_text)
        try:
            messagebox.showerror(
                "中英输入助手启动失败",
                f"程序启动时出错，已写入：{log_path}\n\n错误摘要：{e}"
            )
        except Exception:
            pass
        try:
            input("按回车退出...")
        except Exception:
            pass
        sys.exit(1)
