"""
cleaner.py - システム・アプリキャッシュの検出・安全クリアモジュール
"""
import os
import shutil
from typing import List, Dict, Tuple
from analyzer import format_size
from operations import send2trash

class CacheTarget:
    def __init__(self, name: str, description: str, paths: List[str], is_safe: bool = True):
        self.name = name
        self.description = description
        self.paths = paths
        self.is_safe = is_safe
        self.total_size = 0
        self.file_count = 0
        self.scan_errors = 0

def get_system_cache_targets() -> List[CacheTarget]:
    user_temp = os.environ.get("TEMP", "")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    
    targets = [
        CacheTarget(
            name="ユーザー一時ファイル (User Temp)",
            description="アプリの動作中やインストーラーによって作成された一時データです。削除しても問題ありません。",
            paths=[user_temp] if user_temp else []
        ),
        CacheTarget(
            name="Windows エクスプローラー サムネイルキャッシュ",
            description="画像や動画の縮小版プレビューのキャッシュです。削除しても再度表示時に自動生成されます。",
            paths=[os.path.join(local_app_data, "Microsoft", "Windows", "Explorer")] if local_app_data else []
        ),
        CacheTarget(
            name="Google Chrome / Edge キャッシュ",
            description="Webサイトの読み込みを速くするための一時データです。削除するとブラウザの容量を大幅に削減できます。",
            paths=[
                os.path.join(local_app_data, "Google", "Chrome", "User Data", "Default", "Cache"),
                os.path.join(local_app_data, "Microsoft", "Edge", "User Data", "Default", "Cache")
            ] if local_app_data else []
        ),
        CacheTarget(
            name="Windows プレビュー / クラッシュダンプ",
            description="アプリが異常終了した際に記録されるエラーログ・ダンプファイルです。",
            paths=[
                os.path.join(local_app_data, "CrashDumps")
            ] if local_app_data else []
        )
    ]
    return targets

def scan_cache_target(target: CacheTarget):
    """キャッシュターゲット内のファイル容量と件数を計算"""
    total_size = 0
    file_count = 0
    errors = 0

    for path in target.paths:
        if not os.path.exists(path):
            continue
        try:
            for root, dirs, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        total_size += sz
                        file_count += 1
                    except Exception:
                        errors += 1
        except Exception:
            errors += 1

    target.total_size = total_size
    target.file_count = file_count
    target.scan_errors = errors

def clean_cache_target(target: CacheTarget, use_trash: bool = True) -> Tuple[int, int, int]:
    """キャッシュをクリア（削除またはゴミ箱送り）"""
    deleted_count = 0
    freed_bytes = 0
    failed_count = 0

    for path in target.paths:
        if not os.path.exists(path):
            continue
        try:
            for root, dirs, files in os.walk(path, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                        if use_trash:
                            send2trash(fp)
                        else:
                            os.remove(fp)
                        deleted_count += 1
                        freed_bytes += sz
                    except Exception:
                        failed_count += 1
                for d in dirs:
                    dp = os.path.join(root, d)
                    try:
                        os.rmdir(dp)
                    except Exception:
                        pass
        except Exception:
            failed_count += 1

    return deleted_count, freed_bytes, failed_count
