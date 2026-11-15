"""
analyzer.py - ファイル・フォルダ解析、安全性判定、アプリ残骸検出、重複ファイル検出モジュール
"""
import os
import time
import hashlib
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Callable

try:
    import winreg
except ImportError:
    winreg = None


class SafetyLevel:
    SAFE = "SAFE"            # 🟢 削除・整理推奨
    CAUTION = "CAUTION"      # 🟡 注意（ユーザーデータ）
    DANGER = "DANGER"        # 🔴 危険（システム・設定・使用中）
    PROTECTED = "PROTECTED"  # 🛡️ 保護リスト登録済み


# カテゴリ定義
CATEGORIES = {
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".ico", ".tiff", ".heic"],
    "Videos": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv", ".m4v"],
    "Audio": [".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma"],
    "Documents": [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".csv", ".md", ".rtf"],
    "Archives": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"],
    "Installers": [".exe", ".msi", ".iso", ".dmg", ".msix"],
    "Code": [".py", ".js", ".ts", ".html", ".css", ".json", ".yaml", ".yml", ".c", ".cpp", ".java", ".go", ".rs", ".cs"],
    "Temp/Cache": [".tmp", ".temp", ".log", ".bak", ".cache", ".old", ".dmp", ".crdownload", ".part"],
    "System": [".dll", ".sys", ".ini", ".bat", ".cmd", ".reg", ".lnk", ".drv"]
}

# 削除危険なキーワード
DANGEROUS_NAMES = {
    "windows", "system32", "syswow64", "program files", "program files (x86)",
    "microsoft", "windowsapps", ".git", ".svn", "boot", "recovery",
    "pagefile.sys", "hiberfil.sys", "swapfile.sys", "ntuser.dat"
}

# 一時・キャッシュとみなせるフォルダ名
CACHE_FOLDER_NAMES = {
    "cache", "caches", "temp", "tmp", "logs", "crashdumps", "thumbnails",
    "cacheddata", ".cache", "gpucache", "code cache", "shader_cache",
    "squirreltemp", "npm-cache", "pip"
}

# 有名アプリ・謎フォルダの正体解説辞書
KNOWN_FOLDER_DICTIONARY = {
    "discord": ("Discord（チャットアプリ）", "チャット履歴のキャッシュや設定データです。Cacheフォルダ内は削除しても再生成されます。"),
    "slack": ("Slack（ビジネスチャット）", "ワークスペースのキャッシュと設定データです。"),
    "zoom": ("Zoom（Web会議アプリ）", "会議の録画データやアプリ構成データが含まれます。"),
    "line": ("LINE（PC版アプリ）", "トークの画像キャッシュや通話データが含まれます。"),
    "code": ("Visual Studio Code", "エディタの設定や拡張機能、キャッシュデータです。"),
    ".vscode": ("Visual Studio Code 拡張・設定", "インストールした拡張機能や設定が入っています。開発中なら残してください。"),
    "google": ("Google Chrome 関連データ", "ブックマークやログイン情報、ブラウザキャッシュが含まれます。"),
    "mozilla": ("Firefox ブラウザ関連データ", "プロファイルやキャッシュデータが含まれます。"),
    "steam": ("Steam（PCゲームプラットフォーム）", "ゲームデータやセーブデータ、シェーダーキャッシュが含まれます。"),
    "adobe": ("Adobe（Acrobat / Creative Cloud）", "PDF閲覧ソフトやクリエイティブツールの設定・メディアキャッシュです。"),
    "nvidia": ("NVIDIA グラフィックス関連", "GPUドライバーのキャッシュやインストーラーデータです。"),
    "node_modules": ("Node.js パッケージ群", "プログラム開発用のライブラリフォルダです。容量が非常に大きくなりやすいですが、`npm install`で再生成可能です。"),
    "__pycache__": ("Python コンパイルキャッシュ", "Pythonが自動生成する高速化用キャッシュです。削除しても実行時に自動再生成されます。"),
    "pip": ("Python パッケージキャッシュ", "pip install 時にダウンロードされたキャッシュです。削除しても問題ありません。"),
    "squirreltemp": ("アプリ更新の一時データ", "DiscordやTeamsなどの自動アップデート時に作られた一時ファイルです。削除して問題ありません。"),
    "crashdumps": ("アプリのエラーダンプ", "ソフトが強制終了した際の診断用記録です。削除しても安全です。")
}

_INSTALLED_APPS_CACHE: Optional[Set[str]] = None


def get_installed_app_keywords() -> Set[str]:
    """Windowsレジストリから現在インストールされているアプリ名・発行元のキーワード集合を取得"""
    global _INSTALLED_APPS_CACHE
    if _INSTALLED_APPS_CACHE is not None:
        return _INSTALLED_APPS_CACHE

    keywords = set()
    if winreg is None:
        _INSTALLED_APPS_CACHE = keywords
        return keywords

    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for root_key, sub_path in reg_paths:
        try:
            with winreg.OpenKey(root_key, sub_path) as key:
                num_subkeys = winreg.QueryInfoKey(key)[0]
                for i in range(num_subkeys):
                    try:
                        sub_name = winreg.EnumKey(key, i)
                        with winreg.OpenKey(key, sub_name) as sub_key:
                            for val_name in ["DisplayName", "Publisher", "InstallLocation"]:
                                try:
                                    val, _ = winreg.QueryValueEx(sub_key, val_name)
                                    if val and isinstance(val, str):
                                        for token in val.lower().replace("\\", " ").replace("/", " ").split():
                                            if len(token) >= 3:
                                                keywords.add(token)
                                except OSError:
                                    pass
                    except OSError:
                        continue
        except OSError:
            continue

    _INSTALLED_APPS_CACHE = keywords
    return keywords


def format_size(size_bytes: int) -> str:
    """バイト数を人間が読みやすい形式に変換"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def get_file_category(extension: str) -> str:
    ext = extension.lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "Other"


def is_file_locked(filepath: str) -> bool:
    """ファイルが他のプロセスによってロック（使用中）されているかを検査"""
    if not os.path.isfile(filepath):
        return False
    try:
        with open(filepath, "a", encoding="utf-8"):
            pass
        return False
    except (IOError, PermissionError):
        return True
    except Exception:
        return False


def analyze_folder_contents(folder_path: str) -> Dict:
    """フォルダの中身を走査して詳細（サイズ、カテゴリ内訳、ファイル数、最新日付など）を集計"""
    total_size = 0
    file_count = 0
    folder_count = 0
    category_counts = {cat: 0 for cat in CATEGORIES.keys()}
    category_counts["Other"] = 0
    category_sizes = {cat: 0 for cat in CATEGORIES.keys()}
    category_sizes["Other"] = 0

    latest_mtime = 0
    oldest_mtime = float("inf")
    sample_files = []

    try:
        for root, dirs, files in os.walk(folder_path):
            folder_count += len(dirs)
            for file in files:
                file_count += 1
                fp = os.path.join(root, file)
                try:
                    stat = os.stat(fp)
                    sz = stat.st_size
                    mtime = stat.st_mtime
                    total_size += sz

                    if mtime > latest_mtime:
                        latest_mtime = mtime
                    if mtime < oldest_mtime:
                        oldest_mtime = mtime

                    ext = os.path.splitext(file)[1].lower()
                    cat = get_file_category(ext)
                    category_counts[cat] += 1
                    category_sizes[cat] += sz

                    if len(sample_files) < 15:
                        sample_files.append({
                            "name": file,
                            "path": fp,
                            "size": sz,
                            "category": cat
                        })
                except (PermissionError, FileNotFoundError, OSError):
                    continue
    except Exception:
        pass

    if oldest_mtime == float("inf"):
        oldest_mtime = 0

    return {
        "total_size": total_size,
        "formatted_size": format_size(total_size),
        "file_count": file_count,
        "folder_count": folder_count,
        "category_counts": category_counts,
        "category_sizes": category_sizes,
        "latest_date": datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%d %H:%M") if latest_mtime > 0 else "不明",
        "oldest_date": datetime.fromtimestamp(oldest_mtime).strftime("%Y-%m-%d %H:%M") if oldest_mtime > 0 else "不明",
        "sample_files": sample_files
    }


class ItemInfo:
    """走査対象のアイテム（ファイルまたはフォルダ）の情報保持クラス"""
    def __init__(self, path: str, is_protected: bool = False):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(self.path) or self.path
        self.is_dir = os.path.isdir(self.path)
        self.extension = os.path.splitext(self.name)[1].lower() if not self.is_dir else ""
        self.category = "Folder" if self.is_dir else get_file_category(self.extension)

        self.size = 0
        self.formatted_size = "0 B"
        self.mtime = 0
        self.formatted_mtime = ""
        self.is_locked = False
        self.is_orphan_candidate = False

        self.safety_level = SafetyLevel.CAUTION
        self.safety_score = 50
        self.description = ""
        self.explanation = ""
        self.tags = []

        self.folder_summary: Optional[Dict] = None
        self._evaluate(is_protected)

    def _evaluate(self, is_protected: bool):
        try:
            stat = os.stat(self.path)
            self.mtime = stat.st_mtime
            self.formatted_mtime = datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M")
            if not self.is_dir:
                self.size = stat.st_size
                self.formatted_size = format_size(self.size)
                self.is_locked = is_file_locked(self.path)
            else:
                self.formatted_size = "クリックで計測"
        except Exception:
            self.formatted_size = "アクセス不可"

        now = time.time()
        days_old = (now - self.mtime) / (24 * 3600) if self.mtime > 0 else 0
        lower_name = self.name.lower()
        lower_path = self.path.lower()

        # 0. ホワイトリスト（保護）チェック
        if is_protected:
            self.safety_level = SafetyLevel.PROTECTED
            self.safety_score = 0
            self.tags.append("🛡️ 保護中")
            self.description = "ユーザーによって保護リストに登録されている大切な項目です。"
            self.explanation = "誤って削除や移動がされないようロックされています。整理対象にする場合は保護を解除してください。"
            return

        # 1. 既知の有名アプリ・フォルダ辞書照合
        matched_known = None
        for key_sig, (app_title, app_desc) in KNOWN_FOLDER_DICTIONARY.items():
            if lower_name == key_sig or key_sig in lower_name:
                matched_known = (app_title, app_desc)
                break

        # 2. 危険判定（システムファイル・重要フォルダ）
        if lower_name in DANGEROUS_NAMES:
            self.safety_level = SafetyLevel.DANGER
            self.safety_score = 10
            self.tags.append("システム・重要データ")
            self.description = "Windowsや主要システムの動作に不可欠なフォルダ/ファイルです。"
            self.explanation = "削除するとOSやソフトが起動しなくなる危険があります。そのまま保持してください。"
            return

        if self.is_locked:
            self.safety_level = SafetyLevel.DANGER
            self.safety_score = 20
            self.tags.append("🔒 使用中ロック")
            self.description = "現在別のアプリケーションが開いて使用中です。"
            self.explanation = "稼働中のアプリが利用しているため削除や移動はできません。"
            return

        if self.extension in CATEGORIES["System"] and self.extension != ".lnk":
            self.safety_level = SafetyLevel.DANGER
            self.safety_score = 15
            self.tags.append("システム設定・DLL")
            self.description = "プログラムの動作・設定ファイルです。"
            self.explanation = "ソフトウェアの稼働に必要な構成ファイルです。手動での削除は避けてください。"
            return

        # 3. フォルダの場合
        if self.is_dir:
            try:
                children = os.listdir(self.path)
                if len(children) == 0:
                    self.safety_level = SafetyLevel.SAFE
                    self.safety_score = 95
                    self.tags.append("空フォルダ")
                    self.description = "中身が空っぽのフォルダです。"
                    self.explanation = "ファイルやサブフォルダが1つも入っていません。削除してもデータ損失はありません。"
                    return
            except PermissionError:
                self.safety_level = SafetyLevel.DANGER
                self.description = "システム保護によりアクセス権限がありません。"
                return

            # キャッシュフォルダ判定
            if lower_name in CACHE_FOLDER_NAMES or any(cname in lower_name for cname in ["cache", "temp", "tmp", "__pycache__"]):
                self.safety_level = SafetyLevel.SAFE
                self.safety_score = 90
                self.tags.append("キャッシュ・一時データ")
                self.description = matched_known[0] if matched_known else "アプリの一時キャッシュフォルダです。"
                self.explanation = matched_known[1] if matched_known else "高速表示などのために一時保存されたデータです。削除しても必要に応じて自動再生成されます。"
                return

            # AppData 内のアンインストール済みアプリ残骸（孤児フォルダ）チェック
            if "appdata" in lower_path and not matched_known:
                installed_kw = get_installed_app_keywords()
                tokens = [t for t in lower_name.replace("-", " ").replace("_", " ").split() if len(t) >= 3]
                is_installed = any(t in installed_kw for t in tokens) if tokens else True
                if not is_installed and days_old > 45:
                    self.is_orphan_candidate = True
                    self.safety_level = SafetyLevel.SAFE
                    self.safety_score = 80
                    self.tags.append(f"🕵️‍♂️ アプリ残骸候補 ({int(days_old)}日間未更新)")
                    self.description = "現在インストールされているアプリ一覧に一致しない古いフォルダです。"
                    self.explanation = "過去にアンインストールしたソフトが残していった設定やデータの残骸（孤児フォルダ）である可能性が高いです。右側の内訳を確認して不要ならゴミ箱へ移動できます。"
                    return

            if matched_known:
                self.safety_level = SafetyLevel.CAUTION
                self.safety_score = 55
                self.tags.append(matched_known[0])
                self.description = f"【正体】{matched_known[0]} の関連フォルダです。"
                self.explanation = matched_known[1]
                return

            self.safety_level = SafetyLevel.CAUTION
            self.safety_score = 50
            self.tags.append("フォルダ")
            self.description = "ファイルが含まれている一般フォルダです。"
            self.explanation = "右側のドーナツグラフと内訳プレビューで中身を確認してから整理・移動を行ってください。"
            return

        # 4. ファイルの場合の安全判定
        if self.category == "Temp/Cache" or lower_name.startswith("~$") or lower_name.endswith(".tmp"):
            self.safety_level = SafetyLevel.SAFE
            self.safety_score = 95
            self.tags.append("一時ファイル・ログ")
            self.description = "作業用の一時保存データまたはログファイルです。"
            self.explanation = "アプリ終了後に残った一時データの可能性が高く、削除しても問題ありません。"
            return

        if self.category == "Installers":
            if days_old > 14:
                self.safety_level = SafetyLevel.SAFE
                self.safety_score = 90
                self.tags.append(f"古いインストーラー ({int(days_old)}日前)")
                self.description = "ダウンロード後しばらく経過したセットアップ用ファイルです。"
                self.explanation = "アプリのインストールがすでに完了していれば、このインストーラー自体は削除して大容量を空けられます。"
            else:
                self.safety_level = SafetyLevel.CAUTION
                self.safety_score = 65
                self.tags.append("最近のインストーラー")
                self.description = "最近ダウンロードされたセットアップファイルです。"
                self.explanation = "すでにインストール済みであればゴミ箱へ移動して構いません。"
            return

        if self.category in ["Images", "Videos", "Audio", "Documents"]:
            self.safety_level = SafetyLevel.CAUTION
            self.safety_score = 60
            self.tags.append(self.category)
            self.description = f"ユーザーの{self.category}ファイルです。"
            self.explanation = "写真や書類などの個人データです。不要なものを整理するか、『種類別に自動仕分け』で専用フォルダにまとめるとスッキリします。"
            return

        if self.category == "Archives":
            self.safety_level = SafetyLevel.CAUTION
            self.safety_score = 70
            self.tags.append("圧縮ファイル (ZIP等)")
            self.description = "まとめられた圧縮アーカイブです。"
            self.explanation = "すでに解凍して中身を取り出し終わっている場合は、元のZIPファイルは削除して容量を節約できます。"
            return

        self.safety_level = SafetyLevel.CAUTION
        self.safety_score = 50
        self.tags.append("ファイル")
        self.description = f"拡張子: {self.extension or 'なし'} のファイルです。"
        self.explanation = "右側のプレビューや最終更新日を確認の上、不要な場合はゴミ箱へ移動してください。"

    def load_folder_details(self):
        """フォルダの詳細集計を実行"""
        if self.is_dir and self.folder_summary is None:
            self.folder_summary = analyze_folder_contents(self.path)
            self.size = self.folder_summary["total_size"]
            self.formatted_size = self.folder_summary["formatted_size"]


# =========================================================
# 重複ファイル検出エンジン（サイズ → 先頭ハッシュ → 完全ハッシュ）
# =========================================================
def _hash_file(filepath: str, first_chunk_only: bool = False) -> Optional[str]:
    hasher = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            if first_chunk_only:
                chunk = f.read(4096)
                hasher.update(chunk)
            else:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    hasher.update(chunk)
        return hasher.hexdigest()
    except (PermissionError, FileNotFoundError, OSError):
        return None


def find_duplicate_files(target_dir: str, min_size_bytes: int = 1024, max_depth: int = 3) -> List[Dict]:
    """
    指定ディレクトリ内の完全一致する重複ファイルを高速検出する。
    戻り値: [{"hash": str, "size": int, "formatted_size": str, "files": [ {"path": str, "name": str, "mtime_str": str} ]}, ...]
    """
    size_groups: Dict[int, List[str]] = defaultdict(list)
    base_depth = target_dir.rstrip(os.sep).count(os.sep)

    for root, dirs, files in os.walk(target_dir):
        current_depth = root.rstrip(os.sep).count(os.sep) - base_depth
        if current_depth >= max_depth:
            dirs[:] = []  # 深すぎる階層はスキップ

        # システム・隠しフォルダは除外
        dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in DANGEROUS_NAMES]

        for f in files:
            fp = os.path.join(root, f)
            try:
                sz = os.path.getsize(fp)
                if sz >= min_size_bytes:
                    size_groups[sz].append(fp)
            except OSError:
                continue

    # 同じサイズのファイルが2つ以上あるものだけハッシュ計算
    candidates_by_size = {sz: paths for sz, paths in size_groups.items() if len(paths) >= 2}

    duplicate_groups = []
    for sz, paths in candidates_by_size.items():
        # Step 1: 先頭4KBのハッシュで絞り込み
        quick_groups: Dict[str, List[str]] = defaultdict(list)
        for p in paths:
            h_quick = _hash_file(p, first_chunk_only=True)
            if h_quick:
                quick_groups[h_quick].append(p)

        # Step 2: 先頭4KBも一致したものだけフルハッシュ計算
        for _, q_paths in quick_groups.items():
            if len(q_paths) < 2:
                continue
            full_groups: Dict[str, List[str]] = defaultdict(list)
            for p in q_paths:
                h_full = _hash_file(p, first_chunk_only=False)
                if h_full:
                    full_groups[h_full].append(p)

            for h_val, dup_paths in full_groups.items():
                if len(dup_paths) >= 2:
                    # 更新日時の古い順（オリジナルを先頭）に並べる
                    file_records = []
                    for dp in dup_paths:
                        try:
                            mt = os.path.getmtime(dp)
                            mt_str = datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
                        except OSError:
                            mt = 0
                            mt_str = "不明"
                        file_records.append({
                            "path": dp,
                            "name": os.path.basename(dp),
                            "mtime": mt,
                            "mtime_str": mt_str
                        })
                    file_records.sort(key=lambda x: x["mtime"])
                    duplicate_groups.append({
                        "hash": h_val[:12],
                        "size": sz,
                        "formatted_size": format_size(sz),
                        "wasted_bytes": sz * (len(file_records) - 1),
                        "files": file_records
                    })

    # 無駄になっている容量が大きい順にソート
    duplicate_groups.sort(key=lambda g: g["wasted_bytes"], reverse=True)
    return duplicate_groups
