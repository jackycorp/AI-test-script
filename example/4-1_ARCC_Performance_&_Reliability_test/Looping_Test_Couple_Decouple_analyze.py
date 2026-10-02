# -*- coding: utf-8 -*-
"""
名稱: 自動化 Looping_Test_Couple_Decouple 測試腳本 (tx & t- 分別判斷)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 輸入「COM 埠」、「執行次數」與「等待延遲時間」。
[Phase 2] 儀器與環境配置 (Spirent & Serial)
  2.1 配置 Spirent TestCenter 預約 Port 並建立 Stream (遵循 SKILL.md Rule 10 雙端配對與防呆清除)。
  2.2 初始化 Serial 連線並發送前置穩定指令 "t-"。
[Phase 3] 自動化測試迴圈
  3.1 Port[0] 開始打流量 (Start Traffic)。
  3.2 等待 2 秒確保流量穩定。
  3.3 發送 "tx" (DeCouple) 指令。
  3.4 等待使用者定義的延遲時間。
  3.5 停止流量 (Stop Traffic)，並獲取數據並判定：
      - Port[0] 收到任何封包 (RxCount > 0) 代表發生 Looping
      - Port[0] 的 TxCount 不等於 Port[1] 的 RxCount 代表封包量不匹配
  3.6 清除全域結果 (ResultsClearAll)，並等待 1s
  3.7 Port[0] 開始打流量 (Start Traffic)。
  3.8 等待 2 秒確保流量穩定。
  3.9 發送 "t-" (Couple) 指令。
  3.10 等待使用者定義的延遲時間。
  3.11 停止流量 (Stop Traffic)。
  3.12 獲取數據並判定：
      - Port[0] 收到任何封包 (RxCount > 0) 代表發生 Looping
      - Port[0] 的 TxCount 不等於 Port[1] 的 RxCount 代表封包量不匹配
  3.13 將 tx 和 t- 結果記錄至日誌 (遵循 SKILL.md Rule 13 集中式路徑)。
  3.14 清除結果統計數據，進入下一輪。
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

def main(com_port=None, iteration=None, delay_time=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    if com_port is None: com_port = get_com_port()
    if iteration is None: iteration = get_iteration_count()
    if delay_time is None: delay_time = get_delay_time()

    # 參數蒐集完畢後動態載入 Spirent 核心 (遵循 SKILL.md Rule 5 Lazy Import)
    load_utils()

    # 初始化連線參考以確保 finally 安全清理
    ser = None
    project = None
    result1, result2, result3 = None, None, None
    chassisAddr = "10.123.38.202"
    slotPortlist = ['4/3', '8/15']
    # 集中式日誌路徑 (遵循 SKILL.md Rule 13)
    log_filename = get_result_log_path(__file__, "result.txt")

    try:
        # --- [Phase 2] 儀器與環境配置 (Spirent TestCenter) ---
        project, port, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)

        # 串口初始化與前置指令
        try:
            ser = serial.Serial(port=com_port, baudrate=115200, timeout=0.5)
            print(f"已開啟串列埠 {com_port}")
            print("發送前置指令: t- (等待 10 秒穩定)...")
            comm_CMD(ser, b"t-\r")
            time.sleep(10)
        except Exception as e:
            print(f"開啟 {com_port} 失敗: {e}")
            sys.exit(1)

        # 寫入日誌分隔線
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*50}\n")
            f_log.write(f"開始新的 Couple/Decouple Looping 測試批次 (tx & t- 分別判斷): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"COM Port: {com_port} | Delay: {delay_time}s\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for i in range(iteration):
            print(f"\n--- 第 {i+1}/{iteration} 次循環 ---")
            
            # === [tx (DeCouple) 測試階段] ===
            # 3.1 Port[0] 開始打流量 (Start Traffic)
            print("3.1 [tx] 開始 Port[0] 流量...")
            clear_results_and_streams(port)
            StartGenerator([port[0]]) 
            
            # 3.2 等待 2 秒確保流量穩定
            print("3.2 [tx] 等待 2 秒穩定...")
            time.sleep(2)
            
            # 3.3 發送 tx (DeCouple) 指令
            tx_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"3.3 [tx] [{tx_time}] 發送指令: tx")
            comm_CMD(ser, b"tx\r")
            
            # 3.4 等待使用者定義的延遲時間
            print(f"3.4 [tx] 等待延遲: {delay_time} 秒...")
            time.sleep(delay_time)
            
            # 3.5 停止流量 (Stop Traffic)，並獲取數據並判定
            print("3.5 [tx] 停止 Port[0] 流量並獲取數據...")
            StopGenerator([port[0]])
            time.sleep(1)
            
            # 獲取 tx 數據與判定
            datalist_tx = getdata(port) 
            tx_p0_drop, tx_p0_rx, tx_p0_tx = datalist_tx[0]
            tx_p1_drop, tx_p1_rx, tx_p1_tx = datalist_tx[1]
            
            tx_is_loop = int(tx_p0_rx) > 0
            tx_is_mismatch = int(tx_p0_tx) != int(tx_p1_rx)
            tx_status = "FAIL" if (tx_is_loop or tx_is_mismatch) else "PASS"
            
            if tx_status == "FAIL":
                if tx_is_mismatch:
                    print(f"  [!] [tx] 偵測到封包量不匹配: Port[0] Tx ({tx_p0_tx}) != Port[1] Rx ({tx_p1_rx})")
                if tx_is_loop:
                    print(f"  [!] [tx] 偵測到 Port[0] 收到封包 (RxCount: {tx_p0_rx})")
            print(f"  [tx 結果]: {tx_status} | P0 RxCount: {tx_p0_rx} | P0 Tx: {tx_p0_tx} vs P1 Rx: {tx_p1_rx}")

            # 3.6 清除結果，等待 1 秒
            print("3.6 [tx] 清除結果，等待 1 秒...")
            clear_results_and_streams(port)
            time.sleep(1)

            # === [t- (Couple) 測試階段] ===
            # 3.7 Port[0] 開始打流量 (Start Traffic)
            print("3.7 [t-] 開始 Port[0] 流量...")
            StartGenerator([port[0]]) 
            
            # 3.8 等待 2 秒確保流量穩定
            print("3.8 [t-] 等待 2 秒穩定...")
            time.sleep(2)
            
            # 3.9 發送 t- (Couple) 指令
            tm_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"3.9 [t-] [{tm_time}] 發送指令: t-")
            comm_CMD(ser, b"t-\r")
            
            # 3.10 等待使用者定義的延遲時間
            print(f"3.10 [t-] 等待延遲: {delay_time} 秒...")
            time.sleep(delay_time)
            
            # 3.11 停止流量 (Stop Traffic)
            print("3.11 [t-] 停止 Port[0] 流量並獲取數據...")
            StopGenerator([port[0]])
            time.sleep(1)
            
            # 3.12 獲取數據並判定
            datalist_tm = getdata(port) 
            tm_p0_drop, tm_p0_rx, tm_p0_tx = datalist_tm[0]
            tm_p1_drop, tm_p1_rx, tm_p1_tx = datalist_tm[1]
            
            tm_is_loop = int(tm_p0_rx) > 0
            tm_is_mismatch = int(tm_p0_tx) != int(tm_p1_rx)
            tm_status = "FAIL" if (tm_is_loop or tm_is_mismatch) else "PASS"
            
            if tm_status == "FAIL":
                if tm_is_mismatch:
                    print(f"  [!] [t-] 偵測到封包量不匹配: Port[0] Tx ({tm_p0_tx}) != Port[1] Rx ({tm_p1_rx})")
                if tm_is_loop:
                    print(f"  [!] [t-] 偵測到 Port[0] 收到封包 (RxCount: {tm_p0_rx})")
            print(f"  [t- 結果]: {tm_status} | P0 RxCount: {tm_p0_rx} | P0 Tx: {tm_p0_tx} vs P1 Rx: {tm_p1_rx}")

            # 綜合判定
            res_status = "FAIL" if (tx_status == "FAIL" or tm_status == "FAIL") else "PASS"
            print(f"=== 第 {i+1} 次循環綜合結果: {res_status} ===")

            # 3.13 將 tx 和 t- 結果記錄至日誌
            print("3.13 將 tx 和 t- 結果記錄至日誌...")
            tx_p0_formatted = f"[RxDrop:\"{tx_p0_drop}\", RxCount:\"{tx_p0_rx}\", TxCount:\"{tx_p0_tx}\"]"
            tx_p1_formatted = f"[RxDrop:\"{tx_p1_drop}\", RxCount:\"{tx_p1_rx}\", TxCount:\"{tx_p1_tx}\"]"
            tm_p0_formatted = f"[RxDrop:\"{tm_p0_drop}\", RxCount:\"{tm_p0_rx}\", TxCount:\"{tm_p0_tx}\"]"
            tm_p1_formatted = f"[RxDrop:\"{tm_p1_drop}\", RxCount:\"{tm_p1_rx}\", TxCount:\"{tm_p1_tx}\"]"

            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f_log.write(f"[{ts}] Round {i+1}: {res_status}\n")
                f_log.write(f"  [tx Phase] Send Time: {tx_time} | Status: {tx_status}\n")
                f_log.write(f"    Port[0] Details: {tx_p0_formatted}\n")
                f_log.write(f"    Port[1] Details: {tx_p1_formatted}\n")
                f_log.write(f"  [t- Phase] Send Time: {tm_time} | Status: {tm_status}\n")
                f_log.write(f"    Port[0] Details: {tm_p0_formatted}\n")
                f_log.write(f"    Port[1] Details: {tm_p1_formatted}\n\n")

            # 3.14 清除結果統計數據，進入下一輪
            print("3.14 清除結果統計數據，進入下一輪...")
            clear_results_and_streams(port)
            time.sleep(1)

    except Exception as e:
        print(f"執行期間發生異常: {e}")
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
        print(f"已完成測試。日誌已更新至 {log_filename}")


if __name__ == "__main__":
    main()
