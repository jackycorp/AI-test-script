# -*- coding: utf-8 -*-
"""
名稱: Warm Start 恢復與 Topology Change/Back 測試 (Warm_start_Recovery_Test.py)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 「執行次數」、「topology change 等待延遲時間」、「topology back 等待延遲時間」、「DUT 登入帳號與密碼」、「選擇測試場景（單選/多選/預設全部）」
  1.2 選擇並讀取測試參數表。
[Phase 2] 儀器與環境配置 (Spirent & Serial)
  2.1 配置 Spirent TestCenter 預約 Port 並建立 Stream。
[Phase 3] 自動化測試迴圈
  對於所選的各個 Scenario 進行以下迴圈測試：
  3.1 ping DUT ，若失敗則跳出迴圈
  3.2 telnet 登入DUT，若失敗則跳出迴圈
  3.3 port [TX] 持續打單向封包
  3.4 等待 1 秒流量穩定 (time sleep 1s)
  3.5 telnet 發送 "re" 指令，執行warm start
  3.6 等待使用者定義的「topology change 等待延遲時間」
  3.7 停止流量 (Stop Traffic)，並獲取數據並判定：
      - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
  3.8 清除結果統計數據
  3.9 port [TX] 持續打單向封包
  3.10 等待使用者定義的「topology back  等待延遲時間」
  3.11 停止流量 (Stop Traffic)，並獲取數據並判定：
      - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
  3.12 清除telnet session ，並等候1s
  3.13 清除結果統計數據，進入下一輪。
"""

import sys
import os
import csv
import time
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Tuple, Optional

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

# 引入共用工具
try:
    from utils.dictionary_parameters import *
    from utils.comm_helper import *
except ImportError as e:
    print(f"無法載入 dictionary_parameters 或 comm_helper: {e}")
    sys.exit(1)

if TYPE_CHECKING:
    from utils.pythontool import *





def load_utils():
    """動態載入 Spirent TestCenter API 核心，並注入全域命名空間"""
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
    """讀取 Warm Start CSV 測試參數表 (支援絕對路徑與相對路徑，具備防禦性解析)"""
    if not os.path.isabs(csv_path):
        candidate_paths = [
            csv_path,
            os.path.join(SCRIPT_DIR, csv_path),
            os.path.join(ROOT_DIR, csv_path),
            os.path.join(os.getcwd(), csv_path)
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
                "Port0": clean_row.get("Port0", ""),
                "Port1": clean_row.get("Port1", ""),
                "PortTX": clean_row.get("PortTX", "").lower(),
                "PortRX": clean_row.get("PortRX", "").lower(),
                "DUT_IP": ip_val
            })
    return scenarios


def select_scenarios(scenarios: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """提示使用者選擇欲執行的 Scenario (支援單選、多選、直接 Enter 預設全部)"""
    print("\n可用的測試場景 (Scenarios):")
    for sc in scenarios:
        print(f"  Scenario {sc['Scenario']}: Port0={sc['Port0']}, Port1={sc['Port1']}, PortTX={sc['PortTX']}, PortRX={sc['PortRX']}, IP={sc['DUT_IP']}")
    
    while True:
        choice = input("\n請選擇要執行的場景 (例如單選: 1, 多選: 1,2,5，直接 Enter 預設全部): ").strip()
        if not choice or choice.lower() == "all":
            print("-> 已選擇執行所有場景 (All Scenarios)")
            return scenarios
        
        selected_ids = [s.strip() for s in choice.split(",") if s.strip()]
        selected_scenarios = [sc for sc in scenarios if sc["Scenario"] in selected_ids]
        if selected_scenarios:
            chosen_str = ", ".join([sc["Scenario"] for sc in selected_scenarios])
            print(f"-> 已選擇執行場景: Scenario {chosen_str}")
            return selected_scenarios
        print("未找到符合的場景編號，請重新輸入。")


def get_telnet_credentials(default_user: str = "admin", default_pwd: str = "moxa") -> Tuple[str, str]:
    """提示使用者輸入 DUT 登入帳號與密碼 (支援直接 Enter 套用預設值)"""
    user_input = input(f"請輸入 DUT 登入帳號 (直接 Enter 預設 '{default_user}'): ").strip()
    username = user_input if user_input else default_user

    pwd_input = input(f"請輸入 DUT 登入密碼 (直接 Enter 預設 '{default_pwd}'): ").strip()
    password = pwd_input if pwd_input else default_pwd

    print(f"-> 已設定 Telnet 登入帳號: '{username}'")
    return username, password


####################### 主程式 ###########################
def main(iteration=None, change_delay_time=None, back_delay_time=None, username=None, password=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    if iteration is None:
        iteration = get_iteration_count()

    if change_delay_time is None:
        while True:
            try:
                change_delay_time = float(input("請輸入 topology change 等待延遲時間 (秒): ").strip())
                if change_delay_time >= 0:
                    break
            except ValueError:
                print("請輸入有效的數字。")

    if back_delay_time is None:
        while True:
            try:
                back_delay_time = float(input("請輸入 topology back 等待延遲時間 (秒): ").strip())
                if back_delay_time >= 0:
                    break
            except ValueError:
                print("請輸入有效的數字。")

    # 1.1 提示輸入 DUT 帳號與密碼
    if username is None or password is None:
        username, password = get_telnet_credentials(default_user="admin", default_pwd="moxa")

    # 1.2 選擇並讀取測試參數表
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

    try:
        # --- [Phase 2] 儀器與環境配置 (Spirent & Serial) ---
        project, port_objs, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)

        # 建立 Slot/Port 到 Port 物件的對照字典
        port_map = {slotPortlist[idx]: port_objs[idx] for idx in range(len(slotPortlist))}

        # 寫入日誌檔標頭
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*50}\n")
            f_log.write(f"開始 Warm Start (Change & Back) 測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"執行次數: {iteration}, Topology Change 等待時間: {change_delay_time} 秒, Topology Back 等待時間: {back_delay_time} 秒, 登入帳號: {username}\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for sc in selected_scenarios:
            sc_id = sc["Scenario"]
            p0_str = sc["Port0"]
            p1_str = sc["Port1"]
            ptx_name = sc["PortTX"]  # 'port0' or 'port1'
            prx_name = sc["PortRX"]
            dut_ip = sc["DUT_IP"]

            port0_obj = port_map[p0_str]
            port1_obj = port_map[p1_str]
            ports_pair = [port0_obj, port1_obj]

            # 確定 TX / RX 埠物件
            if ptx_name == "port0":
                tx_port_obj = port0_obj
                rx_port_obj = port1_obj
            else:
                tx_port_obj = port1_obj
                rx_port_obj = port0_obj

            print(f"\n==================== 開始執行 Scenario {sc_id} ====================")
            print(f"Port0: {p0_str}, Port1: {p1_str}, PortTX: {ptx_name}, PortRX: {prx_name}, DUT IP: {dut_ip}")

            # 防呆清除：確保 Port 上沒有上次殘留的舊 StreamBlock，防止 getdata 解析多個 handle 異常
            for p in [port0_obj, port1_obj]:
                try:
                    old_sbs = tclsh.eval(f"stc::get {p} -children-StreamBlock").split()
                    for old_sb in old_sbs:
                        tclsh.eval(f"stc::delete {old_sb}")
                except Exception:
                    pass

            # 動態建立 Stream Block (每個 Scenario 建立一次)
            sb0 = CreateStreamBlock(port0_obj, StreamBlock, Frame)
            sb1 = CreateStreamBlock(port1_obj, StreamBlock, Frame1)
            Generator(port0_obj, Generatortype)
            Generator(port1_obj, Generatortype)

            for i in range(iteration):
                print(f"\n--- Scenario {sc_id} | 第 {i+1}/{iteration} 次循環 ---")

                # 3.1 ping DUT ，若失敗則跳出迴圈
                print(f"[3.1] 正在 Ping DUT ({dut_ip})...")
                ping_success = Pingfunc(dut_ip, times=1)
                if not ping_success:
                    msg = f"Scenario {sc_id} Iteration {i+1}: Ping DUT ({dut_ip}) 失敗，跳出此場景測試"
                    print(f"[FAIL] {msg}")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        f_log.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                    break

                # 3.2 telnet 登入DUT，若失敗則跳出迴圈
                print(f"[3.2] 正在 Telnet 登入 DUT ({dut_ip}) (帳號: {username})...")
                tn = telnet_login(dut_ip, username=username, password=password)
                if tn is None:
                    msg = f"Scenario {sc_id} Iteration {i+1}: Telnet 登入 DUT ({dut_ip}) 失敗，跳出此場景測試"
                    print(f"[FAIL] {msg}")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        f_log.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                    break

                try:
                    # 3.3 port [TX] 持續打單向封包
                    print(f"[3.3] 清除歷史數據，Port [{ptx_name}] 開始發送單向流量...")
                    clear_results_and_streams(ports_pair)
                    StartGenerator([tx_port_obj])

                    # 3.4 等待 1 秒流量穩定 (time sleep 1s)
                    print("[3.4] 等待 1 秒使流量穩定...")
                    time.sleep(1)

                    # 3.5 telnet 發送 "re" 指令，執行warm start
                    cmd_timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    print(f"[3.5] [{cmd_timestamp}] Telnet 發送 're' 指令並確認 'y' 執行 Warm Start...")
                    comm_TELNET(tn, 'Enter', 're')
                    time.sleep(1)
                    comm_TELNET(tn, 'reload', 'y')

                    # 3.6 等待使用者定義的「topology change 等待延遲時間」
                    print(f"[3.6] 等待 Topology Change 延遲: {change_delay_time} 秒...")
                    time.sleep(change_delay_time)

                    # 3.7 停止流量 (Stop Traffic)，並獲取數據並判定
                    print("[3.7] [Topology Change] 停止流量並統計封包...")
                    StopGenerator([tx_port_obj])
                    time.sleep(1)

                    datalist_change = getdata(ports_pair)
                    p0_tx_c = int(datalist_change[0][2])
                    p0_rx_c = int(datalist_change[0][1])
                    p1_tx_c = int(datalist_change[1][2])
                    p1_rx_c = int(datalist_change[1][1])

                    tx_pkts_c = p0_tx_c if ptx_name == "port0" else p1_tx_c
                    rx_pkts_c = p1_rx_c if ptx_name == "port0" else p0_rx_c
                    lost_pkts_c = tx_pkts_c - rx_pkts_c

                    msg_change = (f"Scenario {sc_id} Iteration {i+1} [Topology Change]: "
                                  f"TX={tx_pkts_c}, RX={rx_pkts_c}, 掉包數={lost_pkts_c}")
                    print(f"[RESULT] {msg_change}")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        f_log.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg_change}\n")

                    # 3.8 清除結果統計數據
                    print("[3.8] 清除 Topology Change 結果統計數據...")
                    clear_results_and_streams(ports_pair)

                    # 3.9 port [TX] 持續打單向封包
                    print(f"[3.9] Port [{ptx_name}] 再次發送單向流量 (Topology Back 階段)...")
                    StartGenerator([tx_port_obj])

                    # 3.10 等待使用者定義的「topology back 等待延遲時間」
                    print(f"[3.10] 等待 Topology Back 延遲: {back_delay_time} 秒...")
                    time.sleep(back_delay_time)

                    # 3.11 停止流量 (Stop Traffic)，並獲取數據並判定
                    print("[3.11] [Topology Back] 停止流量並統計封包...")
                    StopGenerator([tx_port_obj])
                    time.sleep(1)

                    datalist_back = getdata(ports_pair)
                    p0_tx_b = int(datalist_back[0][2])
                    p0_rx_b = int(datalist_back[0][1])
                    p1_tx_b = int(datalist_back[1][2])
                    p1_rx_b = int(datalist_back[1][1])

                    tx_pkts_b = p0_tx_b if ptx_name == "port0" else p1_tx_b
                    rx_pkts_b = p1_rx_b if ptx_name == "port0" else p0_rx_b
                    lost_pkts_b = tx_pkts_b - rx_pkts_b

                    msg_back = (f"Scenario {sc_id} Iteration {i+1} [Topology Back]: "
                                f"TX={tx_pkts_b}, RX={rx_pkts_b}, 掉包數={lost_pkts_b}")
                    print(f"[RESULT] {msg_back}")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        f_log.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg_back}\n")

                finally:
                    # 3.12 清除telnet session ，並等候1s
                    print("[3.12] 關閉 Telnet Session 並等待 1 秒...")
                    try:
                        tn.close()
                    except Exception as ex:
                        print(f"關閉 Telnet 例外: {ex}")
                    time.sleep(1)

                    # 3.13 清除結果統計數據，進入下一輪。
                    print("[3.13] 清除全域統計數據，準備進入下一輪循環...")
                    clear_results_and_streams(ports_pair)
                    time.sleep(0.5)

            # 清除當前場景建立的 Stream Block，防止 handle 殘留與疊加
            for sb in [sb0, sb1]:
                try:
                    tclsh.eval(f"stc::delete {sb}")
                except Exception:
                    pass

    except Exception as e:
        print(f"\n測試執行過程中發生未預期異常: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # 資源清理保護區塊 (Resource Teardown)
        print("\n==================== 執行資源釋放與環境清理 ====================")
        for res in [result1, result2, result3]:
            if res is not None:
                try:
                    unsubscribe(res)
                except Exception:
                    pass
        if project:
            try:
                tclsh.eval(f"stc::delete {project}")
                print("Spirent 專案已清除。")
            except Exception as e:
                print(f"清除專案時例外: {e}")
        try:
            Disconnect(chassisAddr)
            print("已自 Spirent Chassis 中斷連線。")
        except Exception:
            pass
        print("資源安全釋放完畢。測試結束。")


if __name__ == "__main__":
    main()
