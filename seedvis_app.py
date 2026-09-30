#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Thin Aptm — Seedvis Veo 3.1 Standalone Application
Tạo video Veo 3.1 Image-to-Video độc lập qua Seedvis Developer API.
"""

import os
import sys
import re
import time
import datetime
import json
import uuid
import queue
import shutil
import random
import base64
import ctypes
import threading
import collections
import subprocess
import urllib.request
import urllib.error

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

# --- Load helper modules from current directory ---
# Bản .exe (PyInstaller): __file__ trỏ vào _internal, phải lấy thư mục chứa .exe mới đúng
if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# --- Chế độ app: mỗi exe build riêng khóa cứng 1 nhà cung cấp video ---
# Runtime hook của PyInstaller (rthook_mode_seedvis.py / rthook_mode_novagate.py) đặt biến môi trường
# này trước khi file chạy. Chạy thẳng từ mã nguồn (không đặt biến) thì cho chọn cả 2 như cũ.
APP_MODE = os.environ.get("SEEDVIS_APP_MODE", "both").strip().lower()
if APP_MODE not in ("seedvis", "nova", "both"):
    APP_MODE = "both"
APP_NAME = "NovaGate" if APP_MODE == "nova" else "Seedvis"
PROVIDER_SEEDVIS = "Seedvis (Veo 3.1)"
PROVIDER_NOVA = "NovaGateway (Flow Veo)"
APP_ICON_FILE = "novagate_icon.ico" if APP_MODE == "nova" else "seedvis_icon.ico"
APP_LOGO_FILE = "novagate_logo.png" if APP_MODE == "nova" else "seedvis_logo.png"


def asset_path(name):
    """Tìm file ảnh: bản exe nằm trong _internal (sys._MEIPASS), chạy mã nguồn thì nằm cạnh file .py."""
    for base in (getattr(sys, "_MEIPASS", None), HERE):
        if base:
            p = os.path.join(base, name)
            if os.path.isfile(p):
                return p
    return None

try:
    import shopeevideo as SV
except Exception as _e:
    SV = None
    print(f"Không nạp được shopeevideo.py: {_e}")

try:
    import engine as E
except Exception:
    E = None

# --- UI Themes & Colors ---
BG = "#f5f7fb"
CARD = "#ffffff"
AC = "#1a73e8"
T1 = "#202124"
T2 = "#5f6368"
GR = "#1e8e3e"
RD = "#d93025"

# --- Seedvis Constants ---
SEEDVIS_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
SEEDVIS_PACKAGE_CONCURRENT = 32

# Sản phẩm có nhân vật bản quyền thường bị Google hủy job (not_found) → bỏ qua ngay từ đầu.
# Dùng ranh giới từ (\b) để không chặn nhầm, ví dụ "Frozen Meat" không bị chặn.
BLOCKED_IP_KEYWORDS = [
    "spider-man", "spiderman", "spider man", "marvel", "avengers", "iron man", "captain america",
    "hulk", "thor", "batman", "superman", "disney", "pixar", "elsa", "hello kitty", "sanrio",
    "kuromi", "cinnamoroll", "my melody", "mickey mouse", "minnie mouse", "pokemon", "pikachu",
    "sponge bob", "spongebob", "doraemon", "naruto", "one piece", "harry potter",
]
BLOCKED_IP_RE = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in BLOCKED_IP_KEYWORDS) + r")\b", re.IGNORECASE)

SETTINGS_FILE = os.path.join(HERE, "seedvis_settings.json")
LOG_FILE = os.path.join(HERE, "log.txt")
# Chạy 24/7 nhiều ngày sẽ làm log.txt phình to không giới hạn → cắt bớt khi vượt ngưỡng, chỉ giữ phần gần nhất
LOG_MAX_BYTES = 20 * 1024 * 1024
LOG_TRIM_KEEP_BYTES = 5 * 1024 * 1024


def parse_count(v):
    """Số đếm nguyên (lượt bán...). Chịu được số JSON gốc lẫn chuỗi có dấu phân cách hàng nghìn
    kiểu VN ("1.500" và "1,000" đều hiểu là 1500). Không dùng cho trường có phần thập phân thật."""
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(re.sub(r'\D', '', str(v)) or "0")
    except Exception:
        return 0


def parse_price(v, default=0.0):
    """Tiền về float. Bỏ dấu phẩy ngăn hàng nghìn, GIỮ dấu chấm vì giá có thể có phần thập phân thật."""
    if isinstance(v, bool):
        return default
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace(",", "").strip()
        return float(s) if s else default
    except Exception:
        return default


def decode_api_error(err_body):
    """Đọc JSON lỗi của API → (message đọc được, tập tên field lỗi, mã type).
    Seedvis trả message dạng \\uXXXX nên phải json.loads mới so khớp được từ khóa tiếng Việt."""
    msg, fields, etype = "", set(), ""
    try:
        data = json.loads(err_body)
        if isinstance(data, dict):
            m = data.get("message")
            if isinstance(m, str):
                msg = m
            err = data.get("error")
            if isinstance(err, dict):
                msg = msg or str(err.get("message", ""))
                etype = str(err.get("type", "") or err.get("code", ""))
            if isinstance(data.get("errors"), dict):
                fields = set(data["errors"].keys())
    except Exception:
        msg = err_body or ""
    return msg, fields, etype


# Lỗi "đầy slot"/quá tải TẠM THỜI → chờ rồi thử lại. TUYỆT ĐỐI không coi là vi phạm hay hết tiền.
#   Seedvis 422: "Đã đạt giới hạn: tối đa 10 lượt đồng thời + 20 lượt chờ"
#   Nova 503:    "Hệ thống đang xử lý lượng lớn yêu cầu cùng lúc... (Không mất Credits)"
CAPACITY_KEYWORDS = ("giới hạn", "đồng thời", "lượt chờ", "thử lại sau", "lượng lớn yêu cầu",
                     "quá tải", "concurrent", "queue full", "too many", "try again")
POLICY_KEYWORDS = ("policy", "violation", "content filter", "safety", "nsfw", "vi phạm", "chính sách", "nhạy cảm")
# Hết tiền thật: chỉ tin mã 402 hoặc type rõ ràng / câu "không đủ". KHÔNG dò chữ "credit" chung chung,
# vì thông báo quá tải của Nova có câu "(Không mất Credits)" → từng bị hiểu nhầm thành hết tiền và DỪNG cả hàng đợi.
NO_CREDIT_TYPES = ("insufficient_balance", "insufficient_credit", "payment_required")
NO_CREDIT_KEYWORDS = ("không đủ", "insufficient", "hết credit", "hết số dư", "nạp thêm")


def is_capacity_full(code, msg, fields):
    if code not in (422, 429, 503):
        return False
    return "quantity" in fields or any(k in msg.lower() for k in CAPACITY_KEYWORDS)


def is_policy_violation(msg):
    return any(k in msg.lower() for k in POLICY_KEYWORDS)


def is_no_credit(code, msg, etype):
    if str(etype).lower() in NO_CREDIT_TYPES:
        return True
    if code == 402:
        return True
    return any(k in msg.lower() for k in NO_CREDIT_KEYWORDS)


# Mã lỗi job NovaGateway mang tính tạm thời (upstream Google Flow quá tải/chậm; Nova tự hoàn credit)
NOVA_TRANSIENT_CODES = {"generation_failed", "upstream_timeout", "upstream_submission_unknown",
                        "upstream_error", "rate_limited", "server_busy", "overloaded"}
NOVA_TRANSIENT_HINTS = ("lượng lớn yêu cầu", "thử lại", "quá tải", "tạm thời", "hoàn lại credits", "try again", "overloaded")


class SeedvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Thin Aptm — NovaGate Flow Veo Video Generator" if APP_MODE == "nova"
                   else "Thin Aptm — Seedvis Veo 3.1 Video Generator")
        _icon = asset_path(APP_ICON_FILE)
        if _icon:
            try:
                self.iconbitmap(_icon)
            except Exception:
                pass
        self.geometry("1260x860")
        self.minsize(1050, 720)
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        self.configure(fg_color=BG)

        self.settings = self._load_settings()

        # AI Prompt Keys (kế thừa từ ThinAptm settings.json)
        self.gemini_keys = list(self.settings.get("gemini_keys", []))
        raw_groq = self.settings.get("groq_api_key", "")
        if isinstance(raw_groq, list):
            self.groq_keys = [k.strip() for k in raw_groq if k.strip()]
        else:
            self.groq_keys = [k.strip() for k in str(raw_groq).splitlines() if k.strip()]
        self._ai_key_lock = threading.Lock()
        self._gemini_key_rr_idx = 0
        self._groq_key_rr_idx = 0

        # State variables
        self._seed_claimed_products = []
        self._seed_running = False
        self._seed_stop_flag = False    # Dừng lần 1: không gửi job mới, chờ job đang render xong
        self._seed_force_stop = False   # Dừng lần 2 / thoát: bỏ ngay cả job đang render
        self._seed_inflight = 0         # số job đã gửi (đã trừ phí) đang chờ kết quả
        self._seed_inflight_lock = threading.Lock()
        self._seed_video_done_count = 0
        self._seed_completion_times = collections.deque()
        self._seed_run_started_at = time.time()
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write(f"--- PHIEN LAM VIEC MOI {APP_NAME.upper()} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
        except Exception:
            pass

        self._seed_log_buffer = []
        self._seed_log_flush_scheduled = False

        self._ui_queue = queue.Queue()
        self._poll_ui_queue()
        self._sweep_temp_render_on_startup()
        self._start_temp_cleaner()

        import multiprocessing
        # Mỗi FFmpeg dùng 2 luồng → chỉ cho chạy đồng thời ~1/2 số nhân CPU để máy còn dư sức.
        # Trần 4 tiến trình: ghép 12s chỉ mất vài giây/video, nhiều hơn không nhanh hơn mà chỉ tranh CPU.
        self._ffmpeg_sem = threading.Semaphore(max(1, min(4, (multiprocessing.cpu_count() or 4) // 4)))

        self._build_ui()
        self._seed_on_ghep_anh_toggle()

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _load_settings(self):
        default_settings = {
            "sv_server_url": "http://100.79.170.67:3000",
            "sv_api_key": "",
            "sv_client_id": "client_novagate" if APP_MODE == "nova" else "client_seedvis",
            "seedvis_api_key": "",
            "seedvis_model": "Veo-3.1",
            "seedvis_duration": "8s",
            "seedvis_upscale": "none",
            "seedvis_threads": "12",
            "seedvis_aspect": "Dọc 9:16 (TikTok)",
            "seedvis_scene": "🎲 Random",
            "seedvis_total_dur": "16s",
            "seedvis_lang": "Tiếng Philippines",
            "seedvis_review_style": "🎲 Random",
            "seedvis_ai_prompt": "Prompt A + B",
            "seedvis_del_img": True,
            "seedvis_ghep_anh": False,
            "seedvis_naming": "Theo Item ID",
            "seedvis_out_dir": os.path.join(HERE, "output_seedvis"),
            "seedvis_claim_limit": "20",
            "seedvis_sort_by": "Số bán cao nhất",
            "seedvis_market": "PH",
            "seedvis_min_item_id": "40000000000",
            "seedvis_min_commission": "1",
            "seedvis_min_sold": "0",
            "seedvis_min_price": "0",
            "seedvis_max_price": "",
            "seedvis_video_provider": PROVIDER_SEEDVIS,
            "novagate_api_key": "",
            "novagate_model": "google/flow-veo",
            "novagate_resolution": "480p",
            "novagate_duration": "6",
            "novagate_slots": "5",
            "seedvis_auto_refill": False,
            "seedvis_auto_refill_threshold": "100",
            "seedvis_auto_refill_amount": "1000",
            "seedvis_daily_limit_enabled": True,
            "seedvis_daily_limit": "1760",
            "gemini_keys": [],
            "groq_api_key": ""
        }
        # Tự động kế thừa cấu hình từ settings.json của ThinAptm
        thin_settings_file = os.path.join(HERE, "settings.json")
        if os.path.exists(thin_settings_file):
            try:
                with open(thin_settings_file, "r", encoding="utf-8") as f:
                    thin_saved = json.load(f)
                    if isinstance(thin_saved, dict):
                        for k in ("gemini_keys", "groq_api_key", "voice_desc", "sv_server_url", "sv_api_key"):
                            if k in thin_saved:
                                default_settings[k] = thin_saved[k]
            except Exception:
                pass

        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if isinstance(saved, dict):
                        default_settings.update(saved)
            except Exception:
                pass
        return default_settings

    def _save_settings(self):
        try:
            self.settings.update({
                "sv_server_url": self._seed_url.get().strip(),
                "sv_api_key": self._seed_apikey.get().strip(),
                "sv_client_id": self._seed_client_entry.get().strip(),
                "seedvis_api_key": self._seed_apikey_input.get("1.0", "end").strip(),
                "seedvis_model": self._seed_model.get(),
                "seedvis_duration": self._seed_duration.get(),
                "seedvis_upscale": self._seed_upscale.get(),
                "seedvis_threads": self._seed_threads.get().strip(),
                "seedvis_aspect": self._seed_aspect.get(),
                "seedvis_scene": self._seed_scene.get(),
                "seedvis_total_dur": self._seed_total_dur.get(),
                "seedvis_lang": self._seed_lang.get(),
                "seedvis_review_style": self._seed_review_style.get(),
                "seedvis_ai_prompt": self._seed_ai_prompt.get(),
                "seedvis_del_img": self._seed_del_img.get(),
                "seedvis_ghep_anh": self._seed_ghep_anh.get(),
                "seedvis_naming": self._seed_naming.get(),
                "seedvis_out_dir": self._seed_outdir.get().strip(),
                "seedvis_claim_limit": self._seed_claim_limit.get().strip(),
                "seedvis_sort_by": self._seed_sort_by.get(),
                "seedvis_market": self._seed_market.get(),
                "seedvis_min_item_id": self._seed_min_item_id.get().strip(),
                "seedvis_min_commission": self._seed_min_commission.get().strip(),
                "seedvis_min_sold": self._seed_min_sold.get().strip(),
                "seedvis_min_price": self._seed_min_price.get().strip(),
                "seedvis_max_price": self._seed_max_price.get().strip(),
                "seedvis_video_provider": self._seed_provider.get(),
                "novagate_api_key": self._nova_apikey_input.get("1.0", "end").strip(),
                "novagate_model": self._nova_model.get(),
                "novagate_resolution": self._nova_resolution.get(),
                "novagate_duration": self._nova_duration.get().strip(),
                "novagate_slots": self._nova_slots.get().strip(),
                "seedvis_auto_refill": self._seed_auto_refill.get(),
                "seedvis_auto_refill_threshold": self._seed_auto_refill_threshold.get().strip(),
                "seedvis_auto_refill_amount": self._seed_auto_refill_amount.get().strip(),
                "seedvis_daily_limit_enabled": self._seed_daily_limit_enabled.get(),
                "seedvis_daily_limit": self._seed_daily_limit_entry.get().strip() or "1760",
                "gemini_keys": self.gemini_keys,
                "groq_api_key": "\n".join(self.groq_keys) if isinstance(self.groq_keys, list) else self.groq_keys,
            })
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Lỗi lưu settings: {e}")


    def _sweep_temp_render_on_startup(self):
        """Dọn sạch toàn bộ temp_render ngay lúc mở app.
        Tiến trình vừa khởi động nên chắc chắn chưa có file nào đang xử lý dở — an toàn xóa hết.
        Đây là lưới an toàn cho trường hợp lần trước app bị tắt cứng (Task Manager, crash, mất điện)."""
        try:
            temp_dir = os.path.join(HERE, "temp_render")
            if os.path.exists(temp_dir):
                count = 0
                for file in os.listdir(temp_dir):
                    try:
                        os.remove(os.path.join(temp_dir, file))
                        count += 1
                    except Exception:
                        pass
                if count > 0:
                    self._seed_log_msg(f"🧹 [Startup] Đã dọn {count} file rác còn sót từ lần chạy trước trong temp_render.")
        except Exception:
            pass

    def _start_temp_cleaner(self):
        def _cleaner_loop():
            import time
            # Chạy suốt vòng đời app (trước đây thoát luôn sau lần bấm Dừng đầu tiên)
            while True:
                interval_mins = int(self.settings.get("seedvis_clean_interval", 60))
                time.sleep(interval_mins * 60)

                try:
                    temp_dir = os.path.join(HERE, "temp_render")
                    if os.path.exists(temp_dir):
                        count = 0
                        for file in os.listdir(temp_dir):
                            # Chỉ xóa file cũ hơn 2 giờ: ảnh SP còn cần cho bước ghép outro sau khi
                            # job render xong, mà job có thể xếp hàng/thử lại tới 30-45 phút.
                            filepath = os.path.join(temp_dir, file)
                            if time.time() - os.path.getmtime(filepath) > 7200:
                                try:
                                    os.remove(filepath)
                                    count += 1
                                except Exception:
                                    pass
                        if count > 0:
                            self._seed_log_msg(f"  🧹 [Auto-Clean] Đã dọn dẹp {count} file rác trong temp_render.")
                except Exception:
                    pass
                    
        import threading
        threading.Thread(target=_cleaner_loop, daemon=True).start()

    def _on_closing(self):
        """Bấm nút X thoát hẳn phần mềm (không còn thu gọn xuống khay hệ thống)."""
        n = getattr(self, "_seed_inflight", 0)
        if getattr(self, "_seed_running", False) and n > 0:
            if not messagebox.askyesno(
                "Còn job đang render",
                f"Đang có {n} job đã gửi (ĐÃ BỊ TRỪ PHÍ) chưa render xong.\n\n"
                f"Thoát ngay sẽ bỏ các job này: chúng vẫn chạy trên server, chiếm slot tài khoản, "
                f"và video sẽ không được tải về.\n\n"
                f"Nên bấm 'No', rồi bấm ⏹ Dừng để app chờ các job này xong.\n\nVẫn thoát ngay?"):
                return
        self._seed_stop_flag = True
        self._seed_force_stop = True
        self._save_settings()
        try:
            c_id = self._seed_client_entry.get().strip()
            if c_id:
                self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": c_id})
        except Exception:
            pass
        # Dọn dẹp temp_render khi tắt phần mềm theo Rule #8
        try:
            temp_dir = os.path.join(HERE, "temp_render")
            if os.path.exists(temp_dir):
                for file in os.listdir(temp_dir):
                    try:
                        os.remove(os.path.join(temp_dir, file))
                    except Exception:
                        pass
        except Exception:
            pass
        self.destroy()

    def _poll_ui_queue(self):
        try:
            while True:
                ms, func, args = self._ui_queue.get_nowait()
                super().after(ms, func, *args)
        except queue.Empty:
            pass
        super().after(100, self._poll_ui_queue)

    def after(self, ms, func=None, *args):
        if threading.current_thread() is threading.main_thread():
            return super().after(ms, func, *args)
        else:
            self._ui_queue.put((ms, func, args))
            return "queued"


    def _build_ui(self):
        f = ctk.CTkFrame(self, fg_color=BG)
        f.pack(fill="both", expand=True, padx=8, pady=8)

        # --- Header ---
        hdr = ctk.CTkFrame(f, fg_color="transparent")
        hdr.pack(fill="x", padx=12, pady=(0, 4))
        hdr_text = "🚀 NovaGate — Flow Veo Image-to-Video (Độc lập)" if APP_MODE == "nova" else "🌱 Seedvis — Veo 3.1 Image-to-Video (Độc lập)"
        _logo = asset_path(APP_LOGO_FILE)
        if _logo:
            try:
                from PIL import Image as _PILImage
                _img = _PILImage.open(_logo)
                _h = 44 if APP_MODE == "nova" else 32
                self._hdr_logo = ctk.CTkImage(light_image=_img, dark_image=_img,
                                              size=(int(_img.width * _h / _img.height), _h))
                ctk.CTkLabel(hdr, image=self._hdr_logo, text="").pack(side="left", padx=(0, 10))
                hdr_text = "NovaGate — Flow Veo Image-to-Video (Độc lập)" if APP_MODE == "nova" else "Veo 3.1 Image-to-Video (Độc lập)"
            except Exception:
                pass
        ctk.CTkLabel(hdr, text=hdr_text, font=("", 18, "bold"), text_color=T1).pack(side="left")
        self._seed_status_lbl = ctk.CTkLabel(hdr, text="Sẵn sàng", font=("", 12), text_color=T2)
        self._seed_status_lbl.pack(side="right")

        # --- Kết nối Server PostgreSQL ---
        conn_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10)
        conn_card.pack(fill="x", padx=12, pady=4)
        conn_row = ctk.CTkFrame(conn_card, fg_color="transparent")
        conn_row.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(conn_row, text="Server URL:", font=("", 12)).pack(side="left")
        self._seed_url = ctk.CTkEntry(conn_row, width=260, font=("", 11))
        self._seed_url.pack(side="left", padx=4)
        self._seed_url.insert(0, self.settings.get("sv_server_url", "http://100.79.170.67:3000"))

        ctk.CTkLabel(conn_row, text="API Key:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._seed_apikey = ctk.CTkEntry(conn_row, width=180, font=("", 11))
        self._seed_apikey.pack(side="left", padx=4)
        self._seed_apikey.insert(0, self.settings.get("sv_api_key", ""))

        ctk.CTkLabel(conn_row, text="Client ID:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._seed_client_entry = ctk.CTkEntry(conn_row, width=160, font=("", 11))
        self._seed_client_entry.pack(side="left", padx=4)
        self._seed_client_entry.insert(0, self.settings.get("sv_client_id", "client_novagate" if APP_MODE == "nova" else "client_seedvis"))

        self._seed_cached_url = self._seed_url.get().strip()
        self._seed_cached_apikey = self._seed_apikey.get().strip()

        # --- Cấu hình Seedvis API ---
        api_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10)
        api_card.pack(fill="x", padx=12, pady=4)
        provider_row = ctk.CTkFrame(api_card, fg_color="transparent")
        provider_row.pack(fill="x", padx=12, pady=(6, 2))
        self._seed_provider = ctk.CTkOptionMenu(provider_row, values=[PROVIDER_SEEDVIS, PROVIDER_NOVA],
                                                width=220, command=lambda _: self._seed_on_provider_toggle())
        if APP_MODE == "both":
            ctk.CTkLabel(provider_row, text="🎬 Nhà cung cấp video:", font=("", 12, "bold"), text_color=T1).pack(side="left")
            self._seed_provider.pack(side="left", padx=4)
            self._seed_provider.set(self.settings.get("seedvis_video_provider", PROVIDER_SEEDVIS))
        else:
            # Exe riêng: khóa cứng nhà cung cấp, không hiện ô chọn (widget vẫn giữ để code đọc .get())
            self._seed_provider.set(PROVIDER_NOVA if APP_MODE == "nova" else PROVIDER_SEEDVIS)

        ctk.CTkLabel(provider_row, text="Luồng:", font=("", 12)).pack(side="left", padx=(16 if APP_MODE == "both" else 0, 0))
        self._seed_threads = ctk.CTkEntry(provider_row, width=50, font=("", 11))
        self._seed_threads.pack(side="left", padx=4)
        self._seed_threads.insert(0, self.settings.get("seedvis_threads", "12"))

        # -- Khối cấu hình riêng cho Seedvis --
        self._seedvis_block = ctk.CTkFrame(api_card, fg_color="transparent")
        key_row = ctk.CTkFrame(self._seedvis_block, fg_color="transparent")
        key_row.pack(fill="x", padx=0, pady=(2, 2))
        ctk.CTkLabel(key_row, text="🔑 Seedvis API Keys (1 key/dòng, tối đa 3):", font=("", 12)).pack(side="left")
        self._seed_apikey_input = ctk.CTkTextbox(key_row, height=52, font=("Consolas", 10))
        self._seed_apikey_input.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._seed_apikey_input.insert("1.0", self.settings.get("seedvis_api_key", ""))

        api_row = ctk.CTkFrame(self._seedvis_block, fg_color="transparent")
        api_row.pack(fill="x", padx=0, pady=(2, 6))
        ctk.CTkLabel(api_row, text="Model:", font=("", 12)).pack(side="left")
        self._seed_model = ctk.CTkOptionMenu(api_row, values=["Veo-3.1"], width=110)
        self._seed_model.pack(side="left", padx=4)
        self._seed_model.set(self.settings.get("seedvis_model", "Veo-3.1"))

        ctk.CTkLabel(api_row, text="Thời lượng clip:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._seed_duration = ctk.CTkOptionMenu(api_row, values=["8s", "6s", "4s"], width=80)
        self._seed_duration.pack(side="left", padx=4)
        self._seed_duration.set(self.settings.get("seedvis_duration", "8s"))

        ctk.CTkLabel(api_row, text="Upscale:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._seed_upscale = ctk.CTkOptionMenu(api_row, values=["none", "1080p"], width=90)
        self._seed_upscale.pack(side="left", padx=4)
        self._seed_upscale.set(self.settings.get("seedvis_upscale", "none"))

        # -- Khối cấu hình riêng cho NovaGateway --
        self._nova_block = ctk.CTkFrame(api_card, fg_color="transparent")
        nova_key_row = ctk.CTkFrame(self._nova_block, fg_color="transparent")
        nova_key_row.pack(fill="x", padx=0, pady=(2, 2))
        ctk.CTkLabel(nova_key_row, text="🔑 NovaGateway API Keys (1 key/dòng):", font=("", 12)).pack(side="left")
        self._nova_apikey_input = ctk.CTkTextbox(nova_key_row, height=52, font=("Consolas", 10))
        self._nova_apikey_input.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._nova_apikey_input.insert("1.0", self.settings.get("novagate_api_key", ""))

        nova_opt_row = ctk.CTkFrame(self._nova_block, fg_color="transparent")
        nova_opt_row.pack(fill="x", padx=0, pady=(2, 6))
        ctk.CTkLabel(nova_opt_row, text="Model:", font=("", 12)).pack(side="left")
        self._nova_model = ctk.CTkOptionMenu(nova_opt_row, values=["google/flow-veo"], width=210)
        self._nova_model.pack(side="left", padx=4)
        self._nova_model.set(self.settings.get("novagate_model", "google/flow-veo"))

        ctk.CTkLabel(nova_opt_row, text="Độ phân giải:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._nova_resolution = ctk.CTkOptionMenu(nova_opt_row, values=["480p", "720p", "1080p"], width=90)
        self._nova_resolution.pack(side="left", padx=4)
        self._nova_resolution.set(self.settings.get("novagate_resolution", "480p"))

        ctk.CTkLabel(nova_opt_row, text="Thời lượng clip (giây, 1-15):", font=("", 12)).pack(side="left", padx=(12, 0))
        self._nova_duration = ctk.CTkEntry(nova_opt_row, width=50, font=("", 11))
        self._nova_duration.pack(side="left", padx=4)
        self._nova_duration.insert(0, self.settings.get("novagate_duration", "6"))

        ctk.CTkLabel(nova_opt_row, text="Slot gói (luồng tạo):", font=("", 12)).pack(side="left", padx=(12, 0))
        self._nova_slots = ctk.CTkEntry(nova_opt_row, width=40, font=("", 11))
        self._nova_slots.pack(side="left", padx=4)
        self._nova_slots.insert(0, self.settings.get("novagate_slots", "5"))

        self._seed_on_provider_toggle()

        # --- Cài đặt Video ---
        cfg = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10)
        cfg.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(cfg, text="⚙ Cài đặt Video", font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(6, 2))
        row1 = ctk.CTkFrame(cfg, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row1, text="Tỉ lệ:", font=("", 12)).pack(side="left")
        self._seed_aspect = ctk.CTkOptionMenu(row1, values=["Dọc 9:16 (TikTok)", "Ngang 16:9", "Vuông 1:1"], width=160)
        self._seed_aspect.pack(side="left", padx=(4, 12))
        self._seed_aspect.set(self.settings.get("seedvis_aspect", "Dọc 9:16 (TikTok)"))

        ctk.CTkLabel(row1, text="Khung cảnh:", font=("", 12)).pack(side="left")
        scene_opts = SV.SCENE_OPTIONS if SV and hasattr(SV, 'SCENE_OPTIONS') else ["🎲 Random"]
        self._seed_scene = ctk.CTkOptionMenu(row1, values=scene_opts, width=180)
        self._seed_scene.pack(side="left", padx=(4, 12))
        self._seed_scene.set(self.settings.get("seedvis_scene", "🎲 Random"))

        ctk.CTkLabel(row1, text="Độ dài:", font=("", 12)).pack(side="left")
        dur_opts = ["8s", "16s", "24s"] if SV else ["16s"]
        self._seed_total_dur = ctk.CTkOptionMenu(row1, values=dur_opts, width=80, command=lambda _: self._seed_on_ghep_anh_toggle())
        self._seed_total_dur.pack(side="left", padx=(4, 12))
        self._seed_total_dur.set(self.settings.get("seedvis_total_dur", "16s"))

        ctk.CTkLabel(row1, text="Ngôn ngữ:", font=("", 12)).pack(side="left")
        lang_opts = SV.LANG_OPTIONS if SV and hasattr(SV, 'LANG_OPTIONS') else ["Tiếng Philippines", "Tiếng Việt", "Tiếng Anh"]
        self._seed_lang = ctk.CTkOptionMenu(row1, values=lang_opts, width=160)
        self._seed_lang.pack(side="left", padx=4)
        self._seed_lang.set(self.settings.get("seedvis_lang", "Tiếng Philippines"))

        row2 = ctk.CTkFrame(cfg, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row2, text="Kiểu Review:", font=("", 12)).pack(side="left")
        style_opts = ["🎲 Random", "Review kho hàng", "Ngồi Review", "POV (Góc nhìn thứ nhất)", "UGC Authentic", "Unboxing", "Demo Công Dụng", "Review tự nhiên", "So Sánh/Đánh Giá"]
        self._seed_review_style = ctk.CTkOptionMenu(row2, values=style_opts, width=180)
        self._seed_review_style.pack(side="left", padx=(4, 12))
        self._seed_review_style.set(self.settings.get("seedvis_review_style", "🎲 Random"))

        ctk.CTkLabel(row2, text="AI Prompt:", font=("", 12)).pack(side="left")
        ai_opts = ["Template (mặc định)", "Prompt A + B", "Gemini", "Groq"]
        self._seed_ai_prompt = ctk.CTkOptionMenu(row2, values=ai_opts, width=155)
        self._seed_ai_prompt.pack(side="left", padx=(4, 6))
        self._seed_ai_prompt.set(self.settings.get("seedvis_ai_prompt", "Prompt A + B"))

        self._seed_btn_test_prompt = ctk.CTkButton(row2, text="🧪 Test Prompt", width=95, fg_color="#5f6368", hover_color="#45484c", command=self._seed_test_prompt)
        self._seed_btn_test_prompt.pack(side="left", padx=(0, 6))

        self._seed_btn_ai_keys = ctk.CTkButton(row2, text="🔑 AI Keys", width=75, fg_color="#1a73e8", hover_color="#1557b0", command=self._seed_open_ai_keys_dialog)
        self._seed_btn_ai_keys.pack(side="left", padx=(0, 10))

        self._seed_del_img = ctk.BooleanVar(value=self.settings.get("seedvis_del_img", True))
        ctk.CTkCheckBox(row2, text="Xóa ảnh", variable=self._seed_del_img, font=("", 11)).pack(side="left", padx=(6, 0))

        self._seed_ghep_anh = ctk.BooleanVar(value=self.settings.get("seedvis_ghep_anh", False))
        self._seed_chk_ghep_anh = ctk.CTkCheckBox(row2, text="🎞 Ghép ảnh (12s)", variable=self._seed_ghep_anh,
                                                   font=("", 11), checkbox_width=18, checkbox_height=18,
                                                   command=self._seed_on_ghep_anh_toggle)
        self._seed_chk_ghep_anh.pack(side="left", padx=(12, 0))

        row3 = ctk.CTkFrame(cfg, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(row3, text="Đặt tên video:", font=("", 12)).pack(side="left")
        self._seed_naming = ctk.CTkOptionMenu(row3, values=["Theo Item ID", "15 ký tự đầu prompt", "Số thứ tự (001...)"], width=190)
        self._seed_naming.pack(side="left", padx=(4, 12))
        self._seed_naming.set(self.settings.get("seedvis_naming", "Theo Item ID"))

        ctk.CTkLabel(row3, text="Lưu Video:", font=("", 12)).pack(side="left")
        self._seed_outdir = ctk.CTkEntry(row3, width=400, font=("", 11))
        self._seed_outdir.pack(side="left", padx=4)
        self._seed_outdir.insert(0, self.settings.get("seedvis_out_dir", os.path.join(HERE, "output_seedvis")))
        ctk.CTkButton(row3, text="Chọn", width=50, command=self._seed_pick_dir).pack(side="left", padx=4)

        # --- Nhận Lô SP từ Database ---
        claim_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10)
        claim_card.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(claim_card, text="📦 Nhận Lô Sản Phẩm từ Database", font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(6, 2))
        claim_row = ctk.CTkFrame(claim_card, fg_color="transparent")
        claim_row.pack(fill="x", padx=12, pady=(2, 6))

        ctk.CTkLabel(claim_row, text="Số lượng:", font=("", 12)).pack(side="left")
        self._seed_claim_limit = ctk.CTkEntry(claim_row, width=60, font=("", 11))
        self._seed_claim_limit.pack(side="left", padx=4)
        self._seed_claim_limit.insert(0, self.settings.get("seedvis_claim_limit", "20"))

        ctk.CTkLabel(claim_row, text="Ưu tiên:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._seed_sort_by = ctk.CTkOptionMenu(claim_row, values=["Số bán cao nhất", "Hoa hồng cao nhất"], width=160)
        self._seed_sort_by.pack(side="left", padx=4)
        self._seed_sort_by.set(self.settings.get("seedvis_sort_by", "Số bán cao nhất"))

        ctk.CTkLabel(claim_row, text="Thị trường:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._seed_market = ctk.CTkOptionMenu(claim_row, values=["PH", "VN", "ID", "TH", "MY", "SG", "TW"], width=70)
        self._seed_market.pack(side="left", padx=4)
        self._seed_market.set(self.settings.get("seedvis_market", "PH"))

        ctk.CTkLabel(claim_row, text="ItemID từ:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._seed_min_item_id = ctk.CTkEntry(claim_row, width=110, font=("", 11))
        self._seed_min_item_id.pack(side="left", padx=4)
        self._seed_min_item_id.insert(0, self.settings.get("seedvis_min_item_id", "40000000000"))

        ctk.CTkLabel(claim_row, text="Hoa hồng từ:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._seed_min_commission = ctk.CTkEntry(claim_row, width=50, font=("", 11))
        self._seed_min_commission.pack(side="left", padx=4)
        self._seed_min_commission.insert(0, self.settings.get("seedvis_min_commission", "1"))

        ctk.CTkLabel(claim_row, text="SL bán (tổng) từ:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._seed_min_sold = ctk.CTkEntry(claim_row, width=60, font=("", 11))
        self._seed_min_sold.pack(side="left", padx=4)
        self._seed_min_sold.insert(0, self.settings.get("seedvis_min_sold", "0"))

        price_row = ctk.CTkFrame(claim_card, fg_color="transparent")
        price_row.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(price_row, text="Giá bán từ:", font=("", 12)).pack(side="left")
        self._seed_min_price = ctk.CTkEntry(price_row, width=80, font=("", 11))
        self._seed_min_price.pack(side="left", padx=4)
        self._seed_min_price.insert(0, self.settings.get("seedvis_min_price", "0"))
        ctk.CTkLabel(price_row, text="đến:", font=("", 12)).pack(side="left", padx=(8, 0))
        self._seed_max_price = ctk.CTkEntry(price_row, width=80, font=("", 11))
        self._seed_max_price.pack(side="left", padx=4)
        self._seed_max_price.insert(0, self.settings.get("seedvis_max_price", ""))
        ctk.CTkLabel(price_row, text="(để trống = không giới hạn giá trên)", font=("", 10), text_color=T2).pack(side="left", padx=(4, 0))

        claim_btn_row = ctk.CTkFrame(claim_card, fg_color="transparent")
        claim_btn_row.pack(fill="x", padx=12, pady=(0, 6))
        self._seed_btn_claim = ctk.CTkButton(claim_btn_row, text="📥 Nhận SP", width=100, fg_color=AC, command=self._seed_claim_jobs)
        self._seed_btn_claim.pack(side="left", padx=(0, 4))
        self._seed_btn_release = ctk.CTkButton(claim_btn_row, text="🔄 Giải phóng SP kẹt", width=150,
                                              fg_color="#E53935", hover_color="#C62828", command=self._seed_release_jobs)
        self._seed_btn_release.pack(side="left", padx=4)
        self._seed_btn_clear_violation = ctk.CTkButton(claim_btn_row, text="🗑 Xóa Vi Phạm CS", width=150,
                                                      fg_color="#E57373", hover_color="#C62828", command=self._seed_clear_violations)
        self._seed_btn_clear_violation.pack(side="left", padx=4)

        # --- Tự động xin thêm SP khi hàng đợi sắp cạn (chạy 24/7 không lo hết job) ---
        refill_row = ctk.CTkFrame(claim_card, fg_color="transparent")
        refill_row.pack(fill="x", padx=12, pady=(0, 8))
        self._seed_auto_refill = ctk.BooleanVar(value=self.settings.get("seedvis_auto_refill", False))
        ctk.CTkCheckBox(refill_row, text="🔁 Tự động xin thêm SP khi hàng đợi còn dưới", variable=self._seed_auto_refill,
                        font=("", 11), checkbox_width=18, checkbox_height=18).pack(side="left")
        self._seed_auto_refill_threshold = ctk.CTkEntry(refill_row, width=60, font=("", 11))
        self._seed_auto_refill_threshold.pack(side="left", padx=4)
        self._seed_auto_refill_threshold.insert(0, self.settings.get("seedvis_auto_refill_threshold", "100"))
        ctk.CTkLabel(refill_row, text="job → tự xin thêm", font=("", 11)).pack(side="left", padx=(4, 0))
        self._seed_auto_refill_amount = ctk.CTkEntry(refill_row, width=70, font=("", 11))
        self._seed_auto_refill_amount.pack(side="left", padx=4)
        self._seed_auto_refill_amount.insert(0, self.settings.get("seedvis_auto_refill_amount", "1000"))
        ctk.CTkLabel(refill_row, text="SP mỗi lần", font=("", 11)).pack(side="left")

        # --- Giới hạn số video tối đa / ngày (Seedvis 880 video/ngày/key) ---
        daily_row = ctk.CTkFrame(claim_card, fg_color="transparent")
        daily_row.pack(fill="x", padx=12, pady=(0, 8))
        self._seed_daily_limit_enabled = ctk.BooleanVar(value=self.settings.get("seedvis_daily_limit_enabled", True))
        ctk.CTkCheckBox(daily_row, text="🛑 Giới hạn:", variable=self._seed_daily_limit_enabled,
                        font=("", 11, "bold"), checkbox_width=18, checkbox_height=18).pack(side="left")
        self._seed_daily_limit_entry = ctk.CTkEntry(daily_row, width=65, font=("", 11))
        self._seed_daily_limit_entry.pack(side="left", padx=4)
        self._seed_daily_limit_entry.insert(0, str(self.settings.get("seedvis_daily_limit", "1760")))
        ctk.CTkLabel(daily_row, text="video/ngày (Đủ số lượng hoặc hết credit sẽ tự dừng & trả SP kẹt)",
                     font=("", 11), text_color=T2).pack(side="left", padx=(4, 0))

        # --- Bottom: Progress + Buttons ---
        bottom = ctk.CTkFrame(f, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=12, pady=(4, 0))
        self._seed_progress = ctk.CTkProgressBar(bottom, width=400)
        self._seed_progress.pack(fill="x", pady=(0, 4))
        self._seed_progress.set(0)

        btn_row = ctk.CTkFrame(bottom, fg_color="transparent")
        btn_row.pack(fill="x")
        self._seed_btn_start = ctk.CTkButton(btn_row, text="▶ Bắt đầu tạo video", height=42, font=("", 15, "bold"),
                                            fg_color=AC, hover_color="#1565C0", command=self._seed_start)
        self._seed_btn_start.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self._seed_btn_stop = ctk.CTkButton(btn_row, text="⏹ Dừng", height=42, width=80,
                                           fg_color="#E57373", hover_color="#C62828", state="disabled",
                                           command=self._seed_stop)
        self._seed_btn_stop.pack(side="left", padx=4)

        self._seed_btn_open = ctk.CTkButton(btn_row, text="📂 Mở thư mục", height=42, width=110,
                                           fg_color="#78909C", hover_color="#546E7A",
                                           command=lambda: os.startfile(self._seed_outdir.get().strip()) if os.path.exists(self._seed_outdir.get().strip()) else None)
        self._seed_btn_open.pack(side="left", padx=(4, 0))

        # --- Middle: Product List + Log ---
        middle = ctk.CTkFrame(f, fg_color="transparent")
        middle.pack(fill="both", expand=True, padx=12, pady=(4, 0))

        # Left: Product list
        list_card = ctk.CTkFrame(middle, fg_color=CARD, corner_radius=10)
        list_card.pack(side="left", fill="both", expand=True, padx=(0, 4))
        list_hdr = ctk.CTkFrame(list_card, fg_color="transparent")
        list_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(list_hdr, text="📋 Danh sách SP", font=("", 12, "bold"), text_color=T1).pack(side="left")
        self._seed_list_count = ctk.CTkLabel(list_hdr, text="0 SP", font=("", 11), text_color=T2)
        self._seed_list_count.pack(side="right")
        self._seed_video_done_lbl = ctk.CTkLabel(list_hdr, text="", font=("", 11, "bold"), text_color="#1B7D2C")
        self._seed_video_done_lbl.pack(side="right", padx=(0, 12))
        self._seed_speed_lbl = ctk.CTkLabel(list_hdr, text="", font=("", 11), text_color=T2)
        self._seed_speed_lbl.pack(side="right", padx=(0, 12))

        self._seed_products_text = ctk.CTkTextbox(list_card, font=("Consolas", 10))
        self._seed_products_text.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self._seed_products_text.tag_config("seed_success", foreground="#1B7D2C")
        self._seed_products_text.tag_config("seed_error", foreground="#D32F2F")
        self._seed_products_text.tag_config("seed_running", foreground="#E65100")
        self._seed_products_text.tag_config("seed_violation", foreground="#F57F17")

        # Right: Log
        log_card = ctk.CTkFrame(middle, fg_color=CARD, corner_radius=10)
        log_card.pack(side="left", fill="both", expand=True, padx=(4, 0))
        log_hdr = ctk.CTkFrame(log_card, fg_color="transparent")
        log_hdr.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(log_hdr, text="📝 Log (logseedvis.txt)", font=("", 12, "bold"), text_color=T1).pack(side="left")
        ctk.CTkButton(log_hdr, text="🗑 Xóa Log", width=70, height=24, font=("", 11),
                      fg_color="#E57373", hover_color="#C62828", command=self._seed_clear_log).pack(side="right", padx=(4, 0))
        ctk.CTkButton(log_hdr, text="📄 Mở logseedvis.txt", width=135, height=24, font=("", 11),
                      fg_color="#546E7A", hover_color="#37474F", command=self._seed_open_log).pack(side="right", padx=(0, 4))
        self._seed_log = ctk.CTkTextbox(log_card, font=("Consolas", 10), state="disabled")
        self._seed_log.pack(fill="both", expand=True, padx=12, pady=(0, 8))

    def _seed_open_log(self):
        if os.path.exists(LOG_FILE):
            try:
                os.startfile(LOG_FILE)
            except Exception as e:
                messagebox.showerror("Lỗi mở log", str(e))
        else:
            messagebox.showinfo("Log Seedvis", "Chưa có file logseedvis.txt")

    def _seed_clear_log(self):
        try:
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.write(f"--- BẮT ĐẦU LOG SEEDVIS ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
        except Exception:
            pass
        try:
            self._seed_log.configure(state="normal")
            self._seed_log.delete("1.0", "end")
            self._seed_log.configure(state="disabled")
        except Exception:
            pass

    def _seed_on_ghep_anh_toggle(self):
        """Nếu chọn độ dài là 8s và chọn ghép ảnh thành video 12s thì AI prompt chỉ được phép là TVC template."""
        is_8s = (self._seed_total_dur.get().strip() == "8s")
        is_ghep = self._seed_ghep_anh.get()
        if is_8s and is_ghep:
            self._seed_ai_prompt.configure(values=["Template (mặc định)"])
            self._seed_ai_prompt.set("Template (mặc định)")
        else:
            current = self._seed_ai_prompt.get()
            self._seed_ai_prompt.configure(values=["Template (mặc định)", "Prompt A + B", "Gemini", "Groq"])
            if current in ["Template (mặc định)", "Prompt A + B", "Gemini", "Groq"]:
                self._seed_ai_prompt.set(current)
            else:
                self._seed_ai_prompt.set("Prompt A + B")

    def _seed_on_provider_toggle(self):
        """Ẩn/hiện khối cấu hình đúng theo nhà cung cấp video đang chọn."""
        is_nova = self._seed_provider.get().startswith("NovaGateway")
        if is_nova:
            self._seedvis_block.pack_forget()
            self._nova_block.pack(fill="x", padx=12, pady=(0, 4))
        else:
            self._nova_block.pack_forget()
            self._seedvis_block.pack(fill="x", padx=12, pady=(0, 4))

    def _seed_pick_dir(self):
        d = filedialog.askdirectory()
        if d:
            self._seed_outdir.delete(0, "end")
            self._seed_outdir.insert(0, d)

    def _seed_api_call(self, method, path, data=None):
        """Gọi API Server PostgreSQL trung tâm cho tab Seedvis."""
        url = self._seed_cached_url.rstrip("/") + path
        api_key = self._seed_cached_apikey
        headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
        if method == "GET":
            req = urllib.request.Request(url, headers=headers)
        else:
            body = json.dumps(data or {}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _seed_report_job_status(self, item_id, status, extra=None, retries=3):
        """Báo trạng thái SP về Server, có thử lại khi lỗi mạng.
        Tránh trường hợp video đã xử lý xong nhưng Server không biết → SP kẹt ở 'processing' oan uổng."""
        payload = {"itemId": item_id, "status": status, "tool": "seedvis"}
        if extra:
            payload.update(extra)
        last_err = None
        for attempt in range(retries):
            try:
                self._seed_api_call("POST", "/api/thinaptm/complete-job", payload)
                return True
            except Exception as e:
                last_err = e
                if attempt < retries - 1:
                    time.sleep(3 * (attempt + 1))
        self._seed_log_msg(
            f"  ⚠ Không báo được trạng thái '{status}' cho SP {item_id} về Server sau {retries} lần: {last_err}. "
            f"SP có thể bị kẹt ở 'processing' → dùng '🔄 Giải phóng SP kẹt' nếu cần.")
        return False

    def _seed_release_single_job(self, item_id):
        """Trả 1 sản phẩm về trạng thái pending trên Database Shopee khi lỗi mạng/server (tránh báo failed oan)."""
        if not item_id:
            return False
        try:
            r = self._seed_api_call("POST", "/api/thinaptm/release-single-job", {"itemId": str(item_id)})
            return r.get("success", False) if isinstance(r, dict) else False
        except Exception:
            return False


    def _seed_inflight_add(self, delta):
        with self._seed_inflight_lock:
            self._seed_inflight = max(0, self._seed_inflight + delta)

    def _seed_log_msg(self, msg):
        self._seed_log_buffer.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if not self._seed_log_flush_scheduled:
            self._seed_log_flush_scheduled = True
            self.after(500, self._seed_flush_log)

    def _seed_flush_log(self):
        self._seed_log_flush_scheduled = False
        if not self._seed_log_buffer:
            return
        batch = self._seed_log_buffer[:]
        self._seed_log_buffer.clear()
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                for m in batch:
                    f.write(f"{m}\n")
            if os.path.getsize(LOG_FILE) > LOG_MAX_BYTES:
                self._seed_trim_log_file()
        except Exception:
            pass
        try:
            self._seed_log.configure(state="normal")
            self._seed_log.insert("end", "\n".join(batch) + "\n")
            line_count = int(self._seed_log.index("end-1c").split(".")[0])
            if line_count > 1000:
                self._seed_log.delete("1.0", f"{line_count - 800}.0")
            self._seed_log.see("end")
            self._seed_log.configure(state="disabled")
        except Exception:
            pass

    def _seed_trim_log_file(self):
        """Cắt bớt log.txt khi vượt LOG_MAX_BYTES, chỉ giữ lại LOG_TRIM_KEEP_BYTES gần nhất."""
        try:
            with open(LOG_FILE, "rb") as f:
                f.seek(-LOG_TRIM_KEEP_BYTES, os.SEEK_END)
                tail = f.read()
            # Cắt tại ranh giới dòng (byte 0x0A không bao giờ nằm giữa 1 ký tự UTF-8 nhiều byte → an toàn)
            nl = tail.find(b"\n")
            if nl != -1:
                tail = tail[nl + 1:]
            with open(LOG_FILE, "wb") as f:
                f.write(f"--- LOG ĐÃ ĐƯỢC CẮT BỚT (giữ {LOG_TRIM_KEEP_BYTES // 1024 // 1024}MB gần nhất) lúc {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n".encode("utf-8"))
                f.write(tail)
        except Exception:
            pass

    def _seed_download_image(self, image_url, save_path, retries=3):
        """Tải ảnh sản phẩm, thử lại khi mạng trục trặc để không mất SP oan vì lỗi tạm thời."""
        last_err = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    with open(save_path, "wb") as wf:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk: break
                            wf.write(chunk)
                if os.path.exists(save_path) and os.path.getsize(save_path) == 0:
                    os.remove(save_path)
                    last_err = "File ảnh rỗng"
                else:
                    return True
            except Exception as e:
                last_err = e
                if os.path.exists(save_path):
                    try: os.remove(save_path)
                    except: pass
            if attempt < retries - 1:
                self._seed_log_msg(f"⚠ Tải ảnh lỗi (thử {attempt+1}/{retries}): {last_err} → thử lại...")
                time.sleep(3 * (attempt + 1))
        self._seed_log_msg(f"❌ Tải ảnh lỗi sau {retries} lần: {last_err}")
        return False

    def _seed_update_line_status(self, line_idx, status):
        prefix_map = {"success": "✅ ", "error": "❌ ", "running": "⏳ ", "violation": "⚠️ vi phạm cs "}
        tag_map = {"success": "seed_success", "error": "seed_error", "running": "seed_running", "violation": "seed_violation"}
        pfx = prefix_map.get(status, "")
        tag = tag_map.get(status)

        def _do():
            try:
                tk_line = line_idx + 1
                content = self._seed_products_text.get(f"{tk_line}.0", f"{tk_line}.end")
                for p in ("✅ ", "❌ ", "⏳ ", "⚠️ vi phạm cs "):
                    if content.startswith(p):
                        content = content[len(p):]
                        break
                self._seed_products_text.delete(f"{tk_line}.0", f"{tk_line}.end")
                self._seed_products_text.insert(f"{tk_line}.0", pfx + content)
                for t in ("seed_success", "seed_error", "seed_running", "seed_violation"):
                    self._seed_products_text.tag_remove(t, f"{tk_line}.0", f"{tk_line}.end")
                if tag:
                    self._seed_products_text.tag_add(tag, f"{tk_line}.0", f"{tk_line}.end")
            except Exception:
                pass
        self.after(0, _do)

    def _seed_claim_jobs(self):
        self._save_settings()
        """Nhận lô SP cho Seedvis từ Server Database."""
        import re as _re
        self._seed_cached_url = self._seed_url.get().strip()
        if self._seed_cached_url and not (self._seed_cached_url.startswith("http://") or self._seed_cached_url.startswith("https://")):
            self._seed_cached_url = "http://" + self._seed_cached_url
        self._seed_cached_apikey = self._seed_apikey.get().strip()

        limit = int(self._seed_claim_limit.get().strip() or "20")
        sort_map = {"Số bán cao nhất": "sold", "Hoa hồng cao nhất": "commission"}
        sort_by = sort_map.get(self._seed_sort_by.get(), "sold")
        market = self._seed_market.get()
        client_id = self._seed_client_entry.get().strip()
        min_item_id_str = self._seed_min_item_id.get().strip()
        min_comm_str = self._seed_min_commission.get().strip()
        try:
            min_item_id = int(_re.sub(r'\D', '', min_item_id_str) or "40000000000")
        except:
            min_item_id = 40000000000
        try:
            min_commission = float(min_comm_str.replace("%", "").strip() or "1.0")
        except:
            min_commission = 1.0
        min_sold = parse_count(self._seed_min_sold.get().strip())
        min_price = parse_price(self._seed_min_price.get().strip(), default=0.0)
        _max_price_str = self._seed_max_price.get().strip()
        max_price = parse_price(_max_price_str, default=None) if _max_price_str else None

        self._seed_btn_claim.configure(state="disabled", text="⏳...")
        self._seed_log_msg(f"📥 Đang xin {limit} SP từ Server (market={market})...")

        def _do():
            try:
                payload = {
                    "market": market, "clientId": client_id, "limit": limit, "sortBy": sort_by,
                    "tool": "seedvis",
                    "min_item_id": min_item_id, "min_commission": min_commission,
                    "minItemId": min_item_id, "minCommission": min_commission,
                    "min_sold": min_sold, "minSold": min_sold,
                    "min_price": min_price, "minPrice": min_price,
                }
                if max_price is not None:
                    payload["max_price"] = max_price
                    payload["maxPrice"] = max_price
                result = self._seed_api_call("POST", "/api/thinaptm/claim-jobs", payload)
                raw = result.get("products", [])
                products = []
                for p in raw:
                    try:
                        iid = int(_re.sub(r'\D', '', str(p.get("item_id", 0))))
                    except:
                        iid = 0
                    try:
                        rc = float(p.get("commission_rate", 0) or 0)
                        comm = rc * 100.0 if 0 < rc <= 1.0 else rc
                        p["commission_rate"] = comm
                    except:
                        comm = 0.0
                    sold_val = parse_count(p.get("sold", 0))
                    price_val = parse_price(p.get("price", 0))
                    # Lọc lại ở client vì Server có thể chưa hỗ trợ tham số min_sold/min_price/max_price
                    if (min_item_id > 0 and iid < min_item_id) or comm < min_commission \
                            or sold_val < min_sold or price_val < min_price \
                            or (max_price is not None and price_val > max_price):
                        continue
                    products.append(p)
                self._seed_claimed_products = products
                count = len(products)

                def _ui():
                    self._seed_products_text.configure(state="normal")
                    self._seed_products_text.delete("1.0", "end")
                    sym = "₫" if market == "VN" else ("Rp" if market == "ID" else "₱")
                    for i, p in enumerate(products):
                        name = (p.get('name', '') or '')[:55]
                        iid = p.get('item_id', '?')
                        try:
                            pv = float(p.get('price', 0) or 0)
                        except:
                            pv = 0.0
                        sold = p.get('sold', 0)
                        comm = float(p.get('commission_rate', 0) or 0)
                        self._seed_products_text.insert("end", f"⏳ [{i+1}] {iid} | {name} | {sym}{pv:,.0f} | Sold:{sold} | Comm:{comm:.1f}%\n")
                    self._seed_list_count.configure(text=f"{count} SP")
                    self._seed_btn_claim.configure(state="normal", text="📥 Nhận SP")
                self.after(0, _ui)
                self._seed_log_msg(f"✅ Đã nhận {count} SP! Bấm ▶ để tạo video qua {APP_NAME}.")
            except Exception as e:
                self._seed_log_msg(f"❌ Lỗi nhận SP: {e}")
                self.after(0, lambda: self._seed_btn_claim.configure(state="normal", text="📥 Nhận SP"))
        threading.Thread(target=_do, daemon=True).start()

    def _seed_release_jobs(self):
        """Giải phóng SP kẹt (processing) cho Seedvis."""
        client_id = self._seed_client_entry.get().strip()
        if not client_id:
            messagebox.showwarning("Thiếu", "Chưa có Client ID.")
            return
        self._seed_cached_url = self._seed_url.get().strip()
        if self._seed_cached_url and not (self._seed_cached_url.startswith("http://") or self._seed_cached_url.startswith("https://")):
            self._seed_cached_url = "http://" + self._seed_cached_url
        self._seed_cached_apikey = self._seed_apikey.get().strip()
        self._seed_log_msg(f"🔄 Đang giải phóng SP kẹt của client '{client_id}'...")

        def _do():
            try:
                r1 = self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                total_released = r1.get("released", 0) if isinstance(r1, dict) else 0
                self._seed_log_msg(f"✅ Đã giải phóng {total_released} SP kẹt của client '{client_id}'")
                self._seed_claimed_products = []
                self._seed_video_done_count = 0

                def _clear_ui():
                    self._seed_products_text.configure(state="normal")
                    self._seed_products_text.delete("1.0", "end")
                    self._seed_list_count.configure(text="0 SP")
                    self._seed_video_done_lbl.configure(text="")
                    self._seed_progress.set(0)
                    self._seed_btn_claim.configure(state="normal", text="📥 Nhận SP")
                self.after(0, _clear_ui)
            except Exception as e:
                self._seed_log_msg(f"❌ Lỗi giải phóng: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _seed_clear_violations(self):
        """Xóa các SP vi phạm chính sách khỏi danh sách."""
        before = len(self._seed_claimed_products)
        self._seed_claimed_products = [p for p in self._seed_claimed_products if p.get("_status") != "vi phạm cs"]
        after = len(self._seed_claimed_products)
        removed = before - after
        if removed > 0:
            self._seed_log_msg(f"🗑 Đã xóa {removed} SP vi phạm CS.")
            self._seed_products_text.configure(state="normal")
            self._seed_products_text.delete("1.0", "end")
            market = self._seed_market.get()
            sym = "₫" if market == "VN" else ("Rp" if market == "ID" else "₱")
            for i, p in enumerate(self._seed_claimed_products):
                name = (p.get('name', '') or '')[:55]
                iid = p.get('item_id', '?')
                st = p.get("_status", "")
                pfx = "✅ " if st == "success" else ("⚠️ vi phạm cs " if st == "vi phạm cs" else ("❌ " if st in ("noretry", "error") else "⏳ "))
                tag = "seed_success" if st == "success" else ("seed_violation" if st == "vi phạm cs" else ("seed_error" if st in ("noretry", "error") else "seed_running"))
                try:
                    pv = float(p.get('price', 0) or 0)
                except:
                    pv = 0.0
                sold = p.get('sold', 0)
                comm = float(p.get('commission_rate', 0) or 0)
                self._seed_products_text.insert("end", f"{pfx}[{i+1}] {iid} | {name} | {sym}{pv:,.0f} | Sold:{sold} | Comm:{comm:.1f}%\n", tag)
            self._seed_list_count.configure(text=f"{after} SP")
        else:
            self._seed_log_msg("ℹ Không có SP vi phạm CS nào để xóa.")

    def _seed_stop(self):
        """Dừng lần 1: ngừng nhận việc mới nhưng để các job đã gửi (đã bị trừ phí, KHÔNG hủy được
        trên server) render xong và tải video về. Bỏ ngang sẽ thành job 'mồ côi' chiếm slot tài khoản.
        Dừng lần 2: bỏ ngay."""
        if not self._seed_stop_flag:
            self._seed_stop_flag = True
            n = self._seed_inflight
            if n > 0:
                self._seed_log_msg(f"⏹ Dừng nhận việc mới. Đang chờ {n} job đã gửi (đã trừ phí) render xong "
                                   f"và tải video về rồi mới dừng hẳn. Bấm ⏹ lần nữa để dừng NGAY.")
                try:
                    self._seed_btn_stop.configure(text="⏹ Dừng ngay")
                except Exception:
                    pass
            else:
                self._seed_log_msg(f"⏹ Đang dừng tạo video {APP_NAME}...")
        elif not self._seed_force_stop:
            self._seed_force_stop = True
            self._seed_log_msg(f"⏹ DỪNG NGAY: bỏ {self._seed_inflight} job đang render (chúng vẫn chạy trên server và đã bị trừ phí).")

    def _seed_update_speed_label(self):
        """Cập nhật '⚡ X.X video/phút'."""
        dq = getattr(self, "_seed_completion_times", None)
        if dq is None:
            return
        WINDOW = 300.0
        now = time.time()
        while dq and now - dq[0] > WINDOW:
            dq.popleft()
        elapsed = min(WINDOW, now - getattr(self, "_seed_run_started_at", now))
        rate = (len(dq) / (elapsed / 60.0)) if elapsed > 1 else 0.0
        try:
            self._seed_speed_lbl.configure(text=f"⚡ {rate:.1f} video/phút")
        except Exception:
            pass
        if getattr(self, "_seed_running", False):
            self.after(5000, self._seed_update_speed_label)

    def _seed_finish(self):
        self._seed_running = False
        self.after(0, lambda: self._seed_btn_start.configure(state="normal"))
        self.after(0, lambda: self._seed_btn_stop.configure(state="disabled", text="⏹ Dừng"))
        self.after(0, lambda: self._seed_btn_claim.configure(state="normal", text="📥 Nhận SP"))

    def _seed_start(self):
        self._save_settings()
        """Bắt đầu tạo video qua Seedvis (Veo 3.1 Image-to-Video)."""
        if SV is None:
            messagebox.showerror("Lỗi", "Module shopeevideo.py không tải được.")
            return
        if not self._seed_claimed_products:
            messagebox.showwarning("Thiếu SP", "Hãy bấm 📥 Nhận SP trước.")
            return
        out_dir = self._seed_outdir.get().strip()
        if not out_dir:
            messagebox.showwarning("Thiếu", "Hãy chọn thư mục lưu video.")
            return
        is_nova = self._seed_provider.get().startswith("NovaGateway")
        if is_nova:
            _raw_keys = self._nova_apikey_input.get("1.0", "end").strip()
            api_keys = [k.strip() for k in _raw_keys.splitlines() if k.strip()]
            if not api_keys:
                messagebox.showerror("Thiếu API Key", "Vui lòng nhập ít nhất 1 NovaGateway API Key.")
                return
        else:
            _raw_keys = self._seed_apikey_input.get("1.0", "end").strip()
            api_keys = [k.strip() for k in _raw_keys.splitlines() if k.strip()]
            if not api_keys:
                messagebox.showerror("Thiếu API Key", "Vui lòng nhập ít nhất 1 Seedvis API Key.")
                return

        self._seed_cached_url = self._seed_url.get().strip()
        if self._seed_cached_url and not (self._seed_cached_url.startswith("http://") or self._seed_cached_url.startswith("https://")):
            self._seed_cached_url = "http://" + self._seed_cached_url
        self._seed_cached_apikey = self._seed_apikey.get().strip()

        self._seed_start_work(api_keys)

    def _run_ghep_anh_12s(self, video_path, image_path, output_path):
        """Ghép ảnh vào video tạo ra video 12s."""
        DEFAULT_CONFIG = {
            "slow_factor": 1.05,
            "image_dur": 3.5,
            "total_dur": 12.0,
            "motion_effect": "Zoom In (Thu phóng vào)",
            "image_position": "Outro (Cuối video)",
            "image_text": "",
            "text_effect": "Random (Ngẫu nhiên)",
            "text_position": "Dưới cùng (Bottom)",
            "text_size": "60",
            "text_color": "Trắng (White)",
            "encoder": "CPU (libx264)",
            "cpu_preset": "superfast"
        }

        config_path = os.path.join(HERE, "config.json")
        config = dict(DEFAULT_CONFIG)
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                    if isinstance(user_cfg, dict):
                        config.update(user_cfg)
            except Exception:
                pass

        slow_factor = float(config.get("slow_factor", 1.05))
        image_dur = float(config.get("image_dur", 3.5))
        total_dur = float(config.get("total_dur", 12.0))
        video_dur = total_dur - image_dur

        motion_effect = config.get("motion_effect", "Zoom In (Thu phóng vào)")
        effect_map = {
            "Zoom In (Thu phóng vào)": "Zoom In",
            "Zoom Out (Thu phóng ra)": "Zoom Out",
            "Pan Left-to-Right (Trượt trái-phải)": "Pan Left-to-Right",
            "Pan Right-to-Left (Trượt phải-trái)": "Pan Right-to-Left",
            "Static (Ảnh tĩnh)": "Static"
        }
        effect = effect_map.get(motion_effect, "Zoom In")
        position = config.get("image_position", "Outro (Cuối video)")

        raw_text = config.get("image_text", "")
        txt_lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        text_effect = config.get("text_effect", "Random (Ngẫu nhiên)")
        text_position = config.get("text_position", "Dưới cùng (Bottom)")
        text_size = config.get("text_size", "60")
        text_color = config.get("text_color", "Trắng (White)")
        encoder_val = config.get("encoder", "CPU (libx264)")
        cpu_preset = config.get("cpu_preset", "superfast")

        def check_has_audio(vp):
            cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_name', '-of', 'default=noprint_wrappers=1:nokey=1', vp]
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo, creationflags=0x08000000)
                return len(result.stdout.strip()) > 0
            except:
                return False

        def get_video_info(vp):
            cmd = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,r_frame_rate', '-of', 'json', vp]
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, startupinfo=startupinfo, creationflags=0x08000000)
                data = json.loads(result.stdout)
                stream = data['streams'][0]
                width = int(stream['width'])
                height = int(stream['height'])
                fps_str = stream['r_frame_rate']
                if '/' in fps_str:
                    num, den = fps_str.split('/')
                    fps = float(num) / float(den)
                else:
                    fps = float(fps_str)
                return width, height, fps
            except:
                pass
            return 1080, 1920, 30.0

        try:
            has_audio = check_has_audio(video_path)
            width, height, fps = get_video_info(video_path)
            fps_int = int(round(fps))
            if fps_int <= 0:
                fps_int = 30

            total_image_frames = int(image_dur * fps_int)
            max_zoom = 1.3
            w_scale = int(width * max_zoom)
            if w_scale % 2 != 0: w_scale += 1
            h_scale = int(height * max_zoom)
            if h_scale % 2 != 0: h_scale += 1

            zoom_step = 0.3 / total_image_frames

            if effect == "Zoom In":
                zoom_expr = f"min(zoom+{zoom_step:.6f},1.3)"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif effect == "Zoom Out":
                zoom_expr = f"max(1.3-{zoom_step:.6f}*on,1.0)"
                x_expr = "iw/2-(iw/zoom/2)"
                y_expr = "ih/2-(ih/zoom/2)"
            elif effect == "Pan Left-to-Right":
                zoom_expr = "1.3"
                x_expr = f"(iw-iw/zoom)*(on/{total_image_frames})"
                y_expr = "(ih-ih/zoom)/2"
            elif effect == "Pan Right-to-Left":
                zoom_expr = "1.3"
                x_expr = f"(iw-iw/zoom)*(1-on/{total_image_frames})"
                y_expr = "(ih-ih/zoom)/2"
            else:
                zoom_expr = "1.0"
                x_expr = "0"
                y_expr = "0"

            video_filter = f"[0:v]setpts={slow_factor}*PTS,scale={width}:{height},fps={fps_int},tpad=stop_mode=clone:stop_duration={video_dur},trim=0:{video_dur},setpts=PTS-STARTPTS[v_part]"
            filter_parts = [video_filter]

            if has_audio:
                audio_slow_factor = 1.0 / slow_factor
                audio_filter = f"[0:a]atempo={audio_slow_factor},apad,atrim=0:{video_dur},asetpts=PTS-STARTPTS[a_part]"
                filter_parts.append(audio_filter)

            if effect == "Static":
                image_filter_base = (
                    f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},"
                    f"fps={fps_int},trim=0:{image_dur},setpts=PTS-STARTPTS"
                )
            else:
                image_filter_base = (
                    f"[1:v]scale={w_scale}:{h_scale}:force_original_aspect_ratio=increase,"
                    f"crop={w_scale}:{h_scale},"
                    f"zoompan=z='{zoom_expr}':d={total_image_frames}:x='{x_expr}':y='{y_expr}':s={width}x{height},"
                    f"fps={fps_int},trim=0:{image_dur},setpts=PTS-STARTPTS"
                )

            txt = ""
            if txt_lines:
                txt = random.choice(txt_lines)

            txt_effect = text_effect
            if txt_effect == "Random (Ngẫu nhiên)":
                valid_effects = ["Chữ tĩnh (Static)", "Mờ dần (Fade In/Out)", "Chạy ngang (Horizontal Scroll)", "Nhấp nháy (Blinking)"]
                txt_effect = random.choice(valid_effects)

            if txt and txt_effect != "Không chèn":
                escaped_txt = txt.replace(":", "\\:").replace("'", "'\\\\''").replace(",", "\\,")
                color_map = {
                    "Trắng (White)": "white",
                    "Vàng (Yellow)": "yellow",
                    "Đỏ (Red)": "red",
                    "Xanh lá (Green)": "green",
                    "Xanh lam (Blue)": "blue"
                }
                ffmpeg_color = color_map.get(text_color, "white")
                try:
                    f_size = int(text_size.strip())
                    if f_size <= 0: f_size = 50
                except ValueError:
                    f_size = 50

                x_val = "(w-text_w)/2"
                pos = text_position
                if pos == "Trên cùng (Top)":
                    y_val = "h*0.1"
                elif pos == "Chính giữa (Center)":
                    y_val = "(h-text_h)/2"
                else:
                    y_val = "h*0.8"

                font_path = "C:\\Windows\\Fonts\\arial.ttf"
                if os.path.exists(font_path):
                    font_opt = "fontfile='C\\:/Windows/Fonts/arial.ttf'"
                else:
                    font_opt = "font='Arial'"

                drawtext_base = (
                    f"drawtext={font_opt}:text='{escaped_txt}':"
                    f"fontsize={f_size}:fontcolor={ffmpeg_color}:box=1:boxcolor=black@0.4:boxborderw=10"
                )

                if txt_effect == "Chữ tĩnh (Static)":
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_val}':y='{y_val}'[i_v]"
                elif txt_effect == "Mờ dần (Fade In/Out)":
                    alpha_expr = f"if(lt(t,0.5),t/0.5,if(gt(t,{image_dur}-0.5),({image_dur}-t)/0.5,1))"
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_val}':y='{y_val}':alpha='{alpha_expr}'[i_v]"
                elif txt_effect == "Chạy ngang (Horizontal Scroll)":
                    x_scroll = f"w-t*(w+text_w)/{image_dur}"
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_scroll}':y='{y_val}'[i_v]"
                elif txt_effect == "Nhấp nháy (Blinking)":
                    alpha_blink = "lt(mod(t,1.0),0.5)"
                    image_filter = f"{image_filter_base},{drawtext_base}:x='{x_val}':y='{y_val}':alpha='{alpha_blink}'[i_v]"
                else:
                    image_filter = f"{image_filter_base}[i_v]"
            else:
                image_filter = f"{image_filter_base}[i_v]"

            filter_parts.append(image_filter)
            image_audio_filter = f"anullsrc=r=48000:cl=stereo,atrim=0:{image_dur},asetpts=PTS-STARTPTS[i_a]"
            filter_parts.append(image_audio_filter)

            if position == "Outro (Cuối video)":
                if has_audio:
                    filter_parts.append("[v_part][a_part][i_v][i_a]concat=n=2:v=1:a=1[outv][outa]")
                    map_args = ["-map", "[outv]", "-map", "[outa]"]
                else:
                    filter_parts.append("[v_part][i_v]concat=n=2:v=1:a=0[outv]")
                    map_args = ["-map", "[outv]"]
            else:
                if has_audio:
                    filter_parts.append("[i_v][i_a][v_part][a_part]concat=n=2:v=1:a=1[outv][outa]")
                    map_args = ["-map", "[outv]", "-map", "[outa]"]
                else:
                    filter_parts.append("[i_v][v_part]concat=n=2:v=1:a=0[outv]")
                    map_args = ["-map", "[outv]"]

            filter_complex_str = "; ".join(filter_parts)

            vcodec = "libx264"
            codec_opts = ["-preset", cpu_preset, "-crf", "22", "-threads", "2"]
            if "NVIDIA" in encoder_val:
                vcodec = "h264_nvenc"
                codec_opts = ["-preset", "fast", "-gpu", "any"]
            elif "Intel" in encoder_val:
                vcodec = "h264_qsv"
                codec_opts = ["-preset", "veryfast"]
            elif "AMD" in encoder_val:
                vcodec = "h264_amf"
                codec_opts = ["-quality", "speed"]

            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-loop", "1", "-t", str(image_dur), "-i", image_path,
                "-filter_complex", filter_complex_str
            ]
            cmd.extend(map_args)
            cmd.extend(["-c:v", vcodec])
            cmd.extend(codec_opts)

            if has_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            cmd.append(output_path)

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            # Giới hạn luồng bộ lọc (đặt TRƯỚC file output, nếu đặt sau FFmpeg sẽ bỏ qua)
            cmd[1:1] = ["-filter_threads", "1", "-filter_complex_threads", "1"]
            self._ffmpeg_sem.acquire()
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                               startupinfo=startupinfo, timeout=120,
                               creationflags=0x08000000 | 0x4000)  # NO_WINDOW | BELOW_NORMAL_PRIORITY
                return True, ""
            except subprocess.TimeoutExpired:
                return False, "FFmpeg timed out after 120s"
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                return False, err_msg
            finally:
                self._ffmpeg_sem.release()
        except Exception as ex:
            return False, str(ex)

    def _seed_open_ai_keys_dialog(self):
        """Mở cửa sổ xem và chỉnh sửa API Keys cho Gemini và Groq."""
        dlg = ctk.CTkToplevel(self)
        dlg.title("🔑 Cài đặt AI Keys (Gemini & Groq)")
        dlg.geometry("680x560")
        dlg.attributes("-topmost", True)
        dlg.after(100, lambda: dlg.attributes("-topmost", False))
        dlg.focus_force()

        header_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        header_frame.pack(fill="x", padx=16, pady=(12, 6))
        ctk.CTkLabel(header_frame, text="🔑 Quản lý API Key AI (Kế thừa từ ThinAptm)", font=("", 14, "bold"), text_color=T1).pack(anchor="w")
        ctk.CTkLabel(header_frame, text="ℹ️ Các key này được nạp tự động từ settings.json của ThinAptm.\nKhi chọn AI Prompt là Gemini hoặc Groq, hệ thống sẽ xoay vòng các key này.", font=("", 11), text_color=T2, justify="left").pack(anchor="w", pady=(2, 0))

        # Gemini card
        gcard = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=8)
        gcard.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(gcard, text="🔷 Gemini API Keys (1 key/dòng):", font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(8, 2))
        txt_gemini = ctk.CTkTextbox(gcard, height=120, font=("Consolas", 10))
        txt_gemini.pack(fill="x", padx=12, pady=(2, 10))
        txt_gemini.insert("1.0", "\n".join(self.gemini_keys))

        # Groq card
        qcard = ctk.CTkFrame(dlg, fg_color=CARD, corner_radius=8)
        qcard.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(qcard, text="🟠 Groq API Keys (1 key/dòng):", font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(8, 2))
        txt_groq = ctk.CTkTextbox(qcard, height=120, font=("Consolas", 10))
        txt_groq.pack(fill="x", padx=12, pady=(2, 10))
        txt_groq.insert("1.0", "\n".join(self.groq_keys))

        btn_row = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(10, 12))

        def _save_keys():
            new_gem = [k.strip() for k in txt_gemini.get("1.0", "end").splitlines() if k.strip()]
            new_groq = [k.strip() for k in txt_groq.get("1.0", "end").splitlines() if k.strip()]
            self.gemini_keys = new_gem
            self.groq_keys = new_groq
            self._save_settings()
            messagebox.showinfo("Thành công", f"Đã lưu:\n- {len(new_gem)} Gemini Key\n- {len(new_groq)} Groq Key", parent=dlg)
            dlg.destroy()

        ctk.CTkButton(btn_row, text="💾 Lưu API Keys", width=130, fg_color=GR, hover_color="#137333", command=_save_keys).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Đóng", width=80, fg_color="#5f6368", command=dlg.destroy).pack(side="right", padx=4)

    def _seed_test_prompt(self):
        """Mở dialog test thử sinh prompt với AI (Gemini/Groq) hoặc Template."""
        try:
            prod_name = "Serum Vitamin C Sáng Da Mờ Thâm Nám 30ml"
            if self._seed_claimed_products:
                prod_name = self._seed_claimed_products[0].get("name", prod_name)

            ai_mode = self._seed_ai_prompt.get()
            duration_sec = SV.parse_duration(self._seed_total_dur.get()) if SV else 16
            n_segments = len(SV.DURATION_MAP.get(duration_sec, [0, 1])) if SV else 2
            scene_choice = self._seed_scene.get()
            lang_val = self._seed_lang.get()
            lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))
            review_style = self._seed_review_style.get()

            if SV:
                scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)
            else:
                scene_name, scene_en = scene_choice, "clean minimalist desk"

            if ai_mode == "Gemini" and not self.gemini_keys:
                messagebox.showwarning("Thiếu Key Gemini", "Chưa có API Key Gemini!\nHãy bấm '🔑 AI Keys' để thêm key hoặc kiểm tra settings.json.")
                return
            if ai_mode == "Groq" and not self.groq_keys:
                messagebox.showwarning("Thiếu Key Groq", "Chưa có API Key Groq!\nHãy bấm '🔑 AI Keys' để thêm key hoặc kiểm tra settings.json.")
                return

            dlg = ctk.CTkToplevel(self)
            dlg.title(f"🧪 Test Prompt (Seedvis): {prod_name[:35]}")
            dlg.geometry("720x540")
            dlg.attributes("-topmost", True)
            dlg.after(100, lambda: dlg.attributes("-topmost", False))
            dlg.focus_force()

            ctk.CTkLabel(dlg, text=f"📦 Sản phẩm: {prod_name}", font=("", 13, "bold"), text_color=T1).pack(anchor="w", padx=16, pady=(12, 2))
            ctk.CTkLabel(dlg, text=f"🤖 AI: {ai_mode}  |  ⏱ {duration_sec}s ({n_segments} đoạn)  |  🏖 {scene_name}  |  🎬 {review_style}", font=("", 11), text_color=T2).pack(anchor="w", padx=16, pady=(0, 8))

            txt = ctk.CTkTextbox(dlg, font=("Consolas", 10), wrap="word")
            txt.pack(fill="both", expand=True, padx=16, pady=(0, 10))
            txt.insert("1.0", f"⏳ Đang tạo prompt ({ai_mode}), vui lòng chờ...\n")

            def _generate():
                prompts = None
                mode_str = ai_mode
                if ai_mode == "Gemini":
                    prompts = self._seed_ai_gen_prompts(
                        prod_name, scene_en, n_segments, duration_sec, lang_code,
                        review_style, mode="gemini", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys, product_desc=p.get("description", ""), img_path=img_path
                    )
                elif ai_mode == "Groq":
                    prompts = self._seed_ai_gen_prompts(
                        prod_name, scene_en, n_segments, duration_sec, lang_code,
                        review_style, mode="groq", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys, product_desc=p.get("description", ""), img_path=img_path
                    )

                if not prompts and SV:
                    if n_segments == 1:
                        p, _ = SV.build_tvc_prompt(prod_name, lang=lang_code, review_style=review_style)
                        prompts = [p]
                    else:
                        prompts = SV.build_video_prompts(
                            prod_name, scene_en, duration_sec=duration_sec,
                            lang=lang_code, review_style=review_style
                        )
                    if ai_mode in ("Gemini", "Groq"):
                        mode_str += " (Lỗi AI → Dùng Template Fallback)"

                def _show_ui():
                    try:
                        txt.delete("1.0", "end")
                        if not prompts:
                            txt.insert("1.0", "❌ Không sinh được prompt.")
                            return
                        header = (
                            f"=== TEST PROMPT (SEEDVIS) ===\n"
                            f"Sản phẩm: {prod_name}\n"
                            f"Engine: {mode_str}\n"
                            f"Kiểu Review: {review_style}\n"
                            f"Khung cảnh: {scene_name}\n"
                            f"Segments: {len(prompts)}\n"
                            + "=" * 60 + "\n\n"
                        )
                        body = ""
                        for idx, pr in enumerate(prompts, 1):
                            body += f"--- SEGMENT {idx} ---\n{pr}\n\n"
                        txt.insert("1.0", header + body)
                    except Exception:
                        pass

                self.after(0, _show_ui)

            threading.Thread(target=_generate, daemon=True).start()
        except Exception as err:
            messagebox.showerror("Lỗi Test Prompt", f"Xảy ra lỗi: {err}")

    def _seed_ai_gen_prompts(self, product_name, scene_en, n_segments,
                              duration_sec, lang_code, review_style,
                              mode="gemini", gemini_keys=None, groq_keys=None, product_desc=None, img_path=None):
        """Gọi Gemini hoặc Groq để sinh prompt video review sản phẩm chất lượng cao.
        Trả về list[str] prompts hoặc None nếu thất bại."""
        lang_map = {"vi": "Vietnamese", "en": "English", "id": "Indonesian", "my": "Malay", "ph": "Filipino"}
        lang_name = lang_map.get(lang_code, "English")

        _REVIEW_STYLE_DESCS = {
            "Review tự nhiên": (
                "NATURAL STANDING REVIEW style: The presenter stands naturally, picks up the product, "
                "walks around the scene, holds items up to camera. Free movement, energetic and authentic. "
                "Casual handheld camera feel with smooth tracking. "
                "CAMERA: Medium shot, handheld with subtle natural shake, 35mm lens feel. "
                "LIGHTING: Natural window light from the side, mixed with warm indoor ambient light, soft shadows. "
                "ENVIRONMENT: Clean but lived-in room, slightly visible background details for authenticity. "
                "ANTI-AI: Include slight camera drift, natural micro-expressions, smartphone camera quality feel."
            ),
            "Ngồi Review": (
                "SEATED DESK REVIEW style: The presenter sits behind a clean minimalist wooden desk "
                "throughout the ENTIRE video. She NEVER stands up or walks. All product interactions "
                "happen on the desk or held above it. Camera is at desk-level, frontal or slightly angled. "
                "CAMERA: Static or slow push-in, eye-level, 50mm lens feel. "
                "LIGHTING: Soft LED panel or ring light from front, warm tone, even illumination. "
                "ENVIRONMENT: Clean desk surface, minimalist background, soft bokeh. "
                "ANTI-AI: Natural hand gestures, occasional glance away from camera, realistic skin texture."
            ),
            "POV (Góc nhìn thứ nhất)": (
                "POV FIRST-PERSON style: Camera IS the viewer's eyes. We NEVER see the presenter's face. "
                "Only hands and arms visible interacting with the product. The viewer feels like THEY are "
                "the one holding, opening, and using the product themselves. "
                "CAMERA: First-person POV, over-the-shoulder or looking-down angle, handheld with natural shake. "
                "LIGHTING: Natural mixed indoor light, overhead kitchen/room light, uncontrolled ambient. "
                "ENVIRONMENT: Real desk/table/counter surface, slight clutter (pen, coffee mug, receipts) for authenticity. "
                "ANTI-AI: Slight lens flare from room lamp, visible fingerprints/dust on product, "
                "natural hand movement speed (not too smooth), iPhone camera compression feel. "
                "CRITICAL: NO face visible. Only hands and forearms. Product is the HERO."
            ),
            "Unboxing": (
                "UNBOXING style: Focus on the satisfying experience of opening packaging and revealing "
                "the product for the first time. Slow, deliberate hand movements. Build anticipation. "
                "CAMERA: Top-down flat lay angle for opening, then switch to close-up for product reveal. "
                "Handheld with subtle movement. "
                "LIGHTING: Warm overhead light, soft shadows on packaging textures, cozy atmosphere. "
                "ENVIRONMENT: Clean wooden desk or floor surface, minimal props (scissors, knife nearby). "
                "ANTI-AI: Include satisfying paper rustling and packaging sounds, tactile textures visible, "
                "slight pause of genuine excitement when product is revealed, natural finger movements "
                "(not perfectly smooth). ASMR-adjacent aesthetic — crisp sounds, deliberate slow pacing. "
                "CRITICAL: Show FULL unboxing journey — sealed box → cutting tape → lifting lid → reveal."
            ),
            "UGC Authentic": (
                "UGC AUTHENTIC style: Raw, unpolished, genuine — like a real customer sharing with friends. "
                "NOT a professional review. This should feel like someone filming with their phone in their "
                "bedroom, genuinely excited about a product they just received. "
                "CAMERA: iPhone selfie front-camera angle, slightly off-center framing, visible camera shake, "
                "occasional focus hunting, vlog-style close talking distance. "
                "LIGHTING: Messy mixed lighting — bedroom lamp + phone screen glow + window light, "
                "NOT studio lighting, slightly warm/yellow indoor tone. "
                "ENVIRONMENT: Slightly messy bedroom or living room, pillows/blankets visible, "
                "personal items in background, lived-in and imperfect. "
                "ANTI-AI: Include casual speech cadence (slight pauses, 'um'), genuine excitement not "
                "performative, natural skin texture with no filter, hair slightly imperfect, "
                "camera tilts/adjusts mid-shot. Shot on smartphone quality — slight grain, natural compression. "
                "CRITICAL: Must feel like a REAL person's phone video, NOT a commercial."
            ),
            "Demo Công Dụng": (
                "PRODUCT DEMONSTRATION style: Focus entirely on showing HOW the product works. "
                "Step-by-step functional demonstration with clear visibility of features and results. "
                "CAMERA: Alternating between close-up macro shots (product details, buttons, textures) "
                "and medium shots (hands demonstrating usage). Steady, controlled movement. "
                "LIGHTING: Bright, even, clinical-style lighting for maximum product visibility. "
                "Natural daylight or bright LED, no dramatic shadows — clarity is priority. "
                "ENVIRONMENT: Clean test surface — white/light desk, neutral background, "
                "comparison items nearby if relevant (ruler for scale, water for waterproof test). "
                "ANTI-AI: Show REAL interaction physics — weight of product visible in hand grip, "
                "realistic material textures, functional result visible (cream absorbed, device screen lit up, "
                "sound produced). Include before/after moments where relevant. "
                "CRITICAL: Product FUNCTIONALITY is the hero — every shot must demonstrate a specific feature."
            ),
            "So Sánh/Đánh Giá": (
                "COMPARISON REVIEW style: Side-by-side honest evaluation. The presenter compares "
                "the product against expectations, price point, or similar alternatives. "
                "Analytical, trustworthy, 'brutally honest' tone. "
                "CAMERA: Medium shot with both products visible, alternating close-ups on each, "
                "split-frame composition when comparing features. Steady tripod feel. "
                "LIGHTING: Consistent even lighting on both products — no favoritism in presentation. "
                "Bright, neutral-tone daylight or LED panel. "
                "ENVIRONMENT: Clean comparison surface, both products clearly labeled/visible, "
                "perhaps a notepad or checklist visible for systematic review. "
                "ANTI-AI: Show genuine contemplation (touching chin, slight frown while thinking), "
                "honest facial reactions (impressed nod OR disappointed head shake), "
                "realistic material/texture differences visible between products. "
                "CRITICAL: Must show BOTH positive and negative aspects — not purely promotional."
            ),
        }
        if review_style in ("🎲 Random", "Random") or not review_style or "random" in str(review_style).lower():
            import random as _rnd
            actual_style = _rnd.choice(list(_REVIEW_STYLE_DESCS.keys()))
            style_desc = _REVIEW_STYLE_DESCS[actual_style]
        else:
            style_desc = _REVIEW_STYLE_DESCS.get(review_style, _REVIEW_STYLE_DESCS["Review tự nhiên"])

        if n_segments == 1:
            flow_desc = (
                "VIDEO FLOW (1 segment × 8 seconds total):\n"
                "- Segment 1 (8s): Full review showcase — presenter reveals the product with genuine excitement, "
                "demonstrates key features and usage, smiles enthusiastically and gives thumbs up to recommend it."
            )
        elif n_segments == 2:
            flow_desc = (
                "VIDEO FLOW (2 segments × 8 seconds = 16 seconds total):\n"
                "- Segment 1 (8s): Opening — presenter discovers/picks up the product with genuine excitement, "
                "examines it closely, shows key features while speaking enthusiastically about it.\n"
                "- Segment 2 (8s): Closing — presenter demonstrates the product in use, gives final verdict "
                "with confident smile, nods approvingly, and gives a thumbs up to recommend it.\n"
                "CONTINUITY: Segment 2 must start from the EXACT pose/position where Segment 1 ended."
            )
        else:
            flow_desc = (
                f"VIDEO FLOW ({n_segments} segments × 8 seconds total):\n"
                "- Segment 1 (8s): Opening — presenter reveals the product with excitement, picks it up, "
                "examines the packaging/design while introducing the product by name.\n"
                "- Segment 2 (8s): Middle — close-up showcase of product features and details, presenter "
                "demonstrates how to use it, touches textures, shows different angles.\n"
                f"- Segment {n_segments} (8s): Closing — presenter gives final review verdict, shows satisfaction, "
                "recommends with enthusiasm, smiles warmly and gives thumbs up.\n"
                "CONTINUITY: Each segment must start from the EXACT pose/position where the previous one ended."
            )

        system_prompt = (
            f"You are an expert prompt engineer for Google Veo 3 (image-to-video AI).\n"
            f"Write EXACTLY {n_segments} video prompts for a Shopee product review.\n\n"
            f"═══ PRODUCT INFO ═══\n"
            f"Product Name: \"{product_name}\"\n"
            f"(This product name is from Shopee. Use it to infer what the product looks like and how to review it.)\n\n"
            f"═══ VIDEO SETTINGS ═══\n"
            f"Total Duration: {duration_sec} seconds ({n_segments} segments × 8 seconds each)\n"
            f"Background/Scene: {scene_en}\n"
            f"Presenter Language: {lang_name}\n"
            f"Review Style: {style_desc}\n\n"
            f"═══ {flow_desc} ═══\n\n"
            f"═══ 6-SECTION PROMPT STRUCTURE & PROMPT LOCKS ═══\n"
            f"Each output prompt must strictly incorporate these 6 sections and prompt locks:\n"
            f"1. SECTION 1 (GENERAL RULES & LOCKS):\n"
            f"   - FRAMING LOCK: Full-frame vertical 9:16 portrait video. Reference image fills frame edge-to-edge with NO letterboxing, NO pillarboxing, NO black bars, NO white borders, NO storyboard/collage layout.\n"
            f"   - PRODUCT CONSISTENCY LOCK: The product shown in frame 1 must be the EXACT SAME product in every subsequent frame. Color, shape, size, material texture, and logos must NOT change, swap, or transform at any point (especially final 1-2s).\n"
            f"   - HAND & ANATOMY LOCK: The presenter has exactly TWO normal human hands with 5 fingers each. DO NOT generate extra hands, extra arms, extra fingers, or limb deformations.\n"
            f"   - ITEM PERSISTENCE: Any object held or worn must remain naturally present throughout.\n"
            f"2. SECTION 2 (PRODUCT TO ADVERTISE): \"{product_name}\" is the HERO. Prominently featured and in sharp focus.\n"
        )

        is_pov_or_unbox = any(k in str(review_style or "").lower() for k in ("pov", "unbox", "đập hộp", "góc nhìn thứ nhất"))
        if is_pov_or_unbox:
            system_prompt += (
                f"3. SECTION 3 (POV / UNBOXING - NO PRESENTER FACE): ABSOLUTELY NO human face, NO head, NO model body visible in any frame. "
                f"Define strictly First-person POV or top-down desk perspective looking directly at the product. "
                f"Only TWO clean natural human hands interacting with and showcasing the product on the table. "
                f"Voiceover speaks off-camera while hands demonstrate the product.\n"
            )
        elif lang_code == "my":
            system_prompt += (
                f"3. SECTION 3 (PRESENTER & OUTFIT LOCK): Define ONE fixed Malay MALE presenter (~25-30yo, "
                f"modest clothing: clean long-sleeve button-down or polo shirt, dark trousers, neat well-groomed hair, "
                f"friendly professional appearance) and REPEAT THAT EXACT MALE CHARACTER AND "
                f"OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts. (CRITICAL: MUST be a MALE presenter, NO female model).\n"
            )
        else:
            system_prompt += (
                f"3. SECTION 3 (PRESENTER & OUTFIT LOCK): Define ONE fixed presenter anchor (~22-26yo Asian woman, "
                f"exact face, exact hairstyle, exact clothing outfit style and color) and REPEAT THAT EXACT "
                f"CHARACTER AND OUTFIT DESCRIPTION VERBATIM in all {n_segments} prompts.\n"
            )
        system_prompt += (
            f"4. SECTION 4 (ACTION & TIMELINE CONTINUITY):\n"
            f"   - Follow strict timeline progression (0-1s anchor/intro, 1-3s speaking/handling, 3-7s demonstration/gestures, 7-8s CRITICAL RETURN TO REFERENCE & FREEZE to static handoff pose).\n"
            f"   - Segment 1 ends with a distinct static pose; Segment 2 starts EXACTLY from that pose. Segment 2 ends with a distinct pose; Segment 3 starts EXACTLY from that pose.\n"
            f"5. SECTION 5 (CAMERA & TECHNICAL SPECS): Smartphone-style photorealism, eye-level angle, 35mm/50mm lens feel, natural soft lighting, clean white balance, optical depth of field.\n"
            f"6. SECTION 6 (DIALOGUE SCRIPT): The presenter speaks naturally in {lang_name} about \"{product_name}\" (authentic UGC tone, ~15-20 words, no exaggerated claims, ending with soft CTA).\n\n"
            f"═══ OUTPUT FORMAT ═══\n"
            f"CRITICAL: DO NOT use negative words like 'extra limbs', 'mutated', 'deformed', or 'missing fingers' in your output because the video AI will block it for safety. Instead, describe the anatomy POSITIVELY (e.g., 'two perfectly normal hands', 'natural five fingers').\nOutput EXACTLY {n_segments} lines. One prompt per line.\n"
            f"No numbering (1. 2. 3.), no bullet points, no markdown, no explanations.\n"
            f"Just {n_segments} raw prompt lines.\n"
        )

        def _run_gemini(keys):
            if not keys: return None
            with getattr(self, "_ai_key_lock", threading.Lock()):
                start_idx = getattr(self, "_gemini_key_rr_idx", 0) % len(keys)
                self._gemini_key_rr_idx = getattr(self, "_gemini_key_rr_idx", 0) + 1
            keys_ordered = list(keys[start_idx:]) + list(keys[:start_idx])
            _MODELS = ["gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3-flash-preview", "gemini-3.5-flash", "gemini-3.7-flash"]
            for key in keys_ordered:
                k_tag = f"...{key[-6:]}" if len(key) >= 6 else key
                for model_name in _MODELS:
                    try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={key}"
                        payload = json.dumps({
                            "contents": [{"parts": [{"text": system_prompt}]}],
                            "generationConfig": {"temperature": 0.9}
                        }).encode("utf-8")
                        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                        text = ""
                        for part in (data.get("candidates", [{}])[0].get("content", {}).get("parts", [])):
                            text += part.get("text", "")
                        prompts = [p.strip() for p in text.strip().split("\n") if p.strip() and len(p.strip()) > 20]
                        if len(prompts) >= n_segments:
                            self._seed_log_msg(f"  ✅ Gemini OK ({model_name} | key {k_tag})")
                            return prompts[:n_segments]
                    except urllib.error.HTTPError as he:
                        if he.code == 429:
                            self._seed_log_msg(f"  ⚠ {model_name} key {k_tag} quota 429 → chuyển key/model tiếp")
                            continue
                        self._seed_log_msg(f"  ⚠ Gemini {model_name} key {k_tag} HTTP {he.code}")
                        break
                    except Exception as e:
                        self._seed_log_msg(f"  ⚠ Gemini key {k_tag} lỗi: {str(e)[:50]}")
                        break
            return None

        def _run_groq(keys):
            if not keys: return None
            with getattr(self, "_ai_key_lock", threading.Lock()):
                start_idx = getattr(self, "_groq_key_rr_idx", 0) % len(keys)
                self._groq_key_rr_idx = getattr(self, "_groq_key_rr_idx", 0) + 1
            keys_ordered = list(keys[start_idx:]) + list(keys[:start_idx])
            groq_model = "llama-3.1-8b-instant"
            for key in keys_ordered:
                k_tag = f"...{key[-6:]}" if len(key) >= 6 else key
                try:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    payload = json.dumps({
                        "model": groq_model,
                        "messages": [
                            {"role": "system", "content": "You generate Google Veo 3 video prompts for Shopee product reviews."},
                            {"role": "user", "content": system_prompt}
                        ],
                        "temperature": 0.9,
                        "max_tokens": 2000
                    }).encode("utf-8")
                    req = urllib.request.Request(url, data=payload, headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    })
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    prompts = [p.strip() for p in text.strip().split("\n") if p.strip() and len(p.strip()) > 20]
                    if len(prompts) >= n_segments:
                        self._seed_log_msg(f"  ✅ Groq OK ({groq_model} | key {k_tag})")
                        return prompts[:n_segments]
                except Exception as e:
                    err_str = str(e).lower()
                    if any(tok in err_str for tok in ("401", "403", "restricted", "blocked", "invalid", "forbidden")):
                        self._seed_log_msg(f"  ⚠ Groq key {k_tag} bị khóa/lỗi ({e}) → Chuyển key tiếp theo.")
                        continue
                    continue
            return None

        if mode == "gemini":
            if gemini_keys:
                res = _run_gemini(gemini_keys)
                if res: return res
            if groq_keys:
                self._seed_log_msg("  🔄 Gemini thất bại, tự động chuyển sang Groq...")
                res = _run_groq(groq_keys)
                if res: return res
        elif mode == "groq":
            if groq_keys:
                res = _run_groq(groq_keys)
                if res: return res
            if gemini_keys:
                self._seed_log_msg("  🔄 Groq thất bại, tự động chuyển sang Gemini...")
                res = _run_gemini(gemini_keys)
                if res: return res
        return None

    def _seed_start_work(self, api_keys):
        """Worker chính xử lý tạo video qua Seedvis API (Veo 3.1)."""
        # Round-robin Seedvis API keys
        self._sv_key_lock = threading.Lock()
        self._sv_key_idx = 0
        def _next_sv_key():
            with self._sv_key_lock:
                key = api_keys[self._sv_key_idx % len(api_keys)]
                self._sv_key_idx += 1
            return key
        api_key = api_keys[0]  # default for backward compat
        out_dir = self._seed_outdir.get().strip()
        products = list(self._seed_claimed_products)
        scene_choice = self._seed_scene.get()
        naming_mode = self._seed_naming.get()
        client_id = self._seed_client_entry.get().strip()
        ai_mode = self._seed_ai_prompt.get()
        review_style = self._seed_review_style.get()
        del_img = self._seed_del_img.get()
        ghep_anh = self._seed_ghep_anh.get()

        # Cấu hình tự động xin thêm SP khi hàng đợi sắp cạn (đọc trên main thread cho an toàn)
        auto_refill = self._seed_auto_refill.get()
        try:
            auto_refill_threshold = max(0, int(self._seed_auto_refill_threshold.get().strip() or "100"))
        except Exception:
            auto_refill_threshold = 100
        try:
            auto_refill_amount = max(1, int(self._seed_auto_refill_amount.get().strip() or "1000"))
        except Exception:
            auto_refill_amount = 1000
        sort_map = {"Số bán cao nhất": "sold", "Hoa hồng cao nhất": "commission"}
        refill_sort_by = sort_map.get(self._seed_sort_by.get(), "sold")
        refill_market = self._seed_market.get()
        try:
            refill_min_item_id = int(re.sub(r'\D', '', self._seed_min_item_id.get().strip()) or "40000000000")
        except Exception:
            refill_min_item_id = 40000000000
        try:
            refill_min_commission = float(self._seed_min_commission.get().strip().replace("%", "") or "1.0")
        except Exception:
            refill_min_commission = 1.0
        refill_min_sold = parse_count(self._seed_min_sold.get().strip())
        refill_min_price = parse_price(self._seed_min_price.get().strip(), default=0.0)
        _rmax = self._seed_max_price.get().strip()
        refill_max_price = parse_price(_rmax, default=None) if _rmax else None

        # Nhà cung cấp video: Seedvis (Veo 3.1) hoặc NovaGateway (google/flow-veo)
        video_provider = "nova" if self._seed_provider.get().startswith("NovaGateway") else "seedvis"
        provider_label = "NovaGateway" if video_provider == "nova" else "Seedvis"
        nova_model = self._nova_model.get().strip() or "google/flow-veo"
        nova_resolution = self._nova_resolution.get().strip() or "480p"
        try:
            nova_seconds = max(1, min(15, int(self._nova_duration.get().strip() or "6")))
        except Exception:
            nova_seconds = 6
        # Số job NovaGateway được render đồng thời theo gói (Studio = 5/tài khoản; 2 tài khoản thì đặt 10).
        # Gửi vượt số này sẽ bị 429 → giữ hàng chờ ngay trong máy thay vì gửi lên để bị từ chối.
        try:
            nova_slots = max(1, min(64, int(self._nova_slots.get().strip() or "5")))
        except Exception:
            nova_slots = 5
        nova_slot_sem = threading.Semaphore(nova_slots)
        # Trạng thái "tạm ngưng gửi" dùng chung mọi luồng khi NovaGateway báo quá tải
        nova_state = {"cooldown_until": 0.0, "busy_streak": 0, "probe_at": 0.0}
        nova_state_lock = threading.Lock()

        if ai_mode == "Gemini" and not self.gemini_keys:
            messagebox.showwarning("Thiếu Key Gemini", "Vui lòng nạp API Key Gemini qua nút '🔑 AI Keys' hoặc kiểm tra settings.json.")
            return
        if ai_mode == "Groq" and not self.groq_keys:
            messagebox.showwarning("Thiếu Key Groq", "Vui lòng nạp API Key Groq qua nút '🔑 AI Keys' hoặc kiểm tra settings.json.")
            return

        try:
            num_threads = int(self._seed_threads.get().strip() or "12")
        except:
            num_threads = 12
        num_threads = max(1, min(64, num_threads))

        model_choice = self._seed_model.get().strip() or "Veo-3.1"
        clip_duration = self._seed_duration.get().strip() or "8s"
        upscale_choice = self._seed_upscale.get().strip() or "none"

        duration_sec = SV.parse_duration(self._seed_total_dur.get()) if SV else 16
        if duration_sec == 8 and ghep_anh:
            ai_mode = "Template (mặc định)"
        n_segments_needed = len(SV.DURATION_MAP.get(duration_sec, [0])) if SV else 1

        aspect_local = self._seed_aspect.get()
        seed_aspect = "16:9" if "16:9" in aspect_local else "9:16"
        # NovaGateway hỗ trợ thêm tỉ lệ vuông 1:1 (Seedvis không có nên seed_aspect giữ nguyên 2 lựa chọn cũ)
        nova_aspect = "1:1" if "1:1" in aspect_local else ("16:9" if "16:9" in aspect_local else "9:16")
        # Nhãn thời lượng để ghi log đúng nhà cung cấp (Seedvis "8s" cố định, Nova nhập tay 1-15s)
        clip_duration_label = f"{nova_seconds}s" if video_provider == "nova" else clip_duration

        lang_val = self._seed_lang.get()
        lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))

        self._seed_running = True
        self._seed_stop_flag = False
        self._seed_force_stop = False
        with self._seed_inflight_lock:
            self._seed_inflight = 0
        self._seed_btn_start.configure(state="disabled")
        self._seed_btn_stop.configure(state="normal", text="⏹ Dừng")
        self._seed_btn_claim.configure(state="disabled")
        self._seed_status_lbl.configure(text=f"⏳ Đang tạo video ({provider_label})...")

        def work():
            total = len(products)
            temp_dir = os.path.join(HERE, "temp_render")
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)

            daily_limit_enabled = self._seed_daily_limit_enabled.get()
            try:
                daily_limit = int(self._seed_daily_limit_entry.get().strip() or "1760")
            except Exception:
                daily_limit = 1760

            def count_today_videos(folder):
                if not folder or not os.path.exists(folder):
                    return 0
                today_d = datetime.date.today()
                c = 0
                try:
                    for entry in os.scandir(folder):
                        if entry.is_file() and entry.name.lower().endswith(".mp4"):
                            try:
                                if datetime.date.fromtimestamp(entry.stat().st_mtime) == today_d:
                                    c += 1
                            except Exception:
                                pass
                except Exception:
                    pass
                return c

            if video_provider != "nova" and daily_limit_enabled and daily_limit > 0:
                cur_today = count_today_videos(out_dir)
                if cur_today >= daily_limit:
                    self._seed_log_msg(f"\n{'='*50}")
                    self._seed_log_msg(f"🛑 [Seedvis] Hôm nay đã hoàn thành {cur_today}/{daily_limit} video (đã đủ hạn mức {daily_limit} video/ngày).")
                    self._seed_log_msg(f"🛑 Tự động giải phóng toàn bộ SP về Database Shopee để các máy khác làm...")
                    try:
                        self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                    except Exception:
                        pass
                    self._seed_finish()
                    return

            seg_info = f"{n_segments_needed} segment × {clip_duration_label}" if n_segments_needed > 1 else f"{clip_duration_label}"
            if video_provider == "nova":
                self._seed_log_msg(f"🌱 NovaGateway — Model: {nova_model} | Video: {duration_sec}s ({seg_info}) | Tỉ lệ: {nova_aspect} | {nova_resolution}")
                self._seed_log_msg(f"🚀 Số luồng xử lý: {num_threads} luồng | Slot gói NovaGateway: {nova_slots} job render cùng lúc")
            else:
                self._seed_log_msg(f"🌱 Seedvis — Model: {model_choice} | Video: {duration_sec}s ({seg_info}) | Tỉ lệ: {seed_aspect}")
                self._seed_log_msg(f"🚀 Số luồng xử lý: {num_threads} luồng")
            self._seed_log_msg(f"📋 {total} SP — Bắt đầu xử lý...")

            done_count = [0]
            self._seed_video_done_count = 0
            self.after(0, lambda: self._seed_video_done_lbl.configure(text=""))
            self._seed_completion_times = collections.deque()
            self._seed_run_started_at = time.time()

            self.after(0, lambda: self._seed_speed_lbl.configure(text="⚡ -- video/phút"))
            self.after(5000, self._seed_update_speed_label)
            error_count = [0]
            jobq = queue.Queue()
            for idx, prod in enumerate(products):
                prod["_idx"] = idx
                prod["_cycles"] = 0
                jobq.put(prod)

            if auto_refill:
                self._seed_log_msg(f"🔁 Tự động xin thêm SP: BẬT (khi còn dưới {auto_refill_threshold} job → xin thêm {auto_refill_amount} SP)")

            refill_state = {"in_progress": False, "next_allowed": 0.0}

            def do_auto_refill():
                """Xin thêm SP từ Server khi hàng đợi sắp cạn, để chạy 24/7 không bị hết job giữa chừng."""
                nonlocal total
                if refill_state["in_progress"] or self._seed_stop_flag:
                    return
                refill_state["in_progress"] = True
                try:
                    self._seed_log_msg(f"🔁 [Auto-Refill] Hàng đợi còn {jobq.qsize()} job (dưới {auto_refill_threshold}) → xin thêm {auto_refill_amount} SP...")
                    try:
                        _p = {
                            "market": refill_market, "clientId": client_id, "limit": auto_refill_amount, "sortBy": refill_sort_by,
                            "tool": "seedvis",
                            "min_item_id": refill_min_item_id, "min_commission": refill_min_commission,
                            "minItemId": refill_min_item_id, "minCommission": refill_min_commission,
                            "min_sold": refill_min_sold, "minSold": refill_min_sold,
                            "min_price": refill_min_price, "minPrice": refill_min_price,
                        }
                        if refill_max_price is not None:
                            _p["max_price"] = refill_max_price
                            _p["maxPrice"] = refill_max_price
                        result = self._seed_api_call("POST", "/api/thinaptm/claim-jobs", _p)
                    except Exception as e:
                        self._seed_log_msg(f"  ⚠ [Auto-Refill] Lỗi xin thêm SP: {e}")
                        refill_state["next_allowed"] = time.time() + 30
                        return
                    raw = result.get("products", []) if isinstance(result, dict) else []
                    new_list = []
                    for p in raw:
                        try:
                            iid = int(re.sub(r'\D', '', str(p.get("item_id", 0))))
                        except Exception:
                            iid = 0
                        try:
                            rc = float(p.get("commission_rate", 0) or 0)
                            comm = rc * 100.0 if 0 < rc <= 1.0 else rc
                            p["commission_rate"] = comm
                        except Exception:
                            comm = 0.0
                        sold_val = parse_count(p.get("sold", 0))
                        price_val = parse_price(p.get("price", 0))
                        if (refill_min_item_id > 0 and iid < refill_min_item_id) or comm < refill_min_commission \
                                or sold_val < refill_min_sold or price_val < refill_min_price \
                                or (refill_max_price is not None and price_val > refill_max_price):
                            continue
                        new_list.append(p)
                    if not new_list:
                        self._seed_log_msg("  ℹ [Auto-Refill] Server chưa có SP mới phù hợp, sẽ thử lại sau 30s.")
                        refill_state["next_allowed"] = time.time() + 30
                        return
                    start_idx = len(products)
                    for j, p in enumerate(new_list):
                        p["_idx"] = start_idx + j
                        p["_cycles"] = 0
                        products.append(p)
                    total += len(new_list)
                    for p in new_list:
                        jobq.put(p)
                    self._seed_claimed_products = list(products)

                    def _ui_append(items=new_list):
                        self._seed_products_text.configure(state="normal")
                        sym = "₫" if refill_market == "VN" else ("Rp" if refill_market == "ID" else "₱")
                        for p in items:
                            name = (p.get('name', '') or '')[:55]
                            iid = p.get('item_id', '?')
                            try: pv = float(p.get('price', 0) or 0)
                            except Exception: pv = 0.0
                            sold = p.get('sold', 0)
                            comm = float(p.get('commission_rate', 0) or 0)
                            self._seed_products_text.insert("end", f"⏳ [{p['_idx']+1}] {iid} | {name} | {sym}{pv:,.0f} | Sold:{sold} | Comm:{comm:.1f}%\n")
                        self._seed_list_count.configure(text=f"{len(products)} SP")
                    self.after(0, _ui_append)
                    self._seed_log_msg(f"  ✅ [Auto-Refill] Đã nhận thêm {len(new_list)} SP (tổng hàng đợi: {total})")
                finally:
                    refill_state["in_progress"] = False

            def submit_seedvis_job(prompt, b64_img, filename, image_url=None):
                _cur_key = _next_sv_key()
                endpoint = "https://seedvis.com/api/v1/developer/generations"
                idem_key = str(uuid.uuid4())
                headers = {
                    "Authorization": f"Bearer {_cur_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idem_key,
                    "User-Agent": SEEDVIS_UA,
                }
                if image_url and str(image_url).startswith("http"):
                    img_data = image_url
                else:
                    img_data = {
                        "data": b64_img,
                        "file_name": filename
                    }
                payload = {
                    "model": model_choice,
                    "prompt": prompt,
                    "mode": "image-to-video",
                    "image": img_data,
                    "aspect_ratio": seed_aspect,
                    "duration": clip_duration,
                    "count": 1,
                    "upscale_video": upscale_choice
                }

                attempt = 0      # lỗi mạng/server: tối đa 5 lần
                busy_tries = 0   # đầy slot / 429: tính riêng, chỉ là chờ tới lượt chứ không phải lỗi
                while attempt < 5:
                    if self._seed_stop_flag: return "stopped", None
                    try:
                        req_data = json.dumps(payload).encode("utf-8")
                        req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
                        with urllib.request.urlopen(req, timeout=60) as resp:
                            res_json = json.loads(resp.read().decode("utf-8"))
                            if isinstance(res_json, dict):
                                res_json["_key"] = _cur_key
                            return "ok", res_json
                    except urllib.error.HTTPError as he:
                        err_body = ""
                        try: err_body = he.read().decode("utf-8")
                        except Exception: pass
                        err_msg, err_fields, err_type = decode_api_error(err_body)
                        err_str = err_msg.lower()
                        # 1) Đầy slot tài khoản (422 "Đã đạt giới hạn..." hoặc 429) → chờ tới lượt, KHÔNG phải vi phạm
                        if is_capacity_full(he.code, err_msg, err_fields) or he.code == 429:
                            busy_tries += 1
                            if busy_tries > 40:
                                return "error", f"Seedvis đầy slot quá lâu: {err_msg[:120]}"
                            if busy_tries == 1 or busy_tries % 5 == 0:
                                self._seed_log_msg(f"  ⏸ Seedvis đầy slot ({busy_tries}/40) → chờ 20s: {err_msg[:130]}")
                            for _ in range(20):
                                if self._seed_stop_flag: return "stopped", None
                                time.sleep(1)
                            continue
                        # 2) Vi phạm nội dung thật (phải có từ khóa chính sách trong thông báo)
                        if is_policy_violation(err_msg):
                            self._seed_log_msg(f"  ⚠️ Seedvis báo vi phạm: {err_msg[:150]}")
                            return "violation", err_msg
                        if he.code == 401 or any(k in err_str for k in ["unauthorized", "invalid api key"]):
                            self._seed_log_msg(f"  ❌ Seedvis API Key không hợp lệ hoặc hết hạn!")
                            return "invalid_key", err_msg
                        if is_no_credit(he.code, err_msg, err_type):
                            self._seed_log_msg(f"  💳 Seedvis báo hết credit ({he.code}): {err_msg[:150]}")
                            return "no_credit", err_msg
                        if he.code in (500, 502, 503, 504):
                            attempt += 1
                            if attempt < 5:
                                self._seed_log_msg(f"  ⚠️ Seedvis lỗi server {he.code} (thử {attempt}/5): {err_msg[:150]}")
                                time.sleep(4)
                                continue
                            return "error", f"HTTP {he.code}: {err_msg[:120]}"
                        # 422 khác (sai tham số...) và mã còn lại: lỗi thường → thử lại SP sau, KHÔNG khóa SP
                        self._seed_log_msg(f"  ❌ Seedvis lỗi HTTP {he.code}: {err_msg[:150]}")
                        return "error", f"HTTP {he.code}: {err_msg[:120]}"
                    except Exception as ex:
                        attempt += 1
                        if attempt < 5:
                            self._seed_log_msg(f"  ⚠️ Seedvis submit lỗi mạng (thử {attempt}/5): {ex}")
                            time.sleep(4)
                            continue
                        return "error", str(ex)
                return "error", "Max retries"

            def poll_seedvis_job(job_id, key=None):
                poll_url = f"https://seedvis.com/api/v1/developer/generations/{job_id}?wait=60"
                headers = {"Authorization": f"Bearer {key or api_key}", "User-Agent": SEEDVIS_UA}
                start_ts = time.time()
                last_note = start_ts
                last_pos = None
                # Tài khoản Seedvis: 10 lượt render đồng thời + 20 lượt chờ. Job xếp cuối hàng có thể mất >10 phút.
                # Bỏ cuộc sớm rồi gửi job mới sẽ để lại job cũ "mồ côi" chiếm slot → đầy 30 slot → lỗi dây chuyền.
                while time.time() - start_ts < 1800:
                    # Chỉ bỏ khi "dừng ngay": job đã trừ phí & không hủy được trên server
                    if self._seed_force_stop: return "stopped", None
                    try:
                        req = urllib.request.Request(poll_url, headers=headers, method="GET")
                        with urllib.request.urlopen(req, timeout=70) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                    except Exception as e:
                        if int(time.time() - start_ts) % 30 < 6:
                            self._seed_log_msg(f"  ⚠️ Seedvis poll lỗi (sẽ tự thử lại): {e}")
                        time.sleep(6)
                        continue

                    job_data = data.get("data", {}) if isinstance(data, dict) else {}
                    is_final = job_data.get("is_final", False)
                    status = (job_data.get("status") or "").lower()
                    queue_info = job_data.get("queue") or {}
                    pos = queue_info.get("position") if isinstance(queue_info, dict) else None

                    if is_final:
                        if status in ("completed", "succeeded"):
                            outputs = job_data.get("outputs", [])
                            if outputs and isinstance(outputs, list):
                                vid_url = outputs[0].get("url")
                                if vid_url:
                                    return "succeeded", vid_url
                            return "error", "Job hoàn thành nhưng không có video url"
                        else:
                            err_obj = job_data.get("error") or {}
                            err_code = err_obj.get("code", "") if isinstance(err_obj, dict) else ""
                            err_msg = err_obj.get("message", "") if isinstance(err_obj, dict) else str(err_obj)
                            main_msg = job_data.get("message") or status
                            msg = f"[{err_code}] {err_msg}" if err_code and err_msg else (err_msg or main_msg)
                            if msg.lstrip().startswith(")]}'"):
                                msg = "Lỗi phiên nội bộ tạm thời của Seedvis (sẽ tự thử lại)"
                            if is_policy_violation(msg):
                                return "violation", msg
                            return "failed", msg

                    waited_min = int((time.time() - start_ts) // 60)
                    if status == "queued" and pos is not None and (last_pos is None or time.time() - last_note >= 300):
                        eta = queue_info.get("estimated_start_seconds")
                        eta_txt = f", dự kiến bắt đầu sau ~{max(1, int(eta) // 60)} phút" if isinstance(eta, (int, float)) else ""
                        self._seed_log_msg(f"  📋 Job {job_id} đang xếp hàng Seedvis: vị trí {pos}{eta_txt} (đã chờ {waited_min} phút)")
                        last_pos, last_note = pos, time.time()
                    elif time.time() - last_note >= 300:
                        last_note = time.time()
                        self._seed_log_msg(f"  ⏳ Job {job_id} vẫn '{status or 'đang chờ'}' sau {waited_min} phút")
                    # Seedvis gợi ý nhịp poll (next.after_seconds, vd 120s khi còn xếp hàng)
                    nxt = job_data.get("next") or {}
                    try:
                        nap = int(nxt.get("after_seconds") or 6) if status == "queued" else 6
                    except Exception:
                        nap = 6
                    for _ in range(max(6, min(nap, 60))):
                        if self._seed_force_stop: return "stopped", None
                        time.sleep(1)
                return "timeout", "Quá 30 phút chờ tạo video"

            # ── NovaGateway (google/flow-veo) ──────────────────────────────────────────────
            NOVA_COOLDOWN_MAX = 600   # tạm ngưng tối đa 10 phút khi nghẽn kéo dài
            NOVA_PROBE_EVERY = 120    # trong lúc tạm ngưng dài, cứ 2 phút cho ĐÚNG 1 luồng đi thăm dò

            def nova_register_busy(reason):
                """NovaGateway/Google Flow báo quá tải → mọi luồng tạm ngưng gửi job mới, thời gian tăng dần."""
                now = time.time()
                with nova_state_lock:
                    nova_state["busy_streak"] += 1
                    wait = min(15 * (2 ** (nova_state["busy_streak"] - 1)), NOVA_COOLDOWN_MAX)
                    until = now + wait
                    extended = until > nova_state["cooldown_until"]
                    if extended:
                        nova_state["cooldown_until"] = until
                    nova_state["probe_at"] = max(nova_state["probe_at"], now + NOVA_PROBE_EVERY)
                if extended:
                    self._seed_log_msg(f"  🧊 NovaGateway quá tải → tạm ngưng gửi job mới {wait}s ({reason[:70]})")
                return wait

            def nova_register_ok():
                """Có video thành công → server đã khỏe, bỏ tạm ngưng ngay cho mọi luồng."""
                with nova_state_lock:
                    nova_state["busy_streak"] = 0
                    nova_state["cooldown_until"] = 0.0
                    nova_state["probe_at"] = 0.0

            def nova_wait_cooldown():
                """True = được phép gửi. Trong lúc tạm ngưng dài, cho 1 luồng đi thăm dò mỗi
                NOVA_PROBE_EVERY giây để phát hiện server hồi phục sớm (thay vì chờ hết 10 phút)."""
                while True:
                    if self._seed_stop_flag or self._seed_force_stop: return False
                    now = time.time()
                    with nova_state_lock:
                        remain = nova_state["cooldown_until"] - now
                        if remain <= 0:
                            return True
                        probe = remain > NOVA_PROBE_EVERY and now >= nova_state["probe_at"]
                        if probe:
                            nova_state["probe_at"] = now + NOVA_PROBE_EVERY
                    if probe:
                        self._seed_log_msg(f"  🔍 Gửi 1 job thăm dò xem NovaGateway hồi phục chưa (còn tạm ngưng {int(remain)}s)")
                        return True
                    time.sleep(min(1.0, remain))

            def submit_nova_job(prompt, b64_img, image_url=None):
                """Gửi job tạo video qua NovaGateway. Ưu tiên link ảnh https gốc để khỏi nhúng base64 nặng."""
                _cur_key = _next_sv_key()
                endpoint = "https://novagateway.net/v1/videos"
                # Cloudflare (đứng trước NovaGateway) chặn request thiếu User-Agent giống trình duyệt,
                # trả lỗi 403 "error code: 1010" trước khi tới được backend Nova.
                headers = {"Authorization": f"Bearer {_cur_key}", "Content-Type": "application/json",
                           "User-Agent": SEEDVIS_UA}
                if image_url and str(image_url).startswith("http"):
                    img_field = {"url": image_url}
                else:
                    img_field = {"url": f"data:image/jpeg;base64,{b64_img}"}
                payload = {
                    "model": nova_model,
                    "prompt": prompt,
                    "seconds": str(nova_seconds),
                    "extra_body": {"resolution": nova_resolution, "aspect_ratio": nova_aspect},
                    "image": img_field,
                }
                attempt = 0
                busy_tries = 0
                while attempt < 5:
                    if self._seed_stop_flag: return "stopped", None
                    try:
                        req_data = json.dumps(payload).encode("utf-8")
                        req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
                        with urllib.request.urlopen(req, timeout=60) as resp:
                            res_json = json.loads(resp.read().decode("utf-8"))
                            if isinstance(res_json, dict):
                                res_json["_key"] = _cur_key
                            return "ok", res_json
                    except urllib.error.HTTPError as he:
                        err_body = ""
                        try: err_body = he.read().decode("utf-8")
                        except Exception: pass
                        err_msg, err_fields, err_type = decode_api_error(err_body)
                        err_str = err_msg.lower()
                        # Xét quá tải TRƯỚC: thông báo 503 của Nova có câu "(Không mất Credits)" — nếu xét
                        # hết-tiền trước sẽ khớp nhầm chữ "credits" và làm DỪNG toàn bộ hàng đợi.
                        if he.code == 429 or is_capacity_full(he.code, err_msg, err_fields):
                            busy_tries += 1
                            if busy_tries > 20:
                                return "error", f"HTTP {he.code} quá 20 lần: {err_msg[:120]}"
                            nova_register_busy(f"HTTP {he.code}: {err_msg}")
                            if not nova_wait_cooldown(): return "stopped", None
                            continue
                        if "content_policy" in err_str or is_policy_violation(err_msg):
                            self._seed_log_msg(f"  ⚠️ NovaGateway báo vi phạm: {err_msg[:150]}")
                            return "violation", err_msg
                        if he.code == 401 or "unauthorized" in err_str:
                            self._seed_log_msg(f"  ❌ NovaGateway API Key không hợp lệ hoặc hết hạn!")
                            return "invalid_key", err_msg
                        if is_no_credit(he.code, err_msg, err_type):
                            self._seed_log_msg(f"  💳 NovaGateway báo hết credit ({he.code}): {err_msg[:150]}")
                            return "no_credit", err_msg
                        if he.code in (500, 502, 504):
                            attempt += 1
                            if attempt < 5:
                                self._seed_log_msg(f"  ⚠️ NovaGateway lỗi server {he.code} (thử {attempt}/5): {err_msg[:150]}")
                                time.sleep(4)
                                continue
                            return "error", f"HTTP {he.code}: {err_msg[:120]}"
                        self._seed_log_msg(f"  ❌ NovaGateway lỗi HTTP {he.code}: {err_msg[:150]}")
                        return "error", f"HTTP {he.code}: {err_msg[:120]}"
                    except Exception as ex:
                        attempt += 1
                        if attempt < 5:
                            self._seed_log_msg(f"  ⚠️ NovaGateway submit lỗi mạng (thử {attempt}/5): {ex}")
                            time.sleep(4)
                            continue
                        return "error", str(ex)
                return "error", "Max retries"

            def poll_nova_job(job_id, key):
                poll_url = f"https://novagateway.net/v1/videos/{job_id}"
                headers = {"Authorization": f"Bearer {key}", "User-Agent": SEEDVIS_UA}
                start_ts = time.time()
                # Nova tự báo failed khi job quá 10 phút → chờ tới 15 phút để nhận đúng kết quả đó,
                # thay vì tự bỏ cuộc sớm rồi gửi lại (job cũ thành mồ côi, tốn slot).
                while time.time() - start_ts < 900:
                    if self._seed_force_stop: return "stopped", None
                    try:
                        req = urllib.request.Request(poll_url, headers=headers, method="GET")
                        with urllib.request.urlopen(req, timeout=70) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                    except Exception as e:
                        if int(time.time() - start_ts) % 60 < 10:
                            self._seed_log_msg(f"  ⚠️ NovaGateway poll lỗi (sẽ tự thử lại): {e}")
                        time.sleep(10)
                        continue

                    status = (data.get("status") or "").lower()
                    if status == "completed":
                        vid_url = data.get("video_url") or data.get("url") or data.get("share_url")
                        if vid_url:
                            return "succeeded", vid_url
                        return "error", "Job hoàn thành nhưng không có video url"
                    elif status == "failed":
                        err_obj = data.get("error") or {}
                        err_code = err_obj.get("code", "") if isinstance(err_obj, dict) else ""
                        err_msg = err_obj.get("message", "") if isinstance(err_obj, dict) else str(err_obj)
                        msg = f"[{err_code}] {err_msg}" if err_code and err_msg else (err_msg or "failed")
                        if err_code == "content_policy" or "content_policy" in msg.lower():
                            return "violation", msg
                        # Quá tải/tạm thời phía Nova hoặc Google Flow (Nova đã hoàn credit) → không phải lỗi của SP
                        if err_code in NOVA_TRANSIENT_CODES or any(k in msg.lower() for k in NOVA_TRANSIENT_HINTS):
                            return "busy", msg
                        return "failed", msg

                    time.sleep(10)  # Veo render mất 1-3 phút, poll dày hơn chỉ tăng nguy cơ 429
                return "timeout", "Quá 15 phút chờ tạo video"

            def submit_and_poll_segment(prompt, b64_img, image_url, item_id):
                """Gộp submit+poll cho cả 2 nhà cung cấp → (status, video_url_or_err).
                status: stopped/invalid_key/no_credit/violation/submit_error/succeeded/failed/timeout/busy/error"""
                if video_provider == "nova":
                    NOVA_SAME_SP_TRIES = 3
                    res, data = "error", None
                    for try_i in range(1, NOVA_SAME_SP_TRIES + 1):
                        if not nova_wait_cooldown(): return "stopped", None
                        if not nova_slot_sem.acquire(blocking=False):
                            self._seed_log_msg(f"  ⏸ Đã đủ {nova_slots} job đang render → chờ slot NovaGateway trống...")
                            while not nova_slot_sem.acquire(timeout=1):
                                if self._seed_stop_flag: return "stopped", None
                        try:
                            sub_res, sub_data = submit_nova_job(prompt, b64_img, image_url=image_url)
                            if sub_res == "stopped": return "stopped", None
                            if sub_res in ("invalid_key", "no_credit", "violation"): return sub_res, sub_data
                            if sub_res != "ok": return "submit_error", sub_data
                            job_id = sub_data.get("id", "") if isinstance(sub_data, dict) else ""
                            self._seed_log_msg(f"  ⏳ Job {job_id} đang render (NovaGateway)...")
                            self._seed_inflight_add(1)
                            try:
                                res, data = poll_nova_job(job_id, sub_data.get("_key"))
                            finally:
                                self._seed_inflight_add(-1)
                        finally:
                            nova_slot_sem.release()
                        if res == "busy":
                            wait = nova_register_busy(str(data))
                            if try_i < NOVA_SAME_SP_TRIES:
                                self._seed_log_msg(f"  🔁 NovaGateway quá tải → thử lại chính SP này sau ~{wait}s (lần {try_i + 1}/{NOVA_SAME_SP_TRIES}): {str(data)[:90]}")
                                continue
                            return "busy", data
                        if res == "succeeded":
                            nova_register_ok()
                        return res, data
                    return res, data

                sub_res, sub_data = submit_seedvis_job(prompt, b64_img, f"{item_id}.jpg", image_url=image_url)
                if sub_res == "stopped": return "stopped", None
                if sub_res in ("invalid_key", "no_credit", "violation"): return sub_res, sub_data
                if sub_res != "ok": return "submit_error", sub_data

                gen_data = sub_data.get("data", {}) if isinstance(sub_data, dict) else {}
                job_id = gen_data.get("id", "")
                self._seed_log_msg(f"  ⏳ Job {job_id} đã gửi, đang chờ Seedvis render...")
                self._seed_inflight_add(1)
                try:
                    return poll_seedvis_job(job_id, sub_data.get("_key"))
                finally:
                    self._seed_inflight_add(-1)

            def process_one(prod):
                idx = prod["_idx"]
                if self._seed_stop_flag: return "retry_soft"
                item_id = prod.get("item_id", "")
                product_name = prod.get("name", f"Product_{item_id}")
                image_url = prod.get("image_url", "")

                blocked = BLOCKED_IP_RE.search(product_name)
                if blocked:
                    self._seed_log_msg(f"\n📦 [{idx+1}/{total}] {product_name[:50]}")
                    self._seed_log_msg(f"  🚫 Bỏ qua: nhân vật bản quyền ('{blocked.group(0)}')")
                    prod["_status"] = "noretry"
                    self._seed_report_job_status(item_id, "failed")
                    self._seed_update_line_status(idx, "error")
                    return ("fail", "Nhân vật bản quyền")

                # PRE-RENDER DUPLICATE SHIELD: Tránh render trùng nếu SP đã có video trong out_dir của máy này
                existing_vid = None
                if out_dir and os.path.exists(out_dir):
                    for c_fn in (f"{item_id}.mp4", f"{item_id}_12s.mp4"):
                        cf = os.path.join(out_dir, c_fn)
                        if os.path.exists(cf) and os.path.getsize(cf) > 10240:
                            existing_vid = cf
                            break

                if existing_vid:
                    self._seed_log_msg(f"  ⚡ SP {item_id} đã có video tại [{existing_vid}]! Tự động bỏ qua để tránh trùng.")
                    prod["_status"] = "noretry"
                    self._seed_report_job_status(item_id, "completed", extra={"video_path": os.path.basename(existing_vid)})
                    self._seed_update_line_status(idx, "success")
                    return ("ok", existing_vid)

                self._seed_update_line_status(idx, "running")
                self._seed_log_msg(f"\n{'='*50}")
                self._seed_log_msg(f"📦 [{idx+1}/{total}] {product_name[:50]}")

                # Tải ảnh
                img_path = os.path.join(temp_dir, f"{item_id}_{idx}.jpg")
                if not os.path.isfile(img_path):
                    if not image_url:
                        self._seed_log_msg(f"  ⚠ Không có image_url")
                        prod["_status"] = "noretry"
                        self._seed_report_job_status(item_id, "failed")
                        self._seed_update_line_status(idx, "error")
                        return ("fail", "Không có ảnh")
                    self._seed_log_msg(f"  📥 Tải ảnh: {image_url[:60]}...")
                    if not self._seed_download_image(image_url, img_path):
                        prod["_status"] = "noretry"
                        self._seed_report_job_status(item_id, "failed")
                        self._seed_update_line_status(idx, "error")
                        return ("fail", "Tải ảnh thất bại")
                    self._seed_log_msg(f"  ✅ Ảnh OK: {os.path.basename(img_path)}")

                # Base64
                try:
                    with open(img_path, "rb") as bf:
                        b64_img = base64.b64encode(bf.read()).decode("utf-8")
                except Exception as e:
                    self._seed_log_msg(f"  ❌ Lỗi đọc file ảnh: {e}")
                    return "retry_soft"

                # Prompt
                scene_name, scene_en = SV.pick_scene(scene_choice, lang=lang_code)
                prompts = None
                if n_segments_needed == 1 and ai_mode in ("Prompt A + B", "Template (mặc định)"):
                    tvc_prompt, tvc_label = SV.build_tvc_prompt(product_name, lang=lang_code, review_style=review_style)
                    prompts = [tvc_prompt]
                    short_name = product_name[:80].strip()
                    self._seed_log_msg(f"  📺 TVC {clip_duration_label}: 1 prompt ({tvc_label} - SP: {short_name[:40]}...)")
                else:
                    if ai_mode == "Gemini":
                        prompts = self._seed_ai_gen_prompts(
                            product_name, scene_en, n_segments_needed, duration_sec, lang_code, review_style,
                            mode="gemini", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys
                        )
                    elif ai_mode == "Groq":
                        prompts = self._seed_ai_gen_prompts(
                            product_name, scene_en, n_segments_needed, duration_sec, lang_code, review_style,
                            mode="groq", gemini_keys=self.gemini_keys, groq_keys=self.groq_keys
                        )

                    if prompts and len(prompts) >= n_segments_needed:
                        prompts = prompts[:n_segments_needed]
                        self._seed_log_msg(f"  🤖 AI sinh {len(prompts)} prompt ({ai_mode}, cảnh: {scene_name})")
                    else:
                        if n_segments_needed == 1:
                            tvc_prompt, tvc_label = SV.build_tvc_prompt(product_name, lang=lang_code, review_style=review_style)
                            prompts = [tvc_prompt]
                            short_name = product_name[:80].strip()
                            if ai_mode in ("Gemini", "Groq"):
                                self._seed_log_msg(f"  ⚠ AI không phản hồi → dùng TVC fallback (SP: {short_name[:40]}...)")
                            else:
                                self._seed_log_msg(f"  📺 TVC {clip_duration_label}: 1 prompt ({tvc_label} - SP: {short_name[:40]}...)")
                        else:
                            prompts = SV.build_video_prompts_fallback(product_name, scene_en, duration_sec, lang=lang_code, review_style=review_style)
                            if ai_mode in ("Gemini", "Groq"):
                                self._seed_log_msg(f"  ⚠ AI không phản hồi → dùng Prompt A + B fallback")
                            else:
                                self._seed_log_msg(f"  📝 Sinh {len(prompts)} prompt ({ai_mode})")

                n_segments = len(prompts)
                clip_paths = []
                for seg_idx, prompt in enumerate(prompts):
                    if self._seed_stop_flag: return "retry_soft"
                    clip_path = os.path.join(temp_dir, f"seed_{item_id}_{idx}_seg{seg_idx}.mp4")
                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 10 * 1024:
                        self._seed_log_msg(f"  ⚡ Seg {seg_idx+1}: Dùng lại file cũ ({os.path.getsize(clip_path)//1024}KB)")
                        clip_paths.append(clip_path)
                        continue

                    api_prompt = prompt
                    if len(api_prompt) > 4900:
                        CONDENSED = "=== SECTION 1: RULES ===\n- Full-frame 9:16 vertical video, edge-to-edge, NO borders/bars/margins.\n- Photorealistic live-action only. NO cartoon/anime/CGI.\n- NO text/subtitles/watermarks on screen.\n- Product must match reference image exactly.\n- Realistic product size. NO oversized items.\n- Neutral color grading, no morphing or identity drift.\n\n"
                        import re as _re
                        api_prompt = _re.sub(r'=== SECTION 1:.*?=== SECTION 2:', CONDENSED + '=== SECTION 2:', api_prompt, count=1, flags=_re.DOTALL)
                        if len(api_prompt) > 4900:
                            api_prompt = api_prompt[:4900]

                    self._seed_log_msg(f"  🎬 Gửi tạo Segment {seg_idx+1}/{n_segments} ({clip_duration_label}, {provider_label})...")
                    seg_res, seg_data = submit_and_poll_segment(api_prompt, b64_img, image_url, item_id)
                    if seg_res == "stopped": return "retry_soft"
                    if seg_res == "invalid_key":
                        prod["_status"] = "noretry"
                        self._seed_update_line_status(idx, "error")
                        return ("fail", f"Sai {provider_label} API Key")
                    if seg_res == "no_credit":
                        if video_provider != "nova":
                            # Seedvis hết credit / chạm hạn mức 880 video/ngày: DỪNG NGAY và giải phóng SP kẹt
                            self._seed_log_msg(f"\n{'='*50}")
                            self._seed_log_msg(f"🛑 [Seedvis] API Key đã hết hạn mức credit (880 video/ngày)!")
                            self._seed_log_msg(f"🛑 Tự động dừng phần mềm và giải phóng toàn bộ SP kẹt về Database Shopee...")
                            self._seed_stop_flag = True
                            self._seed_force_stop = True
                            try:
                                self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                            except Exception:
                                pass
                            return ("no_credit", "Hết credit Seedvis (880/ngày)")
                        else:
                            self._seed_log_msg(f"  ⚠️ {provider_label} báo hết credit/số dư (nghi lỗi tạm thời) → hoãn SP")
                            nova_register_busy("báo hết credit (nghi lỗi tạm thời)")
                            return "retry_busy"
                    if seg_res == "violation":
                        prod["_status"] = "vi phạm cs"
                        self._seed_report_job_status(item_id, "vi phạm cs")
                        self._seed_update_line_status(idx, "violation")
                        return ("fail", f"Vi phạm chính sách {provider_label}")
                    if seg_res == "submit_error":
                        self._seed_log_msg(f"  ❌ Submit Segment {seg_idx+1} thất bại: {seg_data}")
                        return "retry_soft"
                    if seg_res == "busy":
                        # Quá tải phía nhà cung cấp, KHÔNG phải lỗi của SP → hoãn, không tính chu kỳ lỗi
                        self._seed_log_msg(f"  ⏸ {provider_label} vẫn quá tải sau nhiều lần thử → hoãn SP, không tính lỗi")
                        return "retry_busy"
                    if seg_res != "succeeded":
                        self._seed_log_msg(f"  ❌ Segment {seg_idx+1} thất bại: {seg_data}")
                        return "retry_soft"

                    video_url = seg_data
                    self._seed_log_msg(f"  📥 Tải video segment {seg_idx+1}...")
                    # Video đã render xong (đã tốn thời gian/credit) → thử tải lại vài lần trước khi bỏ
                    dl_err = None
                    for dl_try in range(4):
                        if self._seed_force_stop: return "retry_soft"
                        try:
                            _dl_req = urllib.request.Request(video_url, headers={"User-Agent": SEEDVIS_UA})
                            with urllib.request.urlopen(_dl_req, timeout=120) as _dl_resp, open(clip_path, "wb") as _dl_f:
                                while True:
                                    chunk = _dl_resp.read(65536)
                                    if not chunk: break
                                    _dl_f.write(chunk)
                            dl_err = None
                            break
                        except Exception as de:
                            dl_err = de
                            if dl_try < 3:
                                self._seed_log_msg(f"  ⚠ Tải video lỗi (thử {dl_try+1}/4): {de} → tải lại...")
                                time.sleep(3 * (dl_try + 1))
                    if dl_err is not None:
                        self._seed_log_msg(f"  ❌ Tải video lỗi sau 4 lần: {dl_err}")
                        try:
                            if os.path.exists(clip_path): os.remove(clip_path)
                        except Exception: pass
                        return "retry_soft"

                    if os.path.exists(clip_path) and os.path.getsize(clip_path) > 10 * 1024:
                        clip_paths.append(clip_path)
                        self._seed_log_msg(f"  ✅ Seg {seg_idx+1} OK ({os.path.getsize(clip_path)//1024}KB)")
                    else:
                        self._seed_log_msg(f"  ❌ Seg {seg_idx+1}: File rỗng")
                        return "retry_soft"

                if not clip_paths: return "retry_soft"

                if len(clip_paths) > 1:
                    self._seed_log_msg(f"  🔗 Ghép {len(clip_paths)} segments...")
                    concat_path = os.path.join(temp_dir, f"seed_{item_id}_{idx}_concat.mp4")
                    try:
                        SV.concat_videos(clip_paths, concat_path, log=lambda m: self._seed_log_msg(f"    {m}"))
                    except Exception as ex:
                        return ("fail", f"Ghép lỗi: {ex}")
                else:
                    concat_path = clip_paths[0]

                # Ghép ảnh outro 12s nếu chọn
                ghep_anh_loi = False
                if ghep_anh and duration_sec == 8:
                    self._seed_log_msg("  🎞 Bắt đầu ghép ảnh outro tạo video 12s...")
                    merged_path = os.path.join(temp_dir, f"seed_{item_id}_{idx}_merged12s.mp4")
                    ok, err = self._run_ghep_anh_12s(concat_path, img_path, merged_path)
                    if ok and os.path.exists(merged_path):
                        concat_path = merged_path
                        self._seed_log_msg("    ✅ Ghép ảnh outro 12s thành công!")
                    else:
                        self._seed_log_msg(f"    ⚠ Ghép ảnh lỗi: {err}. Giữ lại video gốc 8s.")
                        ghep_anh_loi = True

                if naming_mode == "Theo Item ID":
                    out_name = f"{item_id}.mp4"
                elif naming_mode == "15 ký tự đầu prompt":
                    out_name = (SV.clean_filename(prompts[0][:15]) if hasattr(SV, 'clean_filename') else f"seed_{item_id}") + ".mp4"
                else:
                    out_name = f"{idx+1:04d}.mp4"

                target_dir = os.path.join(out_dir, "video8sloi") if ghep_anh_loi else out_dir
                os.makedirs(target_dir, exist_ok=True)
                out_path = os.path.join(target_dir, out_name)
                counter = 2
                while os.path.exists(out_path):
                    base, ext = os.path.splitext(out_name)
                    out_path = os.path.join(target_dir, f"{base}_{counter}{ext}")
                    counter += 1

                try:
                    shutil.move(concat_path, out_path)
                    self._seed_log_msg(f"  ✅ Hoàn tất video: {os.path.basename(out_path)}")
                except Exception as ex:
                    return ("fail", f"Lỗi di chuyển file: {ex}")

                self._seed_report_job_status(item_id, "completed", {"videoFile": os.path.basename(out_path)})

                if del_img:
                    try:
                        if os.path.isfile(img_path):
                            os.remove(img_path)
                    except Exception:
                        pass

                prod["_status"] = "success"
                self._seed_update_line_status(idx, "success")
                return ("ok", out_path)

            def worker_thread():
                while not self._seed_stop_flag:
                    try:
                        prod = jobq.get(timeout=1)
                    except queue.Empty:
                        # Bật auto-refill → hàng đợi rỗng chỉ là tạm thời, chờ tiếp thay vì thoát luồng
                        if auto_refill:
                            continue
                        break
                    idx = prod["_idx"]
                    try:
                        res = process_one(prod)
                        if isinstance(res, tuple) and res[0] == "ok":
                            done_count[0] += 1
                            self._seed_video_done_count = done_count[0]
                            self._seed_completion_times.append(time.time())
                            pct = done_count[0] / total
                            self.after(0, lambda p=pct: self._seed_progress.set(p))
                            self.after(0, lambda: self._seed_video_done_lbl.configure(text=f"✅ {done_count[0]}/{total} xong"))

                            # Kiểm tra hạn mức video/ngày của Seedvis (mặc định 880 video/ngày)
                            if video_provider != "nova" and daily_limit_enabled and daily_limit > 0:
                                today_video_cnt = count_today_videos(out_dir)
                                if today_video_cnt >= daily_limit:
                                    self._seed_log_msg(f"\n{'='*50}")
                                    self._seed_log_msg(f"🛑 [Seedvis] ĐÃ ĐẠT HẠN MỨC {daily_limit} VIDEO/NGÀY HÔM NAY (Đã tạo {today_video_cnt} video).")
                                    self._seed_log_msg(f"🛑 Tự động dừng phần mềm và giải phóng toàn bộ SP còn lại về Database Shopee...")
                                    self._seed_stop_flag = True
                                    self._seed_force_stop = True
                                    try:
                                        self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                                    except Exception:
                                        pass
                                    self.after(0, lambda c=today_video_cnt: self._seed_status_lbl.configure(
                                        text=f"🛑 Đủ {c}/{daily_limit} video hôm nay - Đã dừng & giải phóng SP"
                                    ))
                        elif isinstance(res, tuple) and res[0] == "no_credit":
                            self._seed_stop_flag = True
                            self._seed_force_stop = True
                            self._seed_update_line_status(idx, "error")
                            self.after(0, lambda: self._seed_status_lbl.configure(
                                text=f"🛑 Hết Credit ({APP_NAME}) - Đã dừng & giải phóng SP"
                            ))
                            break
                        elif res == "retry_busy":
                            # Nhà cung cấp quá tải: hoãn SP về cuối hàng đợi, KHÔNG tăng chu kỳ → không bị báo failed oan
                            if not self._seed_stop_flag:
                                jobq.put(prod)
                            self._seed_update_line_status(idx, "running")
                        elif res == "retry_soft":
                            prod["_cycles"] = prod.get("_cycles", 0) + 1
                            if prod["_cycles"] < 3 and not self._seed_stop_flag:
                                self._seed_log_msg(f"  🔄 Thử lại SP {prod.get('item_id')} (chu kỳ {prod['_cycles']}/3)...")
                                jobq.put(prod)
                            else:
                                error_count[0] += 1
                                self._seed_update_line_status(idx, "error")
                                if not self._seed_stop_flag:
                                    self._seed_release_single_job(prod.get("item_id", ""))
                                    self._seed_log_msg(f"  🔄 Đã trả SP {prod.get('item_id')} về pending sau 3 chu kỳ thử lỗi.")
                        else:
                            error_count[0] += 1
                    except Exception as ex:
                        error_count[0] += 1
                        self._seed_log_msg(f"  ❌ Lỗi luồng xử lý SP {prod.get('item_id', '')}: {ex}")
                        self._seed_update_line_status(idx, "error")
                    finally:
                        jobq.task_done()
            threads = []
            for _ in range(num_threads):
                t = threading.Thread(target=worker_thread, daemon=True)
                t.start()
                threads.append(t)

            while True:
                if self._seed_stop_flag:
                    if all(not t.is_alive() for t in threads):
                        break
                elif jobq.unfinished_tasks == 0 and not auto_refill:
                    break  # Hết hàng đợi và không bật auto-refill → kết thúc như bình thường
                elif auto_refill and not refill_state["in_progress"] and time.time() >= refill_state["next_allowed"] \
                        and jobq.qsize() < auto_refill_threshold:
                    threading.Thread(target=do_auto_refill, daemon=True).start()
                time.sleep(0.5)

            for t in threads:
                t.join(timeout=5)

            remaining = [p for p in products if p.get("_status") not in ("success", "noretry", "vi phạm cs")]
            if remaining:
                self._seed_log_msg(f"🔄 Đang trả {len(remaining)} SP chưa xử lý về pending...")
                try:
                    self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                except Exception as e:
                    self._seed_log_msg(f"  ⚠ Lỗi release-jobs: {e}")

            self._seed_log_msg(f"\n{'='*50}")
            self._seed_log_msg(f"🏁 HOÀN TẤT {APP_NAME.upper()}: ✅ {done_count[0]}/{total} thành công, ❌ {error_count[0]} lỗi")
            self.after(0, lambda: self._seed_status_lbl.configure(text=f"✅ {done_count[0]}/{total} xong"))
            self._seed_finish()

        threading.Thread(target=work, daemon=True).start()


# Chống mở nhiều bản cùng lúc: các bản chạy song song dùng chung Client ID và temp_render,
# dễ giẫm lên nhau và khi 1 bản thoát sẽ release-jobs giải phóng luôn SP bản kia đang xử lý.
# Mỗi exe có khóa riêng → vẫn chạy được Seedvis và NovaGate cùng lúc.
_SINGLE_INSTANCE_MUTEX_NAME = "NovaGateAppSingleInstanceMutex" if APP_MODE == "nova" else "SeedvisAppSingleInstanceMutex"
ERROR_ALREADY_EXISTS = 183


def _seed_acquire_single_instance_lock():
    try:
        mutex = ctypes.windll.kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return None
        return mutex  # Giữ tham chiếu để mutex không bị giải phóng (tự mất khi tiến trình thoát)
    except Exception:
        return True  # Không phải Windows hoặc lỗi ctypes → bỏ qua khóa, không chặn chạy


if __name__ == "__main__":
    _single_instance_mutex = _seed_acquire_single_instance_lock()
    if _single_instance_mutex is None:
        try:
            _tmp = tk.Tk()
            _tmp.withdraw()
            messagebox.showwarning(f"{APP_NAME} đang chạy",
                                   f"Đã có một cửa sổ {APP_NAME} đang mở.\nVui lòng dùng cửa sổ đó thay vì mở thêm bản mới.")
            _tmp.destroy()
        except Exception:
            pass
        sys.exit(0)

    app = SeedvisApp()
    app.mainloop()
