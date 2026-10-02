# -*- coding: utf-8 -*-
"""
名稱: 自動化 Couple 恢復時間效能測試腳本

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 建立 Serial Session 並讓使用者輸入 COM 埠。
  1.2 輸入執行次數。
[Phase 2] 儀器與環境配置 (Spirent TestCenter)
  2.1 預約實體 Port 並建立測試 Stream (遵循 SKILL.md Rule 10)。
  2.2 發送前置指令並等待環境穩定。
[Phase 3] 自動化測試迴圈
  3.1 寫入 "tx" 指令 (斷開 Couple)。
  3.2 等待 5 秒確保穩定。
  3.3 Port[0] 開始打流量 (Start Traffic)。
  3.4 等待 2 秒確保穩定。
  3.5 寫入 "t-" 指令 (恢復 Couple)，並記錄精確時間戳 T1。
  3.6 等待 5 秒確保流量恢復穩定後停止流量 (Stop Traffic)，並記錄精確時間戳 T2。
  3.7 獲取數據並計算結果：
      - P1收到封包數量轉換成時間 (p1_rx/FPS) : (p1_rx) / 1000 FPS
      - 指令間隔 (T2-T1) : T2 - T1 (從 Couple 接上到停止 traffic 間的時間)
      - COUP 時間 : 指令間隔 - P1 收到封包數量轉換成時間 (單位：秒，精度至 ms)
  3.8 清除統計數據，進入下一輪。
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

def main(com_port=None, iteration=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    if com_port is None: com_port = get_com_port()
    if iteration is None: iteration = get_iteration_count()

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

        # 確保環境穩定
        print("發送前置指令: t- (等待 10 秒穩定)...")
        comm_CMD(ser, b"t-\r")
        time.sleep(10)

        # 寫入日誌標頭
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*60}\n")
            f_log.write(f"開始 Couple 恢復時間測試: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"流量速度: {Generatortype['FixedLoad']} FPS\n")
            f_log.write(f"{'='*60}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for i in range(iteration):
            print(f"\n--- 第 {i+1}/{iteration} 次循環 ---")
            clear_results_and_streams(port)
            
            # 3.1 寫入 "tx" 指令 (斷開 Couple)
            print("3.1 發送指令: tx (Couple Down)")
            comm_CMD(ser, b"tx\r")
            
            # 3.2 等待 5 秒確保穩定
            time.sleep(5)
            
            # 3.3 Port[0] 開始打流量 (Start Traffic)
            print("3.3 開始流量 (Port 0)...")
            StartGenerator([port[0]])
            
            # 3.4 等待 2 秒確保穩定
            time.sleep(2)
            
            # 3.5 寫入 "t-" 指令 (恢復 Couple)，並記錄精確時間戳 T1
            print("3.5 發送指令: t- (Couple Up)")
            t1 = time.time()
            comm_CMD(ser, b"t-\r")
            t1_str = datetime.fromtimestamp(t1).strftime('%H:%M:%S.%f')[:-3]
            
            # 3.6 等待 5 秒確保流量恢復穩定後停止流量 (Stop Traffic)，並記錄精確時間戳 T2
            time.sleep(5)
            print("3.6 停止流量...")
            t2 = time.time()
            StopGenerator([port[0]])
            t2_str = datetime.fromtimestamp(t2).strftime('%H:%M:%S.%f')[:-3]
            time.sleep(1)
            
            # 3.7 獲取數據並計算結果
            datalist = getdata(port)
            p1_rx = int(datalist[1][1])
            fps = float(Generatortype['FixedLoad'])
            
            # P1 收到封包數量轉換成時間 (p1_rx / FPS)
            rx_time = p1_rx / fps
            
            # 指令間隔 (T2 - T1)
            interval_time = t2 - t1
            
            # COUP 時間 : 指令間隔 - rx_time
            coup_time_sec = interval_time - rx_time
            coup_time_ms = coup_time_sec * 1000
            
            print(f"T1 (Send t-) 時間戳:      {t1_str}")
            print(f"T2 (Stop Traffic) 時間戳: {t2_str}")
            print(f"P1 Received Packets: {p1_rx}")
            print(f"P1 收包轉換時間:      {rx_time:.6f} s")
            print(f"指令間隔 (T2-T1):     {interval_time:.6f} s")
            print(f"-> COUP 時間: {coup_time_sec:.3f} s ({coup_time_ms:.2f} ms)")

            # 紀錄結果
            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                f_log.write(f"Iteration {i+1}:\n")
                f_log.write(f"  T1 (Send t-) 時間戳:      {t1_str}\n")
                f_log.write(f"  T2 (Stop Traffic) 時間戳: {t2_str}\n")
                f_log.write(f"  P1 Received Packets: {p1_rx}\n")
                f_log.write(f"  P1 收包轉換時間:      {rx_time:.6f} s\n")
                f_log.write(f"  指令間隔 (T2-T1):     {interval_time:.6f} s\n")
                f_log.write(f"  COUP 時間: (指令間隔 - 收包轉換時間) = {coup_time_sec:.3f} s ({coup_time_ms:.2f} ms)\n\n")

            # 3.8 清除統計數據
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
        print(f"已完成測試。日誌已更新至 {log_filename}")


if __name__ == "__main__":
    main()
