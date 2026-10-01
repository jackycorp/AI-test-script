# -*- coding: utf-8 -*-
"""
名稱: Cold start Recovery Test (Cold_start_Recovery_Test.py)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 輸入「執行次數」、「power down等待延遲時間」、「power up 等待延遲時間」、「選擇測試場景（單選/多選/預設全部）」、「輸入制具 COM Port」。
  1.2 選擇並讀取測試參數表 (scenarios.csv)。
[Phase 2] 儀器與環境配置 (Spirent & Serial)
  2.1 配置 Spirent TestCenter 預約 Port 並建立 Stream。
  2.2 使用 Serial 連線斷線制具，預設 COM2、115200 baud。
[Phase 3] 自動化測試迴圈
  對於所選的各個 Scenario 進行以下迴圈測試：
  3.1 port [TX] 持續打單向封包
  3.2 COM port 發送 power off 指令 dc{channel} off
  3.3 等待使用者定義的「power down等待延遲時間」
  3.4 停止流量 (Stop Traffic)，並獲取數據並判定：
      - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
  3.5 清除結果統計數據
  3.6 port [TX] 持續打單向封包 
  3.7 COM port 發送 power on 指令 dc{channel} on
  3.8 等待使用者定義的「power up 等待延遲時間」
  3.9 停止流量 (Stop Traffic)，並獲取數據並判定：
      - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
  3.10 清除結果統計數據，進入下一輪。
"""

import sys
import os
import csv
import time
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Tuple, Optional

# 動態向上搜尋包含 utils 的根目錄，確保無論放置於哪一層子目錄均能正常引入 utils
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
current_dir_check = SCRIPT_DIR
while current_dir_check and os.path.dirname(current_dir_check) != current_dir_check:
    if os.path.exists(os.path.join(current_dir_check, "utils", "comm_helper.py")):
        if current_dir_check not in sys.path:
            sys.path.insert(0, current_dir_check)
        break
    current_dir_check = os.path.dirname(current_dir_check)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# 虛擬環境自動跳轉防呆機制 (若以全域 Python 啟動，自動切換至專案 .venv 執行)
ROOT_DIR = current_dir_check
_venv_py = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")
if os.path.exists(_venv_py) and os.path.normcase(sys.executable) != os.path.normcase(_venv_py):
    import subprocess
    sys.exit(subprocess.run([_venv_py] + sys.argv).returncode)

# 引入通訊套件
try:
    import serial
except ImportError:
    serial = None

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
    """動態載入 Spirent TestCenter API 核心，並注入全域命名空間 (依 SKILL.md 進行路徑變數隔離)"""
    print("\n正在載入 Spirent TestCenter API 與通訊工具，請稍候...")
    try:
        import utils.pythontool as pt
        # 排除模組內部私有或路徑變數，避免污染全域工作區命名空間
        excluded = {'current_dir', 'tool_tcl_path', 'lib_pathes', 'scripts', 'path'}
        for name in dir(pt):
            if not name.startswith('_') and name not in excluded:
                globals()[name] = getattr(pt, name)
    except ImportError as e:
        print(f"無法載入 pythontool: {e}")
        sys.exit(1)


def setup_spirent(chassisAddr: str, slotPortlist: list) -> tuple:
    """配置 Spirent TestCenter 預約 Port 並訂閱流量結果"""
    Connect(chassisAddr)
    ReservePort(chassisAddr, slotPortlist)
    
    project = tclsh.eval('CreateProject')
    port_objs = []
    for i in range(len(slotPortlist)):
        port_objs.append(tclsh.eval('CreatePort {0} {1} {2}'.format(slotPortlist[i], project, chassisAddr)))

    # 設定 Port 屬性 (雙工、速率、流控)
    for p in port_objs:
        CreatePortType_Copper(p, PortType_1G_Full_AN)
    print(f"Ports initialized: {port_objs}")

    tclsh.eval('Mapping')
    
    # 訂閱統計結果
    now = datetime.now()
    filename = "generatorTx" + now.strftime("%m%d%y%H%M%S")
    filename2 = "analyzerRx" + now.strftime("%m%d%y%H%M%S")
    filename3 = "droppedRx" + now.strftime("%m%d%y%H%M%S")
    
    result1 = ResultSubscribe_Tx(project, filename)
    result2 = ResultSubscribe_Rx(project, filename2)
    result3 = ResultSubscribe_Rxstreams(project, filename3)
    
    return project, port_objs, result1, result2, result3


def clear_results_and_streams(active_ports):
    """清除全域統計數據（包含埠與串流），防止 RxDrop 在 iteration 之間累加"""
    tclsh.eval("stc::perform ResultsClearAll")


def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """讀取 CSV 測試參數表 (具備防禦性解析與多路徑搜尋)"""
    candidate_paths = [
        csv_path,
        os.path.join(SCRIPT_DIR, csv_path),
        os.path.join(SCRIPT_DIR, "scenarios.csv"),
    ]
    # 若上一層或工作區根目錄有 scenarios.csv 也列入搜尋候選
    parent_dir = os.path.dirname(SCRIPT_DIR)
    if parent_dir:
        candidate_paths.append(os.path.join(parent_dir, csv_path))
        grand_dir = os.path.dirname(parent_dir)
        if grand_dir:
            candidate_paths.append(os.path.join(grand_dir, csv_path))

    resolved_path = None
    for cp in candidate_paths:
        if os.path.exists(cp):
            resolved_path = cp
            break

    if not resolved_path:
        print(f"錯誤：找不到參數表檔案 {csv_path}")
        sys.exit(1)

    print(f"-> 成功載入參數表: {resolved_path}")
    scenarios = []
    with open(resolved_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 防禦性清理欄位，避免 NoneType.strip() 錯誤 (SKILL.md Rule 12)
            clean_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k is not None}
            if not clean_row or not clean_row.get("Scenario"):
                continue
            
            # channel 與 Path 相容處理
            channel_val = clean_row.get("channel") or clean_row.get("Path") or "1"
            scenarios.append({
                "Scenario": clean_row.get("Scenario", ""),
                "Port0": clean_row.get("Port0", ""),
                "Port1": clean_row.get("Port1", ""),
                "PortTX": clean_row.get("PortTX", "").lower(),
                "PortRX": clean_row.get("PortRX", "").lower(),
                "channel": channel_val
            })
    return scenarios


def select_scenarios(scenarios: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """提示使用者選擇欲執行的 Scenario (支援單選、多選、直接 Enter 預設全部)"""
    print("\n可用的測試場景 (Scenarios):")
    for sc in scenarios:
        print(f"  Scenario {sc['Scenario']}: Port0={sc['Port0']}, Port1={sc['Port1']}, PortTX={sc['PortTX']}, PortRX={sc['PortRX']}, Channel={sc['channel']}")
    
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


####################### 主程式 ###########################

def main(com_port=None, iteration=None, power_down_delay=None, power_up_delay=None):
    print("=" * 65)
    print("  Cold Start Recovery Test (冷啟動斷電/復電恢復測試)")
    print("=" * 65)

    # --- [Phase 1] 參數蒐集與初始化 ---
    # 1.1 嚴格遵守 SKILL.md 規範使用 0 參數輸入函式
    if iteration is None:
        iteration = get_iteration_count()

    if power_down_delay is None:
        print("\n--- 請設定 Power Down 等待延遲時間 ---")
        power_down_delay = get_delay_time()

    if power_up_delay is None:
        print("\n--- 請設定 Power Up 開機重啟等待延遲時間 ---")
        power_up_delay = get_boot_wait_time()

    if com_port is None:
        # 提示制具 COM 埠 (支援直接 Enter 預設 COM2)
        try:
            val = input("請輸入斷線/電源制具 COM 埠 [直接 Enter 預設 COM2]: ").strip()
            com_port = val if val else "COM2"
        except Exception:
            com_port = get_com_port()

    # 1.2 選擇並讀取測試參數表
    all_scenarios = load_scenarios_from_csv("scenarios.csv")
    selected_scenarios = select_scenarios(all_scenarios)

    # 收集被選中場景使用埠的聯集 (Phase 2 一次性預約)
    used_ports_set = set()
    for sc in selected_scenarios:
        used_ports_set.add(sc["Port0"])
        used_ports_set.add(sc["Port1"])
    slotPortlist = sorted(list(used_ports_set))

    # Spirent 機箱設定
    default_chassis = "10.123.38.202"
    chassis_input = input(f"\n請輸入 Spirent 機箱 IP [直接 Enter 預設 {default_chassis}]: ").strip()
    chassisAddr = chassis_input if chassis_input else default_chassis

    # 動態載入 Spirent API 核心工具
    load_utils()

    # 日誌檔案使用集中式路徑 (test result/<測試目錄>_result/result.txt)
    log_filename = get_result_log_path(__file__, "result.txt")
    result1, result2, result3 = None, None, None
    project, port_objs = None, []
    ser = None

    try:
        # --- [Phase 2] 儀器與環境配置 (Spirent & Serial) ---
        # 2.1 配置 Spirent TestCenter 預約 Port 並建立專案
        print(f"\n連接 Spirent 機箱 ({chassisAddr}) 並預約連接埠 {slotPortlist} ...")
        project, port_objs, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)
        port_map = {slotPortlist[idx]: port_objs[idx] for idx in range(len(slotPortlist))}

        # 2.2 使用 Serial 連線斷線/電源制具，預設 115200 baud
        if serial is not None:
            try:
                ser = serial.Serial(port=com_port, baudrate=115200, timeout=0.5)
                print(f"成功連線電源制具 {com_port} (115200 baud)")
            except Exception as e:
                print(f"警告：無法開啟串口 {com_port}: {e}，將以模擬模式執行制具控制。")
                ser = None
        else:
            print("未安裝 pyserial 模組，跳過實體 Serial 控制。")

        # 前置通電與穩定環境 (確保 DUT 在測試開始前為通電運作狀態)
        print("\n發送前置通電穩定指令 (確保所有 Channel 均已開啟)...")
        for sc in selected_scenarios:
            ch = sc.get("channel", "1")
            if ser is not None:
                comm_CMD(ser, f"dc{ch} on\r".encode('ascii'))
        print("等待 3 秒使 DUT 電源與連線狀態穩定...")
        time.sleep(3)

        # 寫入測試日誌標頭
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*75}\n")
            f_log.write(f"開始 Cold Start Recovery (冷啟動斷電/復電恢復) 測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"機箱: {chassisAddr} | 測試埠口: {slotPortlist} | 制具 COM 埠: {com_port}\n")
            f_log.write(f"執行輪數: {iteration} 輪 | Power Down 等待: {power_down_delay} 秒 | Power Up 等待: {power_up_delay} 秒\n")
            f_log.write(f"{'='*75}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for sc_idx, sc in enumerate(selected_scenarios, 1):
            sc_id = sc["Scenario"]
            port0_str = sc["Port0"]
            port1_str = sc["Port1"]
            tx_target = sc["PortTX"]
            channel_id = sc["channel"]

            p0_obj = port_map[port0_str]
            p1_obj = port_map[port1_str]

            if tx_target == "port1":
                tx_port_obj = p1_obj
                rx_port_obj = p0_obj
                tx_port_str = port1_str
                rx_port_str = port0_str
            else:
                tx_port_obj = p0_obj
                rx_port_obj = p1_obj
                tx_port_str = port0_str
                rx_port_str = port1_str

            ports_pair = [p0_obj, p1_obj]

            print(f"\n{'#'*70}")
            print(f"  執行 Scenario {sc_id} ({sc_idx}/{len(selected_scenarios)}): TX={tx_port_str} -> RX={rx_port_str}, Channel={channel_id}")
            print(f"{'#'*70}")

            # 防呆清除前輪殘留 StreamBlock (確保兩端各為 0 個)
            for p in ports_pair:
                existing_sbs = tclsh.eval(f"stc::get {p} -children-StreamBlock").split()
                for sb in existing_sbs:
                    if sb:
                        try:
                            tclsh.eval(f"stc::delete {sb}")
                        except Exception:
                            pass

            # 依 SKILL.md Rule 10：兩端剛好各配對 1 個 StreamBlock，嚴防 invalid handle 陷阱
            sb0 = CreateStreamBlock(p0_obj, StreamBlock, Frame)
            sb1 = CreateStreamBlock(p1_obj, StreamBlock, Frame1)
            Generator(p0_obj, Generatortype)
            Generator(p1_obj, Generatortype)

            for it in range(1, iteration + 1):
                iter_header = f">>> Scenario {sc_id} - 第 {it}/{iteration} 次測試迴圈 [{datetime.now().strftime('%H:%M:%S')}] <<<"
                print(f"\n{iter_header}")

                # # 3.1 port [TX] 持續打單向封包
                print(f"[3.1] 清除全域統計並啟動單向流量 (TX: {tx_port_str})...")
                clear_results_and_streams(ports_pair)
                time.sleep(1)
                StartGenerator([tx_port_obj])
                print("-> 等待 2 秒使初始流量發送穩定...")
                time.sleep(2)

                # # 3.2 COM port 發送 power off 指令 dc{channel} off
                off_cmd_str = f"dc{channel_id} off"
                t_off = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{t_off}] [3.2] 發送 Power Off 指令: {off_cmd_str}")
                if ser is not None:
                    comm_CMD(ser, f"{off_cmd_str}\r".encode('ascii'))

                # # 3.3 等待使用者定義的「power down等待延遲時間」
                print(f"[3.3] 等待 Power Down 延遲時間 ({power_down_delay} 秒)...")
                time.sleep(power_down_delay)

                # # 3.4 停止流量 (Stop Traffic)，並獲取數據並判定
                print("[3.4] 停止流量並獲取數據...")
                StopGenerator([tx_port_obj])
                time.sleep(1)

                datalist_off = getdata(ports_pair)
                p0_tx_off = int(datalist_off[0][2])
                p0_rx_off = int(datalist_off[0][1])
                p1_tx_off = int(datalist_off[1][2])
                p1_rx_off = int(datalist_off[1][1])

                tx_cnt_off = p0_tx_off if tx_target == "port0" else p1_tx_off
                rx_cnt_off = p1_rx_off if tx_target == "port0" else p0_rx_off
                drop_off = max(0, tx_cnt_off - rx_cnt_off)
                loss_rate_off = (drop_off / tx_cnt_off * 100.0) if tx_cnt_off > 0 else 0.0

                log_entry_off = (
                    f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} 輪次 {it:02d}/{iteration:02d} [Power Down / 斷電]: "
                    f"TX={tx_cnt_off}, RX={rx_cnt_off}, 掉包數={drop_off} (丟失率 {loss_rate_off:.2f}%)\n"
                )
                print(f"-> {log_entry_off.strip()}")
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(log_entry_off)

                # # 3.5 清除結果統計數據
                print("[3.5] 清除結果統計數據 (ResultsClearAll)...")
                clear_results_and_streams(ports_pair)
                time.sleep(1)

                # # 3.6 port [TX] 持續打單向封包
                print(f"[3.6] 重新啟動單向流量 (TX: {tx_port_str})...")
                StartGenerator([tx_port_obj])
                time.sleep(1)

                # # 3.7 COM port 發送 power on 指令 dc{channel} on
                on_cmd_str = f"dc{channel_id} on"
                t_on = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{t_on}] [3.7] 發送 Power On 指令: {on_cmd_str}")
                if ser is not None:
                    comm_CMD(ser, f"{on_cmd_str}\r".encode('ascii'))

                # # 3.8 等待使用者定義的「power up 等待延遲時間」
                print(f"[3.8] 等待 Power Up 開機重啟延遲時間 ({power_up_delay} 秒)...")
                time.sleep(power_up_delay)

                # # 3.9 停止流量 (Stop Traffic)，並獲取數據並判定
                print("[3.9] 停止流量並獲取數據...")
                StopGenerator([tx_port_obj])
                time.sleep(1)

                datalist_on = getdata(ports_pair)
                p0_tx_on = int(datalist_on[0][2])
                p0_rx_on = int(datalist_on[0][1])
                p1_tx_on = int(datalist_on[1][2])
                p1_rx_on = int(datalist_on[1][1])

                tx_cnt_on = p0_tx_on if tx_target == "port0" else p1_tx_on
                rx_cnt_on = p1_rx_on if tx_target == "port0" else p0_rx_on
                drop_on = max(0, tx_cnt_on - rx_cnt_on)
                loss_rate_on = (drop_on / tx_cnt_on * 100.0) if tx_cnt_on > 0 else 0.0

                log_entry_on = (
                    f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} 輪次 {it:02d}/{iteration:02d} [Power Up / 復電開機恢復]: "
                    f"TX={tx_cnt_on}, RX={rx_cnt_on}, 掉包數={drop_on} (丟失率 {loss_rate_on:.2f}%)\n"
                )
                print(f"-> {log_entry_on.strip()}")
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(log_entry_on)

                # # 3.10 清除結果統計數據，進入下一輪
                print("[3.10] 清除統計數據，完成本輪測試。")
                clear_results_and_streams(ports_pair)
                time.sleep(1)

            # 場景結束，清理該場景的 StreamBlock 物件
            print(f"\n清理 Scenario {sc_id} 的 StreamBlock 物件...")
            try:
                tclsh.eval(f"stc::delete {sb0}")
            except Exception:
                pass
            try:
                tclsh.eval(f"stc::delete {sb1}")
            except Exception:
                pass

        print("\n" + "=" * 65)
        print("  所有選定測試場景執行完成！")
        print("=" * 65)

    except KeyboardInterrupt:
        print("\n使用者手動中斷測試 (Ctrl+C)。")
    except Exception as e:
        print(f"\n測試執行過程中發生未預期異常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # --- 資源必定安全清理 (Teardown) ---
        print("\n正在執行環境與資源釋放...")
        if ser is not None:
            try:
                # 安全防護：確保離開前設備維持通電狀態
                for sc in selected_scenarios:
                    ch = sc.get("channel", "1")
                    comm_CMD(ser, f"dc{ch} on\r".encode('ascii'))
                ser.close()
                print("已關閉 Serial 連線並確認恢復 DUT 通電狀態。")
            except Exception as e:
                print(f"關閉 Serial 異常: {e}")

        for res in [result1, result2, result3]:
            if res is not None:
                try:
                    unsubscribe(res)
                except Exception as e:
                    print(f"取消訂閱異常: {e}")

        if project is not None:
            try:
                tclsh.eval(f"stc::delete {project}")
                print("已刪除 Spirent Project。")
            except Exception as e:
                print(f"刪除 Project 異常: {e}")

        try:
            Disconnect(chassisAddr)
            print(f"已自 Spirent 機箱 {chassisAddr} 中斷連線並釋放預約連接埠。")
        except Exception as e:
            print(f"中斷連線機箱異常: {e}")

        print(f"測試結束。日誌已追加儲存至 {log_filename}")


if __name__ == "__main__":
    main()
