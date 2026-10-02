# -*- coding: utf-8 -*-
"""
名稱: 定期Warm Start 並採集log (Warm_start_and_debuglog_collect.py)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 提示輸入測試參數：
      - 「warm start 執行次數」(整數)
      - 「採集 log 間隔 (分鐘)」(數值，支援小數如 0.5 代表 30 秒，預設 0.5)
      - 「warm start 間隔 (分鐘)」(數值)
      - 「DUT 登入帳號」(字串，預設 admin) 與「登入密碼」(字串，預設 moxa)
      - 「選擇測試場景」(支援單選 / 多選 / 直接 Enter 預設全部)
  1.2 選擇並讀取測試參數表 (scenarios.csv)。

[Phase 2] 變數初始化與環境配置
  2.1 宣告並初始化狀態 Flag：
      - Flag_Scenario = True   (預設 True，程式啟動時先執行第一輪 log 採集)
      - Flag_warmstart = False (預設 False，達 warm start 間隔才觸發)
      - Flag_clear_log = True  (預設 True，僅第一輪採集前清除歷史 log)
  2.2 初始化基準時間戳記與計數器：
      - Time_Scenario = 當前時間
      - Time_WarmStart = 當前時間
      - warm_start_count = 0 (累計完成次數)
  2.3 建立本地 log 資料夾（每次執行於 log 目錄下建立獨立子資料夾，如 log/<日期時間>/），供存放本次各輪日誌記錄。

[Phase 3] 自動化測試迴圈
  3.1 終止條件判定：
      - 檢查 warm_start_count 是否已達到「warm start 執行次數」。
      - 若已達到則結束測試並產出總結。

  3.2 狀態判定與流程分流：
      - 判定 Flag_Scenario 或 Flag_warmstart 任意 Flag 為 True：
        -> 進入 3.3「執行動作迴圈」
      - 若兩者皆為 False：
        -> 跳至 3.4「時間間隔判定」

  3.3 「執行動作迴圈」動作：
      3.3.1 更新執行時間基準與計數器：
          - 更新 Time_Scenario = 當前時間
          - 若 Flag_warmstart == True：warm_start_count 累計 +1，更新 Time_WarmStart = 當前時間

      3.3.2 輪巡執行所有選定之測試場景 (Scenario / DUT)：
          - 步驟 A: Ping 檢查 DUT。若失敗則記錄錯誤並換下一個 Scenario。
          - 步驟 B: Telnet 登入 DUT。若登入失敗則記錄錯誤並換下一個 Scenario。
                    (若所有 DUT 皆無法連線，將於巡檢完後自動進入 3.4)
          - 步驟 C: 依據 Flag 狀態對 DUT 下達 CLI 指令（各指令間隔 1 秒，記錄於「log_WS<次數>_sc<ID>_<MMDD_HHMMSS>.txt」）：
              [基礎指令 (每次登入必執行)]
              - terminal length 0

              [歷史日誌清除 (僅當 Flag_clear_log 為 True 時執行)]
              - clear logging event-log

              [進入工程除錯模式 (僅當 Flag_clear_log、Flag_Scenario 或 Flag_warmstart 為 True 時執行)]
              - moxaie terminal
              - clear logging debug-log (Flag_clear_log 為 True 時執行)

              [狀態與日誌採集 (當 Flag_Scenario 或 Flag_warmstart 為 True 時執行)]
              - show logging debug-log
              - show memory info
              - show memory kernel
              - show thread info
              - show stack info
              - exit (退出 moxaie 模式回一般模式)
              - show logging event-log

              [設備重開機 (僅當 Flag_warmstart 為 True 時執行)]
              - re
              - Y

          - 步驟 D: 清除並關閉該 DUT 之 Telnet session。

      3.3.3 Scenario 全部輪巡完畢後處理：
          - 重置三組 Flag 為 False：
              - Flag_Scenario = False
              - Flag_warmstart = False
              - Flag_clear_log = False (確保清除 log 僅在第一輪執行一次)
          - 退出「執行動作迴圈」。

  3.4 時間間隔判定 (Timer Polling Check)：
      - 判定採集 log 間隔：
        若 (當前時間 - Time_Scenario) >= 「採集 log 間隔」，則設定 Flag_Scenario = True
      - 判定 warm start 間隔：
        若 (當前時間 - Time_WarmStart) >= 「warm start 間隔」，則設定 Flag_warmstart = True
      - 若任一 Flag 變更為 True，將當時時間與變更資訊記錄至 result.txt

  3.5 輪詢間隔等候：
      - 固定等候 30 秒後，返回 3.1 進行下一輪判定。
"""

import sys
import os
import csv
import time
import telnetlib
from datetime import datetime
from typing import List, Dict, Optional, Tuple

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

# 虛擬環境自動跳轉防呆機制 (若以全域 Python 啟動，自動切換至專案 .venv 執行)
_venv_py = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(_venv_py) and os.path.normcase(sys.executable) != os.path.normcase(_venv_py):
    import subprocess
    sys.exit(subprocess.run([_venv_py] + sys.argv).returncode)

# 引入共用通訊工具（依按需裝配原則，本測試純使用 Telnet 與 Ping，毋須載入 Spirent 或 Serial）
try:
    from utils.comm_helper import get_iteration_count, Pingfunc, comm_TELNET, get_result_dir, get_result_log_path
except ImportError as e:
    print(f"無法載入 comm_helper: {e}")
    sys.exit(1)


####################### 輔助函式 ###########################
def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """讀取 CSV 測試參數表 (支援絕對路徑與相對路徑，具備防禦性解析)"""
    if not os.path.isabs(csv_path):
        candidate_paths = [
            csv_path,
            os.path.join(SCRIPT_DIR, csv_path),
            os.path.join(ROOT_DIR, csv_path)
        ]
        for cp in candidate_paths:
            if os.path.exists(cp):
                csv_path = cp
                break

    if not os.path.exists(csv_path):
        print(f"錯誤：找不到參數表檔案 {csv_path}")
        sys.exit(1)
        
    scenarios = []
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k is not None}
            if not clean_row or not clean_row.get("Scenario"):
                continue
            ip_val = ""
            for k, v in clean_row.items():
                if "ip" in k.lower():
                    ip_val = v
                    break
            scenarios.append({
                "Scenario": clean_row.get("Scenario", ""),
                "DUT_IP": ip_val
            })
    return scenarios


def select_scenarios(scenarios: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """提示使用者選擇欲執行的 Scenario (支援單選、多選、直接 Enter 預設全部)"""
    print("\n可用的測試場景 (Scenarios):")
    for sc in scenarios:
        print(f"  Scenario {sc['Scenario']}: DUT_IP={sc['DUT_IP']}")
    
    while True:
        choice = input("\n請選擇要執行的場景 (例如單選: 1, 多選: 1,2，直接 Enter 預設全部): ").strip()
        if not choice or choice.lower() == "all":
            print("-> 已選擇執行所有場景 (All Scenarios)")
            return scenarios
        
        selected_ids = [s.strip() for s in choice.split(",") if s.strip()]
        selected_scenarios = [sc for sc in scenarios if sc["Scenario"] in selected_ids]
        if selected_scenarios:
            chosen_str = ", ".join([sc["Scenario"] for sc in selected_scenarios])
            print(f"-> 已選擇執行場景: {chosen_str}")
            return selected_scenarios
        else:
            print("輸入無效或找不到對應的 Scenario ID，請重新輸入。")


def get_interval_minutes(prompt_message: str, default_val: float = 1.0) -> float:
    """提示輸入時間間隔 (分鐘)，具備非負數防呆驗證，支援小數 (例如 0.5 代表 30 秒)"""
    while True:
        try:
            val = input(f"{prompt_message} (可輸入小數如 0.5 代表 30 秒，預設 {default_val} 分鐘): ").strip()
            if not val:
                return default_val
            minutes = float(val)
            if minutes > 0:
                return minutes
            print("間隔時間必須大於 0，請重新輸入。")
        except ValueError:
            print("請輸入有效的數字格式 (例如 0.5 或 1)。")


def send_telnet_and_log(tn, cmd: str, log_file_path: str, wait_time: float = 1.0) -> str:
    """發送 Telnet 指令，並將下達指令與 DUT 回傳資訊同步記錄至指定 txt 檔"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output = ""
    try:
        tn.write(cmd.encode('ascii') + b"\n")
        time.sleep(wait_time)
        raw_output = tn.read_very_eager()
        output = raw_output.decode(errors='ignore')
    except Exception as e:
        output = f"[連線中斷或回應讀取異常: {e}]"
    
    log_content = (
        f"\n[{timestamp}] >>> SEND COMMAND: {cmd}\n"
        f"{'-'*50}\n"
        f"{output.strip()}\n"
        f"{'-'*50}\n"
    )
    try:
        with open(log_file_path, "a+", encoding="utf-8") as f:
            f.write(log_content)
    except Exception as e:
        print(f"寫入日誌異常: {e}")
        
def get_telnet_credentials(default_user: str = "admin", default_pwd: str = "moxa") -> Tuple[str, str]:
    """提示使用者輸入 DUT 登入帳號與密碼 (支援直接 Enter 套用預設值)"""
    user_input = input(f"請輸入 DUT 登入帳號 (直接 Enter 預設 {default_user}): ").strip()
    username = user_input if user_input else default_user

    pwd_input = input(f"請輸入 DUT 登入密碼 (直接 Enter 預設 {default_pwd}): ").strip()
    password = pwd_input if pwd_input else default_pwd

    print(f"-> 已設定登入帳號: '{username}'")
    return username, password


def custom_telnet_login(target_ip: str, username: str = "admin", password: str = "moxa") -> Optional[telnetlib.Telnet]:
    """嘗試 Telnet 登入設備，支援自訂帳號與密碼之登入交握"""
    print(f"正在嘗試登入設備: {target_ip} (帳號: {username}) ...")
    try:
        tn = telnetlib.Telnet(target_ip, timeout=10)
        time.sleep(2)
        comm_TELNET(tn, 'login', username)
        time.sleep(2)
        comm_TELNET(tn, 'Password', password)
        time.sleep(2)
        comm_TELNET(tn)  # 發送 Enter 鍵確認
        print(f"Telnet 登入成功 ({target_ip})。")
        return tn
    except Exception as e:
        print(f"Telnet 登入失敗 ({target_ip}): {e}")
        return None


####################### 主程式 ###########################
def main():
    print("=" * 60)
    print("  定期 Warm Start 並採集 log 自動化測試")
    print("=" * 60)

    # --- [Phase 1] 參數蒐集與初始化 ---
    # 1.1 提示輸入「warm start 執行次數」、「採集 log 間隔(分鐘)」、「warm start 間隔(分鐘)」、「DUT 帳號密碼」、「選擇測試場景」
    target_warm_start_count = get_iteration_count()
    log_interval_min = get_interval_minutes("請輸入採集 log 間隔時間 (分鐘)", default_val=0.5)
    warm_start_interval_min = get_interval_minutes("請輸入 Warm Start 間隔時間 (分鐘)", default_val=5.0)
    dut_username, dut_password = get_telnet_credentials(default_user="admin", default_pwd="moxa")
    
    log_interval_sec = log_interval_min * 60.0
    warm_start_interval_sec = warm_start_interval_min * 60.0

    # 1.2 選擇並讀取測試參數表
    all_scenarios = load_scenarios_from_csv("scenarios.csv")
    selected_scenarios = select_scenarios(all_scenarios)

    # --- [Phase 2] 變數初始化與環境配置 ---
    # 2.1 宣告並初始化狀態 Flag
    Flag_Scenario = True
    Flag_warmstart = False
    Flag_clear_log = True

    # 2.2 初始化基準時間戳記與計數器
    test_start_time = time.time()
    Time_Scenario = test_start_time
    Time_WarmStart = test_start_time
    warm_start_count = 0

    # 2.3 建立集中式 log 資料夾，供存放各輪日誌記錄 (於 test result/<測試名稱>_result/log/ 下建立)
    session_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = get_result_dir(__file__, sub_dir=os.path.join("log", session_str))
    print(f"[Phase 2] 已建立本次測試專屬日誌資料夾: {log_dir}")
    summary_log = get_result_log_path(__file__, "result.txt")

    with open(summary_log, "a+", encoding="utf-8") as f_sum:
        f_sum.write(f"\n{'='*60}\n")
        f_sum.write(f"開始定期 Warm Start 與 Log 採集測試: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f_sum.write(f"目標 Warm Start 次數: {target_warm_start_count} 次\n")
        f_sum.write(f"採集 Log 間隔: {log_interval_min} 分鐘 ({log_interval_sec:.1f} 秒)\n")
        f_sum.write(f"Warm Start 間隔: {warm_start_interval_min} 分鐘 ({warm_start_interval_sec:.1f} 秒)\n")
        f_sum.write(f"參與測試場景: {', '.join([sc['Scenario'] for sc in selected_scenarios])}\n")
        f_sum.write(f"詳細日誌目錄: log/{session_str}\n")
        f_sum.write(f"{'='*60}\n")

    # --- [Phase 3] 自動化測試迴圈 ---
    try:
        loop_round = 0
        while True:
            loop_round += 1
            now = time.time()
            
            # 3.1 判定 warm start 執行總數是否已達到，若已達到則結束測試
            if warm_start_count >= target_warm_start_count:
                print(f"\n[3.1] 目標 Warm Start 總次數已達成 ({warm_start_count}/{target_warm_start_count})，結束測試。")
                break

            # 3.2 判定 Flag_Scenario, Flag_warmstart 任意 flag 為 true，則進入「執行動作迴圈」，都不為 true 則跳到 3.4
            if not (Flag_Scenario or Flag_warmstart):
                print(f"\n[3.2] 目前無觸發 Flag (Scenario={Flag_Scenario}, WarmStart={Flag_warmstart})，跳至 3.4 時間判定。")
            else:
                # 3.3 「執行動作迴圈」動作
                print(f"\n{'='*60}")
                print(f"  >>> [3.3] 進入執行動作迴圈 (當前狀態: Scenario={Flag_Scenario}, WarmStart={Flag_warmstart}, ClearLog={Flag_clear_log}) <<<")
                print(f"  >>> 已完成 Warm Start 次數: {warm_start_count}/{target_warm_start_count} <<<")
                print(f"{'='*60}")

                # 3.3.1 根據哪個 flag 為 True，更新對應的 Time_Scenario 和 Time_WarmStart
                action_time = time.time()
                Time_Scenario = action_time
                print(f"[3.3.1] 更新 Time_Scenario: {datetime.fromtimestamp(Time_Scenario).strftime('%H:%M:%S')}")
                if Flag_warmstart:
                    warm_start_count += 1
                    Time_WarmStart = action_time
                    print(f"[3.3.1] 執行 Warm Start，累計次數: {warm_start_count}/{target_warm_start_count}，更新 Time_WarmStart: {datetime.fromtimestamp(Time_WarmStart).strftime('%H:%M:%S')}")
                    with open(summary_log, "a+", encoding="utf-8") as f_sum:
                        f_sum.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 開始執行第 {warm_start_count}/{target_warm_start_count} 次 Warm Start 巡檢\n")

                # 3.3.2 輪巡執行所有選定之測試場景 (Scenario / DUT)
                for sc_idx, sc in enumerate(selected_scenarios, 1):
                    sc_id = sc["Scenario"]
                    dut_ip = sc["DUT_IP"]
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] --- Scenario {sc_id} ({sc_idx}/{len(selected_scenarios)}) | DUT IP: {dut_ip} ---")

                    # 步驟 A: Ping 檢查 DUT
                    print(f"[步驟 A] Ping 檢查 DUT ({dut_ip})...")
                    ping_ok = Pingfunc(dut_ip, times=1)
                    if not ping_ok:
                        msg = f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} ({dut_ip}): Ping 失敗/離線中，跳至下一個 Scenario。"
                        print(f"[FAIL] {msg}")
                        with open(summary_log, "a+", encoding="utf-8") as f_sum:
                            f_sum.write(f"{msg}\n")
                        continue

                    # 步驟 B: Telnet 登入 DUT
                    print(f"[步驟 B] Telnet 登入 DUT ({dut_ip})...")
                    tn = custom_telnet_login(dut_ip, username=dut_username, password=dut_password)
                    if tn is None:
                        msg = f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} ({dut_ip}): Telnet 登入失敗，跳至下一個 Scenario。"
                        print(f"[FAIL] {msg}")
                        with open(summary_log, "a+", encoding="utf-8") as f_sum:
                            f_sum.write(f"{msg}\n")
                        continue

                    # 建立濃縮日誌檔名：log_WS<次數>_sc<ID>_<MMDD_HHMMSS>.txt
                    time_stamp_str = datetime.now().strftime("%m%d_%H%M%S")
                    detail_log_name = f"log_WS{warm_start_count}_sc{sc_id}_{time_stamp_str}.txt"
                    detail_log_path = os.path.join(log_dir, detail_log_name)

                    try:
                        with open(detail_log_path, "w", encoding="utf-8") as f_detail:
                            f_detail.write(f"{'='*50}\n")
                            f_detail.write(f"DUT IP: {dut_ip}, Scenario: {sc_id}, WS Count: {warm_start_count}/{target_warm_start_count}\n")
                            f_detail.write(f"採集時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                            f_detail.write(f"當前狀態: Scenario={Flag_Scenario}, WarmStart={Flag_warmstart}, ClearLog={Flag_clear_log}\n")
                            f_detail.write(f"{'='*50}\n")

                        # 步驟 C: 依據 Flag 狀態對 DUT 下達 CLI 指令，每個指令間隔 1s
                        # [基礎指令 (每次登入必執行)]
                        send_telnet_and_log(tn, "terminal length 0", detail_log_path, wait_time=1.0)

                        # [歷史日誌清除 (僅當 Flag_clear_log 為 True 時執行)]
                        if Flag_clear_log:
                            send_telnet_and_log(tn, "clear logging event-log", detail_log_path, wait_time=1.0)

                        # [進入工程除錯模式 (僅當 Flag_clear_log、Flag_Scenario 或 Flag_warmstart 為 True 時執行)]
                        if Flag_clear_log or Flag_Scenario or Flag_warmstart:
                            send_telnet_and_log(tn, "moxaie terminal", detail_log_path, wait_time=1.0)
                            if Flag_clear_log:
                                send_telnet_and_log(tn, "clear logging debug-log", detail_log_path, wait_time=1.0)

                        # [狀態與日誌採集 (當 Flag_Scenario 或 Flag_warmstart 為 True 時執行)]
                        if Flag_Scenario or Flag_warmstart:
                            collect_cmds = [
                                "show logging debug-log",
                                "show memory info",
                                "show memory kernel",
                                "show thread info",
                                "show stack info",
                                "exit",
                                "show logging event-log"
                            ]
                            for c in collect_cmds:
                                send_telnet_and_log(tn, c, detail_log_path, wait_time=1.0)

                        # [設備重開機 (僅當 Flag_warmstart 為 True 時執行)]
                        if Flag_warmstart:
                            print(f"[Action] 發送 Warm Start 重啟指令 (re -> Y)...")
                            send_telnet_and_log(tn, "re", detail_log_path, wait_time=1.0)
                            send_telnet_and_log(tn, "Y", detail_log_path, wait_time=1.0)
                            log_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} ({dut_ip}): 已下達 Warm Start 重啟指令。"
                            with open(summary_log, "a+", encoding="utf-8") as f_sum:
                                f_sum.write(f"{log_msg}\n")

                    finally:
                        # 步驟 D: 清除並關閉該 DUT 之 Telnet session
                        try:
                            tn.close()
                            print(f"[步驟 D] 已清除 Telnet Session ({dut_ip})")
                        except Exception as e:
                            print(f"關閉 Telnet 異常: {e}")

                # 3.3.3 Scenario 全部輪巡完畢後處理：
                # 重置三組 Flag 為 False
                Flag_Scenario = False
                Flag_warmstart = False
                Flag_clear_log = False
                print(f"[3.3.3] 已重置 Flag: Scenario=False, warmstart=False, clear_log=False，退出執行動作迴圈。")

                # 若剛剛完成的 warm start 已達目標總數，直接退出迴圈結束測試
                if warm_start_count >= target_warm_start_count:
                    print(f"\n[3.1] 目標 Warm Start 總次數已達成 ({warm_start_count}/{target_warm_start_count})，結束測試。")
                    break

            # 3.4 時間間隔判定 (Timer Polling Check)
            now = time.time()
            elapsed_scenario = now - Time_Scenario
            elapsed_warmstart = now - Time_WarmStart

            print(f"\n[3.4] 時間間隔判定:")
            print(f"      Log 採集間隔: 已過 {elapsed_scenario:.1f} 秒 / 閥值 {log_interval_sec:.1f} 秒 ({log_interval_min} 分)")
            print(f"      Warm Start 間隔: 已過 {elapsed_warmstart:.1f} 秒 / 閥值 {warm_start_interval_sec:.1f} 秒 ({warm_start_interval_min} 分)")

            if elapsed_scenario >= log_interval_sec:
                Flag_Scenario = True
                log_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"      -> 已達採集 log 間隔，設定 Flag_Scenario = True")
                with open(summary_log, "a+", encoding="utf-8") as f_sum:
                    f_sum.write(f"[{log_time_str}] [Trigger] 已達採集 log 間隔 ({log_interval_min} 分鐘)，Flag_Scenario 變更為 True\n")

            if elapsed_warmstart >= warm_start_interval_sec:
                Flag_warmstart = True
                log_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"      -> 已達 warm start 間隔，設定 Flag_warmstart = True")
                with open(summary_log, "a+", encoding="utf-8") as f_sum:
                    f_sum.write(f"[{log_time_str}] [Trigger] 已達 warm start 間隔 ({warm_start_interval_min} 分鐘)，Flag_warmstart 變更為 True\n")

            # 3.5 輪詢間隔等候
            print(f"\n[3.5] 固定等候 30 秒後進行下一輪判定...")
            time.sleep(30)

    except KeyboardInterrupt:
        print("\n[INFO] 使用者手動中斷測試 (Ctrl+C)。")
    except Exception as e:
        print(f"\n[ERROR] 測試執行期間發生未預期異常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\n{'='*60}")
        print(f"測試結束。已執行 Warm Start 總次數: {warm_start_count}/{target_warm_start_count}")
        print(f"總結日誌已更新至: {summary_log}")
        print(f"詳細指令記錄已存放於: {log_dir}")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
