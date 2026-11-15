"""
maintenance.py - ドライブ情報取得・デフラグ/最適化モジュール
"""
import os
import subprocess
import psutil
from typing import List, Dict, Tuple

def get_disk_drives() -> List[Dict]:
    """PCに接続されているローカルドライブの空き容量と使用率を取得"""
    drives = []
    partitions = psutil.disk_partitions(all=False)
    for part in partitions:
        if 'cdrom' in part.opts or part.fstype == '':
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
            drives.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent
            })
        except PermissionError:
            continue
    return drives

def launch_windows_defrag_gui():
    """Windows標準の『ドライブのデフラグと最適化』ツールを起動"""
    try:
        subprocess.Popen("dfrgui.exe", shell=True)
        return True, "Windows標準の最適化ツールを起動しました。"
    except Exception as e:
        return False, f"起動に失敗しました: {str(e)}"

def analyze_drive_fragmentation(drive_letter: str) -> Tuple[bool, str]:
    """指定ドライブの断片化状況をコマンドで分析 (defrag C: /A)"""
    try:
        cmd = f"defrag {drive_letter}: /A"
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True, timeout=30)
        return True, result.stdout if result.stdout else "分析が完了しました。"
    except Exception as e:
        return False, f"分析中にエラーが発生しました: {str(e)}"
