"""
ui_main.py - メインウィンドウUI実装（ダッシュボード・フォルダ診断・重複検出・キャッシュ削除・デフラグ・履歴＆パステルテーマ設定）
"""
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Dict

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QLabel, QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFileDialog, QAbstractItemView, QStatusBar,
    QProgressBar, QFrame, QCheckBox, QTabWidget, QScrollArea, QTextEdit,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QThread, Signal, QSize
from PySide6.QtGui import QColor, QFont, QDragEnterEvent, QDropEvent, QIcon, QPixmap

from analyzer import ItemInfo, SafetyLevel, format_size, find_duplicate_files
from operations import FileManager
from preview_widget import DetailPreviewPanel
from cleaner import get_system_cache_targets, scan_cache_target, clean_cache_target, CacheTarget
from maintenance import get_disk_drives, launch_windows_defrag_gui, analyze_drive_fragmentation
from settings_manager import SettingsManager, THEMES


class ScanWorker(QThread):
    """バックグラウンドでフォルダ内アイテムをスキャンして解析するスレッド"""
    progress = Signal(int, int)
    finished_scan = Signal(list)

    def __init__(self, target_dir: str, settings: SettingsManager):
        super().__init__()
        self.target_dir = target_dir
        self.settings = settings
        self.is_cancelled = False

    def run(self):
        items = []
        try:
            entries = os.listdir(self.target_dir)
            total = len(entries)
            for idx, entry in enumerate(entries):
                if self.is_cancelled:
                    break
                full_path = os.path.join(self.target_dir, entry)
                try:
                    is_prot = self.settings.is_protected(full_path)
                    info = ItemInfo(full_path, is_protected=is_prot)
                    items.append(info)
                except Exception:
                    continue
                self.progress.emit(idx + 1, total)
        except Exception:
            pass

        self.finished_scan.emit(items)


class DuplicateScanWorker(QThread):
    """バックグラウンドで重複ファイルを検出するスレッド"""
    finished_dup_scan = Signal(list)

    def __init__(self, target_dir: str):
        super().__init__()
        self.target_dir = target_dir

    def run(self):
        groups = find_duplicate_files(self.target_dir)
        self.finished_dup_scan.emit(groups)


class CacheScanWorker(QThread):
    """キャッシュスキャン用スレッド"""
    finished_cache_scan = Signal(list)

    def run(self):
        targets = get_system_cache_targets()
        for t in targets:
            scan_cache_target(t)
        self.finished_cache_scan.emit(targets)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CCCC - Clean ・ Compact ・ Care ・ Color")
        self.resize(1220, 780)
        self.setAcceptDrops(True)  # ウィンドウ全体でドラッグ＆ドロップを受け付ける

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.icon_png_path = os.path.join(base_dir, "assets", "cccc_icon.png")
        self.icon_ico_path = os.path.join(base_dir, "assets", "cccc_icon.ico")
        if os.path.exists(self.icon_ico_path):
            self.setWindowIcon(QIcon(self.icon_ico_path))

        self.settings = SettingsManager()
        self.file_manager = FileManager(self.settings)
        self.current_target_dir = str(Path.home() / "Downloads")
        self.dup_target_dir = str(Path.home() / "Downloads")

        self.all_items: List[ItemInfo] = []
        self.filtered_items: List[ItemInfo] = []
        self.duplicate_groups: List[Dict] = []
        self.cache_targets: List[CacheTarget] = []

        self.scan_thread: Optional[ScanWorker] = None
        self.dup_thread: Optional[DuplicateScanWorker] = None

        self._apply_theme()
        self._init_ui()

        # 起動時にダウンロードフォルダを自動スキャン
        self._start_scan(self.current_target_dir)

    def _apply_theme(self):
        self.setStyleSheet(self.settings.get_stylesheet())

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(8)

        # 最上部ヘッダーバー（CCCCアイコン＋アプリタイトル＋パステルテーマ切り替え）
        top_header = QHBoxLayout()
        if os.path.exists(self.icon_png_path):
            lbl_logo = QLabel()
            pix = QPixmap(self.icon_png_path).scaled(QSize(34, 34), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            lbl_logo.setPixmap(pix)
            top_header.addWidget(lbl_logo)

        app_title = QLabel("CCCC  ―  Clean ・ Compact ・ Care ・ Color （掃除して整頓しケアをして色を添える）")
        font_title = QFont()
        font_title.setPointSize(11)
        font_title.setBold(True)
        app_title.setFont(font_title)
        top_header.addWidget(app_title)

        top_header.addStretch()

        lbl_theme = QLabel("🎨 背景カラー:")
        lbl_theme.setStyleSheet("font-weight: bold;")
        top_header.addWidget(lbl_theme)

        self.combo_theme = QComboBox()
        self.theme_keys = list(THEMES.keys())
        for k in self.theme_keys:
            self.combo_theme.addItem(THEMES[k]["name"], k)
        if self.settings.theme in self.theme_keys:
            self.combo_theme.setCurrentIndex(self.theme_keys.index(self.settings.theme))
        self.combo_theme.currentIndexChanged.connect(self._on_theme_changed)
        top_header.addWidget(self.combo_theme)

        main_layout.addLayout(top_header)

        # タブウィジェット（6タブ構成）
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_home_tab(), "🏠 ホーム診断")
        self.tabs.addTab(self._create_organize_tab(), "📁 フォルダ整理・中身診断")
        self.tabs.addTab(self._create_duplicate_tab(), "👯 重複ファイル検出")
        self.tabs.addTab(self._create_cache_tab(), "🧹 キャッシュ削除")
        self.tabs.addTab(self._create_maintenance_tab(), "⚙️ ドライブ最適化")
        self.tabs.addTab(self._create_history_settings_tab(), "📜 履歴 & 🛡️ 保護リスト")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.tabs)

        # ステータスバー
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("💡 ヒント: エクスプローラーから気になるフォルダやファイルを画面にドラッグ＆ドロップすると即座に正体を診断できます！")

    def _on_theme_changed(self, idx: int):
        if 0 <= idx < len(self.theme_keys):
            self.settings.theme = self.theme_keys[idx]
            self.settings.save()
            self._apply_theme()

    def _on_tab_changed(self, idx: int):
        if idx == 0:
            self._refresh_home_dashboard()
        elif idx == 5:
            self._refresh_history_and_whitelist()

    def closeEvent(self, event):
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.is_cancelled = True
            self.scan_thread.wait(2000)
        if hasattr(self, "cache_worker") and self.cache_worker and self.cache_worker.isRunning():
            self.cache_worker.wait(2000)
        if self.dup_thread and self.dup_thread.isRunning():
            self.dup_thread.wait(2000)
        super().closeEvent(event)

    # ==========================================
    # ドラッグ＆ドロップ対応（ウィンドウ全体）
    # ==========================================
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        dropped_path = urls[0].toLocalFile()
        if not dropped_path or not os.path.exists(dropped_path):
            return

        # フォルダ整理タブに切り替えて即座に診断
        self.tabs.setCurrentIndex(1)
        if os.path.isdir(dropped_path):
            self._start_scan(dropped_path)
            info = ItemInfo(dropped_path, is_protected=self.settings.is_protected(dropped_path))
            self.preview_panel.display_item(info)
        else:
            parent_dir = os.path.dirname(dropped_path)
            self._start_scan(parent_dir)
            info = ItemInfo(dropped_path, is_protected=self.settings.is_protected(dropped_path))
            self.preview_panel.display_item(info)
        self.status_bar.showMessage(f"🎯 ドロップされた項目を診断しました: {dropped_path}")

    # ==========================================
    # タブ 0: 🏠 ホーム（PCヘルス・ダッシュボード）
    # ==========================================
    def _create_home_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ウェルカム＆ドラッグ＆ドロップ案内バナー
        drop_banner = QFrame()
        drop_banner.setObjectName("themeCard")
        drop_banner.setStyleSheet("""
            QFrame#themeCard {
                border: 2px dashed #3b82f6;
                border-radius: 12px;
                padding: 18px;
            }
        """)
        b_layout = QVBoxLayout(drop_banner)
        lbl_drop_title = QLabel("🖱️ 「これ何のフォルダ？消して大丈夫？」と思ったら、ここへドラッグ＆ドロップ！")
        font_b = QFont()
        font_b.setPointSize(13)
        font_b.setBold(True)
        lbl_drop_title.setFont(font_b)
        lbl_drop_title.setAlignment(Qt.AlignCenter)
        b_layout.addWidget(lbl_drop_title)

        lbl_drop_sub = QLabel(
            "エクスプローラーからフォルダやファイルをこの画面にドロップするだけで、\n"
            "「何のアプリのデータか」「消しても安全か」「中身の円グラフ内訳」を自動で診断します。"
        )
        lbl_drop_sub.setAlignment(Qt.AlignCenter)
        b_layout.addWidget(lbl_drop_sub)
        layout.addWidget(drop_banner)

        # 3つのステータスメーターカード横並び
        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)

        # カード1: Cドライブ空き状況
        card_disk = QFrame()
        card_disk.setObjectName("themeCard")
        cd_layout = QVBoxLayout(card_disk)
        lbl_c1 = QLabel("💾 Cドライブの空き容量")
        lbl_c1.setStyleSheet("font-weight: bold; font-size: 13px;")
        cd_layout.addWidget(lbl_c1)
        self.lbl_home_disk = QLabel("計測中...")
        self.lbl_home_disk.setStyleSheet("font-size: 18px; font-weight: bold; color: #2563eb;")
        cd_layout.addWidget(self.lbl_home_disk)
        self.pbar_home_disk = QProgressBar()
        self.pbar_home_disk.setFixedHeight(14)
        cd_layout.addWidget(self.pbar_home_disk)
        cards_row.addWidget(card_disk, stretch=1)

        # カード2: 今すぐ削減できるキャッシュ容量
        card_cache = QFrame()
        card_cache.setObjectName("themeCard")
        cc_layout = QVBoxLayout(card_cache)
        lbl_c2 = QLabel("🧹 今すぐ空けられる一時キャッシュ")
        lbl_c2.setStyleSheet("font-weight: bold; font-size: 13px;")
        cc_layout.addWidget(lbl_c2)
        self.lbl_home_cache = QLabel("スキャン中...")
        self.lbl_home_cache.setStyleSheet("font-size: 18px; font-weight: bold; color: #059669;")
        cc_layout.addWidget(self.lbl_home_cache)
        btn_go_cache = QPushButton("キャッシュ掃除画面へ →")
        btn_go_cache.clicked.connect(lambda: self.tabs.setCurrentIndex(3))
        cc_layout.addWidget(btn_go_cache)
        cards_row.addWidget(card_cache, stretch=1)

        # カード3: 保護＆整理履歴ステータス
        card_hist = QFrame()
        card_hist.setObjectName("themeCard")
        ch_layout = QVBoxLayout(card_hist)
        lbl_c3 = QLabel("🛡️ 安心・安全ガード状態")
        lbl_c3.setStyleSheet("font-weight: bold; font-size: 13px;")
        ch_layout.addWidget(lbl_c3)
        self.lbl_home_guard = QLabel("保護中: 0 件 / 履歴: 0 件")
        self.lbl_home_guard.setStyleSheet("font-size: 14px; font-weight: bold;")
        ch_layout.addWidget(self.lbl_home_guard)
        btn_go_hist = QPushButton("操作履歴・保護リストを見る →")
        btn_go_hist.clicked.connect(lambda: self.tabs.setCurrentIndex(5))
        ch_layout.addWidget(btn_go_hist)
        cards_row.addWidget(card_hist, stretch=1)

        layout.addLayout(cards_row)

        # 目的別クイックスタートボタン群
        lbl_quick = QLabel("🚀 目的から選んでワンクリック整理")
        lbl_quick.setFont(font_b)
        layout.addWidget(lbl_quick)

        quick_grid = QHBoxLayout()
        quick_grid.setSpacing(12)

        btn_q_dl = QPushButton("📥 ダウンロードフォルダを診断・仕分け\n（古いインストーラーや散らかった書類を整理）")
        btn_q_dl.setMinimumHeight(64)
        btn_q_dl.clicked.connect(lambda: (self.tabs.setCurrentIndex(1), self._start_scan(str(Path.home() / "Downloads"))))
        quick_grid.addWidget(btn_q_dl)

        btn_q_appdata = QPushButton("🕵️‍♂️ アンインストール済みアプリの残骸を探す\n（AppData内の使われていない謎フォルダを診断）")
        btn_q_appdata.setMinimumHeight(64)
        btn_q_appdata.clicked.connect(self._scan_appdata_orphans)
        quick_grid.addWidget(btn_q_appdata)

        btn_q_dup = QPushButton("👯 同じファイルの重複コピーを見つける\n（名前が違っても中身が同じファイルを比較整理）")
        btn_q_dup.setMinimumHeight(64)
        btn_q_dup.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        quick_grid.addWidget(btn_q_dup)

        layout.addLayout(quick_grid)
        layout.addStretch()

        self._refresh_home_dashboard()
        return widget

    def _refresh_home_dashboard(self):
        drives = get_disk_drives()
        if drives:
            c = drives[0]
            self.lbl_home_disk.setText(f"空き {format_size(c['free'])} / 全体 {format_size(c['total'])}")
            self.pbar_home_disk.setMaximum(100)
            self.pbar_home_disk.setValue(int(c["percent"]))

        total_cache = sum(t.total_size for t in self.cache_targets)
        self.lbl_home_cache.setText(f"約 {format_size(total_cache)} 削減可能")

        self.lbl_home_guard.setText(
            f"保護登録: {len(self.settings.whitelist)} 件  |  復元可能な履歴: {len(self.settings.history)} 件"
        )

    def _scan_appdata_orphans(self):
        local_appdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        self.tabs.setCurrentIndex(1)
        self.combo_filter.setCurrentIndex(0)
        self._start_scan(local_appdata)

    # ==========================================
    # タブ 1: 📁 フォルダ整理・中身診断タブ
    # ==========================================
    def _create_organize_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top_bar = QHBoxLayout()
        lbl_target = QLabel("📁 対象フォルダ:")
        lbl_target.setStyleSheet("font-weight: bold; font-size: 13px;")
        top_bar.addWidget(lbl_target)

        self.lbl_current_path = QLabel(self.current_target_dir)
        self.lbl_current_path.setStyleSheet("background: #ffffff; border: 1px solid #94a3b8; border-radius: 4px; padding: 5px 8px; font-weight: bold;")
        top_bar.addWidget(self.lbl_current_path, stretch=1)

        btn_select_dir = QPushButton("📂 フォルダ選択...")
        btn_select_dir.clicked.connect(self._select_directory)
        top_bar.addWidget(btn_select_dir)

        btn_dl = QPushButton("📥 ダウンロード")
        btn_dl.clicked.connect(lambda: self._start_scan(str(Path.home() / "Downloads")))
        top_bar.addWidget(btn_dl)

        btn_desk = QPushButton("🖥️ デスクトップ")
        btn_desk.clicked.connect(lambda: self._start_scan(str(Path.home() / "Desktop")))
        top_bar.addWidget(btn_desk)

        btn_doc = QPushButton("📄 ドキュメント")
        btn_doc.clicked.connect(lambda: self._start_scan(str(Path.home() / "Documents")))
        top_bar.addWidget(btn_doc)

        btn_appdata = QPushButton("🕵️‍♂️ AppData診断")
        btn_appdata.setToolTip("アプリのキャッシュやアンインストール後の残骸フォルダを調査します")
        btn_appdata.clicked.connect(self._scan_appdata_orphans)
        top_bar.addWidget(btn_appdata)

        btn_refresh = QPushButton("🔄 再スキャン")
        btn_refresh.clicked.connect(lambda: self._start_scan(self.current_target_dir))
        top_bar.addWidget(btn_refresh)

        layout.addLayout(top_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        splitter = QSplitter(Qt.Horizontal)

        # 左ペイン
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("🔍 絞り込み:"))
        self.combo_filter = QComboBox()
        self.combo_filter.addItems([
            "すべて表示",
            "🟢 安全に消せるものだけ (キャッシュ・古いインストーラー・空フォルダ・残骸)",
            "🕵️‍♂️ アンインストール済みアプリの残骸候補のみ",
            "🟡 ユーザーデータ (書類・写真・動画)",
            "🛡️ 保護リスト登録済みアイテム",
            "🔴 危険・使用中 (システム・設定)",
            "📦 大容量ファイル (50MB以上)",
            "⏳ 古い項目 (30日以上未更新)"
        ])
        self.combo_filter.currentIndexChanged.connect(self._apply_filter)
        filter_bar.addWidget(self.combo_filter, stretch=1)

        self.chk_select_all = QCheckBox("すべてチェック")
        self.chk_select_all.toggled.connect(self._toggle_select_all)
        filter_bar.addWidget(self.chk_select_all)
        left_layout.addLayout(filter_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["選択", "安全性", "名前", "サイズ", "正体・用途タグ"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        self.table.itemChanged.connect(self._on_table_item_changed)
        left_layout.addWidget(self.table)

        splitter.addWidget(left_widget)

        # 右ペイン: ドーナツグラフ付き詳細パネル
        self.preview_panel = DetailPreviewPanel()
        self.preview_panel.whitelist_toggled.connect(self._toggle_whitelist_for_path)
        splitter.addWidget(self.preview_panel)
        splitter.setSizes([660, 500])

        layout.addWidget(splitter, stretch=1)

        # 下部操作バー
        bottom_bar = QHBoxLayout()
        self.lbl_selection_summary = QLabel("選択中: 0 項目 (0 B)")
        self.lbl_selection_summary.setStyleSheet("font-weight: bold;")
        bottom_bar.addWidget(self.lbl_selection_summary)

        bottom_bar.addStretch()

        self.btn_undo = QPushButton("↩️ 直前の操作を元に戻す")
        self.btn_undo.clicked.connect(self._undo_last_op)
        bottom_bar.addWidget(self.btn_undo)

        btn_organize = QPushButton("📁 チェックした項目を種類別に自動仕分け")
        btn_organize.setObjectName("btnOrganize")
        btn_organize.clicked.connect(self._organize_selected)
        bottom_bar.addWidget(btn_organize)

        btn_trash = QPushButton("🗑️ チェックした項目をゴミ箱へ移動")
        btn_trash.setObjectName("btnTrash")
        btn_trash.clicked.connect(self._trash_selected)
        bottom_bar.addWidget(btn_trash)

        layout.addLayout(bottom_bar)
        return widget

    def _toggle_whitelist_for_path(self, path: str):
        if self.settings.is_protected(path):
            self.settings.remove_from_whitelist(path)
            self.status_bar.showMessage(f"🔓 保護を解除しました: {os.path.basename(path)}")
        else:
            self.settings.add_to_whitelist(path)
            self.status_bar.showMessage(f"🛡️ 保護リストに登録しました: {os.path.basename(path)}")
        self._start_scan(self.current_target_dir)

    # ==========================================
    # タブ 2: 👯 重複ファイル検出タブ
    # ==========================================
    def _create_duplicate_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        top_h = QHBoxLayout()
        lbl_dup_title = QLabel("👯 重複ファイル（同じ内容のコピー）検出:")
        lbl_dup_title.setStyleSheet("font-weight: bold; font-size: 13px;")
        top_h.addWidget(lbl_dup_title)

        self.lbl_dup_path = QLabel(self.dup_target_dir)
        self.lbl_dup_path.setStyleSheet("background: #ffffff; border: 1px solid #94a3b8; border-radius: 4px; padding: 5px 8px; font-weight: bold;")
        top_h.addWidget(self.lbl_dup_path, stretch=1)

        btn_dup_browse = QPushButton("📂 フォルダ選択...")
        btn_dup_browse.clicked.connect(self._select_dup_directory)
        top_h.addWidget(btn_dup_browse)

        self.btn_start_dup = QPushButton("🔍 重複スキャン開始")
        self.btn_start_dup.setObjectName("btnPrimary")
        self.btn_start_dup.clicked.connect(self._start_duplicate_scan)
        top_h.addWidget(self.btn_start_dup)

        layout.addLayout(top_h)

        desc_lbl = QLabel("ファイル名が違っても中身のデータ（SHA-256ハッシュ）が100%一致する重複ファイルを検出します。原本を1つ残してコピーだけを安全に整理できます。")
        layout.addWidget(desc_lbl)

        self.table_dup = QTableWidget()
        self.table_dup.setColumnCount(5)
        self.table_dup.setHorizontalHeaderLabels(["削除対象", "グループ", "ファイル名", "サイズ", "場所 / 更新日時"])
        self.table_dup.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_dup.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_dup.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_dup.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_dup.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.table_dup, stretch=1)

        bot_h = QHBoxLayout()
        self.lbl_dup_summary = QLabel("「🔍 重複スキャン開始」を押してください。")
        self.lbl_dup_summary.setStyleSheet("font-weight: bold;")
        bot_h.addWidget(self.lbl_dup_summary)
        bot_h.addStretch()

        btn_auto_check_dup = QPushButton("✨ 原本（1つ目）を残して重複コピーだけ自動チェック")
        btn_auto_check_dup.clicked.connect(self._auto_check_duplicates)
        bot_h.addWidget(btn_auto_check_dup)

        btn_trash_dup = QPushButton("🗑️ チェックした重複ファイルをゴミ箱へ移動")
        btn_trash_dup.setObjectName("btnTrash")
        btn_trash_dup.clicked.connect(self._trash_checked_duplicates)
        bot_h.addWidget(btn_trash_dup)

        layout.addLayout(bot_h)
        return widget

    def _select_dup_directory(self):
        d = QFileDialog.getExistingDirectory(self, "重複チェックするフォルダを選択", self.dup_target_dir)
        if d:
            self.dup_target_dir = os.path.normpath(d)
            self.lbl_dup_path.setText(self.dup_target_dir)
            self._start_duplicate_scan()

    def _start_duplicate_scan(self):
        self.btn_start_dup.setEnabled(False)
        self.lbl_dup_summary.setText("重複ファイルを高速ハッシュ検査中...")
        self.table_dup.setRowCount(0)

        self.dup_thread = DuplicateScanWorker(self.dup_target_dir)
        self.dup_thread.finished_dup_scan.connect(self._on_dup_scan_finished)
        self.dup_thread.start()

    def _on_dup_scan_finished(self, groups: List[Dict]):
        self.btn_start_dup.setEnabled(True)
        self.duplicate_groups = groups
        self.table_dup.setRowCount(0)

        total_wasted = sum(g["wasted_bytes"] for g in groups)
        self.lbl_dup_summary.setText(
            f"検出結果: {len(groups)} グループの重複ファイル （削減可能な無駄容量: {format_size(total_wasted)}）"
        )

        row_idx = 0
        for g_idx, g in enumerate(groups, start=1):
            for f_idx, f_info in enumerate(g["files"]):
                self.table_dup.insertRow(row_idx)
                is_original = (f_idx == 0)

                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Unchecked if is_original else Qt.Checked)
                chk.setData(Qt.UserRole, f_info["path"])
                self.table_dup.setItem(row_idx, 0, chk)

                grp_label = f"グループ #{g_idx} ({'🟢 原本候補' if is_original else '👯 コピー'})"
                self.table_dup.setItem(row_idx, 1, QTableWidgetItem(grp_label))
                self.table_dup.setItem(row_idx, 2, QTableWidgetItem(f_info["name"]))
                self.table_dup.setItem(row_idx, 3, QTableWidgetItem(g["formatted_size"]))
                self.table_dup.setItem(row_idx, 4, QTableWidgetItem(f"{f_info['path']}  ({f_info['mtime_str']})"))
                row_idx += 1

    def _auto_check_duplicates(self):
        for r in range(self.table_dup.rowCount()):
            grp_text = self.table_dup.item(r, 1).text()
            chk = self.table_dup.item(r, 0)
            if "原本候補" in grp_text:
                chk.setCheckState(Qt.Unchecked)
            else:
                chk.setCheckState(Qt.Checked)

    def _trash_checked_duplicates(self):
        paths = []
        for r in range(self.table_dup.rowCount()):
            chk = self.table_dup.item(r, 0)
            if chk and chk.checkState() == Qt.Checked:
                paths.append(chk.data(Qt.UserRole))

        if not paths:
            QMessageBox.information(self, "案内", "削除する重複ファイルにチェックを入れてください。")
            return

        reply = QMessageBox.question(
            self,
            "重複ファイルのゴミ箱移動",
            f"チェックされた {len(paths)} 個の重複コピーをWindowsのゴミ箱へ移動します。\nよろしいですか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            ok_cnt = 0
            for p in paths:
                ok, _ = self.file_manager.move_to_trash(p)
                if ok:
                    ok_cnt += 1
            QMessageBox.information(self, "完了", f"{ok_cnt} 個の重複ファイルをゴミ箱へ移動しました！")
            self._start_duplicate_scan()

    # ==========================================
    # タブ 3: 🧹 キャッシュ削除タブ
    # ==========================================
    def _create_cache_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        header_layout = QHBoxLayout()
        header_lbl = QLabel("🧹 システムおよびアプリのキャッシュ・不要ファイル削除")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        header_lbl.setFont(font)
        header_layout.addWidget(header_lbl)
        header_layout.addStretch()

        btn_scan_cache = QPushButton("🔄 キャッシュを再スキャン")
        btn_scan_cache.clicked.connect(self._scan_cache)
        header_layout.addWidget(btn_scan_cache)
        layout.addLayout(header_layout)

        desc_lbl = QLabel("Windowsの一時ファイルやブラウザのキャッシュなどを一括検出して安全に削除し、空き容量を回復します。")
        layout.addWidget(desc_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.cache_list_widget = QWidget()
        self.cache_list_layout = QVBoxLayout(self.cache_list_widget)
        self.cache_list_layout.setSpacing(10)
        scroll.setWidget(self.cache_list_widget)
        layout.addWidget(scroll, stretch=1)

        action_bar = QHBoxLayout()
        self.lbl_cache_summary = QLabel("合計キャッシュ: 計算中...")
        self.lbl_cache_summary.setStyleSheet("font-size: 14px; font-weight: bold; color: #059669;")
        action_bar.addWidget(self.lbl_cache_summary)
        action_bar.addStretch()

        btn_clean_all = QPushButton("✨ 安全にキャッシュを全クリア")
        btn_clean_all.setObjectName("btnPrimary")
        btn_clean_all.clicked.connect(self._clean_all_cache)
        action_bar.addWidget(btn_clean_all)

        layout.addLayout(action_bar)

        self._scan_cache()
        return widget

    def _scan_cache(self):
        self.lbl_cache_summary.setText("キャッシュを走査中...")
        while self.cache_list_layout.count():
            item = self.cache_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.cache_worker = CacheScanWorker()
        self.cache_worker.finished_cache_scan.connect(self._on_cache_scanned)
        self.cache_worker.start()

    def _on_cache_scanned(self, targets: List[CacheTarget]):
        self.cache_targets = targets
        total_all_bytes = sum(t.total_size for t in targets)
        self.lbl_cache_summary.setText(f"削除可能なキャッシュ合計: {format_size(total_all_bytes)}")
        self._refresh_home_dashboard()

        for t in targets:
            card = QFrame()
            card.setObjectName("themeCard")
            clayout = QHBoxLayout(card)

            v_info = QVBoxLayout()
            lbl_name = QLabel(f"🟢 {t.name}")
            lbl_name.setStyleSheet("font-weight: bold; font-size: 13px;")
            v_info.addWidget(lbl_name)

            lbl_desc = QLabel(t.description)
            lbl_desc.setWordWrap(True)
            v_info.addWidget(lbl_desc)

            clayout.addLayout(v_info, stretch=1)

            lbl_size = QLabel(f"{format_size(t.total_size)}\n({t.file_count} ファイル)")
            lbl_size.setAlignment(Qt.AlignCenter)
            lbl_size.setStyleSheet("font-weight: bold; color: #2563eb; min-width: 110px;")
            clayout.addWidget(lbl_size)

            btn_clean_one = QPushButton("🗑️ 消去")
            btn_clean_one.clicked.connect(lambda _, target=t: self._clean_single_cache(target))
            clayout.addWidget(btn_clean_one)

            self.cache_list_layout.addWidget(card)

        self.cache_list_layout.addStretch()

    def _clean_single_cache(self, target: CacheTarget):
        reply = QMessageBox.question(
            self,
            "キャッシュ消去の確認",
            f"『{target.name}』のファイル（{format_size(target.total_size)}）を削除します。\n実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            cnt, freed, _ = clean_cache_target(target, use_trash=True)
            QMessageBox.information(
                self,
                "完了",
                f"キャッシュを削除しました。\n\n削除件数: {cnt} 個\n解放容量: {format_size(freed)}"
            )
            self._scan_cache()

    def _clean_all_cache(self):
        total_all_bytes = sum(t.total_size for t in self.cache_targets)
        if total_all_bytes == 0:
            QMessageBox.information(self, "案内", "削除するキャッシュが見つかりませんでした。")
            return

        reply = QMessageBox.question(
            self,
            "一括消去の確認",
            f"検出されたすべてのキャッシュ（合計 {format_size(total_all_bytes)}）を安全に削除します。\n実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            total_cnt = 0
            total_freed = 0
            for t in self.cache_targets:
                cnt, freed, _ = clean_cache_target(t, use_trash=True)
                total_cnt += cnt
                total_freed += freed
            QMessageBox.information(
                self,
                "一括消去完了",
                f"クリーンアップが完了しました！\n\n削除件数: {total_cnt} 個\n解放容量: {format_size(total_freed)}"
            )
            self._scan_cache()

    # ==========================================
    # タブ 4: ⚙️ ドライブ最適化 & デフラグタブ
    # ==========================================
    def _create_maintenance_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        header_lbl = QLabel("⚙️ ドライブの最適化 & デフラグ (SSD/HDD)")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        header_lbl.setFont(font)
        layout.addWidget(header_lbl)

        desc_lbl = QLabel("PCのストレージ（SSD/HDD）の利用状況を確認し、Windows標準の最適化ツール（TRIM / デフラグ）を起動できます。")
        layout.addWidget(desc_lbl)

        self.drives_container = QVBoxLayout()
        layout.addLayout(self.drives_container)
        self._refresh_drive_list()

        analysis_frame = QFrame()
        analysis_frame.setObjectName("themeCard")
        a_layout = QVBoxLayout(analysis_frame)
        a_layout.addWidget(QLabel("🔍 クイック断片化分析 & Windows最適化ツール連携"))

        btn_h = QHBoxLayout()
        self.btn_analyze_c = QPushButton("Cドライブの断片化を分析")
        self.btn_analyze_c.clicked.connect(self._run_fragmentation_analysis)
        btn_h.addWidget(self.btn_analyze_c)

        btn_launch_defrag = QPushButton("🚀 Windows標準の最適化ツールを起動")
        btn_launch_defrag.setObjectName("btnPrimary")
        btn_launch_defrag.clicked.connect(launch_windows_defrag_gui)
        btn_h.addWidget(btn_launch_defrag)
        a_layout.addLayout(btn_h)

        self.txt_defrag_log = QTextEdit()
        self.txt_defrag_log.setReadOnly(True)
        self.txt_defrag_log.setMaximumHeight(150)
        self.txt_defrag_log.setPlaceholderText("分析結果がここに表示されます...")
        a_layout.addWidget(self.txt_defrag_log)

        layout.addWidget(analysis_frame)
        layout.addStretch()
        return widget

    def _refresh_drive_list(self):
        drives = get_disk_drives()
        for d in drives:
            card = QFrame()
            card.setObjectName("themeCard")
            c_layout = QVBoxLayout(card)

            top_h = QHBoxLayout()
            lbl_dev = QLabel(f"💾 ドライブ {d['device']} ({d['fstype'].upper()})")
            lbl_dev.setStyleSheet("font-weight: bold; font-size: 13px;")
            top_h.addWidget(lbl_dev)
            top_h.addStretch()

            lbl_usage = QLabel(f"使用中: {format_size(d['used'])} / 空き: {format_size(d['free'])} / 全体: {format_size(d['total'])} ({d['percent']}%)")
            top_h.addWidget(lbl_usage)
            c_layout.addLayout(top_h)

            pbar = QProgressBar()
            pbar.setMaximum(100)
            pbar.setValue(int(d["percent"]))
            pbar.setFixedHeight(14)
            c_layout.addWidget(pbar)

            self.drives_container.addWidget(card)

    def _run_fragmentation_analysis(self):
        self.txt_defrag_log.setPlainText("分析を実行中... (数秒かかる場合があります)")
        self.btn_analyze_c.setEnabled(False)
        QApplication.processEvents()

        _, output = analyze_drive_fragmentation("C")
        self.txt_defrag_log.setPlainText(output)
        self.btn_analyze_c.setEnabled(True)

    # ==========================================
    # タブ 5: 📜 操作履歴タイムライン & 🛡️ 保護リスト管理タブ
    # ==========================================
    def _create_history_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        splitter = QSplitter(Qt.Horizontal)

        # 左: 操作履歴タイムライン
        hist_frame = QFrame()
        hist_frame.setObjectName("themeCard")
        h_layout = QVBoxLayout(hist_frame)

        h_top = QHBoxLayout()
        lbl_h = QLabel("📜 操作履歴タイムライン（後からいつでも元の場所へ復元）")
        font_b = QFont()
        font_b.setPointSize(11)
        font_b.setBold(True)
        lbl_h.setFont(font_b)
        h_top.addWidget(lbl_h)
        h_top.addStretch()

        btn_restore_sel = QPushButton("↩️ 選択した移動履歴を元の場所へ戻す")
        btn_restore_sel.setObjectName("btnPrimary")
        btn_restore_sel.clicked.connect(self._restore_selected_history)
        h_top.addWidget(btn_restore_sel)
        h_layout.addLayout(h_top)

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(4)
        self.table_history.setHorizontalHeaderLabels(["日時", "操作内容", "ファイル名", "元の場所 → 移動先"])
        self.table_history.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_history.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table_history.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_history.setSelectionMode(QAbstractItemView.SingleSelection)
        h_layout.addWidget(self.table_history)

        splitter.addWidget(hist_frame)

        # 右: ホワイトリスト（保護リスト）管理
        prot_frame = QFrame()
        prot_frame.setObjectName("themeCard")
        p_layout = QVBoxLayout(prot_frame)

        lbl_p = QLabel("🛡️ 保護リスト（誤削除・移動を防止するロック項目）")
        lbl_p.setFont(font_b)
        p_layout.addWidget(lbl_p)

        lbl_p_desc = QLabel("ここに登録されたフォルダやファイルは、一括削除や仕分けの対象から自動的に除外されます。")
        lbl_p_desc.setWordWrap(True)
        p_layout.addWidget(lbl_p_desc)

        self.list_whitelist = QListWidget()
        p_layout.addWidget(self.list_whitelist, stretch=1)

        p_btns = QHBoxLayout()
        btn_add_prot_dir = QPushButton("➕ フォルダを保護追加")
        btn_add_prot_dir.clicked.connect(self._add_folder_to_whitelist_dialog)
        p_btns.addWidget(btn_add_prot_dir)

        btn_rem_prot = QPushButton("🔓 選択項目の保護を解除")
        btn_rem_prot.clicked.connect(self._remove_selected_whitelist)
        p_btns.addWidget(btn_rem_prot)
        p_layout.addLayout(p_btns)

        splitter.addWidget(prot_frame)
        splitter.setSizes([700, 440])

        layout.addWidget(splitter, stretch=1)
        self._refresh_history_and_whitelist()
        return widget

    def _refresh_history_and_whitelist(self):
        # 履歴テーブル更新
        self.table_history.setRowCount(0)
        for idx, h in enumerate(self.settings.history):
            self.table_history.insertRow(idx)
            self.table_history.setItem(idx, 0, QTableWidgetItem(h.get("timestamp", "")))

            op_type = h.get("op_type", "")
            restored = h.get("restored", False)
            if restored:
                op_str = "✅ 復元済み"
            elif op_type == "MOVE":
                op_str = "📁 仕分け移動"
            else:
                op_str = "🗑️ ゴミ箱移動"

            op_item = QTableWidgetItem(op_str)
            op_item.setData(Qt.UserRole, h)
            self.table_history.setItem(idx, 1, op_item)
            self.table_history.setItem(idx, 2, QTableWidgetItem(h.get("item_name", "")))

            src = h.get("source_path", "")
            tgt = h.get("target_path") or "Windowsのごみ箱"
            self.table_history.setItem(idx, 3, QTableWidgetItem(f"{src}  →  {tgt}"))

        # 保護リスト更新
        self.list_whitelist.clear()
        for w_path in self.settings.whitelist:
            item = QListWidgetItem(f"🛡️ {w_path}")
            item.setData(Qt.UserRole, w_path)
            self.list_whitelist.addItem(item)

    def _restore_selected_history(self):
        rows = self.table_history.selectionModel().selectedRows()
        if not rows:
            QMessageBox.information(self, "案内", "復元したい履歴の行を選択してください。")
            return
        row = rows[0].row()
        h_entry = self.table_history.item(row, 1).data(Qt.UserRole)
        ok, msg = self.file_manager.restore_from_history(h_entry)
        if ok:
            QMessageBox.information(self, "復元完了", msg)
            self._refresh_history_and_whitelist()
            self._start_scan(self.current_target_dir)
        else:
            QMessageBox.warning(self, "案内", msg)

    def _add_folder_to_whitelist_dialog(self):
        d = QFileDialog.getExistingDirectory(self, "保護するフォルダを選択", str(Path.home()))
        if d:
            self.settings.add_to_whitelist(d)
            self._refresh_history_and_whitelist()
            self._start_scan(self.current_target_dir)

    def _remove_selected_whitelist(self):
        cur = self.list_whitelist.currentItem()
        if not cur:
            return
        w_path = cur.data(Qt.UserRole)
        self.settings.remove_from_whitelist(w_path)
        self._refresh_history_and_whitelist()
        self._start_scan(self.current_target_dir)

    # ==========================================
    # フォルダ整理イベントハンドラ
    # ==========================================
    def _select_directory(self):
        dir_path = QFileDialog.getExistingDirectory(self, "整理するフォルダを選択", self.current_target_dir)
        if dir_path:
            self._start_scan(dir_path)

    def _start_scan(self, dir_path: str):
        if not os.path.isdir(dir_path):
            QMessageBox.warning(self, "エラー", f"指定されたフォルダが存在しません: {dir_path}")
            return

        self.current_target_dir = os.path.normpath(dir_path)
        self.lbl_current_path.setText(self.current_target_dir)
        self.status_bar.showMessage(f"スキャン中: {self.current_target_dir}...")
        self.progress_bar.show()

        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.is_cancelled = True
            self.scan_thread.wait()

        self.scan_thread = ScanWorker(self.current_target_dir, self.settings)
        self.scan_thread.progress.connect(self._on_scan_progress)
        self.scan_thread.finished_scan.connect(self._on_scan_finished)
        self.scan_thread.start()

    def _on_scan_progress(self, current: int, total: int):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def _on_scan_finished(self, items: List[ItemInfo]):
        self.progress_bar.hide()
        self.all_items = items
        self.status_bar.showMessage(f"スキャン完了: {self.current_target_dir} （合計 {len(items)} 項目）")
        self._apply_filter()
        self._refresh_home_dashboard()

    def _apply_filter(self):
        filter_idx = self.combo_filter.currentIndex()
        now = time.time()

        if filter_idx == 0:
            self.filtered_items = self.all_items
        elif filter_idx == 1:
            self.filtered_items = [it for it in self.all_items if it.safety_level == SafetyLevel.SAFE]
        elif filter_idx == 2:
            self.filtered_items = [it for it in self.all_items if it.is_orphan_candidate]
        elif filter_idx == 3:
            self.filtered_items = [it for it in self.all_items if it.safety_level == SafetyLevel.CAUTION]
        elif filter_idx == 4:
            self.filtered_items = [it for it in self.all_items if it.safety_level == SafetyLevel.PROTECTED]
        elif filter_idx == 5:
            self.filtered_items = [it for it in self.all_items if it.safety_level == SafetyLevel.DANGER]
        elif filter_idx == 6:
            self.filtered_items = [it for it in self.all_items if it.size >= 50 * 1024 * 1024]
        elif filter_idx == 7:
            self.filtered_items = [it for it in self.all_items if (now - it.mtime) >= 30 * 24 * 3600]

        self._populate_table()

    def _populate_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setSortingEnabled(False)

        is_all_checked = self.chk_select_all.isChecked()
        allow_danger_check = (self.combo_filter.currentIndex() == 5)

        for row_idx, item in enumerate(self.filtered_items):
            self.table.insertRow(row_idx)

            chk_item = QTableWidgetItem()
            if item.safety_level == SafetyLevel.PROTECTED:
                chk_item.setFlags(Qt.ItemIsEnabled)
            else:
                chk_item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                if is_all_checked and (allow_danger_check or item.safety_level != SafetyLevel.DANGER):
                    chk_item.setCheckState(Qt.Checked)
                else:
                    chk_item.setCheckState(Qt.Unchecked)
            self.table.setItem(row_idx, 0, chk_item)

            if item.safety_level == SafetyLevel.PROTECTED:
                badge_str = "🛡️ 保護中"
            elif item.safety_level == SafetyLevel.SAFE:
                badge_str = "🟢 安全"
            elif item.safety_level == SafetyLevel.CAUTION:
                badge_str = "🟡 確認"
            else:
                badge_str = "🔴 危険"
            badge_item = QTableWidgetItem(badge_str)
            badge_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 1, badge_item)

            name_str = f"{'📁 ' if item.is_dir else '📄 '}{item.name}"
            name_item = QTableWidgetItem(name_str)
            name_item.setData(Qt.UserRole, item)
            self.table.setItem(row_idx, 2, name_item)

            size_item = QTableWidgetItem(item.formatted_size)
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row_idx, 3, size_item)

            tag_str = ", ".join(item.tags) if item.tags else item.category
            tag_item = QTableWidgetItem(tag_str)
            self.table.setItem(row_idx, 4, tag_item)

        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection_summary()

    def _on_table_selection_changed(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if selected_rows:
            row = selected_rows[0].row()
            name_item = self.table.item(row, 2)
            if name_item:
                item_info = name_item.data(Qt.UserRole)
                if item_info:
                    self.preview_panel.display_item(item_info)
                    # フォルダ容量が計測されたらテーブルの容量表示も更新
                    if item_info.is_dir:
                        sz_cell = self.table.item(row, 3)
                        if sz_cell:
                            sz_cell.setText(item_info.formatted_size)

    def _on_table_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            self._update_selection_summary()

    def _toggle_select_all(self, checked: bool = False):
        is_checked = self.chk_select_all.isChecked()
        check_state = Qt.Checked if is_checked else Qt.Unchecked
        allow_danger_check = (self.combo_filter.currentIndex() == 5)

        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            name_item = self.table.item(row, 2)
            item_info = name_item.data(Qt.UserRole) if name_item else None
            if chk_item and item_info and item_info.safety_level != SafetyLevel.PROTECTED:
                if is_checked and not allow_danger_check and item_info.safety_level == SafetyLevel.DANGER:
                    chk_item.setCheckState(Qt.Unchecked)
                else:
                    chk_item.setCheckState(check_state)
        self.table.blockSignals(False)
        self.table.viewport().update()
        self._update_selection_summary()

    def _get_checked_items(self) -> List[ItemInfo]:
        checked = []
        for row in range(self.table.rowCount()):
            chk_item = self.table.item(row, 0)
            if chk_item and chk_item.checkState() == Qt.Checked:
                name_item = self.table.item(row, 2)
                item_info = name_item.data(Qt.UserRole)
                if item_info:
                    checked.append(item_info)
        return checked

    def _update_selection_summary(self):
        checked_items = self._get_checked_items()
        count = len(checked_items)
        total_bytes = sum(it.size for it in checked_items)
        self.lbl_selection_summary.setText(f"選択中: {count} 項目 ({format_size(total_bytes)})")

    def _trash_selected(self):
        checked_items = self._get_checked_items()
        if not checked_items:
            QMessageBox.information(self, "案内", "ゴミ箱へ移動する項目をチェックしてください。")
            return

        dangers = [it.name for it in checked_items if it.safety_level == SafetyLevel.DANGER]
        if dangers:
            danger_list = "\n".join(f"• {name}" for name in dangers[:5])
            if len(dangers) > 5:
                danger_list += f"\n...他 {len(dangers)-5} 件"

            reply = QMessageBox.warning(
                self,
                "⚠️ 危険な項目が含まれています",
                f"選択された項目の中に、システムやアプリに必要な【危険】と判定されたファイルが含まれています：\n\n"
                f"{danger_list}\n\n"
                "これらを削除するとアプリが動かなくなる可能性があります。本当にゴミ箱へ移動しますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        else:
            reply = QMessageBox.question(
                self,
                "ゴミ箱へ移動の確認",
                f"選択した {len(checked_items)} 項目をWindowsのゴミ箱へ移動します。\nよろしいですか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if reply != QMessageBox.Yes:
                return

        success_count = 0
        fail_count = 0
        for it in checked_items:
            success, _ = self.file_manager.move_to_trash(it.path)
            if success:
                success_count += 1
            else:
                fail_count += 1

        self.status_bar.showMessage(f"{success_count} 個の項目をゴミ箱に移動しました。（失敗/スキップ: {fail_count} 個）")
        self._start_scan(self.current_target_dir)

    def _organize_selected(self):
        checked_items = self._get_checked_items()
        if not checked_items:
            QMessageBox.information(self, "案内", "仕分け移動する項目をチェックしてください。")
            return

        file_paths = [it.path for it in checked_items if not it.is_dir]
        if not file_paths:
            QMessageBox.information(self, "案内", "自動仕分けはファイルのみが対象です。フォルダは選択から外してください。")
            return

        reply = QMessageBox.question(
            self,
            "自動仕分けの確認",
            f"選択した {len(file_paths)} 個のファイルを、拡張子に応じて「画像」「書類」などの専用フォルダへ移動します。\n実行しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if reply != QMessageBox.Yes:
            return

        res = self.file_manager.organize_by_category(self.current_target_dir, file_paths)
        QMessageBox.information(
            self,
            "仕分け完了",
            f"仕分けが完了しました！\n\n移動成功: {res['success']} 件\nスキップ/失敗: {res['failed'] + res['skipped']} 件\n\n（「📜 履歴 & 保護リスト」タブからいつでも元の場所へ戻せます）"
        )
        self._start_scan(self.current_target_dir)

    def _undo_last_op(self):
        success, msg = self.file_manager.undo_last_operation()
        if success:
            QMessageBox.information(self, "復元完了", msg)
            self._start_scan(self.current_target_dir)
        else:
            QMessageBox.warning(self, "案内", msg)
