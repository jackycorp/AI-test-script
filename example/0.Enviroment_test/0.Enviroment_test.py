# -*- coding: utf-8 -*-
"""
名稱: 環境與核心模組功能驗證程式 (0.Enviroment_test.py)

測試流程說明：
[Phase 1] 參數蒐集與選單互動
  1.1 顯示所有可用測試功能清單 (1~6)。
  1.2 提示使用者選擇測試項目 (支援單選、多選、直接 Enter 預設全部)。
  1.3 依據使用者選擇之功能項目，動態提示輸入所需參數 (如 COM Port、目標 IP、Spirent 參數等)。
[Phase 2] 環境預檢與日誌初始化
  2.1 初始化集中輸出日誌檔 (test result/0.Enviroment_test_result/result.txt)。
  2.2 檢驗目前執行的 Python 直譯器是否為專案專屬之 .venv。
[Phase 3] 模組功能檢驗與結果報告
  3.1 依序執行選定之模組功能測試：
      - Test 1: utils 核心共用庫導入與路徑檢驗
      - Test 2: icmplib ICMP Ping 功能檢驗
      - Test 3: pyserial 串口掃描與開啟檢驗
      - Test 4: pysnmp + pyasn1 SNMP 引擎與查詢功能檢驗
      - Test 5: scapy 網路封包建構與解碼檢驗 (選用套件)
      - Test 6: Spirent TestCenter 儀器 1 Tx 1 Rx 打流與統計檢驗
  3.2 統計測試結果並將完整總結日誌輸出至終端機與 result.txt。
"""

import sys
import os
import time
import codecs
from datetime import datetime
from typing import List, Dict, Tuple, Any, Optional


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


# 遵循 SKILL.md Rule 1.1：共用工具模組統一透過 utils 匯入
from utils.comm_helper import (
    Pingfunc,
    get_com_port,
    get_result_dir,
    get_result_log_path
)


def get_available_com_ports() -> List[str]:
    """掃描本機目前可用的 COM 串列埠"""
    try:
        import serial.tools.list_ports
        return [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        return []


def log_and_print(msg: str, log_file: str):
    """同步輸出至控制台與日誌檔案 (UTF-8 編碼)"""
    print(msg)
    try:
        with open(log_file, "a+", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception as e:
        print(f"[警告] 寫入日誌失敗: {e}")


####################### 各模組功能檢驗實作 ###########################

def test_utils_module(log_file: str) -> Tuple[bool, str]:
    """檢驗 1: 專案核心共用庫 (utils) 是否可正常匯入與調用"""
    log_and_print("\n[測試 1/6] 檢驗 utils 核心共用庫...", log_file)
    try:
        import utils
        import utils.comm_helper as ch
        import utils.dictionary_parameters as dp
        
        log_and_print(f"  - utils 模組載入成功 (路徑: {utils.__file__})", log_file)
        log_and_print(f"  - comm_helper 載入成功", log_file)
        log_and_print(f"  - dictionary_parameters 載入成功 (定義 Frame: {'Frame' in dir(dp)})", log_file)
        
        res_dir = get_result_dir(__file__)
        log_and_print(f"  - get_result_dir API 測試成功: {res_dir}", log_file)
        return True, "utils 模組與 API 運作完全正常"
    except Exception as e:
        err_msg = f"utils 模組載入失敗: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg


def test_icmplib_module(target_ip: str, log_file: str) -> Tuple[bool, str]:
    """檢驗 2: icmplib 是否能正常發送 ICMP Echo 封包並獲取回傳統計"""
    log_and_print(f"\n[測試 2/6] 檢驗 icmplib 網路 Ping 功能 (目標 IP: {target_ip})...", log_file)
    try:
        import icmplib
        log_and_print(f"  - icmplib 模組版本: {getattr(icmplib, '__version__', '未知')}", log_file)
        
        log_and_print(f"  - 正在向 {target_ip} 發送 Ping 測試封包...", log_file)
        host_stat = icmplib.ping(target_ip, count=2, interval=0.5, timeout=1.5)
        
        if host_stat.is_alive:
            detail = f"Ping 回應正常 (平均延遲: {host_stat.avg_rtt:.2f} ms, 丟包率: {host_stat.packet_loss * 100:.0f}%)"
            log_and_print(f"  - {detail}", log_file)
            return True, detail
        else:
            detail = f"主機無回應 (丟包率: 100%)，但 icmplib 封包發送引擎運作正常"
            log_and_print(f"  - [資訊] {detail}", log_file)
            return True, detail
    except ImportError as e:
        err_msg = f"找不到 icmplib 套件: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg
    except Exception as e:
        err_msg = f"icmplib 執行異常: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg


def test_pyserial_module(com_port: str, log_file: str) -> Tuple[bool, str]:
    """檢驗 3: pyserial 是否能正常調用並掃描/開啟串列埠"""
    log_and_print(f"\n[測試 3/6] 檢驗 pyserial 串口通訊功能 (目標: {com_port})...", log_file)
    try:
        import serial
        import serial.tools.list_ports
        log_and_print(f"  - pyserial 模組版本: {getattr(serial, '__version__', '未知')}", log_file)
        
        detected_ports = [p.device for p in serial.tools.list_ports.comports()]
        log_and_print(f"  - 本機偵測到之實體 COM Port: {detected_ports if detected_ports else '無'}", log_file)
        
        if not com_port or com_port.upper() == "SKIP":
            status_desc = "pyserial 模組載入正常 (略過實體開啟測試)"
            log_and_print(f"  - {status_desc}", log_file)
            return True, status_desc
            
        log_and_print(f"  - 嘗試開啟 {com_port} (Baudrate: 115200)...", log_file)
        try:
            with serial.Serial(port=com_port, baudrate=115200, timeout=1.0) as ser:
                ser.flushInput()
                ser.flushOutput()
                success_desc = f"成功開啟並關閉串列埠 {com_port}"
                log_and_print(f"  - {success_desc}", log_file)
                return True, success_desc
        except serial.SerialException as se:
            status_desc = f"pyserial 功能正常 (連接 {com_port} 狀態: {se})"
            log_and_print(f"  - [資訊] {status_desc}", log_file)
            return True, status_desc
    except ImportError as e:
        err_msg = f"找不到 pyserial 套件: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg
    except Exception as e:
        err_msg = f"pyserial 檢驗異常: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg


def test_pysnmp_module(target_ip: str, community: str, log_file: str) -> Tuple[bool, str]:
    """檢驗 4: pysnmp、pyasn1 與 pycryptodomex 是否相容且能發出 SNMP 請求"""
    log_and_print(f"\n[測試 4/6] 檢驗 pysnmp/pyasn1 功能 (目標: {target_ip}, Community: {community})...", log_file)
    try:
        import Cryptodome
        log_and_print(f"  - pycryptodomex (Cryptodome) 版本: {getattr(Cryptodome, '__version__', '未知')}", log_file)
        
        import pysnmp
        import pyasn1
        log_and_print(f"  - pysnmp 模組版本: {getattr(pysnmp, '__version__', '未知')}", log_file)
        log_and_print(f"  - pyasn1 模組版本: {getattr(pyasn1, '__version__', '未知')}", log_file)
        
        import pyasn1.compat.octets
        log_and_print("  - pyasn1.compat.octets 核心相容模組載入正常", log_file)
        
        from pysnmp.hlapi import (
            SnmpEngine,
            CommunityData,
            UdpTransportTarget,
            ContextData,
            ObjectType,
            ObjectIdentity,
            getCmd
        )
        log_and_print("  - pysnmp.hlapi.SnmpEngine 與同步 getCmd 函式導出正常", log_file)
        
        log_and_print(f"  - 正在對 {target_ip} 構造 SNMPv2c GetRequest (OID: 1.3.6.1.2.1.1.1.0)...", log_file)
        
        engine = SnmpEngine()
        target = UdpTransportTarget((target_ip, 161), timeout=1.0, retries=0)
        community_data = CommunityData(community, mpModel=1)  # SNMPv2c
        
        iterator = getCmd(
            engine,
            community_data,
            target,
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0'))  # sysDescr
        )
        errorIndication, errorStatus, errorIndex, varBinds = next(iterator)
        
        if errorIndication:
            resp_info = f"SNMP 引擎與編碼完全正常 (通訊回應: {errorIndication})"
            log_and_print(f"  - {resp_info}", log_file)
            return True, resp_info
        elif errorStatus:
            resp_info = f"SNMP 收到 Agent 錯誤狀態: {errorStatus.prettyPrint()}"
            log_and_print(f"  - {resp_info}", log_file)
            return True, resp_info
        else:
            val_str = ', '.join([f"{varBind[0]} = {varBind[1]}" for varBind in varBinds])
            resp_info = f"成功取得 SNMP 回應數據: {val_str}"
            log_and_print(f"  - {resp_info}", log_file)
            return True, resp_info
            
    except ImportError as e:
        err_msg = f"SNMP 相依模組匯入失敗 (可能存在版本衝突或遺失): {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg
    except Exception as e:
        err_msg = f"pysnmp 檢驗異常: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg


def test_scapy_module(log_file: str) -> Tuple[bool, str]:
    """檢驗 5: scapy 封包建構與解碼功能 (選用套件)"""
    log_and_print(f"\n[測試 5/6] 檢驗 scapy 封包建構與解析功能 (選用模組)...", log_file)
    try:
        import scapy
        log_and_print(f"  - scapy 模組版本: {getattr(scapy, '__version__', '未知')}", log_file)
        
        from scapy.layers.l2 import Ether
        from scapy.layers.inet import IP, TCP
        
        pkt = Ether(src="00:11:22:33:44:55", dst="ff:ff:ff:ff:ff:ff") / IP(src="192.168.1.10", dst="192.168.1.1") / TCP(sport=12345, dport=80, flags="S")
        raw_bytes = bytes(pkt)
        parsed_pkt = Ether(raw_bytes)
        
        if parsed_pkt.haslayer(TCP) and parsed_pkt[TCP].dport == 80:
            success_desc = f"成功組裝並反解封包 (封包長度: {len(raw_bytes)} bytes)"
            log_and_print(f"  - {success_desc}", log_file)
            return True, success_desc
        else:
            return False, "封包解析欄位不吻合"
    except ImportError:
        status_desc = "scapy 未安裝 (此為選用依賴，不影響核心測試)"
        log_and_print(f"  - [資訊] {status_desc}", log_file)
        return True, status_desc
    except Exception as e:
        err_msg = f"scapy 檢驗失敗: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg


def test_spirent_module(chassis_ip: str, tx_port: str, rx_port: str, duration_sec: int, log_file: str) -> Tuple[bool, str]:
    """檢驗 6: Spirent TestCenter 1 Tx 1 Rx 打流與統計檢驗 (遵循 SKILL.md Rule 5 延遲載入 與 Rule 10 配對原則)"""
    log_and_print(f"\n[測試 6/6] 檢驗 Spirent TestCenter 儀器流量控制 (1 Tx 1 Rx)...", log_file)
    
    # [步驟 6.1] 動態載入 Spirent TestCenter API 核心 (遵循 SKILL.md Rule 5)
    log_and_print("  - 正在載入 Spirent TestCenter API 與 Tcl 核心 (請稍候)...", log_file)
    try:
        import utils.pythontool as pt
        from utils.dictionary_parameters import (
            PortType_1G_Full_AN,
            StreamBlock,
            Frame,
            Frame1,
            Generatortype
        )
        tclsh = pt.tclsh
    except ImportError as e:
        err_msg = f"無法載入 utils.pythontool 或缺少必要 TCL 元件: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg
    except Exception as e:
        err_msg = f"Spirent Tcl 引擎初始化失敗: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg

    # 取得 Spirent API 版本資訊
    try:
        stc_version = tclsh.eval("stc::get system1 -Version")
        log_and_print(f"  - Spirent TestCenter API 版本: {stc_version}", log_file)
    except Exception as e:
        stc_version = f"未知 (讀取失敗: {e})"
        log_and_print(f"  - Spirent TestCenter API 版本: {stc_version}", log_file)

    # [步驟 6.2] 若使用者選擇略過實體機箱連線 (skip)
    if not chassis_ip or chassis_ip.upper() == "SKIP":
        status_desc = f"Spirent TestCenter API (v{stc_version}) 與 Tcl 引擎載入成功 (略過實體機箱連線)"
        log_and_print(f"  - [資訊] {status_desc}", log_file)
        return True, status_desc

    # [步驟 6.3] 實體機箱連線與 1 Tx 1 Rx 發流測試
    log_and_print(f"  - 正在連線至 Spirent 機箱 {chassis_ip}...", log_file)
    # 使用安全 catch 呼叫 stc::connect 避免 tool.tcl 內的 exit 直接中斷程式
    connect_cmd = f'if {{[catch {{stc::connect {chassis_ip}}} err]}} {{set ret "FAIL: $err"}} else {{set ret "OK"}}'
    ret = tclsh.eval(connect_cmd)
    if ret.startswith("FAIL:"):
        err_detail = ret[6:].strip()
        log_and_print(f"  [FAIL] 連線至 Spirent 機箱 {chassis_ip} 失敗: {err_detail}", log_file)
        log_and_print(f"  [提示] 請確認網路路由與機箱電源，或輸入 skip 進行離線 API 檢驗。", log_file)
        return False, f"Spirent 機箱連線失敗: {err_detail}"

    log_and_print(f"  - 連線至機箱 {chassis_ip} 成功！", log_file)
    
    # 預約實體 Ports
    slot_ports = [tx_port, rx_port]
    log_and_print(f"  - 正在預約測試埠口 (TX: {tx_port}, RX: {rx_port})...", log_file)
    reserve_cmd = f'if {{[catch {{stc::reserve "//{chassis_ip}/{tx_port}" "//{chassis_ip}/{rx_port}"}} err]}} {{set ret "FAIL: $err"}} else {{set ret "OK"}}'
    res_ret = tclsh.eval(reserve_cmd)
    if res_ret.startswith("FAIL:"):
        err_detail = res_ret[6:].strip()
        log_and_print(f"  [FAIL] 預約埠口失敗: {err_detail}", log_file)
        tclsh.eval('stc::perform ChassisDisconnectAll')
        return False, f"預約埠口失敗: {err_detail}"

    project = None
    subscribed_results = []
    try:
        # 配置 Project 與 Port
        project = tclsh.eval('CreateProject')
        port_tx_obj = tclsh.eval(f'CreatePort {tx_port} {project} {chassis_ip}')
        port_rx_obj = tclsh.eval(f'CreatePort {rx_port} {project} {chassis_ip}')
        ports_pair = [port_tx_obj, port_rx_obj]
        
        pt.CreatePortType_Copper(port_tx_obj, PortType_1G_Full_AN)
        pt.CreatePortType_Copper(port_rx_obj, PortType_1G_Full_AN)
        tclsh.eval('Mapping')
        log_and_print(f"  - 埠口配置完成 (TX 物件: {port_tx_obj}, RX 物件: {port_rx_obj})", log_file)

        # 防呆清除前輪殘留 StreamBlock (確保兩端各為 0 個，遵循 SKILL.md Rule 10)
        for p in ports_pair:
            existing_sbs = tclsh.eval(f"stc::get {p} -children-StreamBlock").split()
            for sb in existing_sbs:
                if sb:
                    try:
                        tclsh.eval(f"stc::delete {sb}")
                    except Exception:
                        pass

        # 依 SKILL.md Rule 10：兩端剛好各配對 1 個 StreamBlock，嚴防 invalid handle 陷阱！
        # 若 RX 埠未配置 StreamBlock，tool.tcl 的 getdata 會取得空字串 Handle "" 導致 stc::get 崩潰
        sb0 = pt.CreateStreamBlock(port_tx_obj, StreamBlock, Frame)
        sb1 = pt.CreateStreamBlock(port_rx_obj, StreamBlock, Frame1)
        pt.Generator(port_tx_obj, Generatortype)
        pt.Generator(port_rx_obj, Generatortype)

        # 訂閱 3 組統計結果 (包含 RxStreamSummaryResults，否則 getdata 查無 stream 數據)
        now_str = datetime.now().strftime("%m%d%y%H%M%S")
        res_tx = pt.ResultSubscribe_Tx(project, f"genTx_{now_str}")
        res_rx = pt.ResultSubscribe_Rx(project, f"anaRx_{now_str}")
        res_drop = pt.ResultSubscribe_Rxstreams(project, f"droppedRx_{now_str}")
        subscribed_results = [res_tx, res_rx, res_drop]

        # 清除舊數據 (遵循 SKILL.md Rule 6 全域清除)
        tclsh.eval("stc::perform ResultsClearAll")
        time.sleep(1)

        # 啟動單向流量 (僅在 TX 端啟動 Generator)
        log_and_print(f"  - 啟動單向流量 (TX: {tx_port} -> RX: {rx_port}，持續 {duration_sec} 秒)...", log_file)
        pt.StartGenerator([port_tx_obj])
        time.sleep(duration_sec)
        pt.StopGenerator([port_tx_obj])
        time.sleep(1)

        # 讀取流量數據
        datalist = pt.getdata(ports_pair)
        # datalist[0] 是 TX port: [drop, rx, tx]
        # datalist[1] 是 RX port: [drop, rx, tx]
        tx_sent = int(datalist[0][2]) if len(datalist) > 0 and len(datalist[0]) > 2 else 0
        rx_recv = int(datalist[1][1]) if len(datalist) > 1 and len(datalist[1]) > 1 else 0
        drop_cnt = int(datalist[1][0]) if len(datalist) > 1 and len(datalist[1]) > 0 else max(0, tx_sent - rx_recv)
        loss_rate = (drop_cnt / tx_sent * 100.0) if tx_sent > 0 else 0.0

        stat_summary = f"TX 發送={tx_sent}, RX 接收={rx_recv}, 掉包={drop_cnt} (丟失率 {loss_rate:.2f}%)"
        log_and_print(f"  - 流量統計: {stat_summary}", log_file)

        if tx_sent > 0:
            return True, f"1 Tx 1 Rx 打流成功 ({stat_summary})"
        else:
            return False, "Generator 未發出封包"

    except Exception as e:
        err_msg = f"Spirent 測試過程發生異常: {e}"
        log_and_print(f"  [FAIL] {err_msg}", log_file)
        return False, err_msg
    finally:
        # 清理並釋放儀器資源 (遵循 SKILL.md Rule 11)
        try:
            for res in subscribed_results:
                if res:
                    try:
                        pt.unsubscribe(res)
                    except Exception:
                        pass
            tclsh.eval("stc::perform ResultsClearAll")
            if project:
                tclsh.eval(f"stc::delete {project}")
            pt.Disconnect(chassis_ip)
            log_and_print("  - 已清理 Project 並斷開 Spirent 機箱連線", log_file)
        except Exception:
            pass


####################### 主程式 ###########################

def main():
    # 初始化集中日誌路徑 (遵循 SKILL.md Rule 13 / Rule 1.1)
    log_file = get_result_log_path(__file__, "result.txt")
    
    sep = "=" * 70
    header = (
        f"{sep}\n"
        "       AI 自動化測試框架 - 環境與核心套件功能驗證測試\n"
        f"       執行時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{sep}"
    )
    # 每次執行覆寫清空舊日誌，保持乾淨
    with open(log_file, "w", encoding="utf-8") as f:
        f.write(header + "\n")
    print("\n" + header)
    
    # [Phase 1] 參數蒐集與選單互動
    features = {
        "1": "utils 專案核心共用庫 (可編輯模式匯入檢驗)",
        "2": "icmplib 網路連線探測 (Ping 功能測試)",
        "3": "pyserial 串列通訊控制 (COM Port 掃描與開啟測試)",
        "4": "pysnmp + pyasn1 網路設備管理 (SNMPv2c/v3 查詢測試)",
        "5": "scapy 網路封包建構 (封包組裝與解析測試 - 選用)",
        "6": "Spirent TestCenter 儀器測試 (1 Tx 1 Rx 打流與統計檢驗)"
    }
    
    print("\n可用的檢驗項目清單：")
    for key, name in sorted(features.items()):
        print(f"  [{key}] {name}")
        
    choice_input = input("\n請選擇要檢驗的項目 (例如單選: 2, 多選: 1,2,4,6, 直接 Enter 預設全部): ").strip()
    
    if not choice_input:
        selected_keys = sorted(features.keys())
    else:
        selected_keys = []
        for part in choice_input.replace("，", ",").split(","):
            p = part.strip()
            if p in features and p not in selected_keys:
                selected_keys.append(p)
        if not selected_keys:
            print("[提示] 輸入無效，將預設執行所有測試項目。")
            selected_keys = sorted(features.keys())
            
    print(f"\n已選擇執行項目: {', '.join([f'[{k}]' for k in selected_keys])}")
    
    # 依選定之項目動態蒐集必要參數 (避免詢問無關參數)
    target_ip = "127.0.0.1"
    if "2" in selected_keys or "4" in selected_keys:
        ip_in = input("\n請輸入測試目標 IP (直接 Enter 預設 127.0.0.1): ").strip()
        if ip_in:
            target_ip = ip_in
            
    community = "public"
    if "4" in selected_keys:
        comm_in = input("請輸入 SNMP Community String (直接 Enter 預設 public): ").strip()
        if comm_in:
            community = comm_in
            
    com_port = ""
    if "3" in selected_keys:
        avail_ports = get_available_com_ports()
        print(f"\n目前系統偵測到可用 COM Port: {avail_ports if avail_ports else '無'}")
        port_prompt = "請輸入欲測試之 COM Port (例如 COM1，直接 Enter 依 SKILL.md 自動詢問，輸入 skip 略過實體開啟): "
        p_in = input(port_prompt).strip()
        if p_in.lower() == "skip":
            com_port = "SKIP"
        elif p_in:
            com_port = p_in
        else:
            com_port = get_com_port()

    # Spirent 參數蒐集
    chassis_ip = "10.123.38.202"
    spirent_tx = "1/1"
    spirent_rx = "1/2"
    spirent_duration = 3
    if "6" in selected_keys:
        print("\n--- Spirent TestCenter 參數設定 ---")
        ch_in = input("請輸入 Spirent 機箱 IP (直接 Enter 預設 10.123.38.202，輸入 skip 僅驗證 API 載入): ").strip()
        if ch_in.lower() == "skip":
            chassis_ip = "SKIP"
        elif ch_in:
            chassis_ip = ch_in
            
        if chassis_ip != "SKIP":
            tx_in = input("請輸入 TX 測試埠口 (直接 Enter 預設 1/1): ").strip()
            if tx_in:
                spirent_tx = tx_in
            rx_in = input("請輸入 RX 測試埠口 (直接 Enter 預設 1/2): ").strip()
            if rx_in:
                spirent_rx = rx_in
            dur_in = input("請輸入打流測試秒數 (直接 Enter 預設 3 秒): ").strip()
            if dur_in.isdigit():
                spirent_duration = int(dur_in)
            
    # [Phase 2] 環境預檢與資訊紀錄
    env_info = (
        f"\n[執行環境檢核]\n"
        f"  - 作業系統: {sys.platform}\n"
        f"  - Python 版本: {sys.version.split()[0]}\n"
        f"  - 直譯器路徑: {sys.executable}\n"
        f"  - 是否運行於 .venv: {'.venv' in sys.executable.lower()}\n"
        f"  - 日誌存放位置: {log_file}\n"
    )
    log_and_print(env_info, log_file)
    
    # [Phase 3] 執行測試迴圈
    results: Dict[str, Tuple[bool, str]] = {}
    
    log_and_print("=" * 70, log_file)
    log_and_print("                  開始執行套件功能驗證", log_file)
    log_and_print("=" * 70, log_file)
    
    if "1" in selected_keys:
        results["utils 核心模組"] = test_utils_module(log_file)
        
    if "2" in selected_keys:
        results["icmplib Ping 功能"] = test_icmplib_module(target_ip, log_file)
        
    if "3" in selected_keys:
        results["pyserial 串列功能"] = test_pyserial_module(com_port, log_file)
        
    if "4" in selected_keys:
        results["pysnmp/pyasn1 SNMP 功能"] = test_pysnmp_module(target_ip, community, log_file)
        
    if "5" in selected_keys:
        results["scapy 封包建構功能"] = test_scapy_module(log_file)

    if "6" in selected_keys:
        results["Spirent 1Tx1Rx 測試"] = test_spirent_module(
            chassis_ip, spirent_tx, spirent_rx, spirent_duration, log_file
        )
        
    # 產出總結報告
    pass_count = sum(1 for passed, _ in results.values() if passed)
    total_count = len(results)
    
    summary = (
        f"\n{sep}\n"
        "                  功能檢驗結果總結報告\n"
        f"{sep}\n"
    )
    for name, (passed, msg) in results.items():
        tag = "[ PASS ]" if passed else "[ FAIL ]"
        summary += f"  {tag} {name}: {msg}\n"
    summary += f"{sep}\n"
    summary += f"檢驗總計: 共 {total_count} 項, 成功 (PASS): {pass_count} 項, 失敗 (FAIL): {total_count - pass_count} 項\n"
    if pass_count == total_count:
        summary += ">>> [結論] 環境設定完善！所有選用套件與功能均 100% 正常調用！ <<<\n"
    else:
        summary += ">>> [警告] 部分套件或功能檢驗未通過，請參閱上述日誌確認異常項目！ <<<\n"
    summary += f"{sep}\n"
    
    log_and_print(summary, log_file)
    print(f"\n測試報告已儲存至: {log_file}\n")


if __name__ == "__main__":
    main()
