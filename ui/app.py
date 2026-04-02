# ui/app.py — Main application window shell

import logging
import customtkinter as ctk
from config import APP_NAME, APP_GEOMETRY

logger = logging.getLogger(__name__)

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry(APP_GEOMETRY)
        self.current_user_id = None
        self.current_username = None
        self._current_screen = None

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True)

        self.show_login()

    def _clear(self):
        if self._current_screen is not None:
            try:
                self._current_screen.destroy()
            except Exception:
                pass
            self._current_screen = None
        for w in self.container.winfo_children():
            w.destroy()

    def show_login(self):
        self._clear()
        self.current_user_id = None
        self.current_username = None
        self.title(APP_NAME)

        from ui.login_screen import LoginScreen
        self._current_screen = LoginScreen(self.container, on_login_success=self._on_login)

    def _on_login(self, user_id: int, username: str):
        self.current_user_id = user_id
        self.current_username = username
        self.title(f"{APP_NAME} — {username}")
        self.show_main()

    def show_main(self):
        self._clear()
        from ui.main_view import MainView
        self._current_screen = MainView(
            self.container,
            user_id=self.current_user_id,
            username=self.current_username,
            on_logout=self.show_login,
        )
