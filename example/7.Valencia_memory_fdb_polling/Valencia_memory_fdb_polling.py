# -*- coding: utf-8 -*-
"""
名稱: Valencia SNMP 記憶體與 FDB 轉發表記錄測試 (Valencia_memory_fdb_polling.py)

背景與設計原理：
經由封包比對分析 (getbulk.pcapng vs getbulk_no memory leak.pcapng)：
  - 記憶體洩漏版本 (getbulk.pcapng): 在單一 GetBulk PDU 中同時打包多個 OID (dot1dTpFdbAddress 與 dot1dTpFdbPort 複合 Multi-VarBind)，
    導致交換機 SNMP 引擎在多欄位併行迭代時配置之記憶體與 Context 未釋放，引發嚴重 Memory Leak。
  - 無洩漏修復版本 (getbulk_no memory leak.pcapng): 每個 GetBulk 請求嚴格僅包含「單一 VarBind (Single-VarBind)」，
    將不同表格欄位拆分為獨立的單一 PDU 進行查詢 (max-repetitions = 50)，交換機每次僅需維護單一迭代器，運作順暢無洩漏。

本腳本 100% 依據「無洩漏修復架構」實作：
  1. SNMP Get memoryUsage: 取得交換機記憶體使用率 (OID: 1.3.6.1.4.1.8691.7.<HW_ID>.1.59.0)
  2. SNMP GetBulk dot1dTpFdbAddress: 單一 VarBind 批次讀取 FDB MAC 轉發表位址 (OID: 1.3.6.1.2.1.17.4.3.1.1，max-repetitions = 50)
  3. SNMP GetBulk dot1dTpFdbPort: 單一 VarBind 批次讀取 FDB 轉發埠映射 (OID: 1.3.6.1.2.1.17.4.3.1.2，max-repetitions = 50)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 讀取測試參數表 (scenarios.csv)，提示使用者選擇欲執行的 Scenario (支援單選、多選或全部)。
  1.2 設定 SNMP 驗證模式 (預設為 SNMPv3 authPriv / SHA-1 / DES，亦支援 SNMPv2c)。
    1.3 選擇 GetBulk 模式：
        [1] 單一 VarBind 無洩漏版 (預設，各欄位獨立單一 PDU 獲取 50 筆，100% 吻合 getbulk_no memory leak.pcapng)
        [2] 複合多欄位崩潰版 (在單一 PDU 同時打包 Address 與 Port 兩欄位，100% 吻合 getbulk_memory leak1.pcapng)
    1.4 提示輸入「執行總輪數」與「每輪間隔等待時間 (秒)」。
  1.5 自動探測或自參數表確認各 DUT 之硬體型號識別碼 (<HW_ID>)。
[Phase 2] 環境預檢與連線配置
  2.1 透過 Pingfunc 檢測各選定 DUT 之網路連線狀態。
  2.2 初始化日誌檔標頭 (result.txt)。
[Phase 3] 自動化測試迴圈
  對於所選之 Scenario (DUT) 進行迴圈檢測：
  3.1 記錄當前輪次起始標記與時間戳記。
  3.2 依序輪詢選定之各個 Scenario (DUT IP)，檢查在線狀態 (Ping 檢測)。
  3.3 執行 SNMP Get 查詢 memoryUsage 並取得記憶體使用百分比。
  3.4 執行 SNMP GetBulk 查詢 dot1dTpFdbAddress (單一 VarBind, max-repetitions = 50)。
  3.5 執行 SNMP GetBulk 查詢 dot1dTpFdbPort (單一 VarBind, max-repetitions = 50)。
  3.6 格式化輸出各項結果 (含筆數、耗時、MAC/Port 範例、跨表邊界判定) 並追加寫入 result.txt。
  3.7 當輪所有 Scenario 執行完畢，等候設定之輪詢間隔時間 (delay_time 秒)。
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

# 虛擬環境自動跳轉防呆機制 (若以全域 Python 啟動，自動切換至專案 .venv 執行)
ROOT_DIR = WORKSPACE_ROOT
_venv_py = os.path.join(WORKSPACE_ROOT, ".venv", "Scripts", "python.exe")
if os.path.exists(_venv_py) and os.path.normcase(sys.executable) != os.path.normcase(_venv_py):
    import subprocess
    sys.exit(subprocess.run([_venv_py] + sys.argv).returncode)

# 引入共用通訊工具（遵循 SKILL.md 工具箱按需裝配原則，本測試純使用 SNMP 與 Ping）
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
        getCmd, bulkCmd,
        UsmUserData, usmHMACSHAAuthProtocol, usmDESPrivProtocol
    )
except ImportError as e:
    print(f"無法載入 pysnmp 套件 (請確認環境已安裝 pysnmp): {e}")
    sys.exit(1)


####################### 輔助函式 ###########################


def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """依 SKILL.md Rule 12 與 Rule 14 規範，防禦性解析讀取 scenarios.csv。"""
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
        print(f"[警告] 找不到參數表檔案 {resolved_path}，將切換為單機互動輸入模式。")
        return []

    scenarios = []
    with open(resolved_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 防禦性清理：嚴格防止 NoneType.strip() 異常
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

            scenarios.append({
                "Scenario": clean_row.get("Scenario", ""),
                "DUT_IP": ip_val,
                "HW_ID": hw_id_val
            })
    return scenarios


def select_scenarios(scenarios: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """提示使用者選擇欲執行的 Scenario (支援單選、多選逗號分隔、直接 Enter 預設全部)。"""
    if not scenarios:
        manual_ip = input("請輸入待測 DUT IP (例如 10.0.17.102): ").strip()
        manual_hw = input("請輸入 DUT HW_ID (直接 Enter 預設自動探測): ").strip()
        return [{"Scenario": "1", "DUT_IP": manual_ip, "HW_ID": manual_hw}]

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

    print("\n" + "-"*65)
    print("SNMP 協定模式選擇：")
    print(f"  [1] SNMPv3 (預設推薦，authPriv / SHA-1 / DES | 預設帳號: {env_user})")
    print("  [2] SNMPv2c (傳統社群字串 | 預設: public)")
    print("-"*(65))
    mode_input = input("請選擇 SNMP 協定模式 (直接 Enter 預設為 [1] SNMPv3): ").strip()

    if mode_input == "2":
        comm_read = input("請輸入 Read Community (直接 Enter 預設 public): ").strip() or "public"
        read_auth = CommunityData(comm_read)
        version_label = f"SNMPv2c (Community: {comm_read})"
        print(f"-> 已啟用模式: {version_label}")
        return read_auth, version_label
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
        version_label = f"SNMPv3 authPriv (User: {user}, Auth: SHA-1, Priv: DES)"
        print(f"-> 已啟用模式: {version_label}")
        return usm_auth, version_label


def select_getbulk_mode() -> Tuple[str, str]:
    """
    選擇 GetBulk 執行模式：
      [1] 單一 VarBind 無洩漏版 (推薦，單次獨立 PDU 50 reps，100% 吻合 getbulk_no memory leak.pcapng)
      [2] 複合多欄位崩潰版 (在單一 PDU 同時打包 Address 與 Port，100% 吻合 getbulk_memory leak1.pcapng)
    """
    print("\n" + "-"*65)
    print("GetBulk 執行模式選擇：")
    print("  [1] 單一 VarBind 無洩漏版 (推薦，各欄位獨立單一 PDU 取 50 筆，完全匹配無洩漏封包)")
    print("  [2] 複合多欄位崩潰版 (在單一 PDU 同時打包 Address 與 Port，重現 getbulk_memory leak1 崩潰洩漏)")
    print("-"*(65))
    choice = input("請選擇模式 (直接 Enter 預設為 [1] 單一 VarBind 無洩漏版): ").strip()
    if choice == "2":
        print("-> 已選擇: [2] 複合多欄位崩潰版 (Multi-VarBind Crash Mode)")
        return "Multi-VarBind Crash Mode (getbulk_memory leak1)", "multi"
    else:
        print("-> 已選擇: [1] 單一 VarBind 無洩漏版 (Single-VarBind Safe Mode)")
        return "Single-VarBind Safe Mode (getbulk_no memory leak)", "single"


def detect_hw_id(target_ip: str, auth_data: Any, port: int = 161, timeout: float = 2.0) -> Optional[str]:
    """透過 MIB-II sysObjectID (1.3.6.1.2.1.1.2.0) 自動探測 DUT 的硬體型號識別碼 (<HW_ID>)。"""
    sys_obj_oid = "1.3.6.1.2.1.1.2.0"
    try:
        iterator = getCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(sys_obj_oid))
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        if not errorIndication and not errorStatus and varBinds:
            val = varBinds[0][1]
            if hasattr(val, "asTuple"):
                tup = val.asTuple()
                for idx in range(len(tup) - 2):
                    if tup[idx] == 8691 and tup[idx + 1] == 7:
                        return str(tup[idx + 2])

            val_str = str(val)
            for prefix in ("1.3.6.1.4.1.8691.7.", "enterprises.8691.7.", "8691.7."):
                if prefix in val_str:
                    candidate = val_str.split(prefix)[1].split(".")[0]
                    if candidate.isdigit():
                        return candidate
    except Exception:
        pass
    return None


def format_mac_from_fdb_oid(oid_str: str, val_str: str = "") -> str:
    """
    自 RFC 1493 FDB 表 (dot1dTpFdbTable) 的 OID 尾碼或回傳值解析出標準 XX:XX:XX:XX:XX:XX MAC 位址。
    dot1dTpFdbAddress OID: 1.3.6.1.2.1.17.4.3.1.1.<m1>.<m2>.<m3>.<m4>.<m5>.<m6>
    dot1dTpFdbPort    OID: 1.3.6.1.2.1.17.4.3.1.2.<m1>.<m2>.<m3>.<m4>.<m5>.<m6>
    """
    for col_prefix in ("1.3.6.1.2.1.17.4.3.1.1.", "1.3.6.1.2.1.17.4.3.1.2.", "1.3.6.1.2.1.17.4.3.1.3."):
        if col_prefix in oid_str:
            suffix = oid_str.split(col_prefix, 1)[1]
            parts = suffix.split(".")
            if len(parts) >= 6:
                try:
                    octets = [int(p) for p in parts[:6]]
                    return ":".join(f"{b:02X}" for b in octets)
                except ValueError:
                    pass

    # 備援：若為 Hex-STRING 格式 (如 0x001094000001)
    cleaned_val = val_str.strip()
    if cleaned_val.startswith("0x") and len(cleaned_val) == 14:
        raw_hex = cleaned_val[2:]
        return ":".join(raw_hex[i:i+2].upper() for i in range(0, 12, 2))

    return val_str


def describe_overflow_oid(oid_str: str) -> str:
    """標註超出目前查詢欄位之溢出 OID 所屬的 MIB 欄位或表名稱。"""
    if oid_str.startswith("1.3.6.1.2.1.17.4.3.1.2."):
        return " (跨欄位: dot1dTpFdbPort)"
    elif oid_str.startswith("1.3.6.1.2.1.17.4.3.1.3."):
        return " (跨欄位: dot1dTpFdbStatus)"
    elif oid_str.startswith("1.3.6.1.2.1.17.4.4."):
        return " (跨表溢出: dot1dTpPortTable)"
    elif "1.3.6.1.2.1.17.5." in oid_str:
        return " (跨表溢出: dot1dStp)"
    elif "1.3.6.1.2.1.17.6." in oid_str:
        return " (跨表溢出: qBridgeMIB)"
    elif "1.3.6.1.2.1.17.7." in oid_str:
        return " (跨表溢出: pBridgeMIB)"
    return " (超出本欄位範圍)"


def snmp_get_memory_usage(target_ip: str, hw_id: str, auth_data: Any, port: int = 161, timeout: float = 2.0, retries: int = 1) -> Tuple[Optional[str], float, Optional[str]]:
    """
    執行單次 SNMP Get 查詢 memoryUsage (OID: 1.3.6.1.4.1.8691.7.<HW_ID>.1.59.0)。
    
    Returns:
        Tuple[memory_value_str, elapsed_ms, error_str]
    """
    oid = f"1.3.6.1.4.1.8691.7.{hw_id}.1.59.0"
    t_start = time.time()
    try:
        iterator = getCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        elapsed_ms = (time.time() - t_start) * 1000.0

        if errorIndication:
            return None, elapsed_ms, str(errorIndication)
        elif errorStatus:
            return None, elapsed_ms, f"{errorStatus.prettyPrint()} (index {errorIndex})"
        else:
            for varBind in varBinds:
                val = varBind[1]
                val_str = val.prettyPrint()
                val_type = type(val).__name__
                if val_type in ('NoSuchInstance', 'NoSuchObject', 'EndOfMibView') or "No Such" in val_str:
                    return None, elapsed_ms, f"NoSuchInstanceOrObject ({val_type})"
                return val_str, elapsed_ms, None
    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return None, elapsed_ms, str(e)

    elapsed_ms = (time.time() - t_start) * 1000.0
    return None, elapsed_ms, "Empty response"


def snmp_getbulk_single_varbind(
    target_ip: str,
    root_oid: str,
    auth_data: Any,
    port: int = 161,
    max_repetitions: int = 50,
    single_pdu_only: bool = True,
    timeout: float = 3.0,
    retries: int = 1
) -> Tuple[List[Dict[str, str]], int, float, Optional[str]]:
    """
    以嚴格「單一 VarBind (Single-VarBind)」發送 GetBulk 請求。
    絕不將多個 OID 打包在同一請求中，徹底避免交換機多欄位併行迭代的記憶體洩漏！
    
    Args:
        target_ip: DUT IP
        root_oid: 單一欄位根節點 OID (如 1.3.6.1.2.1.17.4.3.1.1)
        auth_data: SNMP 認證物件
        max_repetitions: 每請求獲取筆數 (預設 50)
        single_pdu_only: True 表示僅發送 1 次 PDU (100% 吻合無洩漏封包行為)，False 表示分頁走訪整表
        
    Returns:
        Tuple[entries_list, valid_table_count, elapsed_ms, error_str]
        每個 entry 包含: {"oid": str, "mac": str, "val": str, "in_table": bool}
    """
    entries: List[Dict[str, str]] = []
    valid_count = 0
    t_start = time.time()

    try:
        iterator = bulkCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            0,                  # non-repeaters = 0
            max_repetitions,    # max-repetitions = 50
            ObjectType(ObjectIdentity(root_oid)),
            lexicographicMode=True, # 必須為 True，以便接收單一 PDU 內超出 root_oid 子樹範圍的跨界 VarBinds
            maxCalls=(1 if single_pdu_only else 0) # 1 表示僅發送單一 PDU 請求；0 表示分頁走訪整表
        )

        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                elapsed_ms = (time.time() - t_start) * 1000.0
                return entries, valid_count, elapsed_ms, str(errorIndication)
            elif errorStatus:
                elapsed_ms = (time.time() - t_start) * 1000.0
                return entries, valid_count, elapsed_ms, f"{errorStatus.prettyPrint()} (index {errorIndex})"
            
            for varBind in varBinds:
                curr_oid = str(varBind[0])
                val_str = varBind[1].prettyPrint()
                val_type = type(varBind[1]).__name__

                if val_type in ('NoSuchInstance', 'NoSuchObject', 'EndOfMibView') or "No Such" in val_str or "End of MIB" in val_str:
                    continue

                in_table = curr_oid.startswith(root_oid + ".")
                if in_table:
                    valid_count += 1
                elif not single_pdu_only:
                    # 分頁走訪模式下，一旦超出本欄位子樹即停止
                    elapsed_ms = (time.time() - t_start) * 1000.0
                    return entries, valid_count, elapsed_ms, None

                mac_fmt = format_mac_from_fdb_oid(curr_oid, val_str)
                entries.append({
                    "oid": curr_oid,
                    "mac": mac_fmt,
                    "val": val_str,
                    "in_table": in_table
                })

        elapsed_ms = (time.time() - t_start) * 1000.0
        return entries, valid_count, elapsed_ms, None

    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return entries, valid_count, elapsed_ms, str(e)


def snmp_getbulk_multi_varbind(
    target_ip: str,
    auth_data: Any,
    port: int = 161,
    max_repetitions: int = 50,
    timeout: float = 3.0,
    retries: int = 1
) -> Tuple[List[Dict[str, str]], float, Optional[str]]:
    """
    以「複合多欄位 (Multi-VarBind)」發送 GetBulk 請求。
    在同一個 PDU 中同時包含 dot1dTpFdbAddress 與 dot1dTpFdbPort (max-repetitions = 50)，
    100% 重現 getbulk_memory leak1.pcapng 的測試行為與交換機端多欄位併行迭代的記憶體洩漏/無回應現象。

    Returns:
        Tuple[entries_list, elapsed_ms, error_str]
        每個 entry 包含: {"oid": str, "mac": str, "val": str}
    """
    entries: List[Dict[str, str]] = []
    t_start = time.time()

    try:
        iterator = bulkCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            0,                  # non-repeaters = 0
            max_repetitions,    # max-repetitions = 50
            ObjectType(ObjectIdentity("1.3.6.1.2.1.17.4.3.1.1")),
            ObjectType(ObjectIdentity("1.3.6.1.2.1.17.4.3.1.2")),
            lexicographicMode=True,
            maxCalls=1
        )
        for errorIndication, errorStatus, errorIndex, varBinds in iterator:
            if errorIndication:
                elapsed_ms = (time.time() - t_start) * 1000.0
                return entries, elapsed_ms, str(errorIndication)
            elif errorStatus:
                elapsed_ms = (time.time() - t_start) * 1000.0
                return entries, elapsed_ms, f"{errorStatus.prettyPrint()} (index {errorIndex})"
            
            for varBind in varBinds:
                curr_oid = str(varBind[0])
                val_str = varBind[1].prettyPrint()
                val_type = type(varBind[1]).__name__

                if val_type in ('NoSuchInstance', 'NoSuchObject', 'EndOfMibView'):
                    continue

                mac_fmt = format_mac_from_fdb_oid(curr_oid, val_str)
                entries.append({
                    "oid": curr_oid,
                    "mac": mac_fmt,
                    "val": val_str
                })

        elapsed_ms = (time.time() - t_start) * 1000.0
        return entries, elapsed_ms, None

    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return entries, elapsed_ms, str(e)


####################### 主程式 ###########################

def main():
    # --- [Phase 1] 參數蒐集與初始化 ---
    print("\n" + "="*75)
    print(" Valencia SNMP GetBulk 測試系統 (單一 VarBind 安全版 vs 複合多欄位崩潰重現版)")
    print(" (支援 getbulk_no memory leak 安全架構 與 getbulk_memory leak1 崩潰現象重現)")
    print("="*75)

    # 1.1 讀取參數表與選擇 Scenario
    all_scenarios = load_scenarios_from_csv("scenarios.csv")
    selected_scenarios = select_scenarios(all_scenarios)
    if not selected_scenarios:
        print("[錯誤] 未選取任何 Scenario，終止測試。")
        sys.exit(1)

    # 1.2 設定 SNMP 驗證與協定版本
    read_auth, snmp_version_label = setup_snmp_auth()

    # 1.3 選擇 GetBulk 執行模式
    mode_label, getbulk_mode = select_getbulk_mode()

    # 1.4 互動輸入執行輪次與間隔時間 (嚴格調用 comm_helper 之 0 參數 API)
    iteration = get_iteration_count()
    delay_time = get_delay_time()

    snmp_port = 161
    log_filename = get_result_log_path(__file__, "result.txt")

    # 1.5 配置各 DUT 之 HW_ID（優先讀取 scenarios.csv 參數，若無則自動探測）
    print("\n正在確認各 DUT 設備之硬體型號識別碼 (HW_ID)...")
    hw_id_map: Dict[str, str] = {}
    for sc in selected_scenarios:
        ip = sc["DUT_IP"]
        configured_hw = sc.get("HW_ID", "").strip()
        if ip not in hw_id_map:
            if configured_hw:
                hw_id_map[ip] = configured_hw
                print(f"  - DUT {ip} -> 自 scenarios.csv 載入參數: HW_ID = {configured_hw}")
            else:
                detected = detect_hw_id(ip, read_auth, snmp_port)
                if detected:
                    hw_id_map[ip] = detected
                    print(f"  - DUT {ip} -> 自動探測成功！HW_ID = {detected}")
                else:
                    hw_id_map[ip] = "125"  # 預設為 125
                    print(f"  - DUT {ip} -> 未探測到 sysObjectID，使用預設 HW_ID = 125")

    # --- [Phase 2] 環境預檢與連線配置 ---
    print("\n=== [Phase 2] 環境預檢：檢測所有選取 DUT 之網路連線 ===")
    online_count = 0
    for sc in selected_scenarios:
        ip = sc["DUT_IP"]
        is_alive = Pingfunc(ip, times=2, interval=0.5)
        if is_alive:
            print(f"  [Scenario {sc['Scenario']}] DUT {ip}: 🟢 在線正常")
            online_count += 1
        else:
            print(f"  [Scenario {sc['Scenario']}] DUT {ip}: 🔴 離線 (Ping 失敗)")

    if online_count == 0:
        print("\n[錯誤] 所有選取之 DUT 皆無法連線，終止測試。請檢查實體連線與 IP 設定。")
        sys.exit(1)

    # 寫入測試批次日誌標頭
    start_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sc_summary_list = [f"Sc{s['Scenario']}({s['DUT_IP']})" for s in selected_scenarios]
    scenario_list_str = ', '.join(sc_summary_list)
    with open(log_filename, 'a+', encoding='utf-8') as f_log:
        f_log.write(f"\n{'='*80}\n")
        f_log.write(f"Valencia SNMP GetBulk 測試批次啟動: {start_time_str}\n")
        f_log.write(f"SNMP 模式: {snmp_version_label}\n")
        f_log.write(f"GetBulk 模式: {mode_label}\n")
        f_log.write(f"執行輪數: {iteration} 輪 | 輪間等待: {delay_time} 秒 | 涵蓋場景數: {len(selected_scenarios)}\n")
        f_log.write(f"場景清單: {scenario_list_str}\n")
        if getbulk_mode == "single":
            f_log.write(f"核心保證: 每個 GetBulk PDU 僅帶 1 個 OID (max-repetitions=50)，杜絕多欄位併行記憶體洩漏\n")
        else:
            f_log.write(f"測試目的: 在單一 PDU 同時打包 Address 與 Port 兩欄位 (max-repetitions=50)，重現 getbulk_memory leak1 崩潰洩漏\n")
        f_log.write(f"{'='*80}\n")

    # --- [Phase 3] 自動化測試迴圈 ---
    print("\n" + "="*75)
    print(f"=== [Phase 3] 自動化測試迴圈啟動 (總計 {iteration} 輪，每輪包含 {len(selected_scenarios)} 個 Scenario) ===")
    print("="*75)

    try:
        for i in range(iteration):
            loop_idx = i + 1
            iter_start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            print(f"\n>>>>>>>>>>>> [第 {loop_idx:02d}/{iteration:02d} 輪測試啟動 (共 {len(selected_scenarios)} 個 Scenario)] <<<<<<<<<<<<")
            
            # # 3.1 記錄本大輪起始標記
            batch_log_header = (
                f"\n╔{'═'*78}╗\n"
                f"║ 測試第 {loop_idx:02d}/{iteration:02d} 輪次 | 起始時間: {iter_start_ts} | 場景總數: {len(selected_scenarios):<3} ║\n"
                f"╚{'═'*78}╝\n"
            )
            print(batch_log_header.strip())
            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                f_log.write(batch_log_header)

            # # 3.2 依序輪詢選定之各個 Scenario (DUT IP)
            for sc_order, sc in enumerate(selected_scenarios, 1):
                sc_id = sc["Scenario"]
                target_ip = sc["DUT_IP"]
                hw_id = hw_id_map.get(target_ip, "125")

                print(f"\n  ---> 正在執行 Scenario {sc_id} (DUT: {target_ip}, HW_ID: {hw_id}) [{sc_order}/{len(selected_scenarios)}] ...")

                # 檢查 DUT 在線狀態 (Ping 檢測)
                if not Pingfunc(target_ip, times=1):
                    print(f"    [警告] Scenario {sc_id} (DUT {target_ip}) Ping 失敗！設備離線。跳過此設備。")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        ts_err = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        f_log.write(f"[{ts_err}] 輪次 {loop_idx:02d} | Scenario {sc_id} ({target_ip}) Ping 失敗 (離線)。跳過。\n")
                    continue

                sc_start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                log_lines = []
                log_lines.append(f"┌{'─'*78}┐")
                log_lines.append(f"│ 輪次: {loop_idx:02d}/{iteration:02d} | Scenario: {sc_id:<4} | 目標: {target_ip:<15} | HW_ID: {hw_id:<4} | 時間: {sc_start_ts} │")
                log_lines.append(f"├{'─'*78}┤")

                # # 3.3 執行 SNMP Get memoryUsage
                t_act_mem = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                mem_val, mem_elapsed, mem_err = snmp_get_memory_usage(target_ip, hw_id, read_auth, snmp_port)
                mem_status = "🟢 PASS" if not mem_err else "🔴 FAIL"
                mem_display = f"{mem_val}%" if not mem_err else f"錯誤: {mem_err}"
                mem_oid = f"1.3.6.1.4.1.8691.7.{hw_id}.1.59.0"
                
                log_lines.append("  [動作 1: SNMP Get memoryUsage]")
                log_lines.append(f"    [{mem_status}] {t_act_mem} | memoryUsage | {mem_oid} = {mem_display} | 耗時: {mem_elapsed:.1f} ms")

                if getbulk_mode == "single":
                    # [模式 1] 單一 VarBind 無洩漏版 (Single-VarBind Safe Mode)
                    # # 3.4 執行 SNMP GetBulk dot1dTpFdbAddress (單一 VarBind, max-repetitions = 50)
                    t_act_bulk_addr = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    fdb_entries, addr_valid_cnt, addr_elapsed, addr_err = snmp_getbulk_single_varbind(
                        target_ip, "1.3.6.1.2.1.17.4.3.1.1", read_auth, snmp_port,
                        max_repetitions=50, single_pdu_only=True, timeout=3.0
                    )
                    addr_status = "🟢 PASS" if not addr_err else "🔴 FAIL"
                    log_lines.append("  [動作 2: SNMP GetBulk dot1dTpFdbAddress (單一 VarBind | max-repetitions = 50)]")
                    if addr_err:
                        log_lines.append(f"    [{addr_status}] {t_act_bulk_addr} | dot1dTpFdbAddress | 查詢失敗: {addr_err} | 耗時: {addr_elapsed:.1f} ms")
                    else:
                        total_rx = len(fdb_entries)
                        overflow_str = f" (有效 FDB 項目: {addr_valid_cnt} 筆, 跨界溢出: {total_rx - addr_valid_cnt} 筆)" if total_rx > addr_valid_cnt else ""
                        log_lines.append(f"    [{addr_status}] {t_act_bulk_addr} | dot1dTpFdbAddress | 回傳總數: {total_rx} 筆{overflow_str} | 耗時: {addr_elapsed:.1f} ms")
                        
                        valid_items = [e for e in fdb_entries if e["in_table"]]
                        if valid_items:
                            show_cnt_v = 5 if len(valid_items) > 5 else len(valid_items)
                            for idx, entry in enumerate(valid_items[:show_cnt_v], 1):
                                log_lines.append(f"          ├─ [{idx:02d}] {entry['mac']} ({entry['oid']})")
                            if len(valid_items) > show_cnt_v:
                                log_lines.append(f"          └─ ... (共 {len(valid_items)} 筆有效 MAC，末筆: [{len(valid_items):02d}] {valid_items[-1]['mac']})")
                        else:
                            log_lines.append("          └─ (目前 FDB MAC 轉發表為空)")

                        # 記錄跨界溢出條目至 result.txt
                        overflow_items = [e for e in fdb_entries if not e["in_table"]]
                        if overflow_items:
                            log_lines.append(f"          ⚠️ [跨界溢出條目 (共 {len(overflow_items)} 筆，超出本欄位範圍)]：")
                            show_cnt_o = 5 if len(overflow_items) > 5 else len(overflow_items)
                            for o_idx, entry in enumerate(overflow_items[:show_cnt_o], 1):
                                tag = describe_overflow_oid(entry['oid'])
                                log_lines.append(f"              ├─ [跨界 {o_idx:02d}] {entry['oid']} = {entry['val']}{tag}")
                            if len(overflow_items) > show_cnt_o:
                                last_tag = describe_overflow_oid(overflow_items[-1]['oid'])
                                log_lines.append(f"              └─ ... (末筆: [跨界 {len(overflow_items):02d}] {overflow_items[-1]['oid']} = {overflow_items[-1]['val']}{last_tag})")

                    # # 3.5 執行 SNMP GetBulk dot1dTpFdbPort (單一 VarBind, max-repetitions = 50)
                    t_act_bulk_port = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    port_entries, port_valid_cnt, port_elapsed, port_err = snmp_getbulk_single_varbind(
                        target_ip, "1.3.6.1.2.1.17.4.3.1.2", read_auth, snmp_port,
                        max_repetitions=50, single_pdu_only=True, timeout=3.0
                    )
                    port_status = "🟢 PASS" if not port_err else "🔴 FAIL"
                    log_lines.append("  [動作 3: SNMP GetBulk dot1dTpFdbPort (單一 VarBind | max-repetitions = 50)]")
                    if port_err:
                        log_lines.append(f"    [{port_status}] {t_act_bulk_port} | dot1dTpFdbPort | 查詢失敗: {port_err} | 耗時: {port_elapsed:.1f} ms")
                    else:
                        total_rx_p = len(port_entries)
                        overflow_p_str = f" (有效 FDB 項目: {port_valid_cnt} 筆, 跨界溢出: {total_rx_p - port_valid_cnt} 筆)" if total_rx_p > port_valid_cnt else ""
                        log_lines.append(f"    [{port_status}] {t_act_bulk_port} | dot1dTpFdbPort | 回傳總數: {total_rx_p} 筆{overflow_p_str} | 耗時: {port_elapsed:.1f} ms")
                        
                        valid_ports = [e for e in port_entries if e["in_table"]]
                        if valid_ports:
                            show_cnt_vp = 5 if len(valid_ports) > 5 else len(valid_ports)
                            for idx, entry in enumerate(valid_ports[:show_cnt_vp], 1):
                                log_lines.append(f"          ├─ [{idx:02d}] {entry['mac']} -> Port: {entry['val']} ({entry['oid']})")
                            if len(valid_ports) > show_cnt_vp:
                                log_lines.append(f"          └─ ... (共 {len(valid_ports)} 筆有效映射，末筆: [{len(valid_ports):02d}] {valid_ports[-1]['mac']} -> Port: {valid_ports[-1]['val']})")
                        else:
                            log_lines.append("          └─ (目前 FDB 轉發埠表為空)")

                        # 記錄跨界溢出條目至 result.txt
                        overflow_ports = [e for e in port_entries if not e["in_table"]]
                        if overflow_ports:
                            log_lines.append(f"          ⚠️ [跨界溢出條目 (共 {len(overflow_ports)} 筆，超出本欄位範圍)]：")
                            show_cnt_op = 5 if len(overflow_ports) > 5 else len(overflow_ports)
                            for o_idx, entry in enumerate(overflow_ports[:show_cnt_op], 1):
                                tag = describe_overflow_oid(entry['oid'])
                                log_lines.append(f"              ├─ [跨界 {o_idx:02d}] {entry['oid']} = {entry['val']}{tag}")
                            if len(overflow_ports) > show_cnt_op:
                                last_tag_p = describe_overflow_oid(overflow_ports[-1]['oid'])
                                log_lines.append(f"              └─ ... (末筆: [跨界 {len(overflow_ports):02d}] {overflow_ports[-1]['oid']} = {overflow_ports[-1]['val']}{last_tag_p})")

                else:
                    # [模式 2] 複合多欄位崩潰版 (Multi-VarBind Crash Mode, 100% 吻合 getbulk_memory leak1.pcapng)
                    # # 3.4 執行 SNMP GetBulk 複合多欄位 (同一個 PDU 同時請求 Address + Port, max-repetitions = 50)
                    t_act_bulk_multi = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    multi_entries, multi_elapsed, multi_err = snmp_getbulk_multi_varbind(
                        target_ip, read_auth, snmp_port, max_repetitions=50, timeout=3.0
                    )
                    multi_status = "🟢 PASS" if not multi_err else "🔴 FAIL"
                    log_lines.append("  [動作 2: SNMP GetBulk 複合多欄位 (Address + Port 複合 PDU | max-repetitions = 50)]")
                    if multi_err:
                        log_lines.append(f"    [{multi_status}] {t_act_bulk_multi} | 複合多欄位查詢 | 查詢失敗: {multi_err} | 耗時: {multi_elapsed:.1f} ms")
                        log_lines.append("          └─ [崩潰/無回應現象] 吻合 getbulk_memory leak1.pcapng 特徵 (交換機多欄位迭代器資源配置失敗丟包/逾時)")
                    else:
                        log_lines.append(f"    [{multi_status}] {t_act_bulk_multi} | 複合多欄位查詢 | 回傳總數: {len(multi_entries)} 筆 | 耗時: {multi_elapsed:.1f} ms")
                        for idx, entry in enumerate(multi_entries[:4], 1):
                            log_lines.append(f"          ├─ [{idx:02d}] {entry['oid']} = {entry['val']} ({entry['mac']})")
                        if len(multi_entries) > 4:
                            log_lines.append(f"          └─ ... (共 {len(multi_entries)} 筆複合回傳，末筆: [{len(multi_entries):02d}] {entry['oid']} = {entry['val']})")

                log_lines.append(f"└{'─'*78}┘\n")

                # # 3.6 記錄該 Scenario 之測試結果至 result.txt 與終端
                formatted_output = "\n".join(log_lines)
                print(formatted_output)
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(formatted_output + "\n")

            # # 3.7 當輪所有 Scenario 執行完畢，等候設定之輪詢間隔時間 (delay_time 秒)
            print(f"--> [第 {loop_idx:02d}/{iteration:02d} 輪全部 {len(selected_scenarios)} 個場景執行完畢！]")
            if i < iteration - 1:
                print(f"--> 依設定等候輪間間隔時間 {delay_time} 秒，準備進入下一輪...")
                time.sleep(delay_time)

    except KeyboardInterrupt:
        print("\n使用者手動中斷測試 (Ctrl+C)。")
    except Exception as e:
        print(f"\n測試迴圈執行期間發生非預期例外: {e}")
        import traceback
        traceback.print_exc()
    finally:
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n[結束] 測試於 {end_time_str} 完成或終止。\n{'='*80}\n")
        print(f"\n已完成所有指定輪次或中斷退出。詳細日誌已安全儲存至: {log_filename}")


if __name__ == "__main__":
    main()
