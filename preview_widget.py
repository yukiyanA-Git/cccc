"""
preview_widget.py - ドーナツチャート内訳グラフ・安全性解説・プレビュー・保護登録ウィジェット
"""
import os
import subprocess
from typing import Dict, List, Tuple
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit,
    QScrollArea, QFrame, QPushButton, QListWidget, QListWidgetItem
)
from PySide6.QtGui import QPixmap, QFont, QColor, QPainter, QPen, QBrush
from PySide6.QtCore import Qt, QSize, QRectF, Signal
from analyzer import ItemInfo, SafetyLevel, format_size


CATEGORY_COLORS = {
    "Images": ("#3b82f6", "🖼️ 画像"),
    "Videos": ("#ec4899", "🎬 動画"),
    "Audio": ("#8b5cf6", "🎵 音声"),
    "Documents": ("#10b981", "📄 書類"),
    "Archives": ("#f59e0b", "📦 圧縮"),
    "Installers": ("#ef4444", "💿 インストーラー"),
    "Code": ("#06b6d4", "💻 コード"),
    "Temp/Cache": ("#84cc16", "🧹 一時データ"),
    "System": ("#64748b", "⚙️ システム"),
    "Other": ("#94a3b8", "📁 その他")
}


class DonutChartWidget(QWidget):
    """フォルダ内訳をカラフルなドーナツグラフと凡例で描画するウィジェット"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(165)
        self.slices: List[Tuple[str, int, str]] = []  # (label, value, hex_color)
        self.center_text = "0 B"

    def set_data(self, category_sizes: Dict[str, int], category_counts: Dict[str, int], total_formatted: str):
        self.center_text = total_formatted
        total_sz = sum(category_sizes.values())
        self.slices = []

        # 容量が0より大きいカテゴリを抽出（すべて0Bの空ファイル群なら個数ベースにする）
        use_size = total_sz > 0
        source_dict = category_sizes if use_size else category_counts

        sorted_items = sorted(source_dict.items(), key=lambda x: x[1], reverse=True)
        for cat, val in sorted_items:
            if val > 0:
                color_hex, jp_label = CATEGORY_COLORS.get(cat, ("#94a3b8", cat))
                cnt = category_counts.get(cat, 0)
                sz_str = format_size(category_sizes.get(cat, 0))
                display_lbl = f"{jp_label}: {cnt}個 ({sz_str})"
                self.slices.append((display_lbl, val, color_hex))

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        if not self.slices:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignCenter, "（フォルダ内にファイルがありません）")
            return

        # 左側にドーナツチャート、右側に凡例を描画
        chart_size = min(130, h - 16)
        chart_x = 12
        chart_y = (h - chart_size) / 2
        rect = QRectF(chart_x, chart_y, chart_size, chart_size)

        total_val = sum(s[1] for s in self.slices)
        start_angle = 90 * 16  # 12時方向から開始

        for label, val, color_hex in self.slices:
            span_angle = -int(round((val / total_val) * 360 * 16))
            if span_angle == 0 and val > 0:
                span_angle = -16
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(color_hex)))
            painter.drawPie(rect, start_angle, span_angle)
            start_angle += span_angle

        # 中央の白抜き（ドーナツ穴）
        hole_ratio = 0.56
        hole_size = chart_size * hole_ratio
        hole_x = chart_x + (chart_size - hole_size) / 2
        hole_y = chart_y + (chart_size - hole_size) / 2
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawEllipse(QRectF(hole_x, hole_y, hole_size, hole_size))

        # 中央テキスト（合計容量）
        painter.setPen(QColor("#111827"))
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(hole_x, hole_y, hole_size, hole_size), Qt.AlignCenter, self.center_text)

        # 右側に凡例（上位6件）を描画
        legend_x = int(chart_x + chart_size + 18)
        legend_y = 16
        font.setPointSize(9)
        font.setBold(False)
        painter.setFont(font)

        for idx, (label, val, color_hex) in enumerate(self.slices[:6]):
            pct = (val / total_val) * 100
            # カラー四角
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(color_hex)))
            painter.drawRoundedRect(legend_x, legend_y + idx * 23, 12, 12, 3, 3)

            # テキスト
            painter.setPen(QColor("#111827"))
            painter.drawText(
                legend_x + 18,
                legend_y + idx * 23 + 11,
                f"{label}  [{pct:.0f}%]"
            )


class DetailPreviewPanel(QWidget):
    """選択されたファイルまたはフォルダの「正体」と「プレビュー」をわかりやすく表示するパネル"""
    whitelist_toggled = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_item: ItemInfo = None
        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # タイトルヘッダー
        header_layout = QHBoxLayout()
        title_label = QLabel("📋 アイテムの正体と中身プレビュー")
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        title_label.setFont(font)
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self.btn_protect = QPushButton("🛡️ 保護する")
        self.btn_protect.setToolTip("大切なファイルやフォルダを保護リストに登録して誤削除を防ぎます")
        self.btn_protect.clicked.connect(self._on_protect_clicked)
        self.btn_protect.setEnabled(False)
        header_layout.addWidget(self.btn_protect)

        self.btn_open_folder = QPushButton("📂 場所を開く")
        self.btn_open_folder.clicked.connect(self._open_in_explorer)
        self.btn_open_folder.setEnabled(False)
        header_layout.addWidget(self.btn_open_folder)
        main_layout.addLayout(header_layout)

        # スクロールエリア
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content_widget = QWidget()
        self.content_layout = QVBoxLayout(content_widget)
        self.content_layout.setSpacing(12)

        # 1. 安全性診断カード
        self.card_safety = QFrame()
        self.card_safety.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border-radius: 8px;
                border: 2px solid #cbd5e1;
                padding: 10px;
            }
        """)
        safety_layout = QVBoxLayout(self.card_safety)
        safety_layout.setSpacing(6)

        self.lbl_safety_badge = QLabel("⚪ 左の一覧からアイテムを選択してください")
        font_badge = QFont()
        font_badge.setPointSize(11)
        font_badge.setBold(True)
        self.lbl_safety_badge.setFont(font_badge)
        safety_layout.addWidget(self.lbl_safety_badge)

        self.lbl_safety_desc = QLabel("選択したファイルやフォルダの正体と、消しても大丈夫かの診断結果がここに表示されます。\nエクスプローラーからフォルダを直接ドラッグ＆ドロップして診断することもできます。")
        self.lbl_safety_desc.setWordWrap(True)
        self.lbl_safety_desc.setStyleSheet("color: #111827; font-weight: bold;")
        safety_layout.addWidget(self.lbl_safety_desc)

        self.lbl_safety_detail = QLabel("")
        self.lbl_safety_detail.setWordWrap(True)
        self.lbl_safety_detail.setStyleSheet("color: #374151; font-size: 12px;")
        safety_layout.addWidget(self.lbl_safety_detail)

        self.content_layout.addWidget(self.card_safety)

        # 2. 基本情報カード
        self.card_info = QFrame()
        self.card_info.setObjectName("themeCard")
        info_layout = QVBoxLayout(self.card_info)
        info_layout.setSpacing(5)

        self.lbl_name = QLabel("名前: -")
        self.lbl_name.setFont(font_badge)
        self.lbl_name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(self.lbl_name)

        self.lbl_size = QLabel("容量: -")
        info_layout.addWidget(self.lbl_size)

        self.lbl_mtime = QLabel("最終更新: -")
        info_layout.addWidget(self.lbl_mtime)

        self.lbl_path = QLabel("場所: -")
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setStyleSheet("color: #4b5563; font-size: 11px;")
        self.lbl_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(self.lbl_path)

        self.content_layout.addWidget(self.card_info)

        # 3. フォルダ内訳＆ドーナツチャート（フォルダの場合に表示）
        self.card_folder_summary = QFrame()
        self.card_folder_summary.setObjectName("themeCard")
        self.folder_layout = QVBoxLayout(self.card_folder_summary)
        self.folder_title = QLabel("📊 フォルダの中身グラフ（内訳）")
        self.folder_title.setFont(font_badge)
        self.folder_layout.addWidget(self.folder_title)

        self.lbl_folder_stats = QLabel("ファイル数: - | サブフォルダ数: -")
        self.folder_layout.addWidget(self.lbl_folder_stats)

        # ドーナツチャートウィジェット
        self.donut_chart = DonutChartWidget()
        self.folder_layout.addWidget(self.donut_chart)

        self.sample_list_label = QLabel("フォルダ内の代表的なファイル:")
        self.sample_list_label.setStyleSheet("font-weight: bold; margin-top: 4px;")
        self.folder_layout.addWidget(self.sample_list_label)

        self.sample_list = QListWidget()
        self.sample_list.setMaximumHeight(120)
        self.folder_layout.addWidget(self.sample_list)

        self.content_layout.addWidget(self.card_folder_summary)
        self.card_folder_summary.hide()

        # 4. プレビュー表示エリア（単一ファイルの場合）
        self.card_preview = QFrame()
        self.card_preview.setObjectName("themeCard")
        preview_layout = QVBoxLayout(self.card_preview)
        self.preview_title = QLabel("👁️ ファイルの中身プレビュー")
        self.preview_title.setFont(font_badge)
        preview_layout.addWidget(self.preview_title)

        self.lbl_image_preview = QLabel()
        self.lbl_image_preview.setAlignment(Qt.AlignCenter)
        self.lbl_image_preview.setMaximumHeight(220)
        self.lbl_image_preview.hide()
        preview_layout.addWidget(self.lbl_image_preview)

        self.txt_preview = QTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setMaximumHeight(180)
        self.txt_preview.setStyleSheet("background-color: #f8fafc; color: #111827; font-family: Consolas, monospace;")
        self.txt_preview.hide()
        preview_layout.addWidget(self.txt_preview)

        self.lbl_no_preview = QLabel("この形式のプレビュー表示は対応していません。")
        self.lbl_no_preview.setStyleSheet("color: #6b7280; font-style: italic;")
        preview_layout.addWidget(self.lbl_no_preview)

        self.content_layout.addWidget(self.card_preview)
        self.card_preview.hide()

        self.content_layout.addStretch()
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

    def display_item(self, item: ItemInfo):
        """選択されたアイテムの情報をパネルに反映"""
        self.current_item = item
        self.btn_open_folder.setEnabled(True)
        self.btn_protect.setEnabled(True)

        if item.safety_level == SafetyLevel.PROTECTED:
            self.btn_protect.setText("🛡️ 保護を解除")
            badge_color = "#2563eb"
            bg_color = "#eff6ff"
            badge_text = "🛡️ 【保護中】ホワイトリスト登録済み（移動・削除ブロック）"
        elif item.safety_level == SafetyLevel.SAFE:
            self.btn_protect.setText("🛡️ 保護する")
            badge_color = "#15803d"
            bg_color = "#f0fdf4"
            badge_text = "🟢 【安全】削除・整理推奨"
        elif item.safety_level == SafetyLevel.CAUTION:
            self.btn_protect.setText("🛡️ 保護する")
            badge_color = "#b45309"
            bg_color = "#fefce8"
            badge_text = "🟡 【要確認】ユーザーデータ・一般フォルダ"
        else:
            self.btn_protect.setText("🛡️ 保護する")
            badge_color = "#b91c1c"
            bg_color = "#fef2f2"
            badge_text = "🔴 【危険】削除禁止（システムまたは使用中）"

        self.card_safety.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 8px;
                border: 2px solid {badge_color};
                padding: 10px;
            }}
        """)
        self.lbl_safety_badge.setText(badge_text)
        self.lbl_safety_badge.setStyleSheet(f"color: {badge_color}; font-weight: bold;")
        self.lbl_safety_desc.setText(item.description)
        self.lbl_safety_detail.setText(item.explanation)

        self.lbl_name.setText(f"{'📁' if item.is_dir else '📄'} {item.name}")
        self.lbl_size.setText(f"容量: {item.formatted_size}")
        self.lbl_mtime.setText(f"最終更新: {item.formatted_mtime}")
        self.lbl_path.setText(f"場所: {item.path}")

        if item.is_dir:
            self.card_preview.hide()
            self.card_folder_summary.show()
            item.load_folder_details()
            self.lbl_size.setText(f"総容量: {item.formatted_size}")

            fs = item.folder_summary
            self.lbl_folder_stats.setText(
                f"ファイル数: {fs['file_count']} 個 | サブフォルダ数: {fs['folder_count']} 個\n"
                f"最新更新: {fs['latest_date']} | 最古: {fs['oldest_date']}"
            )

            self.donut_chart.set_data(
                fs["category_sizes"],
                fs["category_counts"],
                fs["formatted_size"]
            )

            self.sample_list.clear()
            for sf in fs["sample_files"]:
                item_widget = QListWidgetItem(f"📄 {sf['name']} ({format_size(sf['size'])})")
                self.sample_list.addItem(item_widget)
        else:
            self.card_folder_summary.hide()
            self.card_preview.show()
            self._load_file_preview(item)

    def _load_file_preview(self, item: ItemInfo):
        self.lbl_image_preview.hide()
        self.txt_preview.hide()
        self.lbl_no_preview.hide()

        ext = item.extension.lower()
        if ext in [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico"]:
            pixmap = QPixmap(item.path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(QSize(320, 200), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.lbl_image_preview.setPixmap(scaled)
                self.lbl_image_preview.show()
                return

        if ext in [".txt", ".log", ".py", ".json", ".csv", ".md", ".yaml", ".yml", ".ini", ".bat", ".xml", ".html", ".css", ".js"]:
            try:
                with open(item.path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [f.readline() for _ in range(35)]
                    content = "".join(lines)
                    if content.strip():
                        self.txt_preview.setPlainText(content)
                        self.txt_preview.show()
                        return
            except Exception:
                pass

        self.lbl_no_preview.show()

    def _on_protect_clicked(self):
        if self.current_item:
            self.whitelist_toggled.emit(self.current_item.path)

    def _open_in_explorer(self):
        if self.current_item and os.path.exists(self.current_item.path):
            path = self.current_item.path
            if os.path.isfile(path):
                subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            else:
                subprocess.Popen(f'explorer "{os.path.normpath(path)}"')
