# -*- coding: utf-8 -*-
"""
名稱: 自動化 Power Down/Up 測試腳本 (Reliability 多設備電源切換版)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 建立 Serial Session 並讓使用者輸入 COM 埠。
  1.2 輸入執行次數與 Power On 等待時間。
  1.3 輸入要執行 power on/off 的插座範圍 (Ex. p1 to p4)。
[Phase 2] 儀器與環境配置 (Spirent TestCenter)
  2.1 預約實體 Port 並建立測試 Stream (遵循 SKILL.md Rule 10)。
[Phase 3] 自動化測試迴圈
  [Power Down 測試段落]
  3.1 透過 Serial 發送指令觸發 Power Off (P off)。
  3.2 等待 2 秒。
  3.3 透過 Serial 發送指令將所有設備依序 Power on (每台間隔 0.5s) (Ex. P1 on -> 等 0.5s -> P2 on -> ...)。
  3.4 等待使用者設定的時間確保設備完成開機。
  3.5 Port[0]、Port[1] 開始打雙向流量。
  3.6 等待 5 秒。
  3.7 停止流量 (Stop Traffic)。
  3.8 獲取數據並判定：
      - 若 (Port[0] Tx == Port[1] Rx) 且 (Port[1] Tx == Port[0] Rx)，判定為 PASS。
      - 否則判定為 FAIL，紀錄至日誌。
  3.9 清除結果統計數據，進入下一輪。
4. 所有次數執行完畢後，釋放資源並結束程式。
"""

import sys
import os
import time
import serial
import re
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

def main(com_port=None, iteration=None, on_wait_time=None, outlets=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    if com_port is None: com_port = get_com_port()
    if iteration is None: iteration = get_iteration_count()
    if on_wait_time is None: on_wait_time = get_boot_wait_time()
    if outlets is None: outlets = get_power_outlets()
    
    print(f"\n已設定控制的電源插座列表: {outlets}")

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
            f_log.write(f"開始新的 Power Down/Up 循環測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"控制插座: {', '.join(outlets)}\n")
            f_log.write(f"Power On 等待時間: {on_wait_time} 秒\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for i in range(iteration):
            print(f"\n--- 第 {i+1}/{iteration} 次循環 ---")
            
            # 3.1 透過 Serial 發送指令觸發 Power Off (P off)
            print("3.1 觸發所有設備 Power Off (P off)...")
            for outlet in outlets:
                cmd = f"{outlet} off"
                print(f"  -> 發送指令: {cmd}")
                comm_CMD(ser, f"{cmd}\r".encode())
            
            # 3.2 等待 2 秒
            print("3.2 等待 2 秒...")
            time.sleep(2)
            
            # 3.3 透過 Serial 發送指令將所有設備依序 Power on (每台間隔 0.5s)
            print("3.3 依序將所有設備 Power On (每台間隔 0.5s)...")
            for idx, outlet in enumerate(outlets):
                if idx > 0:
                    time.sleep(0.5)
                cmd = f"{outlet} on"
                print(f"  -> 發送指令: {cmd}")
                comm_CMD(ser, f"{cmd}\r".encode())
            
            # 3.4 等待使用者設定的時間確保設備完成開機
            print(f"3.4 等待開機時間: {on_wait_time} 秒...")
            time.sleep(on_wait_time)
            
            # 3.5 Port[0]、Port[1] 開始打雙向流量
            print("3.5 開始雙向流量...")
            clear_results_and_streams(port)
            StartGenerator([port[0], port[1]]) 
            
            # 3.6 等待 5 秒
            print("3.6 等待 5 秒...")
            time.sleep(5)
            
            # 3.7 停止流量 (Stop Traffic)
            print("3.7 停止流量...")
            StopGenerator([port[0], port[1]])
            time.sleep(1)
            
            # 3.8 獲取數據並判定
            print("3.8 獲取數據並進行判定...")
            datalist = getdata(port)
            p0_rx_drop, p0_rx_count, p0_tx_count = datalist[0]
            p1_rx_drop, p1_rx_count, p1_tx_count = datalist[1]
            
            cond0 = (int(p0_tx_count) == int(p1_rx_count)) and (int(p0_tx_count) > 0)
            cond1 = (int(p1_tx_count) == int(p0_rx_count)) and (int(p1_tx_count) > 0)
            
            is_pass = cond0 and cond1
            status_str = "PASS" if is_pass else "FAIL"
            
            print(f"  Port[0] Tx: {p0_tx_count} | Port[1] Rx: {p1_rx_count} -> 一致性 (且有流量): {cond0}")
            print(f"  Port[1] Tx: {p1_tx_count} | Port[0] Rx: {p0_rx_count} -> 一致性 (且有流量): {cond1}")
            print(f"  回合判定結果: {status_str}")
            
            # 紀錄至日誌
            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f_log.write(f"[{ts}] Round {i+1}: {status_str}\n")
                f_log.write(f"  Port[0] Details: [RxDrop:\"{p0_rx_drop}\", RxCount:\"{p0_rx_count}\", TxCount:\"{p0_tx_count}\"]\n")
                f_log.write(f"  Port[1] Details: [RxDrop:\"{p1_rx_drop}\", RxCount:\"{p1_rx_count}\", TxCount:\"{p1_tx_count}\"]\n\n")
            
            # 3.9 清除結果統計數據，進入下一輪
            print("3.9 清除結果統計數據...")
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
        print(f"結束時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
