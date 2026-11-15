"""
main.py - CCCC (Clean, Compact, Care, Color) アプリケーション起動エントリーポイント
"""
import sys
import os
import ctypes
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from ui_main import MainWindow

def main():
    # Windowsタスクバーに独自アプリアイコンを正しく表示させるためのAppUserModelID設定
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CCCC.Organizer.Clover.1")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("CCCC")
    app.setStyle("Fusion")

    base_dir = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(base_dir, "assets", "cccc_icon.ico")
    if os.path.exists(ico_path):
        app.setWindowIcon(QIcon(ico_path))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
