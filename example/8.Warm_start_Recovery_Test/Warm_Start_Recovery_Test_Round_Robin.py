# -*- coding: utf-8 -*-
"""
名稱: Warm Start 跨場景輪詢恢復測試 (Warm_start_Recovery_Test_round_robin.py)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 「輪詢次數」、「topology change 等待延遲時間」、「topology back 等待延遲時間」、「DUT 登入帳密」、「選擇測試場景（單選/多選/預設全部）」
  1.2 選擇並讀取測試參數表。
[Phase 2] 儀器與環境配置 (Spirent & Serial)
  2.1 配置 Spirent TestCenter 預約 Port 並建立 Stream。
  2.2 建立本次測試的 PCAP 輸出目錄。
[Phase 3] 自動化測試迴圈
  對於所選的各個 Scenario 進行輪詢迴圈測試（選中之 Scenario 依序執行 1 次為一輪，重複 N 輪）：
  3.1 ping DUT ，若失敗則跳出迴圈
  3.2 telnet 登入DUT，若失敗則跳出迴圈
  3.3 在 TX Port 啟動 Topology Change 封包擷取。
  3.4 port [TX] 持續打單向封包
  3.5 等待 1 秒流量穩定 (time sleep 1s)
  3.6 telnet 發送 "re" 指令，執行warm start
  3.7 等待使用者定義的「topology change 等待延遲時間」
  3.8 停止流量 (Stop Traffic)，並獲取數據並判定：
      - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
  3.9 清除結果統計數據，Capture 保持執行。
  3.10 等待 1 秒。
  3.11 port [TX] 持續打單向封包
  3.12 等待使用者定義的「topology back  等待延遲時間」
  3.13 停止流量 (Stop Traffic)，並獲取數據並判定：
      - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
  3.14 清除telnet session ，並等候1s
  3.15 清除結果統計數據，停止擷取並保存 Change & Back PCAP。
  3.16 進入下一場景或下一輪。
"""

import sys
import os
import csv
import time
import telnetlib
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Optional, Tuple

# 動態向上搜尋包含 utils 的根目錄，確保無論放置於哪一層子目錄均能正常引入 utils
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
    from utils.dictionary_parameters import *
    from utils.comm_helper import *
except ImportError as e:
    print(f"無法載入 dictionary_parameters 或 comm_helper: {e}")
    sys.exit(1)

if TYPE_CHECKING:
    from utils.pythontool import *


####################### 輔助函式 ###########################



def load_utils():
    """動態載入 Spirent TestCenter API 核心，並注入全域命名空間"""
    print("\n正在載入 Spirent TestCenter API 與通訊工具，請稍候...")
    try:
        import utils.pythontool as pt
        for name in dir(pt):
            if not name.startswith('_'):
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


def tcl_braced(value: str) -> str:
    """將檔案路徑轉為單一 Tcl 參數，支援空白字元。"""
    normalized_value = str(value).replace("\\", "/")
    if "{" in normalized_value or "}" in normalized_value:
        raise ValueError(f"Capture 路徑不可包含大括號: {normalized_value}")
    return "{{{}}}".format(normalized_value)


def create_capture_output_dir() -> str:
    """建立本次 Round Robin 測試專用的 PCAP 目錄 (存放於 test result/<測試名稱>_result/captures/ 下)。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return get_result_dir(__file__, sub_dir=os.path.join("captures", f"warm_start_round_robin_{timestamp}"))


def build_capture_filename(
    output_dir: str,
    poll_number: int,
    scenario_id: str,
    phase: str,
    tx_slot_port: str,
) -> str:
    """建立可識別 Round、Scenario、階段與 TX Port 的 PCAP 檔名。"""
    safe_scenario = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in str(scenario_id)
    )
    safe_port = tx_slot_port.replace("/", "_")
    filename = (
        f"round_{poll_number:03d}_scenario_{safe_scenario}_"
        f"{phase}_tx_port_{safe_port}.pcap"
    )
    return os.path.join(output_dir, filename)


def start_capture(port):
    """在指定 Spirent Port 啟動 RX Capture。"""
    capture = tclsh.eval(f"stc::get {port} -children-Capture")
    if not capture.strip():
        raise RuntimeError(f"Port {port} 找不到 Capture 物件")
    tclsh.eval(f"stc::config {capture} -BufferMode STOP_ON_FULL")
    tclsh.eval("stc::apply")
    tclsh.eval(f"stc::perform CaptureStart -CaptureProxyId {capture}")
    return capture


def stop_capture_and_save(capture, filename: str) -> int:
    """停止 Capture、保存為 PCAP，並回傳擷取封包數。"""
    tclsh.eval(f"stc::perform CaptureStop -CaptureProxyId {capture}")
    tclsh.eval(
        "stc::perform CaptureDataSave "
        f"-CaptureProxyId {capture} "
        f"-FileName {tcl_braced(filename)} "
        "-FileNameFormat PCAP -IsScap FALSE"
    )
    return int(tclsh.eval(f"stc::get {capture} -PktCount"))


def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """讀取 Warm Start CSV 測試參數表 (支援多個常見預設路徑自動搜尋)"""
    candidates = [
        csv_path,
        "scenarios.csv",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), csv_path),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "scenarios.csv"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "example", "Warm_start_Recovery_Test", "scenarios.csv"),
    ]
    resolved_path = None
    for cand in candidates:
        if os.path.exists(cand):
            resolved_path = cand
            break

    if not resolved_path:
        print(f"錯誤：找不到參數表檔案 {csv_path} 或 scenarios.csv")
        sys.exit(1)
        
    scenarios = []
    with open(resolved_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            clean_row = {k.strip(): v.strip() for k, v in row.items() if k}
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
        choice = input("\n請選擇要執行的場景 (例如單選: 1, 多選: 1,2,3，直接 Enter 預設全部): ").strip()
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


def get_polling_count() -> int:
    """提示使用者輸入輪詢次數（防呆必須為正整數）"""
    while True:
        try:
            val = input("請輸入輪詢次數 (例如 5 表示整套場景輪流跑 5 輪，直接 Enter 預設 1): ").strip()
            if not val:
                return 1
            count = int(val)
            if count > 0:
                return count
        except ValueError:
            print("請輸入有效的正整數。")


def get_telnet_credentials(default_user: str = "admin", default_pwd: str = "moxa") -> Tuple[str, str]:
    """提示使用者輸入 DUT 登入帳號與密碼 (支援直接 Enter 套用預設值)"""
    print("\n" + "-"*50)
    print("DUT Telnet 登入資訊設定：")
    user_input = input(f"請輸入 DUT 登入帳號 (直接 Enter 預設 '{default_user}'): ").strip()
    username = user_input if user_input else default_user

    pwd_input = input(f"請輸入 DUT 登入密碼 (直接 Enter 預設 '{default_pwd}'): ").strip()
    password = pwd_input if pwd_input else default_pwd

    print(f"-> 已設定 Telnet 登入帳號: '{username}'")
    print("-"*(50) + "\n")
    return username, password


def telnet_login_custom(target_ip: str, username: str = "admin", password: str = "moxa") -> Optional[telnetlib.Telnet]:
    """嘗試 Telnet 登入設備，支援使用者自訂帳號與密碼之登入交握"""
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
def main(polling_count=None, change_delay_time=None, back_delay_time=None, username=None, password=None):
    # --- [Phase 1] 參數蒐集與初始化 ---
    # 1.1 「輪詢次數」、「topology change 等待延遲時間」、「topology back 等待延遲時間」、「DUT 登入帳密」、「選擇測試場景」
    if polling_count is None:
        polling_count = get_polling_count()

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

    if username is None or password is None:
        u, p = get_telnet_credentials()
        if username is None:
            username = u
        if password is None:
            password = p

    # 1.2 選擇並讀取測試參數表 (共用 scenarios.csv)
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
    active_capture = None
    active_capture_filename = None

    try:
        # --- [Phase 2] 儀器與環境配置 (Spirent & Serial) ---
        project, port_objs, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)

        # 建立 Slot/Port 到 Port 物件的對照字典
        port_map = {slotPortlist[idx]: port_objs[idx] for idx in range(len(slotPortlist))}

        # 建立本次測試的 PCAP 輸出目錄
        capture_output_dir = create_capture_output_dir()
        print(f"封包擷取檔案將儲存至: {capture_output_dir}")

        # 寫入日誌檔標頭
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*50}\n")
            f_log.write(f"開始 Warm Start 跨場景輪詢測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"輪詢次數: {polling_count} 輪 (包含場景: {', '.join([s['Scenario'] for s in selected_scenarios])})\n")
            f_log.write(f"Topology Change 等待時間: {change_delay_time} 秒, Topology Back 等待時間: {back_delay_time} 秒\n")
            f_log.write(f"Telnet 登入帳號: {username}\n")
            f_log.write(f"{'='*50}\n")

        # --- [Phase 3] 自動化測試迴圈 (場景輪流依序執行為一輪) ---
        for poll_idx in range(polling_count):
            print(f"\n==================================================")
            print(f"=== 輪詢 (Round-Robin) 第 {poll_idx + 1}/{polling_count} 輪開始 ===")
            print(f"==================================================")

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

                print(f"\n--- [輪詢第 {poll_idx+1}/{polling_count} 輪] 執行 Scenario {sc_id} ---")
                print(f"Port0: {p0_str}, Port1: {p1_str}, PortTX: {ptx_name}, PortRX: {prx_name}, DUT IP: {dut_ip}")

                # 動態建立 Stream Block (為當前場景配置)
                sb0 = CreateStreamBlock(port0_obj, StreamBlock, Frame)
                sb1 = CreateStreamBlock(port1_obj, StreamBlock, Frame1)
                Generator(port0_obj, Generatortype)
                Generator(port1_obj, Generatortype)

                # 3.1 ping DUT ，若失敗則跳出迴圈
                print(f"[3.1] 正在 Ping DUT ({dut_ip})...")
                ping_success = Pingfunc(dut_ip, times=1)
                if not ping_success:
                    msg = f"輪詢 {poll_idx+1}/{polling_count} Scenario {sc_id}: Ping DUT ({dut_ip}) 失敗，跳過此場景"
                    print(f"[FAIL] {msg}")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        f_log.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                    # 釋放 stream block
                    try: tclsh.eval(f"stc::delete {sb0}")
                    except: pass
                    try: tclsh.eval(f"stc::delete {sb1}")
                    except: pass
                    continue

                # 3.2 telnet 登入DUT，若失敗則跳出迴圈
                print(f"[3.2] 正在 Telnet 登入 DUT ({dut_ip})，帳號: {username} ...")
                tn = telnet_login_custom(dut_ip, username=username, password=password)
                if tn is None:
                    msg = f"輪詢 {poll_idx+1}/{polling_count} Scenario {sc_id}: Telnet 登入 DUT ({dut_ip}) 失敗，跳過此場景"
                    print(f"[FAIL] {msg}")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        f_log.write(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}\n")
                    # 釋放 stream block
                    try: tclsh.eval(f"stc::delete {sb0}")
                    except: pass
                    try: tclsh.eval(f"stc::delete {sb1}")
                    except: pass
                    continue

                # 3.3 port [TX] 持續打單向封包
                print(f"[3.3] 清除歷史數據並在 Port [{ptx_name}] 啟動 Topology Change Capture...")
                clear_results_and_streams(ports_pair)
                active_capture_filename = build_capture_filename(
                    capture_output_dir,
                    poll_idx + 1,
                    sc_id,
                    "topology_change_and_back",
                    p0_str if ptx_name == "port0" else p1_str,
                )
                active_capture = start_capture(tx_port_obj)

                # 3.4 port [TX] 持續打單向封包
                print(f"[3.4] Port [{ptx_name}] 開始發送單向流量...")
                StartGenerator([tx_port_obj])

                # 3.5 等待 1 秒流量穩定 (time sleep 1s)
                print("[3.5] 等待 1 秒流量穩定...")
                time.sleep(1)

                # 3.6 telnet 發送 "re" 指令，執行warm start
                cmd_timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"[3.6] [{cmd_timestamp}] Telnet 發送 're' 指令並回應 'y' 執行 Warm Start...")
                comm_TELNET(tn, 'Enter', 're')
                time.sleep(1)
                comm_TELNET(tn, 'reload', 'y')

                # 3.7 等待使用者定義的「topology change 等待延遲時間」
                print(f"[3.7] 等待 topology change 延遲時間 ({change_delay_time} 秒)...")
                time.sleep(change_delay_time)

                # 3.8 停止流量 (Stop Traffic)，並獲取數據並判定：
                #     - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
                print("[3.8] [Topology Change] 停止流量並統計封包...")
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

                # 3.9 清除結果統計數據，Capture 保持執行
                print("[3.9] 清除 Topology Change 統計，Capture 保持執行...")
                clear_results_and_streams(ports_pair)

                # 3.10 等待 1 秒，Capture 持續執行
                print("[3.10] 等待 1 秒，Capture 持續執行...")
                time.sleep(1)

                # 3.11 port [TX] 持續打單向封包
                print(f"[3.11] Port [{ptx_name}] 重新開始發送單向流量 (Topology Back 測試)...")
                StartGenerator([tx_port_obj])

                # 3.12 等待使用者定義的「topology back  等待延遲時間」
                print(f"[3.12] 等待 topology back 延遲時間 ({back_delay_time} 秒)...")
                time.sleep(back_delay_time)

                # 3.13 停止流量 (Stop Traffic)，並獲取數據並判定：
                #     - 換算掉包數量 (Port[TX] Tx - Port[RX] Rx ) ，並記錄至日誌
                print("[3.13] [Topology Back] 停止流量並統計封包...")
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

                log_entry = (
                    f"[{datetime.now().strftime('%H:%M:%S')}] [輪詢第 {poll_idx+1}/{polling_count} 輪] Scenario {sc_id}\n"
                    f"  Warm Start 指令觸發精確時間: {cmd_timestamp}\n"
                    f"  --- [Topology Change 階段] ---\n"
                    f"  Port0 ({p0_str}): [Rx={p0_rx_c}, Tx={p0_tx_c}]\n"
                    f"  Port1 ({p1_str}): [Rx={p1_rx_c}, Tx={p1_tx_c}]\n"
                    f"  流量方向: {ptx_name} -> {prx_name}\n"
                    f"  Topology Change 丟包數: {lost_pkts_c} pkts (Tx={tx_pkts_c}, Rx={rx_pkts_c})\n"
                    f"  --- [Topology Back 階段] ---\n"
                    f"  Port0 ({p0_str}): [Rx={p0_rx_b}, Tx={p0_tx_b}]\n"
                    f"  Port1 ({p1_str}): [Rx={p1_rx_b}, Tx={p1_tx_b}]\n"
                    f"  Topology Back 丟包數: {lost_pkts_b} pkts (Tx={tx_pkts_b}, Rx={rx_pkts_b})\n"
                    f"{'-'*50}\n"
                )
                print(log_entry.strip())
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(log_entry)

                # 3.14 清除telnet session ，並等候1s
                print("[3.14] 清除 Telnet session，等候 1 秒...")
                try:
                    tn.close()
                except Exception:
                    pass
                time.sleep(1)

                # 3.15 清除結果統計數據，停止擷取並保存 Change & Back PCAP
                print("[3.15] 清除統計並保存 Change & Back Capture...")
                clear_results_and_streams(ports_pair)
                capture_count = stop_capture_and_save(
                    active_capture, active_capture_filename
                )
                print(
                    f"Change & Back Capture 已儲存: "
                    f"{active_capture_filename} ({capture_count} packets)"
                )
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(
                        f"  Change & Back Capture: {active_capture_filename}\n"
                    )
                active_capture = None
                active_capture_filename = None

                # 3.16 釋放當前場景的 Stream Block，進入下一場景或下一輪
                try:
                    tclsh.eval(f"stc::delete {sb0}")
                except Exception:
                    pass
                try:
                    tclsh.eval(f"stc::delete {sb1}")
                except Exception:
                    pass

    except Exception as e:
        print(f"執行期間發生異常: {e}")
    finally:
        # 資源必定清理機制
        if active_capture is not None:
            try:
                emergency_count = stop_capture_and_save(
                    active_capture, active_capture_filename
                )
                print(
                    f"異常中止 Capture 已儲存: {active_capture_filename} "
                    f"({emergency_count} packets)"
                )
            except Exception as capture_error:
                print(f"停止或儲存 Capture 失敗: {capture_error}")
        for res in [result1, result2, result3]:
            if res is not None:
                try:
                    unsubscribe(res)
                except Exception:
                    pass
        try:
            Disconnect(chassisAddr)
        except Exception:
            pass
        print(f"\n已完成測試。日誌已記錄至 {log_filename}")


if __name__ == "__main__":
    main()
