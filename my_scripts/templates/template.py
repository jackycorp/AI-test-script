# -*- coding: utf-8 -*-
"""
名稱: 測試腳本標準樣板 (template.py)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 「目標 IP / COM 埠」、「執行次數」與「等待延遲時間」等防呆輸入。
  1.2 讀取測試參數表 scenarios.csv（支援多場景輪詢與路徑自動搜尋）。
[Phase 2] 儀器與環境配置 (Spirent & Serial/Telnet)
  2.1 配置儀器連線 (如 Spirent TestCenter 預約 Port 與 Stream，若無使用可略過)。
  2.2 初始化 Serial 或 Telnet 通訊連線並發送前置穩定指令。
  2.3 建立本次測試的日誌檔案 (test result/<當前測試目錄>/result.txt)。
[Phase 3] 自動化測試迴圈
  3.1 Ping DUT 確認設備在線。
  3.2 發送測試流量或下達測試指令。
  3.3 等待收斂延遲時間。
  3.4 獲取測試數據並判定測試結果。
  3.5 記錄該輪測試結果至 test result 日誌與終端機。
  3.6 清除結果統計或重置連線，進入下一輪。

使用說明：
1. 複製本檔案（templates/template.py）至 my_scripts/ 並更名為您的測試腳本名稱（如 my_new_test.py）。
2. 詳細各模組函式規格與禁止事項請務必參閱根目錄下的 SKILL.md。
"""

import sys
import os
import csv
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# ========================================================
# 專案路徑動態相容設定 (確保深層子資料夾均可成功引用 utils)
# ========================================================
for parent in Path(__file__).resolve().parents:
    if (parent / "utils").is_dir():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break

try:
    from utils.comm_helper import (
        get_com_port,
        get_iteration_count,
        get_delay_time,
        get_boot_wait_time,
        get_target_ip,
        comm_CMD,
        comm_TELNET,
        check_ping,
        Pingfunc,
        get_result_dir,
        get_result_log_path
    )
    # 若需使用 Spirent 測試儀，請取消下行註解：
    # from utils.pythontool import StartGenerator, StopGenerator, getdata, Disconnect
except ImportError as err:
    print(f"[錯誤] 無法載入 utils 共用庫: {err}")
    print("請確認已在專案根目錄執行過 setup.bat 或路徑結構正確。")
    sys.exit(1)


####################### 輔助函式 ###########################

def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """讀取 CSV 測試參數表 (支援多個常見預設路徑自動搜尋)"""
    script_dir = Path(__file__).resolve().parent
    candidates = [
        Path(csv_path),
        script_dir / csv_path,
        script_dir / "scenarios.csv",
        Path.cwd() / csv_path,
    ]
    resolved_path = None
    for cand in candidates:
        if cand.exists():
            resolved_path = cand
            break

    scenarios = []
    if resolved_path:
        with open(resolved_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                scenarios.append({k.strip(): v.strip() for k, v in row.items() if k})
        print(f"成功載入參數表 ({len(scenarios)} 筆場景): {resolved_path}")
    else:
        print(f"[提示] 未發現參數表 ({csv_path})，將使用單一目標配置執行。")
    return scenarios




####################### 主程式 ###########################

def main():
    script_name = Path(__file__).stem
    print("=" * 60)
    print(f"啟動測試腳本: {script_name}")
    print("=" * 60)

    # ----------------------------------------------------
    # [Phase 1] 參數蒐集與初始化
    # ----------------------------------------------------
    # 1.1 防呆輸入參數 (執行次數、等待時間、目標 IP / COM 埠)
    iterations = get_iteration_count()
    delay_time = get_delay_time()
    target_ip = get_target_ip()

    # 1.2 讀取測試參數表 scenarios.csv (若無可略過)
    scenarios = load_scenarios_from_csv("scenarios.csv")

    # ----------------------------------------------------
    # [Phase 2] 儀器與環境配置
    # ----------------------------------------------------
    # 2.1 配置儀器預約 (如 Spirent TestCenter，若無使用可略过)
    # project, port, r1, r2, r3 = setup_spirent(chassisAddr, slotPortlist)

    # 2.2 初始化通訊連線 (Telnet 或 Serial)
    tn_client = None  # 若使用 Telnet，請透過 telnetlib 連線並建立物件
    ser_client = None # 若使用 Serial，請透過 serial.Serial 建立物件

    # 2.3 建立本次測試的集中式日誌檔案 (test result/<當前目錄>_result/result.txt)
    log_path = get_result_log_path(__file__, "result.txt")
    print(f"測試次數: {iterations}")
    print(f"日誌存放路徑: {log_path}\n")

    try:
        with open(log_path, "w", encoding="utf-8") as f_log:
            f_log.write(f"測試開始時間: {datetime.now()}\n")
            f_log.write(f"目標 IP: {target_ip}\n")
            f_log.write(f"測試次數: {iterations}\n")
            f_log.write("=" * 60 + "\n\n")

            # ----------------------------------------------------
            # [Phase 3] 自動化測試迴圈
            # ----------------------------------------------------
            for current_round in range(1, iterations + 1):
                round_msg = f"--- [Round {current_round}/{iterations}] ---"
                print(round_msg)
                f_log.write(round_msg + "\n")

                # 3.1 Ping DUT 確認設備在線
                is_alive = check_ping(target_ip, times=1)
                if not is_alive:
                    fail_msg = f"Round {current_round}: Ping {target_ip} 失敗！"
                    print(fail_msg)
                    f_log.write(fail_msg + "\n")
                    continue

                # 3.2 發送測試流量或下達測試指令 (依需求調用 comm_CMD 或 comm_TELNET)
                # comm_CMD(ser_client, b"show version\r")

                # 3.3 等待收斂延遲時間
                time.sleep(delay_time)

                # 3.4 獲取測試數據並判定測試結果
                # loss_rate, drop_count = ...
                test_passed = True

                # 3.5 記錄該輪測試結果至 test result 日誌與終端機
                status_str = "PASS" if test_passed else "FAIL"
                result_line = f"Round {current_round}: 測試結果 = {status_str}"
                print(result_line)
                f_log.write(result_line + "\n")

                # 3.6 清除結果統計或重置連線，進入下一輪
                time.sleep(1)

            f_log.write(f"\n測試結束時間: {datetime.now()}\n")

    except KeyboardInterrupt:
        print("\n[使用者中斷] 測試已手動停止。")
    except Exception as e:
        print(f"\n[執行異常] 錯誤訊息: {e}")
    finally:
        # 資源安全釋放 (妥善關閉開啟之連線)
        if tn_client:
            try:
                tn_client.close()
                print("Telnet 連線已安全釋放。")
            except Exception:
                pass
        if ser_client:
            try:
                ser_client.close()
                print("Serial 串列埠已安全關閉。")
            except Exception:
                pass
        print("資源清理完成，測試結束。")


if __name__ == "__main__":
    main()
