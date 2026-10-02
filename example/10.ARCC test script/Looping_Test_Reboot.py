# -*- coding: utf-8 -*-
"""
名稱: 自動化 Reboot 測試腳本 (Looping 檢測版)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 輸入「執行次數」、「等待開機時間」與「目標位址 IP」。
[Phase 2] 儀器與環境配置 (Spirent & Telnet)
  2.1 配置 Spirent TestCenter 預約 Port 並建立 Stream (遵循 SKILL.md Rule 10)。
  2.2 執行 Ping 預檢與初始 Telnet 登入測試。
[Phase 3] 自動化測試迴圈
  3.1 Port[0] 開始打流量 (Start Traffic)。
  3.2 等待 2 秒確保流量穩定。
  3.3 透過 Telnet 發送 "re" (Reboot) 指令。
  3.4 等待使用者自定義的開機等待時間。
  3.5 停止流量 (Stop Traffic)。
  3.6 獲取數據並判定：
      - 若 Port[0] 收到任何封包 (RxCount > 0)，判定為 FAIL (Looping)，紀錄至日誌。
      - 若未收到封包，判定為 PASS，紀錄至日誌。
  3.7 執行 clear_results_and_streams(port)，清除統計數據後進入下一輪。
4. 所有次數執行完畢後，釋放資源並結束程式。
"""

import sys
import os
import time
import telnetlib
from datetime import datetime
from typing import TYPE_CHECKING, List

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
    from utils.dictionary_parameters import *
    from utils.comm_helper import *
except ImportError as e:
    print(f"無法載入 dictionary_parameters 或 comm_helper: {e}")
    sys.exit(1)

if TYPE_CHECKING:
    from utils.pythontool import *


####################### 輔助函式 ###########################

def load_utils():
    """動態載入 Spirent TestCenter API 核心，並注入全域命名空間 (遵循 SKILL.md Rule 5)"""
    print("\n正在載入 Spirent TestCenter API 與通訊工具，請稍候...")
    try:
        import utils.pythontool as pt
        # 排除模組內部私有或路徑變數，避免污染全域工作區命名空間 (遵循 SKILL.md Rule 13)
        excluded = {'current_dir', 'tool_tcl_path', 'lib_pathes', 'scripts', 'path'}
        for name in dir(pt):
            if not name.startswith('_') and name not in excluded:
                globals()[name] = getattr(pt, name)
    except ImportError as e:
        print(f"無法載入 pythontool: {e}")
        sys.exit(1)


def setup_spirent(chassisAddr: str, slotPortlist: list) -> tuple:
    """配置 Spirent TestCenter 預約 Port、建立 Stream，並訂閱流量結果 (遵循 SKILL.md Rule 10)"""
    Connect(chassisAddr)
    ReservePort(chassisAddr, slotPortlist)
    
    project = tclsh.eval('CreateProject')
    port = []
    for i in range(len(slotPortlist)):
        port.append(tclsh.eval('CreatePort {0} {1} {2}'.format(slotPortlist[i], project, chassisAddr)))

    # 設定 Port 屬性 (雙工、速率、流控)
    CreatePortType_Copper(port[0], PortType_1G_Full_AN)
    CreatePortType_Copper(port[1], PortType_1G_Full_AN)
    print(f"Ports initialized: {port}")

    tclsh.eval('Mapping')
    
    # 防呆清除殘留 StreamBlock (遵循 SKILL.md Rule 10)
    for p in port:
        existing_sbs = tclsh.eval(f"stc::get {p} -children-StreamBlock").split()
        for sb in existing_sbs:
            if sb:
                try:
                    tclsh.eval(f"stc::delete {sb}")
                except Exception:
                    pass

    # 兩端各配對 1 個 StreamBlock，嚴防 invalid handle (遵循 SKILL.md Rule 10)
    Streamblocklist = []
    Streamblocklist.append(CreateStreamBlock(port[0], StreamBlock, Frame))
    Streamblocklist.append(CreateStreamBlock(port[1], StreamBlock, Frame1))

    Generator(port[0], Generatortype)
    Generator(port[1], Generatortype)
    
    # 紀錄 testcenter counter 到 csv 檔案，啟動 Spirent 統計引擎
    now = datetime.now()
    filename = "generatorTx" + now.strftime("%m%d%y%H%M%S")
    filename2 = "analyzerRx" + now.strftime("%m%d%y%H%M%S")
    filename3 = "droppedRx" + now.strftime("%m%d%y%H%M%S")
    
    result1 = ResultSubscribe_Tx(project, filename)
    result2 = ResultSubscribe_Rx(project, filename2)
    result3 = ResultSubscribe_Rxstreams(project, filename3)
    
    return project, port, result1, result2, result3


def clear_results_and_streams(active_ports=None):
    """清除全域統計數據（包含埠與串流），防止 RxDrop 在 iteration 之間累加 (遵循 SKILL.md Rule 6)"""
    tclsh.eval("stc::perform ResultsClearAll")


####################### 主程式 ###########################

def main(iteration=None, reboot_wait_time=None, target_ip=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    if iteration is None: iteration = get_iteration_count()
    if reboot_wait_time is None: reboot_wait_time = get_boot_wait_time()
    if target_ip is None: target_ip = get_target_ip()

    # 參數蒐集完畢後動態載入 Spirent 核心 (遵循 SKILL.md Rule 5 Lazy Import)
    load_utils()

    # 初始化連線參考以確保 finally 安全清理
    project = None
    result1, result2, result3 = None, None, None
    tn = None
    chassisAddr = "10.123.38.202"
    slotPortlist = ['8/15', '8/16']
    # 集中式日誌路徑 (遵循 SKILL.md Rule 13)
    log_filename = get_result_log_path(__file__, "result.txt")

    try:
        # --- [Phase 2] 儀器與環境配置 (Spirent TestCenter) ---
        project, port, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)

        # 初始連線檢查
        print(f"\n[Phase 2] 正在檢測設備 {target_ip} 狀態...")
        if not Pingfunc(target_ip, 2):
            print("Ping 失敗，終止測試。")
            sys.exit(1)
        
        tn = telnet_login(target_ip)
        if not tn:
            print(f"Telnet 登入 {target_ip} 失敗，終止測試。")
            sys.exit(1)

        # 寫入日誌分隔線
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*50}\n")
            f_log.write(f"開始新的 Reboot Looping 測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"目標 IP: {target_ip} | 等待時間: {reboot_wait_time}s\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for i in range(iteration):
            print(f"\n--- 第 {i+1}/{iteration} 次循環 ---")
            
            # 3.1 開始流量
            print("3.1 開始 Port[0] 流量...")
            clear_results_and_streams(port)
            StartGenerator([port[0]]) 
            
            # 3.2 等待 2 秒穩定
            time.sleep(2)
            
            # 3.3 發送 Reboot
            print(f"3.3 [{datetime.now().strftime('%H:%M:%S')}] 發送重啟指令...")
            comm_TELNET(tn, '#', 're') 
            comm_TELNET(tn, 'Y/N', 'y')
            tn.close()
            tn = None
            
            # 3.4 等待開機
            print(f"3.4 等待設備開機恢復 ({reboot_wait_time} 秒)...")
            time.sleep(reboot_wait_time)
            
            # 3.5 停止流量
            print("3.5 停止 Port[0] 流量...")
            StopGenerator([port[0]])
            time.sleep(1)
            
            # 3.6 獲取數據並判定結果
            print("3.6 獲取數據並判定結果...")
            datalist = getdata(port) 
            p0_drop, p0_rx, p0_tx = datalist[0]
            p1_drop, p1_rx, p1_tx = datalist[1]
            
            res_status = "PASS" if int(p0_rx) == 0 else "FAIL" 
            p0_formatted = f"[RxDrop:\"{p0_drop}\", RxCount:\"{p0_rx}\", TxCount:\"{p0_tx}\"]"
            p1_formatted = f"[RxDrop:\"{p1_drop}\", RxCount:\"{p1_rx}\", TxCount:\"{p1_tx}\"]"
            
            print(f"結果: {res_status} | P0 RxCount: {p0_rx}")
                
            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f_log.write(f"[{ts}] Iteration {i+1}: {res_status}\n")
                f_log.write(f"  Port[0] Details: {p0_formatted}\n")
                f_log.write(f"  Port[1] Details: {p1_formatted}\n\n")

            # 3.7 清除結果並恢復連線
            print("3.7 清除結果並準備下一輪連線...")
            clear_results_and_streams(port)
            
            if i < iteration - 1:
                while not Pingfunc(target_ip, 1):
                    print("等待開機中 (5s)...")
                    time.sleep(5)
                
                print("重新嘗試登入...")
                tn = telnet_login(target_ip)
                while not tn:
                    print("登入失敗，5秒後重試...")
                    time.sleep(5)
                    tn = telnet_login(target_ip)

    except Exception as e:
        print(f"執行期間發生異常: {e}")
    finally:
        # 遵循 SKILL.md Rule 11 安全釋放資源
        for res_val in [result1, result2, result3]:
            if res_val is not None:
                try: 
                    unsubscribe(res_val)
                except Exception: 
                    pass
        if project is not None:
            try:
                tclsh.eval(f"stc::delete {project}")
            except Exception:
                pass
        try:
            Disconnect(chassisAddr)
        except Exception: 
            pass
        if tn is not None:
            try:
                tn.close()
            except Exception:
                pass
        print(f"已完成測試。日誌已更新至 {log_filename}")


if __name__ == "__main__":
    main()
