"""
test_logic.py - 新機能（パステルテーマ・保護リスト・重複検出・履歴復元・安全性診断）の自動テスト
"""
import os
import shutil
import time
from analyzer import ItemInfo, SafetyLevel, find_duplicate_files
from operations import FileManager
from settings_manager import SettingsManager, THEMES

def run_tests():
    test_dir = os.path.join(os.path.dirname(__file__), "test_sandbox")
    if os.path.exists(test_dir):
        shutil.rmtree(test_dir)
    os.makedirs(test_dir, exist_ok=True)

    settings = SettingsManager()
    # デフォルトテーマがパステル系かつ黒文字であることを確認
    assert "pastel_blue" in THEMES
    assert THEMES["pastel_blue"]["text_main"] == "#111827"

    # 1. 重複ファイル作成と検出テスト
    dup1 = os.path.join(test_dir, "report_original.txt")
    dup2 = os.path.join(test_dir, "report_copy.txt")
    diff = os.path.join(test_dir, "different.txt")
    content_same = "A" * 2048  # 2KB
    with open(dup1, "w", encoding="utf-8") as f:
        f.write(content_same)
    with open(dup2, "w", encoding="utf-8") as f:
        f.write(content_same)
    with open(diff, "w", encoding="utf-8") as f:
        f.write("B" * 2048)

    dup_groups = find_duplicate_files(test_dir, min_size_bytes=512)
    assert len(dup_groups) == 1
    assert len(dup_groups[0]["files"]) == 2
    print("Duplicate detection OK:", len(dup_groups), "group found.")

    # 2. ホワイトリスト（保護リスト）テスト
    protected_file = os.path.join(test_dir, "important_doc.pdf")
    with open(protected_file, "w", encoding="utf-8") as f:
        f.write("important data")

    settings.add_to_whitelist(protected_file)
    assert settings.is_protected(protected_file) is True
    info_prot = ItemInfo(protected_file, is_protected=settings.is_protected(protected_file))
    assert info_prot.safety_level == SafetyLevel.PROTECTED

    fm = FileManager(settings)
    ok, msg = fm.move_to_trash(protected_file)
    assert ok is False  # 保護されているので削除ブロックされる
    assert os.path.exists(protected_file)
    settings.remove_from_whitelist(protected_file)
    print("Whitelist protection guard OK.")

    # 3. 仕分け移動 & 履歴タイムラインからの復元テスト
    res = fm.organize_by_category(test_dir, [protected_file])
    assert res["success"] == 1
    assert not os.path.exists(protected_file)

    latest_hist = settings.history[0]
    ok_rest, msg_rest = fm.restore_from_history(latest_hist)
    assert ok_rest is True
    assert os.path.exists(protected_file)
    print("History timeline restore OK.")

    shutil.rmtree(test_dir)
    print("ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
