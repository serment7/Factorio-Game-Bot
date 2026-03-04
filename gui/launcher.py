"""Tkinter GUI launcher for Factorio Agent."""

import logging
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox

from PIL import ImageTk, Image

from memory.database import init_db, reset_db
from memory.knowledge import KnowledgeStore
import requests

from body.controller import BodyController
from body.ollama_client import DEFAULT_URL, DEFAULT_MODEL
from brain.bridge import BrainBridge

logger = logging.getLogger(__name__)

DEFAULT_BRAIN_INTERVAL = 30.0


class LauncherGUI:
    """Tkinter-based GUI for controlling the Factorio Agent."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Factorio Agent")
        self.root.geometry("1100x700")
        self.root.resizable(True, True)

        init_db()
        self.knowledge = KnowledgeStore()

        self.brain = BrainBridge(self.knowledge, log_callback=self._log,
                                 goal_interval=DEFAULT_BRAIN_INTERVAL)
        self.body = BodyController(
            knowledge=self.knowledge,
            goal_getter=lambda: self.brain.current_goal,
            log_callback=self._log,
            wiki_requester=self.brain.request_wiki,
        )

        self._build_ui()
        self._update_stats()

    def _build_ui(self):
        # --- Settings ---
        settings_frame = ttk.LabelFrame(self.root, text="Settings", padding=8)
        settings_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        row0 = ttk.Frame(settings_frame)
        row0.pack(fill=tk.X, pady=2)
        ttk.Label(row0, text="Ollama URL:").pack(side=tk.LEFT)
        self.var_ollama_url = tk.StringVar(value=DEFAULT_URL)
        ttk.Entry(row0, textvariable=self.var_ollama_url, width=28).pack(side=tk.LEFT, padx=4)
        ttk.Label(row0, text="Model:").pack(side=tk.LEFT, padx=(12, 0))
        self.var_model = tk.StringVar(value=DEFAULT_MODEL)
        self.cmb_model = ttk.Combobox(row0, textvariable=self.var_model, width=22)
        self.cmb_model.pack(side=tk.LEFT, padx=4)
        self._refresh_ollama_models()

        row1 = ttk.Frame(settings_frame)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="Brain interval (s):").pack(side=tk.LEFT)
        self.var_brain_interval = tk.StringVar(value=str(DEFAULT_BRAIN_INTERVAL))
        ttk.Entry(row1, textvariable=self.var_brain_interval, width=6).pack(side=tk.LEFT, padx=4)

        # --- Status ---
        status_frame = ttk.LabelFrame(self.root, text="Status", padding=8)
        status_frame.pack(fill=tk.X, padx=8, pady=4)

        status_row = ttk.Frame(status_frame)
        status_row.pack(fill=tk.X)
        self.lbl_body_status = ttk.Label(status_row, text="Body: Stopped", foreground="gray")
        self.lbl_body_status.pack(side=tk.LEFT, padx=(0, 16))
        self.lbl_brain_status = ttk.Label(status_row, text="Brain: Stopped", foreground="gray")
        self.lbl_brain_status.pack(side=tk.LEFT, padx=(0, 16))
        self.lbl_cycle = ttk.Label(status_row, text="Cycles: 0")
        self.lbl_cycle.pack(side=tk.LEFT, padx=(0, 16))
        self.lbl_speed = ttk.Label(status_row, text="Speed: -")
        self.lbl_speed.pack(side=tk.LEFT, padx=(0, 16))
        self.lbl_window = ttk.Label(status_row, text="Window: -")
        self.lbl_window.pack(side=tk.LEFT)

        goal_row = ttk.Frame(status_frame)
        goal_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(goal_row, text="Goal:").pack(side=tk.LEFT)
        self.lbl_goal = ttk.Label(goal_row, text="(none)", wraplength=650, justify=tk.LEFT)
        self.lbl_goal.pack(side=tk.LEFT, padx=4)

        # --- Buttons ---
        btn_frame = ttk.Frame(self.root, padding=4)
        btn_frame.pack(fill=tk.X, padx=8)
        self.btn_start = ttk.Button(btn_frame, text="Start", command=self._on_start)
        self.btn_start.pack(side=tk.LEFT, padx=4)
        self.btn_stop = ttk.Button(btn_frame, text="Stop", command=self._on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=4)
        self.btn_reset = ttk.Button(btn_frame, text="Reset Learning DB", command=self._on_reset)
        self.btn_reset.pack(side=tk.LEFT, padx=4)

        # --- Stats ---
        stats_frame = ttk.LabelFrame(self.root, text="Learning Stats", padding=8)
        stats_frame.pack(fill=tk.X, padx=8, pady=4)
        self.stats_labels = {}
        stats_row = ttk.Frame(stats_frame)
        stats_row.pack(fill=tk.X)
        for name in ["known_controls", "observations", "wiki_entries",
                      "known_entities", "known_recipes"]:
            lbl = ttk.Label(stats_row, text=f"{name}: 0")
            lbl.pack(side=tk.LEFT, padx=(0, 16))
            self.stats_labels[name] = lbl

        # --- Bottom: Capture preview + Log side by side ---
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        # Capture preview (left)
        preview_frame = ttk.LabelFrame(bottom_frame, text="Last Capture", padding=4)
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=(0, 4))
        self.preview_label = ttk.Label(preview_frame, text="No capture yet",
                                       anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True)
        self._preview_photo = None  # keep reference to prevent GC

        # Log (right)
        log_frame = ttk.LabelFrame(bottom_frame, text="Log", padding=4)
        log_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=15, state=tk.DISABLED,
            font=("Consolas", 9), wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _log(self, message: str):
        def _append():
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        self.root.after(0, _append)

    def _refresh_ollama_models(self):
        """Fetch model list from Ollama and populate the combobox."""
        try:
            url = self.var_ollama_url.get().rstrip("/")
            resp = requests.get(f"{url}/api/tags", timeout=3)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            self.cmb_model["values"] = models
            if models and self.var_model.get() not in models:
                self.var_model.set(models[0])
        except Exception:
            self.cmb_model["values"] = [DEFAULT_MODEL]

    def _apply_settings(self):
        try:
            self.brain.goal_interval = float(self.var_brain_interval.get())
        except ValueError:
            pass
        self.body.llm.url = self.var_ollama_url.get().rstrip("/")
        self.body.llm.model = self.var_model.get()

    def _on_start(self):
        self._apply_settings()
        self._log("[GUI] Starting agent...")
        try:
            self.brain.start()
        except Exception as e:
            self._log(f"[GUI] Brain start failed: {e}")
            logger.exception("Brain start failed")
        try:
            self.body.start()
        except Exception as e:
            self._log(f"[GUI] Body start failed: {e}")
            logger.exception("Body start failed")
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.btn_reset.config(state=tk.DISABLED)
        self._update_status_loop()

    def _on_stop(self):
        self._log("[GUI] Stopping agent...")
        self.body.stop()
        self.brain.stop()
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_reset.config(state=tk.NORMAL)
        self._update_status_display()

    def _on_reset(self):
        if messagebox.askyesno("Confirm Reset", "Reset all learning data? This cannot be undone."):
            self.knowledge.close()
            reset_db()
            self.knowledge = KnowledgeStore()
            self.body.knowledge = self.knowledge
            self.brain.knowledge = self.knowledge
            self._log("[GUI] Learning database reset.")
            self._update_stats()

    def _update_status_display(self):
        if self.body.is_running:
            self.lbl_body_status.config(text="Body: Running", foreground="green")
        else:
            self.lbl_body_status.config(text="Body: Stopped", foreground="gray")
        if self.brain.is_running:
            self.lbl_brain_status.config(text="Brain: Running", foreground="green")
        else:
            self.lbl_brain_status.config(text="Brain: Stopped", foreground="gray")
        self.lbl_cycle.config(text=f"Cycles: {self.body.cycle_count}")
        if self.body.last_cycle_time > 0:
            self.lbl_speed.config(text=f"Speed: {self.body.last_cycle_time:.1f}s/cycle")
        size = self.body.capture.window_size
        if size:
            self.lbl_window.config(text=f"Window: {size[0]}x{size[1]}")
        self.lbl_goal.config(text=self.brain.current_goal)
        self._update_preview()

    def _update_preview(self):
        """Update the capture preview thumbnail."""
        img = self.body.last_capture
        if img is None:
            return
        try:
            thumb = img.copy()
            thumb.thumbnail((320, 240), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(thumb)
            self.preview_label.config(image=self._preview_photo, text="")
        except Exception:
            pass

    def _update_stats(self):
        try:
            stats = self.knowledge.get_stats()
            for name, lbl in self.stats_labels.items():
                lbl.config(text=f"{name}: {stats.get(name, 0)}")
        except Exception:
            pass

    def _update_status_loop(self):
        if self.body.is_running or self.brain.is_running:
            self._update_status_display()
            self._update_stats()
            self.root.after(1000, self._update_status_loop)

    def run(self):
        self._log("[GUI] Factorio Agent ready. Click Start to begin.")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.mainloop()

    def _on_close(self):
        self.body.stop()
        self.brain.stop()
        self.knowledge.close()
        self.root.destroy()
