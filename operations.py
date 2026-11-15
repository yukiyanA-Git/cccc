"""
operations.py - ファイル移動・ゴミ箱送り・保護ガード・永続履歴管理モジュール
"""
import os
import shutil
from typing import List, Dict, Optional, Tuple
try:
    from send2trash import send2trash
except ImportError:
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.WORD),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    def send2trash(path: str):
        FO_DELETE = 3
        FOF_ALLOWUNDO = 0x0040
        FOF_NOCONFIRMATION = 0x0010
        FOF_SILENT = 0x0004

        pFrom = os.path.abspath(path) + "\0\0"
        fileop = SHFILEOPSTRUCTW()
        fileop.wFunc = FO_DELETE
        fileop.pFrom = pFrom
        fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
        if result != 0:
            raise OSError(f"SHFileOperation failed with code {result}")

from analyzer import get_file_category, format_size
from settings_manager import SettingsManager


class OperationLog:
    def __init__(self, op_type: str, source_path: str, target_path: Optional[str] = None, history_id: Optional[str] = None):
        self.op_type = op_type
        self.source_path = source_path
        self.target_path = target_path
        self.history_id = history_id


class FileManager:
    def __init__(self, settings: Optional[SettingsManager] = None):
        self.settings = settings or SettingsManager()
        self.undo_stack: List[OperationLog] = []

    def move_to_trash(self, path: str) -> Tuple[bool, str]:
        """指定したファイルまたはフォルダをOSのゴミ箱へ移動（保護リストチェック付き）"""
        if not os.path.exists(path):
            return False, "対象のファイルまたはフォルダが見つかりません。"
        if self.settings.is_protected(path):
            return False, "🛡️ この項目は保護リストに登録されているため移動できません。"
        try:
            sz_str = ""
            if os.path.isfile(path):
                try:
                    sz_str = format_size(os.path.getsize(path))
                except OSError:
                    pass
            send2trash(path)
            hid = self.settings.add_history("TRASH", path, None, sz_str)
            self.undo_stack.append(OperationLog("TRASH", path, None, hid))
            return True, "ゴミ箱に移動しました。（Windowsのゴミ箱からいつでも復元可能です）"
        except Exception as e:
            return False, f"ゴミ箱への移動に失敗しました: {str(e)}"

    def move_file(self, src_path: str, dest_dir: str) -> Tuple[bool, str]:
        """ファイルを指定したフォルダへ移動（保護リストチェック＆履歴保存付き）"""
        if not os.path.exists(src_path):
            return False, "移動元のファイルが見つかりません。"
        if self.settings.is_protected(src_path):
            return False, "🛡️ この項目は保護リストに登録されているため移動できません。"
        try:
            sz_str = ""
            if os.path.isfile(src_path):
                try:
                    sz_str = format_size(os.path.getsize(src_path))
                except OSError:
                    pass

            os.makedirs(dest_dir, exist_ok=True)
            filename = os.path.basename(src_path)
            dest_path = os.path.join(dest_dir, filename)

            if os.path.exists(dest_path):
                base, ext = os.path.splitext(filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(dest_dir, f"{base}_{counter}{ext}")
                    counter += 1

            shutil.move(src_path, dest_path)
            hid = self.settings.add_history("MOVE", src_path, dest_path, sz_str)
            self.undo_stack.append(OperationLog("MOVE", src_path, dest_path, hid))
            return True, f"'{os.path.basename(dest_dir)}' フォルダへ移動しました。"
        except Exception as e:
            return False, f"移動に失敗しました: {str(e)}"

    def organize_by_category(self, parent_dir: str, file_paths: List[str]) -> Dict[str, int]:
        """ファイルをカテゴリ別に分類して自動移動"""
        category_folder_names = {
            "Images": "画像 (Images)",
            "Videos": "動画 (Videos)",
            "Audio": "音声 (Audio)",
            "Documents": "書類 (Documents)",
            "Archives": "圧縮ファイル (Archives)",
            "Installers": "インストーラー (Installers)",
            "Code": "プログラム・コード (Code)",
            "Temp/Cache": "一時ファイル (Temp)",
            "Other": "その他 (Other)"
        }

        results = {"success": 0, "failed": 0, "skipped": 0}

        for path in file_paths:
            if not os.path.isfile(path) or self.settings.is_protected(path):
                results["skipped"] += 1
                continue

            ext = os.path.splitext(path)[1]
            cat = get_file_category(ext)
            folder_name = category_folder_names.get(cat, "その他 (Other)")
            target_dir = os.path.join(parent_dir, folder_name)

            success, _ = self.move_file(path, target_dir)
            if success:
                results["success"] += 1
            else:
                results["failed"] += 1

        return results

    def undo_last_operation(self) -> Tuple[bool, str]:
        """直前の操作を取り消す"""
        if not self.undo_stack:
            return False, "元に戻す直前の操作履歴がありません。（履歴タブから過去の操作を確認できます）"

        op = self.undo_stack.pop()
        if op.op_type == "MOVE":
            if not op.target_path or not os.path.exists(op.target_path):
                return False, "移動先のファイルが見つかりません。"
            try:
                dest_dir = os.path.dirname(op.source_path)
                os.makedirs(dest_dir, exist_ok=True)
                shutil.move(op.target_path, op.source_path)
                if op.history_id:
                    self.settings.mark_restored(op.history_id)
                return True, f"'{os.path.basename(op.source_path)}' を元の場所に戻しました。"
            except Exception as e:
                return False, f"復元に失敗しました: {str(e)}"

        elif op.op_type == "TRASH":
            return False, "ゴミ箱へ移動したファイルは、Windows標準の『ごみ箱』を開いて右クリック『元に戻す』で復元できます。"

        return False, "対応していない操作です。"

    def restore_from_history(self, history_entry: Dict) -> Tuple[bool, str]:
        """操作履歴タイムラインから特定の移動操作を元の場所へ復元する"""
        if history_entry.get("restored"):
            return False, "この項目はすでに復元済みです。"

        op_type = history_entry.get("op_type")
        if op_type == "TRASH":
            return False, "ゴミ箱へ送った項目は、デスクトップの『ごみ箱』から『元に戻す』を実行してください。"

        src = history_entry.get("source_path")
        target = history_entry.get("target_path")
        if not src or not target or not os.path.exists(target):
            return False, "移動先のファイルがすでに存在しないか、別の場所へ移動されています。"

        try:
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.move(target, src)
            self.settings.mark_restored(history_entry.get("id", ""))
            return True, f"『{os.path.basename(src)}』を元の場所（{os.path.dirname(src)}）へ復元しました！"
        except Exception as e:
            return False, f"復元中にエラーが発生しました: {str(e)}"
