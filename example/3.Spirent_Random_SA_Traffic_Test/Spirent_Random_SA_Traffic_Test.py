# -*- coding: utf-8 -*-
"""
名稱: Spirent TestCenter 500 組隨選 10 組 SA 隨機打流測試 (Spirent_Random_SA_Traffic_Test.py)

目的 MAC (DA) 規格：
  - 固定指定位址: 00:00:01:00:00:01

SA 位址池規格 (500 組)：
  - 前綴 OUI: 00:10:94:00:
  - 起始位址 (第 001 組): 00:10:94:00:00:01
  - 結束位址 (第 500 組): 00:10:94:00:01:F4 (十六進位 0x01F4 = 500)
  - 特性說明: 500 組連續唯一之 Moxa 標準 Source MAC 位址，每輪隨機無重複抽樣 10 組

測試流程說明：
[Phase 1] 參數蒐集與初始化
  1.1 輸入「執行輪數」與「每輪打流時間 (秒)」。
  1.2 確認 Spirent 機箱 IP 與測試連接埠 (預設 TG1: 8/1, TG2: 8/3)。
  1.3 動態載入 Spirent TestCenter API 核心 (load_utils)。
[Phase 2] 儀器預約與環境連線配置
  2.1 連線 Spirent 機箱並預約測試連接埠 (ReservePort)。
  2.2 初始化專案、Port 屬性 (1G Copper Full-Duplex) 與邏輯映射。
  2.3 訂閱 TX / RX / Dropped 統計結果至 CSV。
  2.4 產生 500 組標準 SA (Source MAC) 位址池 (00:10:94:00:00:01 ~ 00:10:94:00:01:F4)。
  2.5 建立專用 Wireshark 抓包目錄 (captures/)。
  2.6 初始化測試日誌檔標頭 (result.txt)。
[Phase 3] 自動化測試迴圈 (每輪自 500 組 SA 池中隨機抽選 10 組發送流量)
  3.1 自 500 組 SA 位址池中隨機無重複抽取 10 組 SA。
  3.2 防呆清除前輪殘留並建立本輪雙端 StreamBlock (Port0 與 Port1)。
  3.3 在發送端 StreamBlock 下掛載 TableModifier 載入該 10 組 SA (VFD 模式)。
  3.4 執行全域結果清除 (stc::perform ResultsClearAll)。
  3.5 對接收端 TG2 啟動 Wireshark 抓包 (start_capture)。
  3.6 啟動發送端流量發送 (StartGenerator)。
  3.7 持續發送流量並等待設定之打流時間。
  3.8 停止流量發送並停止抓包保存 PCAP 檔案 (stop_capture_and_save)。
  3.9 獲取即時統計數據 (safe_getdata) 並精確計算發送數、接收數與掉包。
  3.10 輸出詳細統計與抽中之 10 組 SA 並寫入 result.txt。
  3.11 安全清理本輪 StreamBlock 物件，準備進入下一輪循環。
"""

import sys
import os
import time
import random
from datetime import datetime
from typing import TYPE_CHECKING, List, Dict, Any, Tuple

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

# 引入共用工具
try:
    from utils.dictionary_parameters import *
    from utils.comm_helper import *
except ImportError as e:
    print(f"無法載入 dictionary_parameters 或 comm_helper: {e}")
    sys.exit(1)

if TYPE_CHECKING:
    from utils.pythontool import *

# 測試指定之固定目的 MAC (DA) 位址
TARGET_DA = "00:00:01:00:00:01"


####################### 輔助函式 ###########################

def load_utils():
    """動態載入 Spirent TestCenter API 核心，並注入全域命名空間 (遵循 SKILL.md 命名空間隔離原則)。"""
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


def generate_sa_pool(count: int = 500) -> List[str]:
    """
    生成指定數量 (預設 500 組) 的標準 Source MAC 位址池。
    
    規格說明:
      - 前綴 (OUI): 00:10:94:00:
      - 起始位址 (第 001 組): 00:10:94:00:00:01
      - 結束位址 (第 500 組): 00:10:94:00:01:F4 (十六進位 0x01F4 = 十進位 500)
      - 總計: 500 組連續且唯一的 Moxa 標準 MAC 位址
    """
    pool = []
    for i in range(1, count + 1):
        b4 = (i >> 8) & 0xFF
        b5 = i & 0xFF
        mac = f"00:10:94:00:{b4:02X}:{b5:02X}"
        pool.append(mac)
    return pool


def setup_spirent(chassisAddr: str, slotPortlist: List[str]) -> Tuple[Any, List[Any], Any, Any, Any]:
    """配置 Spirent TestCenter 預約 Port 並訂閱流量結果。"""
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


def clear_results_and_streams(active_ports: List[Any]):
    """
    清除全域統計數據（包含埠與串流），防止丟包數據在 iteration 之間累加。
    
    遵循 SKILL.md 規範，使用原生 ResultsClearAll 全域清除。
    """
    tclsh.eval("stc::perform ResultsClearAll")


def safe_getdata(ports_pair: List[Any]) -> List[List[str]]:
    """
    防禦性讀取即時流量統計數據：
    優先調用共用庫標準 getdata(ports_pair)。
    若因多重 sub-streams 結果導致底層 getdata 拋出 invalid handle，則防禦性加總所有串流之數據，確保 100% 不中斷。
    """
    try:
        return getdata(ports_pair)
    except Exception as e:
        if "invalid handle" in str(e):
            datalist = []
            for p in ports_pair:
                gen = tclsh.eval(f"stc::get {p} -children-generator").strip()
                ana = tclsh.eval(f"stc::get {p} -children-analyzer").strip()
                sb_list = tclsh.eval(f"stc::get {p} -children-StreamBlock").split()

                tx_sig = "0"
                rx_sig = "0"
                if gen:
                    gen_res = tclsh.eval(f"stc::get {gen} -children-GeneratorPortResults").strip()
                    if gen_res:
                        tx_sig = tclsh.eval(f"stc::get {gen_res} -GeneratorSigFrameCount").strip()
                if ana:
                    ana_res = tclsh.eval(f"stc::get {ana} -children-AnalyzerPortResults").strip()
                    if ana_res:
                        rx_sig = tclsh.eval(f"stc::get {ana_res} -SigFrameCount").strip()

                total_drop = 0
                for sb in sb_list:
                    if not sb:
                        continue
                    rx_streams = tclsh.eval(f"stc::get {sb} -children-RxStreamSummaryResults").split()
                    for rxs in rx_streams:
                        if not rxs:
                            continue
                        try:
                            d = int(tclsh.eval(f"stc::get {rxs} -DroppedFrameCount"))
                            total_drop += d
                        except Exception:
                            pass
                datalist.append([str(total_drop), rx_sig, tx_sig])
            return datalist
        raise


####################### 主程式 ###########################

def main():
    print("=" * 70)
    print("  Spirent TestCenter: 500 組 SA 隨機抽取 10 組打流測試")
    print("=" * 70)

    # --- [Phase 1] 參數蒐集與初始化 ---
    # 1.1 輸入執行次數與打流持續時間 (嚴格依據 SKILL.md 採用 0 個參數防呆函式)
    iteration = get_iteration_count()
    traffic_duration = get_delay_time()

    # 1.2 Spirent 機箱與連接埠設定 (支援 Enter 直接使用預設值)
    default_chassis = "10.123.38.202"
    chassis_input = input(f"請輸入 Spirent 機箱 IP [直接 Enter 預設 {default_chassis}]: ").strip()
    chassisAddr = chassis_input if chassis_input else default_chassis

    default_ports = "8/1, 8/3"
    ports_input = input(f"請輸入測試連接埠 (TG1_TX, TG2_RX) [直接 Enter 預設 {default_ports}]: ").strip()
    slotPortlist = [p.strip() for p in (ports_input if ports_input else default_ports).split(",") if p.strip()]
    if len(slotPortlist) < 2:
        slotPortlist = ["8/1", "8/3"]

    # 1.3 參數輸入完畢後，動態載入 Spirent API 核心工具
    load_utils()

    # 集中式路徑 (test result/<測試目錄>_result/result.txt)
    log_filename = get_result_log_path(__file__, "result.txt")
    project = None
    port_objs: List[Any] = []
    result1, result2, result3 = None, None, None

    try:
        # --- [Phase 2] 儀器預約與環境連線配置 ---
        print(f"\n連接 Spirent 機箱 ({chassisAddr}) 並預約連接埠 {slotPortlist} ...")
        project, port_objs, result1, result2, result3 = setup_spirent(chassisAddr, slotPortlist)
        ports_pair = [port_objs[0], port_objs[1]]

        # 2.4 建立 500 組標準 Source MAC 位址池
        sa_pool = generate_sa_pool(500)
        print(f"\n已成功建立 500 組 SA 位址池: {sa_pool[0]} ~ {sa_pool[-1]} (共 {len(sa_pool)} 組 Moxa 標準 MAC)")
        print(f"  - 前綴 OUI: 00:10:94:00:")
        print(f"  - 起始 (第 001 組): {sa_pool[0]}")
        print(f"  - 結束 (第 500 組): {sa_pool[-1]} (0x01F4 = 500)")

        # 2.5 [Wireshark 抓包 - 暫時註解] 建立帶時間戳記的輸出目錄 (若需啟用抓包請取消註解)
        # capture_dir = create_capture_output_dir(prefix="random_sa_traffic")
        # print(f"已建立 Wireshark 抓包目錄: {capture_dir}")
        capture_dir = None
        active_captures: List[Tuple[str, str]] = []

        # 2.6 寫入測試日誌標頭
        with open(log_filename, 'a+', encoding='utf-8') as f_log:
            f_log.write(f"\n{'='*75}\n")
            f_log.write(f"開始 Spirent 500 抽 10 SA 隨機打流測試批次: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f_log.write(f"機箱: {chassisAddr} | TX 埠 (TG1): {slotPortlist[0]} | RX 埠 (TG2): {slotPortlist[1]}\n")
            f_log.write(f"總輪數: {iteration} 輪 | 每輪打流時長: {traffic_duration} 秒\n")
            f_log.write(f"目的 MAC (DA): {TARGET_DA}\n")
            f_log.write(f"SA 位址池範圍 (共 500 組): {sa_pool[0]} ~ {sa_pool[-1]} (前綴 00:10:94:00:)\n")
            if capture_dir:
                f_log.write(f"Wireshark 封包儲存目錄: {capture_dir}\n")
            f_log.write(f"{'='*75}\n")

        # --- [Phase 3] 自動化測試迴圈 ---
        for it in range(1, iteration + 1):
            iter_start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n{'#'*70}")
            print(f"  >>> 第 {it}/{iteration} 輪測試啟動 [{iter_start_time}] <<<")
            print(f"{'#'*70}")

            # # 3.1 自 500 組 SA 位址池中隨機無重複抽取 10 組 SA
            selected_sas = random.sample(sa_pool, 10)
            print(f"本輪隨機抽選之 10 組 Source MAC 位址:")
            for idx, sa in enumerate(selected_sas, 1):
                print(f"  [{idx:02d}] {sa}")

            # # 3.2 防呆清除前輪殘留並建立本輪雙端 StreamBlock (Port0 與 Port1 兩端剛好各 1 個)
            for p in ports_pair:
                existing_sbs = tclsh.eval(f"stc::get {p} -children-StreamBlock").split()
                for sb in existing_sbs:
                    if sb:
                        try:
                            tclsh.eval(f"stc::delete {sb}")
                        except Exception:
                            pass

            # 發送端封包：覆寫目的 MAC (DA) 為指定之 00:00:01:00:00:01
            tx_frame = dict(Frame, Ethernet_dstMAc=TARGET_DA)
            sb0 = CreateStreamBlock(port_objs[0], StreamBlock, tx_frame)
            sb1 = CreateStreamBlock(port_objs[1], StreamBlock, Frame1)
            Generator(port_objs[0], Generatortype)
            Generator(port_objs[1], Generatortype)

            # # 3.3 在發送端 StreamBlock 下掛載 TableModifier 載入該 10 組 SA
            mac_data_str = " ".join(selected_sas)
            tm_handle = tclsh.eval(
                f"stc::create TableModifier -under {sb0} "
                f"-OffsetReference eth_sb1.srcMac "
                f"-Data {{{mac_data_str}}} "
                f"-EnableStream FALSE"
            )
            tclsh.eval("stc::apply")
            print(f"-> 成功於發送端配置 TableModifier ({tm_handle})，載入 10 組隨機 SA (VFD 模式)。")

            # # 3.4 執行全域結果清除 (stc::perform ResultsClearAll)
            print("-> 清除全域統計數據 (ResultsClearAll)...")
            clear_results_and_streams(ports_pair)
            time.sleep(1)

            # # 3.5 [Wireshark 抓包 - 暫時註解] 啟動接收端 TG2 (Port1) 抓包 (若需啟用請取消註解)
            # if not capture_dir:
            #     capture_dir = create_capture_output_dir(prefix="random_sa_traffic")
            # pcap_filename = f"round_{it:02d}_TG2_rx.pcap"
            # pcap_filepath = os.path.join(capture_dir, pcap_filename)
            # cap_handle = start_capture(port_objs[1])
            # active_captures.append((cap_handle, pcap_filepath))
            # print(f"-> 接收端 TG2 ({slotPortlist[1]}) 已啟動 Wireshark 封包擷取...")

            # # 3.6 啟動發送端流量發送 (StartGenerator)
            t_tx_start = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{t_tx_start}] -> 開始流量發送 (TX Port: {slotPortlist[0]}) ...")
            StartGenerator([port_objs[0]])

            # # 3.7 持續發送流量並等待設定之打流時間
            print(f"-> 流量發送中，等待 {traffic_duration} 秒...")
            time.sleep(traffic_duration)

            # # 3.7 停止流量發送，等待計數穩定
            StopGenerator([port_objs[0]])
            t_tx_stop = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{t_tx_stop}] -> 停止流量發送，等待 1 秒計數穩定...")
            time.sleep(1)

            # # 3.8 [Wireshark 抓包 - 暫時註解] 停止接收端抓包並保存 PCAP (若需啟用請取消註解)
            # pcap_pkts = stop_capture_and_save(cap_handle, pcap_filepath)
            # active_captures.clear()
            # print(f"-> Wireshark 抓包已儲存: {pcap_filename} (共擷取 {pcap_pkts} 個封包)")

            # # 3.9 獲取即時統計數據 (safe_getdata) 並精確計算發送數、接收數與掉包
            datalist = safe_getdata(ports_pair)
            p0_tx = int(datalist[0][2])
            p0_rx = int(datalist[0][1])
            p1_tx = int(datalist[1][2])
            p1_rx = int(datalist[1][1])

            tx_count = p0_tx
            rx_count = p1_rx
            drop_count = max(0, tx_count - rx_count)
            loss_rate = (drop_count / tx_count * 100.0) if tx_count > 0 else 0.0

            result_summary = (
                f"[{datetime.now().strftime('%H:%M:%S')}] 輪次: {it:02d}/{iteration:02d} | "
                f"TX: {tx_count} pkts | RX: {rx_count} pkts | 掉包: {drop_count} pkts ({loss_rate:.2f}%)"
            )
            print(f"-> 結果統計: {result_summary}")

            # # 3.10 輸出詳細統計與抽中之 10 組 SA 並寫入 result.txt
            with open(log_filename, 'a+', encoding='utf-8') as f_log:
                f_log.write(f"┌{'─'*72}┐\n")
                f_log.write(f"│ 輪次: {it:02d}/{iteration:02d} | 啟動時間: {iter_start_time} | 打流時長: {traffic_duration}s │\n")
                f_log.write(f"├{'─'*72}┤\n")
                f_log.write(f"  目的 MAC (DA): {TARGET_DA}\n")
                f_log.write(f"  抽中 10 組 SA: {', '.join(selected_sas[:5])}\n")
                f_log.write(f"                 {', '.join(selected_sas[5:])}\n")
                f_log.write(f"  發送端 (Port0 {slotPortlist[0]}): Tx = {p0_tx}, Rx = {p0_rx}\n")
                f_log.write(f"  接收端 (Port1 {slotPortlist[1]}): Tx = {p1_tx}, Rx = {p1_rx}\n")
                f_log.write(f"  測試結果: TX={tx_count}, RX={rx_count}, 掉包={drop_count} (丟失率 {loss_rate:.2f}%)\n")
                # if 'pcap_filename' in locals() and 'pcap_pkts' in locals():
                #     f_log.write(f"  Wireshark PCAP: {pcap_filename} (共 {pcap_pkts} 封包)\n")
                f_log.write(f"└{'─'*72}┘\n\n")

            # # 3.11 安全清理本輪 StreamBlock 物件，準備進入下一輪循環
            try:
                tclsh.eval(f"stc::delete {sb0}")
            except Exception:
                pass
            try:
                tclsh.eval(f"stc::delete {sb1}")
            except Exception:
                pass

        print("\n" + "=" * 70)
        print("  所有測試輪次執行完成！")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\n使用者手動中斷測試 (Ctrl+C)。")
    except Exception as e:
        print(f"\n測試執行過程中發生未預期異常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # --- 資源必定安全釋放 ---
        print("\n正在執行環境與資源釋放...")
        # 未儲存 Capture 的緊急保存機制 (遵循 SKILL.md Rule 8)
        if 'active_captures' in locals() and active_captures:
            for cap_h, save_p in active_captures:
                try:
                    emergency_pkts = stop_capture_and_save(cap_h, save_p)
                    print(f"異常中斷已緊急保存 Capture: {save_p} ({emergency_pkts} pkts)")
                except Exception:
                    pass

        for res in [result1, result2, result3]:
            if res is not None:
                try:
                    unsubscribe(res)
                    print(f"已取消結果訂閱 ({res})。")
                except Exception as e:
                    print(f"取消訂閱異常: {e}")

        if project is not None:
            try:
                tclsh.eval(f"stc::delete {project}")
                print("已刪除 Spirent 專案。")
            except Exception as e:
                print(f"刪除專案異常: {e}")

        try:
            Disconnect(chassisAddr)
            print(f"已自 Spirent 機箱 {chassisAddr} 中斷連線並釋放預約埠。")
        except Exception as e:
            print(f"中斷連線機箱異常: {e}")

        print(f"測試結束。詳細日誌已更新至: {log_filename}")


if __name__ == "__main__":
    main()
