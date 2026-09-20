#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Thin Aptm — Seedvis Veo 3.1 Standalone Application
Tạo video Veo 3.1 Image-to-Video độc lập qua Seedvis Developer API.
"""

import os
import sys
import time
import json
import uuid
import queue
import shutil
import random
import base64
import threading
import collections
import subprocess
import urllib.request
import urllib.error

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox

# --- Load helper modules from current directory ---
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

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
SETTINGS_FILE = os.path.join(HERE, "seedvis_settings.json")
LOG_FILE = os.path.join(HERE, "log.txt")


class SeedvisApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Thin Aptm — Seedvis Veo 3.1 Video Generator")
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
        self._seed_stop_flag = False
        self._seed_video_done_count = 0
        self._seed_completion_times = collections.deque()
        self._seed_run_started_at = time.time()
        # Xoa trang file log.txt khi khoi dong
        with open("log.txt", "w", encoding="utf-8") as f:
            f.write(f"--- PHIEN LAM VIEC MOI SEEDVIS ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")

        self._seed_log_buffer = []
        self._seed_log_flush_scheduled = False

        self._ui_queue = queue.Queue()
        self._poll_ui_queue()
        self._start_temp_cleaner()

        import multiprocessing
        self._ffmpeg_sem = threading.Semaphore(max(2, (multiprocessing.cpu_count() or 4) // 2))

        self._build_ui()
        self._seed_on_ghep_anh_toggle()

        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _load_settings(self):
        default_settings = {
            "sv_server_url": "http://100.79.170.67:3000",
            "sv_api_key": "",
            "sv_client_id": "client_seedvis",
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
                "seedvis_api_key": self._seed_apikey_input.get().strip(),
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
                "gemini_keys": self.gemini_keys,
                "groq_api_key": "\n".join(self.groq_keys) if isinstance(self.groq_keys, list) else self.groq_keys,
            })
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Lỗi lưu settings: {e}")


    def _start_temp_cleaner(self):
        def _cleaner_loop():
            import time
            import shutil
            while True:
                interval_mins = int(self.settings.get("seedvis_clean_interval", 60))
                time.sleep(interval_mins * 60)
                if getattr(self, '_seed_stop_flag', False):
                    break
                
                try:
                    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_render")
                    if os.path.exists(temp_dir):
                        count = 0
                        for file in os.listdir(temp_dir):
                            # Skip recent files (less than 10 mins old) to avoid deleting active processing files!
                            filepath = os.path.join(temp_dir, file)
                            if time.time() - os.path.getmtime(filepath) > 600:
                                try:
                                    os.remove(filepath)
                                    count += 1
                                except Exception:
                                    pass
                        if count > 0:
                            self._seed_log_msg(f"  dYZz [Auto-Clean] dA? d?n d?p {count} file rAc trong temp_render.")
                except Exception:
                    pass
                    
        import threading
        threading.Thread(target=_cleaner_loop, daemon=True).start()

    def _on_closing(self):
        self.withdraw()
        try:
            import pystray
            from PIL import Image, ImageDraw
            
            def create_image():
                image = Image.new('RGB', (64, 64), color=(26, 115, 232))
                draw = ImageDraw.Draw(image)
                draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255))
                return image

            def on_show(icon, item):
                icon.stop()
                self.after(0, self.deiconify)
                
            def on_quit(icon, item):
                icon.stop()
                self._seed_stop_flag = True
                self._save_settings()
                try:
                    c_id = self._seed_client_entry.get().strip()
                    if c_id:
                        self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": c_id})
                except Exception:
                    pass
                # Dọn dẹp temp_render khi tắt phần mềm theo Rule #8
                try:
                    import shutil
                    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_render")
                    if os.path.exists(temp_dir):
                        for file in os.listdir(temp_dir):
                            try:
                                os.remove(os.path.join(temp_dir, file))
                            except Exception:
                                pass
                except Exception:
                    pass
                self.after(0, self.destroy)
                
            menu = pystray.Menu(
                pystray.MenuItem('Hiển thị cửa sổ', on_show, default=True),
                pystray.MenuItem('Thoát hoàn toàn', on_quit)
            )
            
            icon = pystray.Icon("Seedvis", create_image(), "Thin Aptm - Seedvis", menu)
            import threading
            threading.Thread(target=icon.run, daemon=True).start()
        except ImportError:
            self._seed_stop_flag = True
            self._save_settings()
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
        ctk.CTkLabel(hdr, text="🌱 Seedvis — Veo 3.1 Image-to-Video (Độc lập)", font=("", 18, "bold"), text_color=T1).pack(side="left")
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
        self._seed_client_entry.insert(0, self.settings.get("sv_client_id", "client_seedvis"))

        self._seed_cached_url = self._seed_url.get().strip()
        self._seed_cached_apikey = self._seed_apikey.get().strip()

        # --- Cấu hình Seedvis API ---
        api_card = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10)
        api_card.pack(fill="x", padx=12, pady=4)
        api_row = ctk.CTkFrame(api_card, fg_color="transparent")
        api_row.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(api_row, text="🔑 Seedvis API Key:", font=("", 12)).pack(side="left")
        self._seed_apikey_input = ctk.CTkEntry(api_row, width=380, font=("", 11), show="*")
        self._seed_apikey_input.pack(side="left", padx=4)
        default_seed_key = self.settings.get("seedvis_api_key", "")
        self._seed_apikey_input.insert(0, default_seed_key)

        ctk.CTkLabel(api_row, text="Model:", font=("", 12)).pack(side="left", padx=(12, 0))
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

        ctk.CTkLabel(api_row, text="Luồng:", font=("", 12)).pack(side="left", padx=(12, 0))
        self._seed_threads = ctk.CTkEntry(api_row, width=50, font=("", 11))
        self._seed_threads.pack(side="left", padx=4)
        self._seed_threads.insert(0, self.settings.get("seedvis_threads", "12"))

        # --- Cài đặt Video ---
        cfg = ctk.CTkFrame(f, fg_color=CARD, corner_radius=10)
        cfg.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(cfg, text="⚙ Cài đặt Video", font=("", 12, "bold"), text_color=T1).pack(anchor="w", padx=12, pady=(6, 2))
        row1 = ctk.CTkFrame(cfg, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row1, text="Tỉ lệ:", font=("", 12)).pack(side="left")
        self._seed_aspect = ctk.CTkOptionMenu(row1, values=["Dọc 9:16 (TikTok)", "Ngang 16:9"], width=160)
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

        self._seed_btn_claim = ctk.CTkButton(claim_row, text="📥 Nhận SP", width=100, fg_color=AC, command=self._seed_claim_jobs)
        self._seed_btn_claim.pack(side="left", padx=(12, 4))
        self._seed_btn_release = ctk.CTkButton(claim_row, text="🔄 Giải phóng SP kẹt", width=150,
                                              fg_color="#E53935", hover_color="#C62828", command=self._seed_release_jobs)
        self._seed_btn_release.pack(side="left", padx=4)
        self._seed_btn_clear_violation = ctk.CTkButton(claim_row, text="🗑 Xóa Vi Phạm CS", width=150,
                                                      fg_color="#E57373", hover_color="#C62828", command=self._seed_clear_violations)
        self._seed_btn_clear_violation.pack(side="left", padx=4)

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

    def _seed_download_image(self, image_url, save_path):
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
                return False
            return True
        except Exception as e:
            if os.path.exists(save_path):
                try: os.remove(save_path)
                except: pass
            self._seed_log_msg(f"⚠ Tải ảnh lỗi: {e}")
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

        self._seed_btn_claim.configure(state="disabled", text="⏳...")
        self._seed_log_msg(f"📥 Đang xin {limit} SP từ Server (market={market})...")

        def _do():
            try:
                result = self._seed_api_call("POST", "/api/thinaptm/claim-jobs", {
                    "market": market, "clientId": client_id, "limit": limit, "sortBy": sort_by,
                    "min_item_id": min_item_id, "min_commission": min_commission,
                    "minItemId": min_item_id, "minCommission": min_commission
                })
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
                    if (min_item_id > 0 and iid < min_item_id) or comm < min_commission:
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
                self._seed_log_msg(f"✅ Đã nhận {count} SP! Bấm ▶ để tạo video qua Seedvis.")
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
                released1 = r1.get("released", 0) if isinstance(r1, dict) else 0
                try:
                    r2 = self._seed_api_call("POST", "/api/thinaptm/auto-release-stuck", {"hours": 2})
                    released2 = r2.get("released", 0) if isinstance(r2, dict) else 0
                except Exception:
                    released2 = 0
                total_released = released1 + released2
                self._seed_log_msg(f"✅ Đã giải phóng {total_released} SP kẹt (Client: {released1}, Kẹt >2h: {released2})")
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
        self._seed_stop_flag = True
        self._seed_log_msg("⏹ Đang dừng tạo video Seedvis...")

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
        self.after(0, lambda: self._seed_btn_stop.configure(state="disabled"))
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
        api_key = self._seed_apikey_input.get().strip()
        if not api_key:
            messagebox.showerror("Thiếu API Key", "Vui lòng nhập Seedvis API Key.")
            return

        self._seed_cached_url = self._seed_url.get().strip()
        if self._seed_cached_url and not (self._seed_cached_url.startswith("http://") or self._seed_cached_url.startswith("https://")):
            self._seed_cached_url = "http://" + self._seed_cached_url
        self._seed_cached_apikey = self._seed_apikey.get().strip()

        self._seed_start_work(api_key)

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
            cmd.extend(["-threads", "2"])
            self._ffmpeg_sem.acquire()
            try:
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo, timeout=120, creationflags=0x08000000)
                return True, ""
            except subprocess.TimeoutExpired:
                return False, "FFmpeg timed out after 120s"
            except subprocess.CalledProcessError as e:
                err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                return False, err_msg
            finally:
                self._ffmpeg_sem.release()
        except Exception as ex:
            if hasattr(self, '_ffmpeg_sem'):
                try: self._ffmpeg_sem.release()
                except: pass
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

    def _seed_start_work(self, api_key):
        """Worker chính xử lý tạo video qua Seedvis API (Veo 3.1)."""
        out_dir = self._seed_outdir.get().strip()
        products = list(self._seed_claimed_products)
        scene_choice = self._seed_scene.get()
        naming_mode = self._seed_naming.get()
        client_id = self._seed_client_entry.get().strip()
        ai_mode = self._seed_ai_prompt.get()
        review_style = self._seed_review_style.get()
        del_img = self._seed_del_img.get()
        ghep_anh = self._seed_ghep_anh.get()

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

        lang_val = self._seed_lang.get()
        lang_code = "vi" if "Việt" in lang_val else ("id" if "Indonesia" in lang_val else ("my" if "Malaysia" in lang_val else ("ph" if "Philippines" in lang_val else "en")))

        self._seed_running = True
        self._seed_stop_flag = False
        self._seed_btn_start.configure(state="disabled")
        self._seed_btn_stop.configure(state="normal")
        self._seed_btn_claim.configure(state="disabled")
        self._seed_status_lbl.configure(text="⏳ Đang tạo video (Seedvis)...")

        def work():
            total = len(products)
            temp_dir = os.path.join(HERE, "temp_render")
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(out_dir, exist_ok=True)

            seg_info = f"{n_segments_needed} segment × {clip_duration}" if n_segments_needed > 1 else f"{clip_duration}"
            self._seed_log_msg(f"🌱 Seedvis — Model: {model_choice} | Video: {duration_sec}s ({seg_info}) | Tỉ lệ: {seed_aspect}")
            self._seed_log_msg(f"🚀 Số luồng xử lý: {num_threads} luồng")
            self._seed_log_msg(f"📋 {total} SP — Bắt đầu xử lý...")

            done_count = [0]
            self._seed_video_done_count = 0
            self.after(0, lambda: self._seed_video_done_lbl.configure(text=""))
            self._seed_completion_times = collections.deque()
            self._seed_run_started_at = time.time()
        # Xoa trang file log.txt khi khoi dong
        with open("log.txt", "w", encoding="utf-8") as f:
            f.write(f"--- PHIEN LAM VIEC MOI SEEDVIS ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")

            self.after(0, lambda: self._seed_speed_lbl.configure(text="⚡ -- video/phút"))
            self.after(5000, self._seed_update_speed_label)
            error_count = [0]
            jobq = queue.Queue()
            for idx, prod in enumerate(products):
                prod["_idx"] = idx
                prod["_cycles"] = 0
                jobq.put(prod)

            def submit_seedvis_job(prompt, b64_img, filename, image_url=None):
                endpoint = "https://seedvis.com/api/v1/developer/generations"
                idem_key = str(uuid.uuid4())
                headers = {
                    "Authorization": f"Bearer {api_key}",
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

                for attempt in range(5):
                    if self._seed_stop_flag: return "stopped", None
                    try:
                        req_data = json.dumps(payload).encode("utf-8")
                        req = urllib.request.Request(endpoint, data=req_data, headers=headers, method="POST")
                        with urllib.request.urlopen(req, timeout=60) as resp:
                            res_json = json.loads(resp.read().decode("utf-8"))
                            return "ok", res_json
                    except urllib.error.HTTPError as he:
                        err_body = ""
                        try: err_body = he.read().decode("utf-8")
                        except Exception: pass
                        err_str = err_body.lower()
                        if he.code == 422 or any(k in err_str for k in ["policy", "violation", "filter", "safety", "nsfw"]):
                            self._seed_log_msg(f"  ⚠️ Seedvis báo vi phạm: {err_body[:120]}")
                            return "violation", err_body
                        if he.code == 401 or any(k in err_str for k in ["unauthorized", "invalid api key"]):
                            self._seed_log_msg(f"  ❌ Seedvis API Key không hợp lệ hoặc hết hạn!")
                            return "invalid_key", err_body
                        if he.code == 402:
                            self._seed_log_msg(f"  💳 Seedvis báo hết credit (402): {err_body[:150]}")
                            return "no_credit", err_body
                        if he.code == 429 or "rate limit" in err_str:
                            wait = min(20 * (attempt + 1), 60)
                            self._seed_log_msg(f"  ⏳ Seedvis Rate limit (429) → chờ {wait}s...")
                            time.sleep(wait)
                            continue
                        if he.code in (500, 502, 504):
                            if attempt < 4:
                                self._seed_log_msg(f"  ⚠️ Seedvis lỗi server {he.code} (thử {attempt+1}/5): {err_body[:150]}")
                                time.sleep(4)
                                continue
                            return "error", f"HTTP {he.code}: {err_body[:120]}"
                        self._seed_log_msg(f"  ❌ Seedvis lỗi HTTP {he.code} (không retry): {err_body[:150]}")
                        return "error", f"HTTP {he.code}: {err_body[:120]}"
                    except Exception as ex:
                        if attempt < 4:
                            self._seed_log_msg(f"  ⚠️ Seedvis submit lỗi mạng (thử {attempt+1}/5): {ex}")
                            time.sleep(4)
                            continue
                        return "error", str(ex)
                return "error", "Max retries"

            def poll_seedvis_job(job_id):
                poll_url = f"https://seedvis.com/api/v1/developer/generations/{job_id}?wait=60"
                headers = {"Authorization": f"Bearer {api_key}", "User-Agent": SEEDVIS_UA}
                start_ts = time.time()
                while time.time() - start_ts < 600:
                    if self._seed_stop_flag: return "stopped", None
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
                            msg_lower = msg.lower()
                            if any(k in msg_lower for k in ["policy", "violation", "filter", "safety"]):
                                return "violation", msg
                            return "failed", msg

                    time.sleep(6)
                return "timeout", "Quá 10 phút chờ tạo video"

            def process_one(prod):
                idx = prod["_idx"]
                if self._seed_stop_flag: return "retry_soft"
                item_id = prod.get("item_id", "")
                product_name = prod.get("name", f"Product_{item_id}")
                image_url = prod.get("image_url", "")

                self._seed_update_line_status(idx, "running")
                self._seed_log_msg(f"\n{'='*50}")
                self._seed_log_msg(f"📦 [{idx+1}/{total}] {product_name[:50]}")

                # Tải ảnh
                img_path = os.path.join(temp_dir, f"{item_id}_{idx}.jpg")
                if not os.path.isfile(img_path):
                    if not image_url:
                        self._seed_log_msg(f"  ⚠ Không có image_url")
                        prod["_status"] = "noretry"
                        try: self._seed_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except Exception: pass
                        self._seed_update_line_status(idx, "error")
                        return ("fail", "Không có ảnh")
                    self._seed_log_msg(f"  📥 Tải ảnh: {image_url[:60]}...")
                    if not self._seed_download_image(image_url, img_path):
                        prod["_status"] = "noretry"
                        try: self._seed_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "failed", "tool": "thinaptm"})
                        except Exception: pass
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
                    self._seed_log_msg(f"  📺 TVC {clip_duration}: 1 prompt ({tvc_label} - SP: {short_name[:40]}...)")
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
                                self._seed_log_msg(f"  📺 TVC {clip_duration}: 1 prompt ({tvc_label} - SP: {short_name[:40]}...)")
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

                    self._seed_log_msg(f"  🎬 Gửi tạo Segment {seg_idx+1}/{n_segments} ({clip_duration})...")
                    sub_res, sub_data = submit_seedvis_job(api_prompt, b64_img, f"{item_id}.jpg", image_url=image_url)
                    if sub_res == "stopped": return "retry_soft"
                    if sub_res == "invalid_key":
                        prod["_status"] = "noretry"
                        self._seed_update_line_status(idx, "error")
                        return ("fail", "Sai Seedvis API Key")
                    if sub_res == "no_credit":
                        prod["_status"] = "noretry"
                        self._seed_update_line_status(idx, "error")
                        self._seed_stop_flag = True
                        self._seed_log_msg(f"  🛑 Hết credit Seedvis → dừng toàn bộ hàng đợi")
                        return ("fail", "Hết credit Seedvis")
                    if sub_res == "violation":
                        prod["_status"] = "vi phạm cs"
                        try: self._seed_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "vi phạm cs", "tool": "thinaptm"})
                        except Exception: pass
                        self._seed_update_line_status(idx, "violation")
                        return ("fail", "Vi phạm chính sách Seedvis")
                    if sub_res != "ok":
                        self._seed_log_msg(f"  ❌ Submit Segment {seg_idx+1} thất bại: {sub_data}")
                        return "retry_soft"

                    gen_data = sub_data.get("data", {}) if isinstance(sub_data, dict) else {}
                    job_id = gen_data.get("id", "")
                    self._seed_log_msg(f"  ⏳ Job {job_id[:16]}... Đang render...")

                    poll_res, vid_url_or_err = poll_seedvis_job(job_id)
                    if poll_res == "stopped": return "retry_soft"
                    if poll_res == "violation":
                        prod["_status"] = "vi phạm cs"
                        try: self._seed_api_call("POST", "/api/thinaptm/complete-job", {"itemId": item_id, "status": "vi phạm cs", "tool": "thinaptm"})
                        except Exception: pass
                        self._seed_update_line_status(idx, "violation")
                        return ("fail", f"Vi phạm CS: {vid_url_or_err}")
                    if poll_res != "succeeded":
                        self._seed_log_msg(f"  ❌ Segment {seg_idx+1} thất bại: {vid_url_or_err}")
                        return "retry_soft"

                    video_url = vid_url_or_err
                    self._seed_log_msg(f"  📥 Tải video segment {seg_idx+1}...")
                    try:
                        _dl_req = urllib.request.Request(video_url, headers={"User-Agent": SEEDVIS_UA})
                        with urllib.request.urlopen(_dl_req, timeout=120) as _dl_resp, open(clip_path, "wb") as _dl_f:
                            while True:
                                chunk = _dl_resp.read(65536)
                                if not chunk: break
                                _dl_f.write(chunk)
                    except Exception as de:
                        self._seed_log_msg(f"  ❌ Tải video lỗi: {de}")
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

                try:
                    self._seed_api_call("POST", "/api/thinaptm/complete-job", {
                        "itemId": item_id, "status": "completed", "tool": "thinaptm",
                        "videoFile": os.path.basename(out_path)
                    })
                except Exception:
                    pass

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
                        prod = jobq.get_nowait()
                    except queue.Empty:
                        break
                    idx = prod["_idx"]
                    res = process_one(prod)
                    if isinstance(res, tuple) and res[0] == "ok":
                        done_count[0] += 1
                        self._seed_video_done_count = done_count[0]
                        self._seed_completion_times.append(time.time())
                        pct = done_count[0] / total
                        self.after(0, lambda p=pct: self._seed_progress.set(p))
                        self.after(0, lambda: self._seed_video_done_lbl.configure(text=f"✅ {done_count[0]}/{total} xong"))
                    elif res == "retry_soft":
                        prod["_cycles"] = prod.get("_cycles", 0) + 1
                        if prod["_cycles"] < 3 and not self._seed_stop_flag:
                            self._seed_log_msg(f"  🔄 Thử lại SP {prod.get('item_id')} (chu kỳ {prod['_cycles']}/3)...")
                            jobq.put(prod)
                        else:
                            error_count[0] += 1
                            self._seed_update_line_status(idx, "error")
                    else:
                        error_count[0] += 1
                    jobq.task_done()
            threads = []
            for _ in range(num_threads):
                t = threading.Thread(target=worker_thread, daemon=True)
                t.start()
                threads.append(t)

            while jobq.unfinished_tasks > 0:
                if self._seed_stop_flag:
                    if all(not t.is_alive() for t in threads):
                        break
                time.sleep(0.5)

            for t in threads:
                t.join(timeout=5)

            remaining = [p for p in products if p.get("_status") not in ("success", "noretry", "vi phạm cs")]
            if remaining and self._seed_stop_flag:
                self._seed_log_msg(f"🔄 Đang trả {len(remaining)} SP chưa xử lý về pending...")
                try:
                    self._seed_api_call("POST", "/api/thinaptm/release-jobs", {"clientId": client_id})
                except Exception as e:
                    self._seed_log_msg(f"  ⚠ Lỗi release-jobs: {e}")

            self._seed_log_msg(f"\n{'='*50}")
            self._seed_log_msg(f"🏁 HOÀN TẤT SEEDVIS: ✅ {done_count[0]}/{total} thành công, ❌ {error_count[0]} lỗi")
            self.after(0, lambda: self._seed_status_lbl.configure(text=f"✅ {done_count[0]}/{total} xong"))
            self._seed_finish()

        threading.Thread(target=work, daemon=True).start()


if __name__ == "__main__":
    app = SeedvisApp()
    app.mainloop()
