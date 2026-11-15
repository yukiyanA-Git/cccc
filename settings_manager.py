"""
settings_manager.py - テーマ設定・保護リスト（ホワイトリスト）・操作履歴の永続管理モジュール
"""
import os
import json
import uuid
from datetime import datetime
from typing import List, Dict, Optional

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_config.json")

# テーマ定義（パステル系の淡い色合い＋くっきり見やすい黒文字を基本とする）
THEMES = {
    "pastel_blue": {
        "name": "💧 パステルブルー（標準・爽やかな淡い青）",
        "window_bg": "#eef6ff",
        "panel_bg": "#ffffff",
        "card_bg": "#f8fbff",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "tab_bg": "#dbeafe",
        "tab_selected": "#ffffff",
        "border": "#bfdbfe",
        "text_main": "#111827",
        "text_sub": "#374151",
        "table_alt": "#f0f7ff",
        "selection_bg": "#dbeafe"
    },
    "pastel_yellow": {
        "name": "🌼 パステルイエロー（温かみのある淡い黄色）",
        "window_bg": "#fefce8",
        "panel_bg": "#ffffff",
        "card_bg": "#fffef5",
        "accent": "#d97706",
        "accent_hover": "#b45309",
        "tab_bg": "#fef08a",
        "tab_selected": "#ffffff",
        "border": "#fde047",
        "text_main": "#111827",
        "text_sub": "#374151",
        "table_alt": "#fefce8",
        "selection_bg": "#fef9c3"
    },
    "pastel_pink": {
        "name": "🌸 パステルピンク（優しく明るい淡いピンク）",
        "window_bg": "#fdf2f8",
        "panel_bg": "#ffffff",
        "card_bg": "#fffafd",
        "accent": "#db2777",
        "accent_hover": "#be185d",
        "tab_bg": "#fbcfe8",
        "tab_selected": "#ffffff",
        "border": "#f9a8d4",
        "text_main": "#111827",
        "text_sub": "#374151",
        "table_alt": "#fdf2f8",
        "selection_bg": "#fce7f3"
    },
    "pastel_mint": {
        "name": "🌿 パステルミント（目に優しい淡いグリーン）",
        "window_bg": "#f0fdf4",
        "panel_bg": "#ffffff",
        "card_bg": "#f7fee7",
        "accent": "#059669",
        "accent_hover": "#047857",
        "tab_bg": "#bbf7d0",
        "tab_selected": "#ffffff",
        "border": "#86efac",
        "text_main": "#111827",
        "text_sub": "#374151",
        "table_alt": "#f0fdf4",
        "selection_bg": "#dcfce7"
    },
    "dark": {
        "name": "🌙 ダークモード（落ち着いた暗色テーマ）",
        "window_bg": "#1e293b",
        "panel_bg": "#0f172a",
        "card_bg": "#1e293b",
        "accent": "#3b82f6",
        "accent_hover": "#2563eb",
        "tab_bg": "#334155",
        "tab_selected": "#0f172a",
        "border": "#475569",
        "text_main": "#f8fafc",
        "text_sub": "#cbd5e1",
        "table_alt": "#1e293b",
        "selection_bg": "#334155"
    }
}

class SettingsManager:
    def __init__(self):
        self.theme: str = "pastel_blue"
        self.whitelist: List[str] = []
        self.history: List[Dict] = []
        self.load()

    def load(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.theme = data.get("theme", "pastel_blue")
                    if self.theme not in THEMES:
                        self.theme = "pastel_blue"
                    self.whitelist = [os.path.normpath(p) for p in data.get("whitelist", [])]
                    self.history = data.get("history", [])
            except Exception:
                pass
        else:
            self.save()

    def save(self):
        data = {
            "theme": self.theme,
            "whitelist": self.whitelist,
            "history": self.history[-200:]  # 最新200件まで保持
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # --- ホワイトリスト（保護リスト）操作 ---
    def is_protected(self, path: str) -> bool:
        norm = os.path.normpath(os.path.abspath(path)).lower()
        for w in self.whitelist:
            w_lower = os.path.normpath(os.path.abspath(w)).lower()
            if norm == w_lower or norm.startswith(w_lower + os.sep):
                return True
        return False

    def add_to_whitelist(self, path: str):
        norm = os.path.normpath(os.path.abspath(path))
        if norm not in self.whitelist:
            self.whitelist.append(norm)
            self.save()

    def remove_from_whitelist(self, path: str):
        norm = os.path.normpath(os.path.abspath(path))
        self.whitelist = [w for w in self.whitelist if w.lower() != norm.lower()]
        self.save()

    # --- 履歴タイムライン操作 ---
    def add_history(self, op_type: str, source_path: str, target_path: Optional[str] = None, size_str: str = "") -> str:
        entry_id = str(uuid.uuid4())[:8]
        entry = {
            "id": entry_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "op_type": op_type,  # "MOVE" or "TRASH"
            "item_name": os.path.basename(source_path),
            "source_path": source_path,
            "target_path": target_path,
            "size_str": size_str,
            "restored": False
        }
        self.history.insert(0, entry)  # 新しい順
        self.save()
        return entry_id

    def mark_restored(self, entry_id: str):
        for h in self.history:
            if h.get("id") == entry_id:
                h["restored"] = True
                break
        self.save()

    def clear_history(self):
        self.history = []
        self.save()

    # --- スタイルシート生成 ---
    def get_stylesheet(self) -> str:
        t = THEMES.get(self.theme, THEMES["pastel_blue"])
        return f"""
            QMainWindow, QDialog {{
                background-color: {t['window_bg']};
                color: {t['text_main']};
            }}
            QWidget {{
                color: {t['text_main']};
                font-family: "Yu Gothic UI", "Meiryo UI", sans-serif;
            }}
            QTabWidget::pane {{
                border: 2px solid {t['border']};
                background: {t['panel_bg']};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: {t['tab_bg']};
                border: 1px solid {t['border']};
                padding: 9px 16px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                font-weight: bold;
                font-size: 12px;
                color: {t['text_main']};
            }}
            QTabBar::tab:selected {{
                background: {t['tab_selected']};
                border-bottom: 3px solid {t['accent']};
                color: {t['accent']};
            }}
            QPushButton {{
                background-color: {t['panel_bg']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                color: {t['text_main']};
            }}
            QPushButton:hover {{
                background-color: {t['tab_bg']};
                border-color: {t['accent']};
            }}
            QPushButton:pressed {{
                background-color: {t['selection_bg']};
            }}
            QPushButton#btnPrimary {{
                background-color: {t['accent']};
                color: #ffffff;
                border: none;
            }}
            QPushButton#btnPrimary:hover {{
                background-color: {t['accent_hover']};
            }}
            QPushButton#btnTrash {{
                background-color: #ef4444;
                color: #ffffff;
                border: none;
            }}
            QPushButton#btnTrash:hover {{
                background-color: #dc2626;
            }}
            QPushButton#btnOrganize {{
                background-color: #10b981;
                color: #ffffff;
                border: none;
            }}
            QPushButton#btnOrganize:hover {{
                background-color: #059669;
            }}
            QTableWidget, QListWidget, QTextEdit {{
                background-color: {t['panel_bg']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                gridline-color: {t['border']};
                selection-background-color: {t['selection_bg']};
                selection-color: {t['text_main']};
                color: {t['text_main']};
            }}
            QHeaderView::section {{
                background-color: {t['tab_bg']};
                border: none;
                border-bottom: 2px solid {t['border']};
                padding: 6px;
                font-weight: bold;
                color: {t['text_main']};
            }}
            QComboBox, QLineEdit {{
                background-color: {t['panel_bg']};
                border: 1px solid {t['border']};
                border-radius: 6px;
                padding: 5px 10px;
                color: {t['text_main']};
            }}
            QFrame#themeCard {{
                background-color: {t['card_bg']};
                border: 1px solid {t['border']};
                border-radius: 8px;
                padding: 10px;
            }}
            QStatusBar {{
                background-color: {t['tab_bg']};
                color: {t['text_main']};
                font-weight: bold;
            }}
        """

    def get_current_theme_dict(self) -> Dict[str, str]:
        return THEMES.get(self.theme, THEMES["pastel_blue"])
