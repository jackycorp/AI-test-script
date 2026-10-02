# -*- coding: utf-8 -*-
"""
名稱: 自動化 Power Down/Up 恢復時間效能測試腳本

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 建立 Serial Session 並讓使用者輸入 COM 埠。
  1.2 輸入執行次數與 Power On 等待時間。
[Phase 2] 儀器與環境配置 (Spirent TestCenter)
  2.1 預約實體 Port 並建立測試 Stream (遵循 SKILL.md Rule 10)。
[Phase 3] 自動化測試迴圈
  [Power Down 測試段落]
  3.1 Port[0]、Port[1] 開始打雙向流量。
  3.2 等待 2 秒確保流量穩定。
  3.3 透過 Serial 發送指令觸發 Power Off。
  3.4 等待 5 秒確保設備已斷電且流量停止。
  3.5 停止流量統計以便獲取期間的數據。
  3.6 獲取數據並計算 Power Down 的恢復時間 (Tx - Rx 最大丟包數)。
  [Power Up 測試段落]
  3.7 再次開始雙向流量。
  3.8 等待 2 秒確保流量穩定 (雖然此時設備應是斷電狀態，但為保持邏輯一致)。
  3.9 透過 Serial 發送指令恢復 Power。
  3.10 等待使用者設定的時間確保設備完成開機並恢復流量。
  3.11 停止流量並獲取數據。
  3.12 清除統計數據，進入下一輪。
4. 所有次數執行完畢後，釋放資源並結束程式。
"""

import sys
import os
import time
import serial
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

def main(com_port=None, iteration=None, on_wait_time=None, power_on_cmd=None, power_off_cmd=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    if com_port is None: com_port = get_com_port()
    if iteration is None: iteration = get_iteration_count()
    if on_wait_time is None: on_wait_time = get_boot_wait_time()
    if power_on_cmd is None or power_off_cmd is None:
        power_on_cmd, power_off_cmd = get_power_on_off_commands()

    # 參數蒐集完畢後動態載入 Spirent 核心 (遵循 SKILL.md Rule 5 Lazy Import)
    load_utils()

    # 初始化連線參考以確保 finally 安全清理
    ser = None
    project = None
    result1, result2, result3 = None, None, None
    chassisAddr = "10.123.38.202"
    slotPortlist = ['8/15', '8/16']
    # 集中式日誌路徑 (遵循 SKILL.md Rule 13)
    log_filename = get_result_log_path(__file__, "result.txt")

    try:
        # --- [Phase 2] 儀器與環境配置 (Spirent TestCenter) ---
        project, port, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)

        # 串口初始化與前置指令
        try:
            ser = serial.Serial(port=com_port, baudrate=115200, timeout=0.5)
            print(f"已開啟串列埠 {com_port}")
        except Exception as e:
            print(f"開啟 {com_port} 失敗: {e}")
            sys.exit(1)

        # 寫入日誌分隔線
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*50}\n")
            f_log.write(f"開始新的 Power Down/Up 測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"測試流量配置: {Generatortype['FixedLoad']} {Generatortype['LoadUnit']}\n")
            f_log.write(f"Power On 等待時間: {on_wait_time} 秒\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for i in range(iteration):
            print(f"\n--- 第 {i+1}/{iteration} 次循環 ---")
            
            # --- [Power Down 測試段落] ---
            
            # 3.1 Port[0]、Port[1] 開始打雙向流量
            print("3.1 開始雙向流量...")
            clear_results_and_streams(port)
            StartGenerator([port[0], port[1]]) 
            
            # 3.2 等待 2 秒確保流量穩定
            time.sleep(2)
            
            # 3.3 透過 Serial 發送指令觸發 Power Off
            print(f"3.3 發送指令: {power_off_cmd} (Power Down)")
            comm_CMD(ser, f"{power_off_cmd}\r".encode())
            
            # 3.4 等待 5 秒確保設備已斷電且流量停止
            print("3.4 等待 5 秒穩定...")
            time.sleep(5)
            
            # 3.5 停止流量統計以便獲取期間的數據
            print("3.5 停止流量並獲取數據...")
            StopGenerator([port[0], port[1]])
            time.sleep(1)
            
            # 3.6 獲取數據並計算 Power Down 的恢復時間 (Tx - Rx 最大丟包數)
            datalist = getdata(port)
            p0_tx_d, p0_rx_d = int(datalist[0][2]), int(datalist[0][1])
            p1_tx_d, p1_rx_d = int(datalist[1][2]), int(datalist[1][1])
            
            loss0 = p0_tx_d - p1_rx_d
            loss1 = p1_tx_d - p0_rx_d
            down_recovery = max(loss0, loss1, 0)
            
            down_detail = f"P0(Tx:{p0_tx_d}, Rx:{p0_rx_d}), P1(Tx:{p1_tx_d}, Rx:{p1_rx_d})"
            print(f"Power Down Info: {down_detail}")
            print(f"Power Down Recovery Packets: {down_recovery}")

            # --- [Power Up 測試段落] ---

            # 3.7 再次開始雙向流量
            clear_results_and_streams(port)
            print("3.7 開始雙向流量...")
            StartGenerator([port[0], port[1]])
            
            # 3.8 等待 2 秒確保流量穩定 (雖然此時設備應是斷電狀態，但為保持邏輯一致)
            time.sleep(2)
            
            # 3.9 透過 Serial 發送指令恢復 Power
            print(f"3.9 發送指令: {power_on_cmd} (Power Up)")
            comm_CMD(ser, f"{power_on_cmd}\r".encode())
            
            # 3.10 等待使用者設定的時間確保設備完成開機並恢復流量
            print(f"3.10 等待 {on_wait_time} 秒開機恢復...")
            time.sleep(on_wait_time)
            
            # 3.11 停止流量並獲取數據
            print("3.11 停止流量並獲取數據...")
            StopGenerator([port[0], port[1]])
            time.sleep(1)
            
            # 獲取數據並計算 Power Up 的恢復時間
            datalist = getdata(port)
            p0_tx_u, p0_rx_u = int(datalist[0][2]), int(datalist[0][1])
            p1_tx_u, p1_rx_u = int(datalist[1][2]), int(datalist[1][1])
            
            loss0_up = p0_tx_u - p1_rx_u
            loss1_up = p1_tx_u - p0_rx_u
            up_recovery = max(loss0_up, loss1_up, 0)
            
            up_detail = f"P0(Tx:{p0_tx_u}, Rx:{p0_rx_u}), P1(Tx:{p1_tx_u}, Rx:{p1_rx_u})"
            print(f"Power Up Info: {up_detail}")
            print(f"Power Up Recovery Packets: {up_recovery}")

            down_detail = f"P0(Tx:{p0_tx_d}, Rx:{p0_rx_d}), P1(Tx:{p1_tx_d}, Rx:{p1_rx_d})"
            up_detail = f"P0(Tx:{p0_tx_u}, Rx:{p0_rx_u}), P1(Tx:{p1_tx_u}, Rx:{p1_rx_u})"

            # 紀錄結果
            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f_log.write(f"[{ts}] Iteration {i+1}:\n")
                f_log.write(f"  Power Down: {down_recovery} pkts | Details: {down_detail}\n")
                f_log.write(f"  Power Up:   {up_recovery} pkts | Details: {up_detail}\n\n")

            # 3.12 清除統計數據
            clear_results_and_streams(port)
            time.sleep(2)

    except Exception as e:
        print(f"執行異常: {e}")
    finally:
        # 遵循 SKILL.md Rule 11 安全釋放資源
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
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
        print(f"測試結束。日誌已更新至 {log_filename}")


if __name__ == "__main__":
    main()
