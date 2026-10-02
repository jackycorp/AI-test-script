# -*- coding: utf-8 -*-
"""
ARCC 自動化測試批次執行機器人 (Batch Test Runner)

測試流程說明：
1. 啟動時依序為每支測試程式獨立詢問其專屬的參數（防呆防空輸入）。
2. 配置完成後，等待使用者確認即可一鍵依序自動執行 7 個測試腳本。
3. 採用 Exception-Safety 機制，即使某個腳本失敗或異常，仍會繼續執行後續腳本。
4. 最終列印美觀的批次測試狀態匯總報告。
"""

import sys
import os
import time
import importlib
from datetime import datetime
from typing import TYPE_CHECKING

# 動態向上搜尋包含 utils 的根目錄，確保無論放置於哪一層子目錄均能正常引入 utils (遵循 SKILL.md Rule 14)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
current_dir_check = SCRIPT_DIR
ROOT_DIR = SCRIPT_DIR
while current_dir_check and os.path.dirname(current_dir_check) != current_dir_check:
    if os.path.exists(os.path.join(current_dir_check, "utils", "comm_helper.py")):
        ROOT_DIR = current_dir_check
        if current_dir_check not in sys.path:
            sys.path.insert(0, current_dir_check)
        break
    current_dir_check = os.path.dirname(current_dir_check)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# 虛擬環境自動跳轉防呆機制 (若以全域 Python 啟動，自動切換至專案 .venv 執行，遵循 SKILL.md Rule 15)
_venv_py = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(_venv_py) and os.path.normcase(sys.executable) != os.path.normcase(_venv_py):
    import subprocess
    sys.exit(subprocess.run([_venv_py] + sys.argv).returncode)

# 引入共用工具
try:
    from utils.comm_helper import (
        get_com_port,
        get_iteration_count,
        get_target_ip,
        get_delay_time,
        get_boot_wait_time,
        get_link_down_up_commands,
        get_power_on_off_commands
    )
except ImportError as e:
    print(f"無法載入 comm_helper: {e}")
    sys.exit(1)


def load_tclsh():
    """動態載入 Spirent TestCenter tclsh 物件 (遵循 SKILL.md Rule 5 Lazy Import)"""
    try:
        from utils.pythontool import tclsh
        return tclsh
    except Exception as e:
        print(f"警告: 無法載入 tclsh: {e}")
        return None


def main():
    print("=" * 70)
    print(" 🤖 ARCC 自動化批次測試執行機器人 (Batch Test Runner) 🤖")
    print("=" * 70)
    print("請依序為每支測試程式進行獨立的參數配置。設定完成後將一鍵啟動自動執行：\n")

    configs = {}

    # 1. Looping_Test_Couple_Decouple_analyze.py
    print("\n" + "-" * 60)
    print(" 📁 [1/7] Looping_Test_Couple_Decouple_analyze.py 參數設定")
    print("-" * 60)
    configs["Looping_Test_Couple_Decouple_analyze"] = {
        "com_port": get_com_port(),
        "iteration": get_iteration_count(),
        "delay_time": get_delay_time()
    }

    # 2. Looping_Test_Master change.py
    print("\n" + "-" * 60)
    print(" 📁 [2/7] Looping_Test_Master change.py 參數設定")
    print("-" * 60)
    configs["Looping_Test_Master change"] = {
        "iteration": get_iteration_count(),
        "target_ip": get_target_ip()
    }

    # 3. Looping_Test_Reboot.py
    print("\n" + "-" * 60)
    print(" 📁 [3/7] Looping_Test_Reboot.py 參數設定")
    print("-" * 60)
    configs["Looping_Test_Reboot"] = {
        "iteration": get_iteration_count(),
        "reboot_wait_time": get_boot_wait_time(),
        "target_ip": get_target_ip()
    }

    # 4. Performance_Test_Couple.py
    print("\n" + "-" * 60)
    print(" 📁 [4/7] Performance_Test_Couple.py 參數設定")
    print("-" * 60)
    configs["Performance_Test_Couple"] = {
        "com_port": get_com_port(),
        "iteration": get_iteration_count()
    }

    # 5. Performance_Test_Link down_up.py
    print("\n" + "-" * 60)
    print(" 📁 [5/7] Performance_Test_Link down_up.py 參數設定")
    print("-" * 60)
    ld_cmd, lu_cmd = get_link_down_up_commands()
    configs["Performance_Test_Link down_up"] = {
        "com_port": get_com_port(),
        "iteration": get_iteration_count(),
        "link_down_cmd": ld_cmd,
        "link_up_cmd": lu_cmd
    }

    # 6. Performance_Test_Power down_up.py
    print("\n" + "-" * 60)
    print(" 📁 [6/7] Performance_Test_Power down_up.py 參數設定")
    print("-" * 60)
    po_cmd, pf_cmd = get_power_on_off_commands()
    configs["Performance_Test_Power down_up"] = {
        "com_port": get_com_port(),
        "iteration": get_iteration_count(),
        "on_wait_time": get_boot_wait_time(),
        "power_on_cmd": po_cmd,
        "power_off_cmd": pf_cmd
    }

    # 7. Reliability_Test_Couple_Decouple.py
    print("\n" + "-" * 60)
    print(" 📁 [7/7] Reliability_Test_Couple_Decouple.py 參數設定")
    print("-" * 60)
    configs["Reliability_Test_Couple_Decouple"] = {
        "com_port": get_com_port(),
        "iteration": get_iteration_count(),
        "delay_time": get_delay_time()
    }

    print("\n" + "=" * 70)
    print(" 🚀 所有測試程式參數配置完成！即將開始依序執行批次測試！")
    print("=" * 70)
    input("請按 [Enter] 鍵以開始自動化批次測試流程...")

    tclsh = load_tclsh()

    # 定義依序執行的 7 個測試腳本清單與對應的模組名稱（支援帶空格之檔名）
    scripts_to_run = [
        ("Looping_Test_Couple_Decouple_analyze.py", "Looping_Test_Couple_Decouple_analyze"),
        ("Looping_Test_Master change.py", "Looping_Test_Master change"),
        ("Looping_Test_Reboot.py", "Looping_Test_Reboot"),
        ("Performance_Test_Couple.py", "Performance_Test_Couple"),
        ("Performance_Test_Link down_up.py", "Performance_Test_Link down_up"),
        ("Performance_Test_Power down_up.py", "Performance_Test_Power down_up"),
        ("Reliability_Test_Couple_Decouple.py", "Reliability_Test_Couple_Decouple")
    ]

    results = []

    for index, (display_name, module_name) in enumerate(scripts_to_run):
        print(f"\n🔥 [{index+1}/{len(scripts_to_run)}] 正在啟動測試: {display_name} ...")
        print("-" * 60)
        start_time = time.time()
        status = "PASS"
        err_msg = ""

        try:
            # 執行新腳本前，重置 Spirent Tcl 會話本地快取，防止專案/埠映射衝突
            if tclsh is not None:
                try:
                    tclsh.eval('stc::perform ResetConfig')
                    print("🧹 已成功重置 Spirent 本地會話快取設定")
                except Exception as re:
                    print(f"⚠️ Spirent 重置會話快取警告: {re}")

            # 透過 importlib 動態載入帶有空白的模組檔名
            test_module = importlib.import_module(module_name)
            cfg = configs[module_name]

            # 依據各子測試的個別配置，分發參數
            if module_name == "Looping_Test_Couple_Decouple_analyze":
                test_module.main(
                    com_port=cfg["com_port"],
                    iteration=cfg["iteration"],
                    delay_time=cfg["delay_time"]
                )
                
            elif module_name == "Looping_Test_Master change":
                test_module.main(
                    iteration=cfg["iteration"],
                    target_ip=cfg["target_ip"]
                )
                
            elif module_name == "Looping_Test_Reboot":
                test_module.main(
                    iteration=cfg["iteration"],
                    reboot_wait_time=cfg["reboot_wait_time"],
                    target_ip=cfg["target_ip"]
                )
                
            elif module_name == "Performance_Test_Couple":
                test_module.main(
                    com_port=cfg["com_port"],
                    iteration=cfg["iteration"]
                )
                
            elif module_name == "Performance_Test_Link down_up":
                test_module.main(
                    com_port=cfg["com_port"],
                    iteration=cfg["iteration"],
                    link_down_cmd=cfg["link_down_cmd"],
                    link_up_cmd=cfg["link_up_cmd"]
                )
                
            elif module_name == "Performance_Test_Power down_up":
                test_module.main(
                    com_port=cfg["com_port"],
                    iteration=cfg["iteration"],
                    on_wait_time=cfg["on_wait_time"],
                    power_on_cmd=cfg["power_on_cmd"],
                    power_off_cmd=cfg["power_off_cmd"]
                )
                
            elif module_name == "Reliability_Test_Couple_Decouple":
                test_module.main(
                    com_port=cfg["com_port"],
                    iteration=cfg["iteration"],
                    delay_time=cfg["delay_time"]
                )

        except SystemExit as se:
            # 捕捉 sys.exit()，判定是否為異常代碼結束
            if se.code != 0 and se.code is not None:
                status = "FAIL"
                err_msg = f"SystemExit (Code: {se.code})"
            else:
                status = "PASS"
        except Exception as e:
            status = "ERROR"
            err_msg = str(e)
            print(f"❌ 腳本執行中發生異常錯誤: {e}")

        elapsed_time = time.time() - start_time
        results.append({
            "name": display_name,
            "status": status,
            "duration": f"{elapsed_time:.1f}s",
            "error": err_msg
        })
        print(f"\n🏁 [{index+1}/{len(scripts_to_run)}] 執行結束: {display_name} | 結果: {status} (耗時: {elapsed_time:.1f} 秒)")
        print("=" * 70)

    # 列印最終的整合測試報告
    print("\n" + "=" * 80)
    print(" 🎉 ARCC 批次自動化測試執行結束！整合彙總報告如下：")
    print("=" * 80)
    print(f"{'測試腳本名稱':<45}{'測試狀態':<15}{'執行耗時':<10}")
    print("-" * 80)
    
    for r in results:
        if r["status"] == "PASS":
            status_str = "🟢 PASS"
        elif r["status"] == "FAIL":
            status_str = "🔴 FAIL"
        else:
            status_str = "⚠️ ERROR"
            
        print(f"{r['name']:<45}{status_str:<15}{r['duration']:<10}")
        if r["error"]:
            print(f"   └─ 錯誤原因: {r['error']}")
            
    print("=" * 80)
    print("所有測試報告已記錄，感謝使用 ARCC 自動化機器人！\n")


if __name__ == "__main__":
    main()
