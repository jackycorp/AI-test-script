# -*- coding: utf-8 -*-
"""
名稱: Valencia 全覆蓋持續 SNMP Polling 測試腳本 (Valencia_SNMP_polling.py)

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 動態載入外部 OID 設定檔 (valencia_oids.txt)，解析各類別 OID 動作。
  1.2 讀取測試參數表 (scenarios.csv)，提示使用者選擇執行的 Scenario (支援單選、多選或全部)。
  1.3 提示輸入「執行總輪數」與「每輪間隔等待時間 (秒)」。
  1.4 自動探測各選定 DUT 之硬體型號識別碼 (<HW_ID>)。
[Phase 2] 環境預檢與連線配置
  2.1 透過 Pingfunc 檢測各選定 DUT 之網路連線狀態。
  2.2 初始化日誌檔標頭 (result.txt)。
[Phase 3] 自動化測試迴圈 (多個 Scenario 輪詢完畢後算作一完整輪次)
  3.1 進入第 i+1 輪測試迴圈。
  3.2 依序輪詢選定之各個 Scenario (DUT IP)，檢查在線狀態 (Ping 檢測)。
  3.3 執行「通電啟動 SNMP Get」查詢。
  3.4 執行「SNMP Get Multi-Varbind」單一 PDU 批次查詢。
  3.5 依序執行「SNMP Walk (GetNext)」子樹深度遍歷。
  3.6 執行「SNMP GetBulk」表格查詢。
  3.7 執行「SNMP Set」安全性寫入驗證 (portEnable)。
  3.8 記錄該 Scenario 之測試結果與通訊耗時至 result.txt 與終端。
  3.9 當輪所有 Scenario 執行完畢，等候設定之輪詢間隔時間 (delay_time 秒)。
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

# 引入共用通訊工具（依 SKILL.md 工具箱按需裝配原則，本測試純使用 SNMP 與 Ping）
try:
    from utils.comm_helper import get_iteration_count, get_delay_time, Pingfunc, get_result_log_path
except ImportError as e:
    print(f"無法載入 comm_helper: {e}")
    sys.exit(1)

# 引入 pysnmp 核心元件 (支援 SNMPv3 USM 安全驗證與 SNMPv1/v2c)
try:
    from pysnmp.hlapi import (
        SnmpEngine, CommunityData, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity, Integer32,
        getCmd, nextCmd, bulkCmd, setCmd,
        UsmUserData, usmHMACSHAAuthProtocol, usmHMACMD5AuthProtocol,
        usmDESPrivProtocol, usmAesCfb128Protocol
    )
except ImportError as e:
    print(f"無法載入 pysnmp 套件 (請確認環境已安裝 pysnmp): {e}")
    sys.exit(1)


####################### 輔助函式 ###########################


def load_valencia_oids(filepath: str = "valencia_oids.txt") -> Dict[str, List[Tuple[str, str]]]:
    """
    自外部 TXT 設定檔動態讀取 Valencia OID 清單，依動作區塊分類解析。
    
    支援格式:
      [SECTION_NAME]
      OID, 名稱/描述
    """
    resolved_path = filepath
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
        print(f"[警告] 找不到 OID 設定檔: {resolved_path}，將使用內建預設 OID 清單。")
        return {
            "STARTUP_GET": [
                ("P.1.89.1.0", "startup_1_89_1"),
                ("P.1.89.3.0", "startup_1_89_3"),
                ("P.1.89.2.0", "startup_1_89_2"),
                ("1.3.6.1.6.3.15.1.1.4.0", "usmStatsUnknownEngineIDs"),
                ("1.3.6.1.6.3.15.1.1.2.0", "usmStatsNotInTimeWindows")
            ],
            "MULTI_VARBIND_GET": [
                ("P.1.53.0", "cpuLoading5s"),
                ("P.1.54.0", "cpuLoading30s"),
                ("P.1.55.0", "cpuLoading300s"),
                ("P.1.59.0", "memoryUsage"),
                ("P.1.4.0", "firmwareVersion"),
                ("1.3.6.1.2.1.1.5.0", "sysName"),
                ("P.1.16.4.0", "activeProtocolOfRedundancy"),
                ("P.1.16.5.1.10.0", "brokenStatusRing1"),
                ("P.1.16.2.14.0", "turboRingBrokenStatus"),
                ("P.1.16.7.1.8.0", "drcBrokenStatusRing"),
                ("P.1.16.5.1.7.0", "rdnt1stPortStatusRing1"),
                ("P.1.16.5.1.6.0", "rdnt1stPortRing1"),
                ("P.1.16.5.1.9.0", "rdnt2ndPortStatusRing1"),
                ("P.1.16.5.1.8.0", "rdnt2ndPortRing1")
            ],
            "WALK": [
                ("P.1.10.3.1.3", "monitorSpeed"),
                ("P.1.16.2.3.1.2", "turboRingPortStatus"),
                ("P.1.10.3.1.5", "monitorTraffic"),
                ("P.1.9.1.1.3", "portEnable"),
                ("P.1.10.3.1.2", "monitorLinkStatus"),
                ("1.3.6.1.2.1.2.2.1.14", "ifInErrors"),
                ("1.3.6.1.2.1.2.2.1.20", "ifOutErrors"),
                ("1.0.8802.1.1.2.1.4.1.1.9", "lldpRemSysName"),
                ("1.0.8802.1.1.2.1.4.1.1.10", "lldpRemSysDesc"),
                ("1.0.8802.1.1.2.1.4.1.1.11", "lldpRemSysCapSupported"),
                ("1.0.8802.1.1.2.1.4.1", "lldpRemTable"),
                ("P.1.40.3.1.2", "OMTS_1_40_3_1_2"),
                ("1.3.6.1.2.1.17.4.3.1.2", "dot1dTpFdbPort")
            ],
            "GETBULK": [
                ("1.3.6.1.2.1.2.2.1.8", "ifOperStatus"),
                ("1.3.6.1.2.1.17.4.3.1.1", "dot1dTpFdbAddress"),
                ("1.3.6.1.2.1.17.4.3.1.2", "dot1dTpFdbPort"),
                ("1.3.6.1.2.1.17.4.3.1.3", "dot1dTpFdbStatus"),
                ("1.0.8802.1.1.2.1.4.1.1.9", "lldpRemSysName")
            ],
            "SET": [
                ("P.1.9.1.1.3", "portEnable")
            ]
        }

    categories: Dict[str, List[Tuple[str, str]]] = {
        "STARTUP_GET": [],
        "MULTI_VARBIND_GET": [],
        "WALK": [],
        "GETBULK": [],
        "SET": []
    }
    current_section = None

    with open(resolved_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_section = line[1:-1].strip().upper()
                if current_section not in categories:
                    categories[current_section] = []
                continue
            
            if current_section:
                # 支援行尾 '#' 註解過濾
                if "#" in line:
                    line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split(",", 1)]
                oid_val = parts[0]
                name_val = parts[1] if len(parts) > 1 else oid_val
                categories[current_section].append((oid_val, name_val))

    print(f"成功自 {os.path.basename(resolved_path)} 載入 OID 配置：")
    for sec, oids in categories.items():
        print(f"  - [{sec}]: 共 {len(oids)} 個項目")
    return categories


def load_scenarios_from_csv(csv_path: str = "scenarios.csv") -> List[Dict[str, str]]:
    """依 SKILL.md Rule 12 規範，防禦性解析讀取 scenarios.csv。"""
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
        print(f"錯誤：找不到參數表檔案 {resolved_path}")
        sys.exit(1)

    scenarios = []
    with open(resolved_path, mode="r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 防禦性清理：嚴格防止 NoneType.strip() 異常
            clean_row = {str(k).strip(): (str(v).strip() if v is not None else "") for k, v in row.items() if k is not None}
            if not clean_row or not clean_row.get("Scenario"):
                continue

            # 動態匹配 IP 欄位與 HW_ID 欄位
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


def setup_snmp_auth() -> Tuple[Any, Any, str]:
    """
    設定 SNMP 驗證資訊，預設使用 SNMPv3 (authPriv / SHA-1 / DES)。
    亦相容自環境變數 (RENFE_SNMP_USER, RENFE_SNMP_AUTH, RENFE_SNMP_PRIV) 或命令列自定義。
    
    Returns:
        Tuple[read_auth, write_auth, version_label]
    """
    env_user = os.environ.get("RENFE_SNMP_USER", "admin")
    env_auth = os.environ.get("RENFE_SNMP_AUTH", "moxamoxa")
    env_priv = os.environ.get("RENFE_SNMP_PRIV", "moxamoxa")

    print("\n" + "-"*65)
    print("SNMP 協定模式選擇：")
    print(f"  [1] SNMPv3 (預設推薦，authPriv / SHA-1 / DES | 預設帳號: {env_user})")
    print("  [2] SNMPv2c (傳統社群字串 | public 讀取 / private 寫入)")
    print("-"*(65))
    mode_input = input("請選擇 SNMP 協定模式 (直接 Enter 預設為 [1] SNMPv3): ").strip()

    if mode_input == "2":
        comm_read = input("請輸入 Read Community (直接 Enter 預設 public): ").strip() or "public"
        comm_write = input("請輸入 Write Community (直接 Enter 預設 private): ").strip() or "private"
        read_auth = CommunityData(comm_read)
        write_auth = CommunityData(comm_write)
        version_label = f"SNMPv2c (Read: {comm_read}, Write: {comm_write})"
        print(f"-> 已啟用模式: {version_label}")
        return read_auth, write_auth, version_label
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
        return usm_auth, usm_auth, version_label


def resolve_oid(template: str, hw_id: str) -> str:
    """將 OID 樣板中的 'P' 替換為該 DUT 對應的企業 Private MIB 前綴。"""
    return template.replace("P", f"1.3.6.1.4.1.8691.7.{hw_id}")


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
            # 優先以 asTuple() 進行精準數字比對: (1, 3, 6, 1, 4, 1, 8691, 7, <HW_ID>, ...)
            if hasattr(val, "asTuple"):
                tup = val.asTuple()
                for idx in range(len(tup) - 2):
                    if tup[idx] == 8691 and tup[idx + 1] == 7:
                        return str(tup[idx + 2])

            # 同時支援以 str(val) 進行字串比對 (例如 1.3.6.1.4.1.8691.7.125)
            val_str = str(val)
            for prefix in ("1.3.6.1.4.1.8691.7.", "enterprises.8691.7.", "8691.7."):
                if prefix in val_str:
                    candidate = val_str.split(prefix)[1].split(".")[0]
                    if candidate.isdigit():
                        return candidate
    except Exception:
        pass
    return None


def snmp_get_single(target_ip: str, oid: str, auth_data: Any, port: int = 161, timeout: float = 2.0, retries: int = 1) -> Tuple[Optional[str], Optional[str]]:
    """執行單一節點 SNMP Get 查詢 (支援 SNMPv3 / SNMPv2c)。"""
    try:
        iterator = getCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            ObjectType(ObjectIdentity(oid))
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        if errorIndication:
            return None, str(errorIndication)
        elif errorStatus:
            return None, str(errorStatus.prettyPrint())
        else:
            for varBind in varBinds:
                val = varBind[1]
                val_str = val.prettyPrint()
                val_type_name = type(val).__name__
                if val_type_name in ('NoSuchInstance', 'NoSuchObject', 'EndOfMibView') or "No Such" in val_str:
                    return None, f"NoSuchInstanceOrObject ({val_type_name})"
                return val_str, None
    except Exception as e:
        return None, str(e)
    return None, "Empty response"


def snmp_get_multi_varbind(target_ip: str, oids_with_names: List[Tuple[str, str]], auth_data: Any, port: int = 161, timeout: float = 3.0, retries: int = 1) -> Tuple[List[Dict[str, Any]], float, Optional[str]]:
    """發送單一 SNMP GET 封包 (Single PDU)，同時攜帶多個 VarBinds 進行一次性輪詢 (支援 SNMPv3 / SNMPv2c)。"""
    object_types = [ObjectType(ObjectIdentity(oid)) for oid, _ in oids_with_names]
    results = []
    t_start = time.time()
    try:
        iterator = getCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            *object_types
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        elapsed_ms = (time.time() - t_start) * 1000.0

        if errorIndication:
            return [], elapsed_ms, str(errorIndication)
        elif errorStatus:
            return [], elapsed_ms, f"{errorStatus.prettyPrint()} (at index {errorIndex})"
        else:
            for idx, varBind in enumerate(varBinds):
                orig_oid, name = oids_with_names[idx] if idx < len(oids_with_names) else (str(varBind[0]), "")
                val = varBind[1]
                val_str = val.prettyPrint()
                val_type = type(val).__name__
                is_err = val_type in ('NoSuchInstance', 'NoSuchObject', 'EndOfMibView') or "No Such" in val_str
                results.append({
                    "oid": orig_oid,
                    "name": name,
                    "val": val_str,
                    "type": val_type,
                    "status": "FAIL" if is_err else "PASS"
                })
            return results, elapsed_ms, None
    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return [], elapsed_ms, str(e)


def snmp_walk(target_ip: str, root_oid: str, auth_data: Any, port: int = 161, timeout: float = 2.0, retries: int = 1, max_rows: int = 500) -> Tuple[List[Tuple[str, str]], float, Optional[str]]:
    """透過 nextCmd 執行 SNMP Walk (GetNext) 深度遍歷指定子樹 (支援 SNMPv3 / SNMPv2c)。"""
    results = []
    t_start = time.time()
    try:
        query_tuple = tuple(int(x) for x in root_oid.split('.') if x.isdigit())
    except Exception:
        query_tuple = ()

    try:
        iterator = nextCmd(
            SnmpEngine(),
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


def snmp_getbulk(target_ip: str, root_oid: str, auth_data: Any, port: int = 161, max_repetitions: int = 10, timeout: float = 2.0, retries: int = 1) -> Tuple[List[Tuple[str, str]], float, Optional[str]]:
    """透過 bulkCmd 執行 SNMP GetBulk 批次擷取表格資訊 (支援 SNMPv3 / SNMPv2c)。"""
    results = []
    t_start = time.time()
    try:
        iterator = bulkCmd(
            SnmpEngine(),
            auth_data,
            UdpTransportTarget((target_ip, port), timeout=timeout, retries=retries),
            ContextData(),
            0,
            max_repetitions,
            ObjectType(ObjectIdentity(root_oid)),
            lexicographicMode=False
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
                    results.append((str(varBind[0]), varBind[1].prettyPrint()))
        elapsed_ms = (time.time() - t_start) * 1000.0
        return results, elapsed_ms, None
    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return results, elapsed_ms, str(e)


def snmp_set_safe_verify(target_ip: str, port_enable_root: str, read_auth: Any, write_auth: Any, port: int = 161, test_port_idx: int = 2) -> Tuple[bool, str, float]:
    """安全驗證 SNMP SET 功能：讀取指定埠口之現值後安全寫回原值 (支援 SNMPv3 / SNMPv2c)。"""
    target_oid = f"{port_enable_root}.{test_port_idx}"
    t_start = time.time()
    
    curr_val, err = snmp_get_single(target_ip, target_oid, read_auth, port)
    if err or curr_val is None:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return False, f"GET 現值失敗 ({err})", elapsed_ms
    
    try:
        val_int = int(curr_val)
    except ValueError:
        val_int = 1

    try:
        iterator = setCmd(
            SnmpEngine(),
            write_auth,
            UdpTransportTarget((target_ip, port), timeout=2.0, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(target_oid), Integer32(val_int))
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        elapsed_ms = (time.time() - t_start) * 1000.0
        if errorIndication:
            return False, f"SET 失敗: {errorIndication}", elapsed_ms
        elif errorStatus:
            return False, f"SET 錯誤狀態: {errorStatus.prettyPrint()}", elapsed_ms
        else:
            set_val = varBinds[0][1].prettyPrint()
            return True, f"成功寫回原值: {set_val} (Port {test_port_idx})", elapsed_ms
    except Exception as e:
        elapsed_ms = (time.time() - t_start) * 1000.0
        return False, f"SET 異常: {e}", elapsed_ms


####################### 主程式 ###########################

def main():
    # --- [Phase 1] 參數蒐集與初始化 ---
    print("\n" + "="*75)
    print("       Valencia 全覆蓋持續 SNMP Polling 測試系統 (Scenarios 批次輪詢)")
    print("="*75)

    # 1.1 載入外部 OID 配置檔
    oid_categories = load_valencia_oids("valencia_oids.txt")

    # 1.2 讀取參數表與選擇 Scenario
    all_scenarios = load_scenarios_from_csv("scenarios.csv")
    selected_scenarios = select_scenarios(all_scenarios)
    if not selected_scenarios:
        print("[錯誤] 未選取任何 Scenario，終止測試。")
        sys.exit(1)

    # 1.3 設定 SNMP 驗證與協定版本 (支援 SNMPv3 與 SNMPv2c)
    read_auth, write_auth, snmp_version_label = setup_snmp_auth()

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
                    hw_id_map[ip] = "80"  # 預設為 80
                    print(f"  - DUT {ip} -> 未探測到 sysObjectID，使用預設 HW_ID = 80")

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
        f_log.write(f"Valencia 全覆蓋 SNMP 輪詢測試批次啟動: {start_time_str}\n")
        f_log.write(f"SNMP 模式: {snmp_version_label}\n")
        f_log.write(f"執行輪數: {iteration} 輪 | 輪間等待: {delay_time} 秒 | 涵蓋場景數: {len(selected_scenarios)}\n")
        f_log.write(f"場景清單: {scenario_list_str}\n")
        f_log.write(f"說明: 每一輪將完整巡檢所有選取之 Scenarios，全部完成後才算一輪完畢。\n")
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
                hw_id = hw_id_map.get(target_ip, "80")

                print(f"\n  ---> 正在執行 Scenario {sc_id} (DUT: {target_ip}, HW_ID: {hw_id}) [{sc_order}/{len(selected_scenarios)}] ...")

                # 檢查 DUT 在線狀態 (Ping 檢測)
                if not Pingfunc(target_ip, times=1):
                    print(f"    [警告] Scenario {sc_id} (DUT {target_ip}) Ping 失敗！設備離線。跳過此設備。")
                    with open(log_filename, 'a+', encoding='utf-8') as f_log:
                        ts_err = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                        f_log.write(f"[{ts_err}] 輪次 {loop_idx:02d} | Scenario {sc_id} ({target_ip}) Ping 失敗 (離線)。跳過。\n")
                    continue

                # 解析該 DUT 的 OID 清單
                resolved_startup = [(resolve_oid(tmpl, hw_id), name) for tmpl, name in oid_categories.get("STARTUP_GET", [])]
                resolved_multi = [(resolve_oid(tmpl, hw_id), name) for tmpl, name in oid_categories.get("MULTI_VARBIND_GET", [])]
                resolved_walks = [(resolve_oid(tmpl, hw_id), name) for tmpl, name in oid_categories.get("WALK", [])]
                resolved_bulk = oid_categories.get("GETBULK", [])
                set_templates = oid_categories.get("SET", [("P.1.9.1.1.3", "portEnable")])
                resolved_set_root = resolve_oid(set_templates[0][0], hw_id)

                sc_start_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                log_lines = []
                log_lines.append(f"┌{'─'*78}┐")
                log_lines.append(f"│ 輪次: {loop_idx:02d}/{iteration:02d} | Scenario: {sc_id:<4} | 目標: {target_ip:<15} | HW_ID: {hw_id:<4} | 時間: {sc_start_ts} │")
                log_lines.append(f"├{'─'*78}┤")

                # # 3.3 執行通電啟動 SNMP Get
                log_lines.append("  [動作 1: 通電啟動 SNMP Get]")
                for oid, name in resolved_startup:
                    t_act = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    val, err = snmp_get_single(target_ip, oid, read_auth, snmp_port)
                    status_tag = "🟢 PASS" if not err else "🔴 FAIL"
                    val_disp = val if not err else f"錯誤: {err}"
                    log_lines.append(f"    [{status_tag}] {t_act} | {name:<20} | {oid} = {val_disp}")

                # # 3.4 執行持續性 SNMP Get Multi-Varbind (單一 PDU 批次查詢)
                t_act_multi = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                multi_res, multi_elapsed, multi_err = snmp_get_multi_varbind(target_ip, resolved_multi, read_auth, snmp_port)
                log_lines.append(f"  [動作 2: SNMP Get Multi-Varbind ({len(resolved_multi)} 個 OID 合併單一 PDU) | 耗時: {multi_elapsed:.1f} ms]")
                if multi_err:
                    log_lines.append(f"    🔴 [PDU 失敗] {t_act_multi} | 錯誤訊息: {multi_err}")
                else:
                    for item in multi_res:
                        status_tag = "🟢 PASS" if item["status"] == "PASS" else "🔴 FAIL"
                        log_lines.append(f"    [{status_tag}] {t_act_multi} | {item['name']:<26} | {item['oid']} = {item['val']}")

                # # 3.5 依序執行持續性 SNMP Walk (GetNext) 子樹深度遍歷
                log_lines.append(f"  [動作 3: 週期性 SNMP Walk / GetNext ({len(resolved_walks)} 個子樹指令)]")
                for walk_idx, (root_oid, name) in enumerate(resolved_walks, 1):
                    t_act_walk = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    w_res, w_elapsed, w_err = snmp_walk(target_ip, root_oid, read_auth, snmp_port)
                    if w_err:
                        log_lines.append(f"    🔴 [{walk_idx}/{len(resolved_walks)}] {t_act_walk} | {name:<22} ({root_oid}) | 耗時: {w_elapsed:.1f} ms | 錯誤: {w_err}")
                    else:
                        log_lines.append(f"    🟢 [{walk_idx}/{len(resolved_walks)}] {t_act_walk} | {name:<22} ({root_oid}) | 筆數: {len(w_res):<3} | 耗時: {w_elapsed:.1f} ms")
                        if w_res:
                            for entry_idx, (e_oid, e_val) in enumerate(w_res[:2]):
                                log_lines.append(f"          ├─ {e_oid} = {e_val}")
                            if len(w_res) > 2:
                                log_lines.append(f"          └─ ... (共 {len(w_res)} 筆，末筆: {w_res[-1][0]} = {w_res[-1][1]})")

                # # 3.6 執行 SNMP GetBulk 表格查詢
                log_lines.append(f"  [動作 4: 司機台 HMI SNMP GetBulk 表格查詢 ({len(resolved_bulk)} 個項目)]")
                for bulk_oid, name in resolved_bulk:
                    t_act_bulk = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    b_res, b_elapsed, b_err = snmp_getbulk(target_ip, bulk_oid, read_auth, snmp_port, max_repetitions=8)
                    if b_err:
                        log_lines.append(f"    🔴 {t_act_bulk} | {name:<18} ({bulk_oid}) | 耗時: {b_elapsed:.1f} ms | 錯誤: {b_err}")
                    else:
                        log_lines.append(f"    🟢 {t_act_bulk} | {name:<18} ({bulk_oid}) | 筆數: {len(b_res):<3} | 耗時: {b_elapsed:.1f} ms")

                # # 3.7 執行 SNMP Set 安全性寫入驗證 (portEnable)
                log_lines.append("  [動作 5: 司機台 HMI SNMP Set 安全性驗證]")
                t_act_set = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                set_ok, set_msg, set_elapsed = snmp_set_safe_verify(target_ip, resolved_set_root, read_auth, write_auth, snmp_port, test_port_idx=2)
                set_tag = "🟢 PASS" if set_ok else "🔴 FAIL"
                log_lines.append(f"    [{set_tag}] {t_act_set} | portEnable 寫入驗證 | 耗時: {set_elapsed:.1f} ms | 結果: {set_msg}")

                log_lines.append(f"└{'─'*78}┘\n")

                # # 3.8 記錄該 Scenario 之測試結果與通訊耗時至 result.txt 與終端
                formatted_output = "\n".join(log_lines)
                print(formatted_output)
                with open(log_filename, 'a+', encoding='utf-8') as f_log:
                    f_log.write(formatted_output + "\n")

            # # 3.9 當輪所有 Scenario 執行完畢，等候設定之輪詢間隔時間 (delay_time 秒)
            print(f"--> [第 {loop_idx:02d}/{iteration:02d} 輪全部 {len(selected_scenarios)} 個場景執行完畢！]")
            if i < iteration - 1:
                print(f"--> 依設定等候輪間間隔時間 {delay_time} 秒，準備進入下一輪...")
                time.sleep(delay_time)

    except KeyboardInterrupt:
        print("\n使用者手動中斷測試 (Ctrl+C)。")
    except Exception as e:
        print(f"\n測試迴圈執行期間發生非預期例外: {e}")
    finally:
        end_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n[結束] 測試於 {end_time_str} 完成或終止。\n{'='*80}\n")
        print(f"\n已完成所有指定輪次或中斷退出。詳細日誌已安全儲存至: {log_filename}")


if __name__ == "__main__":
    main()
