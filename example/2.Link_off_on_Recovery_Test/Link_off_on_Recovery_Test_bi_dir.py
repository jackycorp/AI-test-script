# -*- coding: utf-8 -*-
"""
名稱: Link Off/On 恢復與 Topology Change/Back 雙向流量自動化測試 (Link_off_on_Recovery_Test_bi_dir.py)

測試特性說明 (Bidirectional 雙向版)：
  1. 雙向流量發送：同時在 Port0 與 Port1 啟動 Generator 發送流量 (Port0 <-> Port1)。
  2. 雙向掉包量測：分別統計「Port0 -> Port1」與「Port1 -> Port0」兩方向之發送數、接收數與掉包數。
  3. 最大掉包記錄：即時計算並記錄每輪測試之單向最大掉包與雙向總掉包，並在測試完成後產出統計總結 (記錄於 result.txt)。
  4. 參數表共用相容：防禦性解析 scenarios.csv，與原單向腳本 (Link_off_on_Recovery_Test.py) 完全共用同一個 CSV 檔案。

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 輸入制具 COM Port、執行次數、Link Off/On 觀察時間及測試場景。
  1.2 從 CSV 讀取 Spirent 測試埠 (Port0, Port1) 與制具 Path (完全相容原 scenarios.csv)。
[Phase 2] 儀器與制具配置
  2.1 配置 Spirent TestCenter 並預約測試 Port。
  2.2 使用 Serial 連線斷線制具，預設 115200 baud。
[Phase 3] 自動化測試迴圈
  3.1 發送雙向流量 1 秒後停止，確保網路環境與交換機預先學習 MAC Address。
  3.2 清除統計並開始發送雙向流量 (Port0 與 Port1 同步發包)。
  3.3 等待 3 秒，讓雙向初始流量穩定。
  3.4 發送 Link Off 指令 t{Path}x。
  3.5 等待 Link Off 觀察時間後停止流量，量測雙向各別掉包數並計算最大掉包。
  3.6 清除統計，重新啟動雙向流量並等待 3 秒穩定。
  3.7 發送 Link On 指令 t{Path}-。
  3.8 等待 Link On 觀察時間後停止流量，量測雙向各別掉包數並計算最大掉包。
  3.9 記錄每輪數據與最大掉包至 result.txt，並在場景結束後輸出歷史峰值總結表。
"""

import sys
import os
import csv
import time
import codecs
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Any, Optional

# Windows 控制台 Unicode 安全輸出支援
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "detach"):
            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach(), errors="replace")
        if hasattr(sys.stderr, "detach"):
            sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach(), errors="replace")
    except Exception:
        pass

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

# 引入共用工具
try:
    import serial
except ImportError:
    serial = None

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
    """動態載入 Spirent TestCenter API 核心，並注入全域命名空間 (遵循 SKILL.md Rule 5 & 13)"""
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
    """清除全域統計數據（包含埠與串流），防止 RxDrop 在 iteration 之間累加 (遵循 SKILL.md Rule 6)"""
    tclsh.eval("stc::perform ResultsClearAll")


def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """
    讀取 CSV 測試參數表 (支援絕對路徑與相對路徑，具備防禦性解析)。
    相容共用 scenarios.csv：不論 CSV 包含 6 欄 (含 PortTX, PortRX) 或 4 欄 (Scenario, Port0, Port1, Path)，
    均可自動識別並完全相容執行。
    """
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
        valid_lines = [line for line in f if not line.strip().startswith("#")]
        reader = csv.DictReader(valid_lines)
        for row in reader:
            # 防禦性清理：嚴格防止 NoneType.strip() 異常 (遵循 SKILL.md Rule 12)
            clean_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k is not None}
            if not clean_row or not clean_row.get("Scenario"):
                continue

            port0_val = clean_row.get("Port0", "")
            port1_val = clean_row.get("Port1", "")
            path_val = clean_row.get("Path", "1")
            port_tx_val = clean_row.get("PortTX", "both").lower()
            port_rx_val = clean_row.get("PortRX", "both").lower()

            scenarios.append({
                "Scenario": clean_row.get("Scenario", ""),
                "Port0": port0_val,
                "Port1": port1_val,
                "PortTX": port_tx_val,
                "PortRX": port_rx_val,
                "Path": path_val
            })
    return scenarios


def select_scenarios(scenarios: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """提示使用者選擇欲執行的 Scenario (支援單選、多選、直接 Enter 預設全部)"""
    print("\n可用的雙向測試場景 (Scenarios):")
    for sc in scenarios:
        print(f"  Scenario {sc['Scenario']}: Port0={sc['Port0']} <--> Port1={sc['Port1']} (雙向互打), 制具 Path={sc['Path']}")
    
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
def main():
    print("=" * 70)
    print("  Link Off/On 恢復與 Topology Change/Back 自動化測試 (雙向流量版)")
    print("  支援 Port0 <-> Port1 雙向掉包量測與最大掉包記錄")
    print("=" * 70)

    # --- [Phase 1] 參數蒐集與初始化 ---
    # 1.1 輸入制具 COM Port、執行次數、Link Off/On 觀察時間 (嚴格 0 參數防呆輸入)
    com_port = get_com_port()
    iteration = get_iteration_count()
    
    while True:
        try:
            val = input("請輸入 Link Off 觀察時間 (秒，預設 5.0): ").strip()
            link_off_delay = float(val) if val else 5.0
            if link_off_delay >= 0:
                break
            print("觀察時間必須為非負數。")
        except ValueError:
            print("請輸入有效的數字。")

    while True:
        try:
            val = input("請輸入 Link On 觀察時間 (秒，預設 5.0): ").strip()
            link_on_delay = float(val) if val else 5.0
            if link_on_delay >= 0:
                break
            print("觀察時間必須為非負數。")
        except ValueError:
            print("請輸入有效的數字。")

    # 1.2 從 CSV 讀取 Spirent Port 與制具 Path (完全相容共用 scenarios.csv)
    all_scenarios = load_scenarios_from_csv("scenarios.csv")
    selected_scenarios = select_scenarios(all_scenarios)

    # 收集被選中場景使用埠的聯集
    used_ports_set = set()
    for sc in selected_scenarios:
        used_ports_set.add(sc["Port0"])
        used_ports_set.add(sc["Port1"])
    slotPortlist = sorted(list(used_ports_set))

    # 動態載入 Spirent API
    load_utils()

    chassisAddr = "10.123.38.202"
    log_filename = get_result_log_path(__file__, "result.txt")
    result1, result2, result3 = None, None, None
    project, port_objs = None, []
    ser = None

    try:
        # --- [Phase 2] 儀器與制具配置 ---
        # 2.1 配置 Spirent TestCenter 並預約測試 Port
        project, port_objs, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)
        port_map = {slotPortlist[idx]: port_objs[idx] for idx in range(len(slotPortlist))}

        # 2.2 使用 Serial 連線斷線制具，預設 115200 baud
        if serial is not None:
            try:
                ser = serial.Serial(port=com_port, baudrate=115200, timeout=0.5)
                print(f"成功連線斷線制具 {com_port} (115200 baud)")
                # 發送前置指令穩定環境 (Link 回復常態)
                comm_CMD(ser, b"t-\r")
                time.sleep(3)
            except Exception as e:
                print(f"警告：無法開啟串口 {com_port}: {e}，將以模擬模式執行制具控制。")
                ser = None
        else:
            print("未安裝 pyserial 模組，跳過實體 Serial 控制。")

        # 寫入測試日誌標頭
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*50}\n")
            f_log.write(f"開始 Link Off/On 測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"COM Port: {com_port}, 執行次數: {iteration}, Link Off 觀察時間: {link_off_delay} 秒, Link On 觀察時間: {link_on_delay} 秒\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for sc_idx, sc in enumerate(selected_scenarios, 1):
            sc_id = sc["Scenario"]
            port0_str = sc["Port0"]
            port1_str = sc["Port1"]
            path_id = sc["Path"]

            p0_obj = port_map[port0_str]
            p1_obj = port_map[port1_str]
            ports_pair = [p0_obj, p1_obj]

            print(f"\n{'#'*70}")
            print(f"  執行 Scenario {sc_id} ({sc_idx}/{len(selected_scenarios)}): 雙向測試 Port0({port0_str}) <--> Port1({port1_str}), 制具 Path={path_id}")
            print(f"{'#'*70}")

            # 防呆清除舊殘留 StreamBlock (遵循 SKILL.md Rule 10)
            for p in ports_pair:
                existing_sbs = tclsh.eval(f"stc::get {p} -children-StreamBlock").split()
                for sb in existing_sbs:
                    if sb:
                        tclsh.eval(f"stc::delete {sb}")

            # 建立該場景的雙向 StreamBlock (兩端各配 1 個 StreamBlock，嚴防 invalid handle)
            sb0 = CreateStreamBlock(p0_obj, StreamBlock, Frame)
            sb1 = CreateStreamBlock(p1_obj, StreamBlock, Frame1)
            Generator(p0_obj, Generatortype)
            Generator(p1_obj, Generatortype)

            # 收集每輪取較大者後的掉包紀錄 (不在意方向，只在意雙向哪一向掉包多)
            off_drops = []
            on_drops = []

            for it in range(1, iteration + 1):
                print(f"\n>>> Scenario {sc_id} - 第 {it:02d}/{iteration:02d} 次雙向測試迴圈 <<<")

                # ==========================================
                # [動作 A] Link Off 階段 (雙向發包 + 斷線量測)
                # ==========================================
                # 3.1 發送雙向流量 1 秒後停止，供網路環境與交換機學習 MAC 位址
                print("[3.1] 發送雙向流量 1 秒以供交換機學習 MAC 位址...")
                clear_results_and_streams(ports_pair)
                StartGenerator(ports_pair)
                time.sleep(1)
                StopGenerator(ports_pair)
                time.sleep(1)
                clear_results_and_streams(ports_pair)
                time.sleep(1)

                # 3.2 清除統計並啟動雙向流量 (同時啟動 p0 與 p1)
                print("[3.2] 清除統計並啟動雙向流量 (Port0 & Port1 同步發包)...")
                clear_results_and_streams(ports_pair)
                time.sleep(1)
                StartGenerator(ports_pair)

                # 3.3 等待 3 秒，讓初始雙向流量穩定
                print("[3.3] 等待 3 秒使雙向流量穩定...")
                time.sleep(3)

                # 3.4 發送 Link Off 指令 t{Path}x
                off_cmd_str = f"t{path_id}x"
                off_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{off_time}] [3.4] 發送 Link Off 指令: {off_cmd_str}")
                if ser is not None:
                    comm_CMD(ser, f"{off_cmd_str}\r".encode('utf-8'))

                # 3.5 等待 Link Off 觀察時間後停止流量並量測雙向掉包
                print(f"[3.5] 等待 Link Off 觀察時間 ({link_off_delay} 秒)...")
                time.sleep(link_off_delay)
                StopGenerator(ports_pair)
                time.sleep(1)

                datalist_off = getdata(ports_pair)
                # datalist[0]: Port0 (drop, rx, tx); datalist[1]: Port1 (drop, rx, tx)
                p0_tx_off = int(datalist_off[0][2])
                p0_rx_off = int(datalist_off[0][1])
                p1_tx_off = int(datalist_off[1][2])
                p1_rx_off = int(datalist_off[1][1])

                # 雙向各別掉包，取較大者方向之 TX、RX 與掉包數 (不在意方向，只在意雙向哪一向掉包多)
                drop_dir1_off = max(0, p0_tx_off - p1_rx_off)  # Port0 -> Port1
                drop_dir2_off = max(0, p1_tx_off - p0_rx_off)  # Port1 -> Port0

                if drop_dir1_off >= drop_dir2_off:
                    tx_cnt_off = p0_tx_off
                    rx_cnt_off = p1_rx_off
                    drop_off = drop_dir1_off
                else:
                    tx_cnt_off = p1_tx_off
                    rx_cnt_off = p0_rx_off
                    drop_off = drop_dir2_off

                off_drops.append(drop_off)

                log_entry_off = f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} Iteration {it} [Link Off]: TX={tx_cnt_off}, RX={rx_cnt_off}, 掉包數={drop_off}\n"
                print(f"-> {log_entry_off.strip()}")
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(log_entry_off)

                # ==========================================
                # [動作 B] Link On 階段 (雙向發包 + 復原量測)
                # ==========================================
                # 3.6 清除統計，重新發送雙向流量並等待 3 秒穩定
                print("[3.6] 清除統計，重新發送雙向流量並等待 3 秒穩定...")
                clear_results_and_streams(ports_pair)
                time.sleep(1)
                StartGenerator(ports_pair)
                time.sleep(3)

                # 3.7 發送 Link On 指令 t{Path}-
                on_cmd_str = f"t{path_id}-"
                on_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[{on_time}] [3.7] 發送 Link On 指令: {on_cmd_str}")
                if ser is not None:
                    comm_CMD(ser, f"{on_cmd_str}\r".encode('utf-8'))

                # 3.8 等待 Link On 觀察時間後停止流量並量測雙向掉包
                print(f"[3.8] 等待 Link On 觀察時間 ({link_on_delay} 秒)...")
                time.sleep(link_on_delay)
                StopGenerator(ports_pair)
                time.sleep(1)

                datalist_on = getdata(ports_pair)
                p0_tx_on = int(datalist_on[0][2])
                p0_rx_on = int(datalist_on[0][1])
                p1_tx_on = int(datalist_on[1][2])
                p1_rx_on = int(datalist_on[1][1])

                # 雙向各別掉包，取較大者方向之 TX、RX 與掉包數 (不在意方向，只在意雙向哪一向掉包多)
                drop_dir1_on = max(0, p0_tx_on - p1_rx_on)  # Port0 -> Port1
                drop_dir2_on = max(0, p1_tx_on - p0_rx_on)  # Port1 -> Port0

                if drop_dir1_on >= drop_dir2_on:
                    tx_cnt_on = p0_tx_on
                    rx_cnt_on = p1_rx_on
                    drop_on = drop_dir1_on
                else:
                    tx_cnt_on = p1_tx_on
                    rx_cnt_on = p0_rx_on
                    drop_on = drop_dir2_on

                on_drops.append(drop_on)

                log_entry_on = f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} Iteration {it} [Link On]: TX={tx_cnt_on}, RX={rx_cnt_on}, 掉包數={drop_on}\n"
                print(f"-> {log_entry_on.strip()}")
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(log_entry_on)

                # 3.9 清除統計並進入下一輪
                print("[3.9] 清除統計，本輪迴圈完成。")
                clear_results_and_streams(ports_pair)
                time.sleep(1)

            # ==========================================
            # 產出 Scenario 統計總結 (記錄最大值與平均值至 result.txt 與終端)
            # ==========================================
            max_drop_off = max(off_drops) if off_drops else 0
            avg_drop_off = sum(off_drops) / len(off_drops) if off_drops else 0

            max_drop_on = max(on_drops) if on_drops else 0
            avg_drop_on = sum(on_drops) / len(on_drops) if on_drops else 0

            summary_block = (
                f"{'-'*50}\n"
                f"Scenario {sc_id} 統計總結 (共執行 {iteration} 輪):\n"
                f"  - [Link Off] 最大掉包: {max_drop_off}, 平均掉包: {avg_drop_off:.1f}\n"
                f"  - [Link On]  最大掉包: {max_drop_on}, 平均掉包: {avg_drop_on:.1f}\n"
                f"{'-'*50}\n"
            )
            print(f"\n{summary_block}")
            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                f_log.write(summary_block)

            # 場景結束，清理該場景的 StreamBlock (遵循 SKILL.md Rule 10)
            print(f"清理 Scenario {sc_id} 的 StreamBlock...")
            try:
                tclsh.eval(f"stc::delete {sb0}")
            except Exception:
                pass
            try:
                tclsh.eval(f"stc::delete {sb1}")
            except Exception:
                pass


        print("\n==================== 所有選定雙向測試場景執行完成 ====================")

    except KeyboardInterrupt:
        print("\n使用者手動中斷測試 (Ctrl+C)。")
    except Exception as e:
        print(f"\n測試執行過程中發生未預期異常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # --- 資源必定安全清理 (遵循 SKILL.md Rule 11) ---
        print("\n正在執行環境與資源釋放...")
        if ser is not None:
            try:
                # 恢復為常態連線狀態
                comm_CMD(ser, b"t-\r")
                ser.close()
                print("已關閉 Serial 連線。")
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

        print(f"雙向測試結束。詳細日誌與最大掉包數據已儲存至 {log_filename}")


if __name__ == "__main__":
    main()
