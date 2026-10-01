# -*- coding: utf-8 -*-
"""
名稱: Valencia SNMPv3 Polling Request ID = 0 壓力測試腳本 (SNMP_polling_ID_0_test.py)

目的與測試重點：
1. 驗證 DUT (交換機) 面對 SNMPv3 Request ID 為 0 (邊界/特殊數值) 之請求時的協議相容性與系統穩定度。
2. 針對目標 OID: 1.3.6.1.2.1.17.4.3.1.2 (dot1dTpFdbPort，FDB 轉發資料庫連接埠表格) 進行 SNMPv3 Walk / GetNext 深度遍歷。
3. 發出的每一個 SNMP Request PDU 之 `request-id` 均強制鎖定為 0。
4. 解析回傳之 OID 後綴以還原 MAC 地址，並對應其學習到的 Bridge Port。
5. 支援多輪壓測、多 Scenario 輪詢、通訊耗時統計與結果存檔 (result.txt)。

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 載入測試參數表 (scenarios.csv)，提示使用者選擇執行的 Scenario。
  1.2 提示輸入「執行總輪數」與「每輪間隔等待時間 (秒)」。
  1.3 設定 SNMP 驗證資訊 (預設 SNMPv3 authPriv: SHA-1 / DES, 帳密: admin / moxamoxa)。
  1.4 啟動底层 Hook 機制，強制所有傳送之 SNMP PDU 其 Request ID = 0。
[Phase 2] 環境預檢與連線配置
  2.1 透過 Pingfunc 檢測各選定 DUT 之網路在線狀態。
  2.2 初始化日誌檔標頭 (result.txt)。
[Phase 3] 自動化測試迴圈
  3.1 進入第 i 輪測試迴圈。
  3.2 輪詢各選定 Scenario 之 DUT IP。
  3.3 發送 Request ID = 0 之 SNMPv3 Walk (GetNext) 走訪 1.3.6.1.2.1.17.4.3.1.2 (dot1dTpFdbPort)。
  3.4 解析回傳之 MAC 地址、Port 號、耗時與筆數。
  3.5 記錄單輪數據至 result.txt 與終端。
  3.6 產出場景統計總結 (平均筆數、平均耗時、成功率)。
"""

import sys
import os
import csv
import time
import codecs
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

# Windows 控制台 Unicode 安全輸出支援 (避免 cp950 編碼異常)
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
WORKSPACE_ROOT = SCRIPT_DIR
while current_dir_check and os.path.dirname(current_dir_check) != current_dir_check:
    if os.path.exists(os.path.join(current_dir_check, "utils", "comm_helper.py")):
        WORKSPACE_ROOT = current_dir_check
        if current_dir_check not in sys.path:
            sys.path.insert(0, current_dir_check)
        break
    current_dir_check = os.path.dirname(current_dir_check)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# 引入共用通訊工具
try:
    from utils.comm_helper import get_iteration_count, get_delay_time, Pingfunc, get_result_log_path
except ImportError as e:
    print(f"無法載入 comm_helper: {e}")
    sys.exit(1)

# 引入 pysnmp 核心元件
try:
    from pysnmp.hlapi import (
        SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity,
        nextCmd,
        UsmUserData, usmHMACSHAAuthProtocol, usmHMACMD5AuthProtocol,
        usmDESPrivProtocol, usmAesCfb128Protocol
    )
    import pysnmp.proto.api.v1 as v1
    import pysnmp.proto.api.v2c as v2c
    from pysnmp.entity.rfc3413 import cmdgen
except ImportError as e:
    print(f"無法載入 pysnmp 套件 (請確認環境已安裝 pysnmp): {e}")
    sys.exit(1)


# 目標測試 OID 定義
TARGET_OID = "1.3.6.1.2.1.17.4.3.1.2"
TARGET_NAME = "dot1dTpFdbPort"


####################### Request ID = 0 核心攔截注入 ###########################

def enforce_snmp_request_id_zero():
    """
    底層 Hook 機制：確保 pysnmp 產生的所有 SNMP Request PDU 其 Request ID 均為 0。
    
    原理說明：
    1. pysnmp 在 cmdgen (CommandGenerator) 中呼叫 v2c.getNextRequestID() 產生隨機/遞增 Request ID。
    2. 將 v1 / v2c 之 getNextRequestID 覆寫為始終回傳 0 的 lambda。
    3. 同時覆寫 v1.PDUAPI.setDefaults 與 v2c.PDUAPI.setRequestID，保證 PDU 第一個欄位 (request-id) 恆為 0。
    """
    # 覆寫 Request ID 產生器回傳 0
    v1.getNextRequestID = lambda: 0
    v2c.getNextRequestID = lambda: 0

    # 確保 setDefaults 函式作用域內的全域參照同步生效
    if 'getNextRequestID' in v1.PDUAPI.setDefaults.__globals__:
        v1.PDUAPI.setDefaults.__globals__['getNextRequestID'] = lambda: 0
    if 'getNextRequestID' in v2c.PDUAPI.setDefaults.__globals__:
        v2c.PDUAPI.setDefaults.__globals__['getNextRequestID'] = lambda: 0

    # Hook setRequestID，確保任何外部設定亦強制設為 0
    orig_v2c_setRequestID = v2c.PDUAPI.setRequestID
    def forced_setRequestID(pdu, value):
        orig_v2c_setRequestID(pdu, 0)
    v2c.PDUAPI.setRequestID = staticmethod(forced_setRequestID)


def register_engine_req_id_verifier(snmp_engine: SnmpEngine) -> None:
    """
    註冊 SnmpEngine 封包發送前觀察器 (Observer)，即時校驗並保證即將送出網卡的 PDU request-id 必為 0。
    """
    def outgoing_pdu_observer(engine, execpoint, variables, cbCtx):
        pdu = variables.get('pdu')
        if pdu is not None:
            # 二度防禦：在序列化加密前再次強制確認 request-id = 0
            v2c.apiPDU.setRequestID(pdu, 0)

    snmp_engine.observer.registerObserver(outgoing_pdu_observer, 'rfc3412.prepareOutgoingMessage')


####################### 輔助函式 ###########################

def parse_fdb_mac_from_oid(oid_str: str, root_prefix: str = TARGET_OID) -> str:
    """
    自 dot1dTpFdbPort 之 OID 後綴解析出 6-byte 實體 MAC 位址字串 (格式: XX:XX:XX:XX:XX:XX)。
    
    例如: 1.3.6.1.2.1.17.4.3.1.2.0.144.232.18.52.86
    後綴為: 0.144.232.18.52.86
    轉換為: 00:90:E8:12:34:56
    """
    try:
        suffix = oid_str[len(root_prefix):].strip('.')
        octets = [int(x) for x in suffix.split('.') if x.isdigit()]
        if len(octets) == 6:
            return ":".join(f"{x:02X}" for x in octets)
    except Exception:
        pass
    return oid_str


def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """依專案防禦性規範解析讀取 scenarios.csv。"""
    resolved_path = csv_path
    if not os.path.isabs(resolved_path):
        candidate_paths = [
            resolved_path,
            os.path.join(SCRIPT_DIR, resolved_path),
            os.path.join(WORKSPACE_ROOT, resolved_path),
            os.path.join(os.getcwd(), resolved_path)
        ]
        for cp in candidate_paths:
            if os.path.exists(cp):
                resolved_path = cp
                break

    if not os.path.exists(resolved_path):
        print(f"[提示] 未發現參數表檔案 {resolved_path}，將提供手動輸入 DUT IP 模式。")
        return []

    scenarios = []
    try:
        with open(resolved_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                clean_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k is not None}
                if not clean_row or not clean_row.get("Scenario"):
                    continue

                ip_val = ""
                hw_id_val = ""
                for k, v in clean_row.items():
                    k_lower = k.lower()
                    if "ip" in k_lower:
                        ip_val = v
                    elif "hw" in k_lower or "model" in k_lower:
                        hw_id_val = v

                if ip_val:
                    scenarios.append({
                        "Scenario": clean_row.get("Scenario", ""),
                        "DUT_IP": ip_val,
                        "HW_ID": hw_id_val
                    })
    except Exception as e:
        print(f"[警告] 讀取 {resolved_path} 異常: {e}")
    return scenarios


def select_scenarios(scenarios: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """提示使用者選擇欲執行的 Scenario (支援單選、多選逗號分隔、直接 Enter 預設全部)。"""
    if not scenarios:
        default_ip = "10.0.17.102"
        manual_ip = input(f"\n請輸入目標 DUT IP (直接 Enter 預設 {default_ip}): ").strip() or default_ip
        return [{"Scenario": "1", "DUT_IP": manual_ip, "HW_ID": "125"}]

    print("\n可用的測試場景清單 (Scenarios):")
    for sc in scenarios:
        hw_info = f", HW_ID={sc['HW_ID']}" if sc.get('HW_ID') else ""
        print(f"  [Scenario {sc['Scenario']}] DUT IP: {sc['DUT_IP']}{hw_info}")

    while True:
        choice = input("\n請選擇要執行的場景 (例如單選: 1, 多選: 1,2，直接 Enter 預設全部): ").strip()
        if not choice or choice.lower() == "all":
            print("-> 已選擇執行所有場景 (All Scenarios)")
            return scenarios

        selected_ids = [s.strip() for s in choice.split(",") if s.strip()]
        selected_scenarios = [sc for sc in scenarios if sc["Scenario"] in selected_ids]
        if selected_scenarios:
            chosen_str = ", ".join([f"Scenario {sc['Scenario']} ({sc['DUT_IP']})" for sc in selected_scenarios])
            print(f"-> 已選擇執行場景: {chosen_str}")
            return selected_scenarios
        else:
            print("輸入無效或找不到對應的 Scenario ID，請重新輸入。")


def setup_snmp_auth() -> Tuple[Any, str]:
    """
    設定 SNMP 驗證資訊，預設使用 SNMPv3 (authPriv / SHA-1 / DES)。
    亦相容自環境變數 (RENFE_SNMP_USER, RENFE_SNMP_AUTH, RENFE_SNMP_PRIV) 或命令列自定義。
    """
    env_user = os.environ.get("RENFE_SNMP_USER", "admin")
    env_auth = os.environ.get("RENFE_SNMP_AUTH", "moxamoxa")
    env_priv = os.environ.get("RENFE_SNMP_PRIV", "moxamoxa")

    print("\n" + "="*65)
    print("SNMP 協定模式設定 (Request ID = 0 專項測試)：")
    print(f"  [1] SNMPv3 authPriv (預設推薦，SHA-1 / DES | 帳號: {env_user})")
    print("  [2] SNMPv2c (傳統社群字串 | public)")
    print("="*65)
    mode_input = input("請選擇 SNMP 協定模式 (直接 Enter 預設為 [1] SNMPv3): ").strip()

    if mode_input == "2":
        comm_read = input("請輸入 Read Community (直接 Enter 預設 public): ").strip() or "public"
        auth_data = CommunityData(comm_read)
        version_label = f"SNMPv2c (Community: {comm_read}, Request ID: 0)"
        print(f"-> 已啟用模式: {version_label}")
        return auth_data, version_label
    else:
        user_prompt = f"請輸入 SNMPv3 使用者名稱 (直接 Enter 預設 '{env_user}'): "
        user = input(user_prompt).strip() or env_user
        
        auth_prompt = f"請輸入 Auth 認證密碼 (SHA-1，直接 Enter 預設 '{env_auth}'): "
        auth_pass = input(auth_prompt).strip() or env_auth
        
        priv_prompt = f"請輸入 Priv 加密密碼 (DES，直接 Enter 預設 '{env_priv}'): "
        priv_pass = input(priv_prompt).strip() or env_priv

        usm_auth = UsmUserData(
            user,
            auth_pass,
            priv_pass,
            authProtocol=usmHMACSHAAuthProtocol,
            privProtocol=usmDESPrivProtocol
        )
        version_label = f"SNMPv3 authPriv (User: {user}, Auth: SHA-1, Priv: DES, Request ID: 0)"
        print(f"-> 已啟用模式: {version_label}")
        return usm_auth, version_label


def snmp_walk_req_id_zero(
    target_ip: str,
    root_oid: str,
    auth_data: Any,
    port: int = 161,
    timeout: float = 2.0,
    retries: int = 1,
    max_rows: int = 2000
) -> Tuple[List[Tuple[str, str]], float, Optional[str]]:
    """
    透過 nextCmd 執行子樹 Walk (GetNext 遍歷)，底層強制每一次發出之 Request ID 必為 0。
    
    Returns:
        Tuple[results: List[(oid, val)], elapsed_ms: float, error_msg: Optional[str]]
    """
    results: List[Tuple[str, str]] = []
    t_start = time.time()

    try:
        query_tuple = tuple(int(x) for x in root_oid.split('.') if x.isdigit())
    except Exception:
        query_tuple = ()

    # 建立獨立的 SnmpEngine 並註冊 Request ID = 0 攔截觀察器
    engine = SnmpEngine()
    register_engine_req_id_verifier(engine)

    try:
        iterator = nextCmd(
            engine,
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            ObjectType(ObjectIdentity(root_oid)),
            lexicographicMode=False,
            ignoreNonIncreasingOid=True
        )

        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                elapsed_ms = (time.time() - t_start) * 1000.0
                return results, elapsed_ms, str(errorIndication)
            elif errorStatus:
                elapsed_ms = (time.time() - t_start) * 1000.0
                return results, elapsed_ms, str(errorStatus.prettyPrint())
            else:
                for varBind in varBinds:
                    curr_oid = str(varBind[0])
                    try:
                        curr_tuple = varBind[0].asTuple()
                    except Exception:
                        curr_tuple = tuple(int(x) for x in curr_oid.split('.') if x.isdigit())
                    
                    # 邊界判定：超出該子樹範圍則結束遍歷
                    if query_tuple and curr_tuple[:len(query_tuple)] != query_tuple:
                        break

                    results.append((curr_oid, varBind[1].prettyPrint()))
                    if len(results) >= max_rows:
                        break

                if len(results) >= max_rows:
                    break

        elapsed_ms = (time.time() - t_start) * 1000.0
        return results, elapsed_ms, None

    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return results, elapsed_ms, str(e)


####################### 主程式邏輯 ###########################

def main():
    print(f"\n{'='*75}")
    print(f"  Valencia 專案 - SNMPv3 Polling (Request ID = 0 特殊壓力測試)")
    print(f"  目標 OID: {TARGET_OID} ({TARGET_NAME})")
    print(f"{'='*75}")

    # 1. 啟用底層 Request ID = 0 攔截
    enforce_snmp_request_id_zero()

    # 2. 載入並選擇場景
    all_scenarios = load_scenarios_from_csv("scenarios.csv")
    selected_scenarios = select_scenarios(all_scenarios)

    # 3. 取得執行次數與輪間等待時間
    iteration = get_iteration_count()
    delay_time = get_delay_time()

    # 4. 設定 SNMP 驗證資訊
    auth_data, version_label = setup_snmp_auth()

    # 5. 初始化集中式日誌檔標頭 (test result/<測試目錄>_result/result.txt)
    log_filename = get_result_log_path(__file__, "result.txt")
    with open(log_filename, "a+", encoding="utf-8") as f_log:
        f_log.write(f"\n{'='*70}\n")
        f_log.write(f"開始 SNMP Polling Request ID = 0 特殊測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f_log.write(f"模式: {version_label}\n")
        f_log.write(f"目標 OID: {TARGET_OID} ({TARGET_NAME})\n")
        f_log.write(f"執行輪數: {iteration} 輪, 輪間等待: {delay_time} 秒\n")
        sc_names = ', '.join([f"Scenario {sc['Scenario']}({sc['DUT_IP']})" for sc in selected_scenarios])
        f_log.write(f"選定場景: {sc_names}\n")
        f_log.write(f"{'='*70}\n")

    print("\n" + "="*70)
    print("即將開始執行自動化測試迴圈...")
    print("="*70)

    try:
        # 逐場景統計彙整清單
        for sc_idx, sc in enumerate(selected_scenarios, 1):
            sc_id = sc["Scenario"]
            dut_ip = sc["DUT_IP"]
            hw_id = sc.get("HW_ID", "")

            print(f"\n{'#'*70}")
            print(f"  >>> 開始執行 Scenario {sc_id} ({sc_idx}/{len(selected_scenarios)}): DUT IP={dut_ip} (HW_ID={hw_id}) <<<")
            print(f"{'#'*70}")

            # 檢測在線狀態 (Ping 檢測)
            print(f"[*] 執行 Ping 探測 DUT ({dut_ip})...")
            ping_ok = Pingfunc(dut_ip, times=1)
            if not ping_ok:
                msg = f"[{datetime.now().strftime('%H:%M:%S')}] Scenario {sc_id} ({dut_ip}): Ping 失敗 (離線中)，跳過本場景。"
                print(f"[FAIL] {msg}")
                with open(log_filename, "a+", encoding="utf-8") as f_log:
                    f_log.write(f"{msg}\n")
                continue

            sc_times: List[float] = []
            sc_entry_counts: List[int] = []
            sc_success_count = 0

            # 執行 iteration 輪次的 Walk
            for it in range(1, iteration + 1):
                timestamp_str = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{timestamp_str}] --- Scenario {sc_id} ({dut_ip}) - 第 {it}/{iteration} 輪 Walk ---")
                print(f"[*] 發送 SNMPv3 GetNext 請求 (目標 OID: {TARGET_OID}, Request ID 強制為 0)...")

                entries, elapsed_ms, err_msg = snmp_walk_req_id_zero(
                    target_ip=dut_ip,
                    root_oid=TARGET_OID,
                    auth_data=auth_data,
                    port=161,
                    timeout=2.0,
                    retries=1
                )

                if err_msg:
                    log_line = f"[{timestamp_str}] Scenario {sc_id} ({dut_ip}) Iteration {it}: Walk {TARGET_NAME} (req_id=0) 失敗: {err_msg} (耗時: {elapsed_ms:.1f} ms)\n"
                    print(f"[FAIL] {log_line.strip()}")
                    with open(log_filename, "a+", encoding="utf-8") as f_log:
                        f_log.write(log_line)
                else:
                    sc_success_count += 1
                    sc_times.append(elapsed_ms)
                    sc_entry_counts.append(len(entries))

                    log_line = f"[{timestamp_str}] Scenario {sc_id} ({dut_ip}) Iteration {it}: Walk {TARGET_NAME} (req_id=0) 成功 -> 共 {len(entries)} 筆 FDB 記錄 (耗時: {elapsed_ms:.1f} ms)\n"
                    print(f"[PASS] {log_line.strip()}")

                    # 控制台與日誌同步記錄解析出的 MAC 與 Port 資訊
                    mac_details = []
                    if entries:
                        print(f"      ┌{'─'*68}┐")
                        print(f"      │ {'#':<3} │ {'MAC Address':<18} │ {'Bridge Port':<12} │ {'Instance OID'}")
                        print(f"      ├{'─'*68}┤")
                        for idx, (oid_val, port_val) in enumerate(entries[:15], 1):
                            mac_str = parse_fdb_mac_from_oid(oid_val, TARGET_OID)
                            print(f"      │ {idx:<3} │ {mac_str:<18} │ {port_val:<12} │ {oid_val}")
                            mac_details.append(f"        ├─ [{idx:02d}] MAC: {mac_str} -> Port: {port_val}")
                        if len(entries) > 15:
                            remain_cnt = len(entries) - 15
                            print(f"      │ ... │ (其餘 {remain_cnt} 筆記錄省略顯示)")
                            mac_details.append(f"        └─ ... (其餘 {remain_cnt} 筆記錄已接收)")
                        print(f"      └{'─'*68}┘")
                    else:
                        print("      [提示] DUT 回傳 FDB 表格目前為空 (0 entries)。")
                        mac_details.append("        └─ (FDB 表格目前為空)")

                    # 寫入詳細日誌至 result.txt
                    with open(log_filename, "a+", encoding="utf-8") as f_log:
                        f_log.write(log_line)
                        for d_line in mac_details:
                            f_log.write(f"{d_line}\n")

                if it < iteration:
                    time.sleep(delay_time)

            # ==========================================
            # 產出 Scenario 統計總結 (記錄最大/平均/成功率至 result.txt 與終端)
            # ==========================================
            avg_time = sum(sc_times) / len(sc_times) if sc_times else 0.0
            max_time = max(sc_times) if sc_times else 0.0
            avg_entries = sum(sc_entry_counts) / len(sc_entry_counts) if sc_entry_counts else 0.0
            max_entries = max(sc_entry_counts) if sc_entry_counts else 0

            summary_block = (
                f"{'-'*60}\n"
                f"Scenario {sc_id} ({dut_ip}) Request ID = 0 測試總結 (共執行 {iteration} 輪):\n"
                f"  - 測試項目: SNMPv3 Walk {TARGET_NAME} ({TARGET_OID})\n"
                f"  - 成功次數: {sc_success_count}/{iteration} (成功率: {(sc_success_count/iteration*100):.1f}%)\n"
                f"  - FDB 表格筆數: 平均 {avg_entries:.1f} 筆, 歷史最大 {max_entries} 筆\n"
                f"  - 查詢耗時: 平均 {avg_time:.1f} ms, 最大 {max_time:.1f} ms\n"
                f"{'-'*60}\n"
            )
            print(f"\n{summary_block}")
            with open(log_filename, "a+", encoding="utf-8") as f_log:
                f_log.write(summary_block)

        print("\n" + "="*70)
        print("所有選定場景之 Request ID = 0 測試已全部執行完成！")
        print(f"詳細測試數據與統計總結已儲存至: {log_filename}")
        print("="*70)

    except KeyboardInterrupt:
        print("\n\n[中斷] 使用者手動中斷測試 (Ctrl+C)。")
    except Exception as e:
        print(f"\n\n[異常] 測試執行過程發生未預期例外: {e}")
        import traceback
        traceback.print_exc()
    finally:
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_filename, "a+", encoding="utf-8") as f_log:
            f_log.write(f"\n[結束] 測試於 {end_time_str} 結束。\n{'='*70}\n")
        print("\n測試結束，環境已安全釋放。")


if __name__ == "__main__":
    main()
