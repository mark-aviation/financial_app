# ui/login_screen.py
# 💎 Dev: No longer subclasses CTkFrame — plain object that builds
#   widgets directly into the parent. Avoids the _register() MRO crash.

import threading
import logging

import customtkinter as ctk
from tkinter import messagebox

from config import APP_NAME, COLORS
from db import is_connected, load_db_config, save_db_config, init_pool
from services import authenticate, register

logger = logging.getLogger(__name__)


class LoginScreen:
    def __init__(self, parent, on_login_success):
        self.parent = parent
        self.on_login_success = on_login_success
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._build_ui()
        self._check_server_async()

    def destroy(self):
        self.frame.destroy()

    def _build_ui(self):
        box = ctk.CTkFrame(self.frame, width=400, corner_radius=15)
        box.place(relx=0.5, rely=0.5, anchor="center")

        ctk.CTkLabel(box, text=APP_NAME, font=("Roboto", 32, "bold"),
                     text_color=COLORS["primary"]).pack(pady=(30, 10))

        self.ent_username = ctk.CTkEntry(box, width=300, height=40, placeholder_text="Username")
        self.ent_username.pack(pady=10)

        self.ent_password = ctk.CTkEntry(box, width=300, height=40,
                                         placeholder_text="Password", show="*")
        self.ent_password.pack(pady=10)
        self.ent_password.bind("<Return>", lambda e: self._login())

        self.btn_login = ctk.CTkButton(box, text="LOGIN", command=self._login,
                                       width=300, height=45, font=("Roboto", 16, "bold"))
        self.btn_login.pack(pady=(20, 10))

        self.btn_register = ctk.CTkButton(box, text="CREATE NEW ACCOUNT",
                                          command=self._register,
                                          fg_color="transparent", border_width=2,
                                          text_color="white", width=300, height=45)
        self.btn_register.pack(pady=(0, 10))

        self.lbl_loading = ctk.CTkLabel(box, text="", font=("Roboto", 12),
                                        text_color=COLORS["warning"])
        self.lbl_loading.pack(pady=(0, 5))

        self.lbl_status = ctk.CTkLabel(box, text="🟡 Checking server...",
                                       font=("Roboto", 12), text_color=COLORS["warning"])
        self.lbl_status.pack(pady=(0, 5))

        btn_row = ctk.CTkFrame(box, fg_color="transparent")
        btn_row.pack(pady=(0, 20))

        self.btn_refresh = ctk.CTkButton(btn_row, text="↻ Refresh",
                                         command=self._refresh_connection,
                                         width=100, height=28, fg_color=COLORS["muted"])
        self.btn_refresh.pack(side="left", padx=5)

        ctk.CTkButton(btn_row, text="⚙️ DB Settings",
                      command=self._open_db_settings,
                      width=100, height=28, fg_color="#e67e22").pack(side="left", padx=5)

    def _login(self):
        username = self.ent_username.get().strip()
        password = self.ent_password.get()
        if not username or not password:
            messagebox.showerror("Error", "Please enter username and password.")
            return
        self._set_busy(True, "🔄 Logging in...")
        threading.Thread(target=self._do_login, args=(username, password), daemon=True).start()

    def _do_login(self, username, password):
        try:
            user = authenticate(username, password)
            if user:
                self.frame.after(0, lambda: self._finish_login(user))
            else:
                self.frame.after(0, lambda: self._finish_error("Invalid username or password."))
        except ConnectionError as e:
            self.frame.after(0, lambda: self._finish_error(str(e)))

    def _finish_login(self, user):
        self._set_busy(False)
        self.on_login_success(user["id"], user["username"])

    def _finish_error(self, message):
        self._set_busy(False)
        messagebox.showerror("Login Failed", message)

    def _register(self):
        username = self.ent_username.get().strip()
        password = self.ent_password.get()
        if not username or not password:
            messagebox.showerror("Error", "Please enter a username and password.")
            return
        try:
            success = register(username, password)
            if success:
                messagebox.showinfo("Success", f"Account '{username}' created! You can now log in.")
            else:
                messagebox.showerror("Error", "Username already exists.")
        except (ValueError, ConnectionError) as e:
            messagebox.showerror("Error", str(e))

    def _refresh_connection(self):
        self.lbl_status.configure(text="🟡 Checking...", text_color=COLORS["warning"])
        self.btn_refresh.configure(state="disabled")
        self._check_server_async()

    def _check_server_async(self):
        threading.Thread(target=self._check_server, daemon=True).start()

    def _check_server(self):
        connected = is_connected()
        def update():
            if not self.frame.winfo_exists():
                return
            if connected:
                self.lbl_status.configure(text="🟢 Connected to Server",
                                          text_color=COLORS["success"])
            else:
                self.lbl_status.configure(text="🔴 Offline (Check Config/Tailscale)",
                                          text_color=COLORS["danger"])
            if self.btn_refresh.winfo_exists():
                self.btn_refresh.configure(state="normal")
        self.frame.after(0, update)

    def _open_db_settings(self):
        win = ctk.CTkToplevel(self.frame)
        win.title("Database Configuration")
        win.geometry("400x450")
        win.grab_set()

        config = load_db_config()
        ctk.CTkLabel(win, text="Database Settings", font=("Roboto", 18, "bold")).pack(pady=20)

        fields = {}
        for key, placeholder in [("host", "Host IP"), ("user", "DB Username"),
                                  ("database", "Database Name")]:
            e = ctk.CTkEntry(win, width=300, placeholder_text=placeholder)
            e.insert(0, config.get(key, ""))
            e.pack(pady=8)
            fields[key] = e

        e_pass = ctk.CTkEntry(win, width=300, placeholder_text="DB Password", show="*")
        e_pass.insert(0, config.get("password", ""))
        e_pass.pack(pady=8)
        fields["password"] = e_pass

        def save_and_close():
            new_cfg = {k: fields[k].get() for k in fields}
            save_db_config(new_cfg)
            try:
                init_pool(new_cfg)
                messagebox.showinfo("Saved", "Database settings updated and reconnected.")
            except Exception as e:
                messagebox.showwarning("Saved", f"Settings saved, but connection failed: {e}")
            win.destroy()
            self._refresh_connection()

        ctk.CTkButton(win, text="SAVE & RECONNECT", command=save_and_close).pack(pady=20)

    def _set_busy(self, busy: bool, message: str = ""):
        state = "disabled" if busy else "normal"
        self.btn_login.configure(state=state)
        self.btn_register.configure(state=state)
        self.lbl_loading.configure(text=message)
