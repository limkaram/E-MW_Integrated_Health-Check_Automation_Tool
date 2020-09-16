import pandas as pd
import time
import os
import telnetlib
import re

desktop_path = os.path.join(os.path.expanduser('~'), 'Desktop')  # 저장될 excel 위치(디폴트 : 바탕화면)
directory_name = 'E-MW 자동 통합 점검 DB'  # 디렉토리명


def get_node_info():
    # SOEM 서버에서 export한 csv 파일 활용 필요 컬럼 추출
    node_table = pd.read_csv('node_info.csv', delimiter=';')
    necessary_columns = ['NE Name', 'IPv4', 'NE Type', 'NE ID', 'Sub-network']  # 필요 컬럼 내역
    node_table = node_table[necessary_columns]
    return node_table


def get_operating_slots_and_npu_temperature(node_ip, node_type):
    try:
        pw = 'ericsson'

        # show rl revision + show temp
        telnet = telnetlib.Telnet(node_ip.rstrip(), timeout=3)

        exception_processing = telnet.read_until(b'Password', 2)  # 접속 불가시 예외처리 변수
        assert len(exception_processing.decode('ascii')) > 0  # 접속 불가시 telnet.read_until() 반환값 len()은 0이며, 해당 경우 에러 발생

        telnet.write(pw.encode('ascii') + b'\r\n')
        telnet.read_until(b'>', 2)
        telnet.write(b'show rl revision' + b'\r\n')
        telnet.read_until(b'** RL Software version information **', 10)
        telnet.write(b'show temp' + b'\r\n')
        telnet.write(b'exit' + b'\r\n')
        displayed_text = telnet.read_all().decode('ascii')

        slots_and_temp_info = {}  # 운용 중인 slots, NPU 온도 정보 담을 dict, {'operating_slots': ['2+3', ...], 'npu_temp': 온도값}

        # displayed_text에서 slot 정보 추출
        slot_regex = re.compile(r'[S][l][o][t][:]\s+([0-9]+)')
        operating_slots = slot_regex.findall(displayed_text)
        operating_slots = ['+'.join(operating_slots[i: i + 2]) for i in range(0, len(operating_slots), 2)]  # ['2+3', '4+5', '6+7', '14+15', '16+17'] 형태로 변환

        # displayed_text에서 temp 정보 추출
        temp_record_list = []
        temp_regex = re.compile(r'\s+([0-9\-]+)\s+([0-9\-]+)\s+([0-9\-]+)\s+([0-9\-]+)')  # group

        for line in displayed_text.split('\r\n'):
            if temp_regex.search(line):
                temp_record_list.append(temp_regex.findall(line))
        temp_record_list = [slot[0] for slot in temp_record_list]  # temp_record_list 형태를 list of tuple로 변환

        if node_type.startswith('AMM 20P'):
            npu_temp = str(temp_record_list[11][1])  # AMM 20P NPU 온도 추출
        elif node_type.startswith('AMM 6P'):
            npu_temp = str(temp_record_list[7][1])  # AMM 6P NPU 온도 추출
        elif node_type.startswith('AMM 2P'):
            npu_temp = str(temp_record_list[1][1])  # AMM 6P NPU 온도 추출

        slots_and_temp_info['operating_slots'] = operating_slots
        slots_and_temp_info['npu_temp'] = npu_temp

        return slots_and_temp_info
    except:  # 장비 접속 불가시
        print('{0} 장비 접속 실패!!!'.format(node_ip))
        print('다음 노드로 넘어갑니다.')
        print('\r\n')
        return []


def get_level_info(text):
    # text : 하나의 노드의 전체 Slot level 텍스트 정보

    text_line_list = text.split('\r\n')
    text_line_list = [i.strip() for i in text_line_list if ('Slot' in i) or ('Current' in i) or ('Tx Capacity - Modulation' in i)]
    #['Slot 2 NEAR END - MMU3 A, RAU2 X 11/A07',
    # 'Current Output Power       1) Stand By,
    # 2) 21 dBm', 'Current Input Power       1) -43 dBm, 2) -39 dBm',
    # Tx Capacity - Modulation   154 Mbit/s - 128QAM]

    need_value_by_slot = []  # [slot, Tx(주), Tx(예비), Rx(주), Rx(예비), QAM] 형태

    for index, line in enumerate(text_line_list):
        if 'Slot' in line:
            need_value_by_slot.append(line[:7].replace('Slot', '').strip())
        elif 'Current Output Power' in line:
            need_value_by_slot += line.replace('Current Output Power', '')\
                .replace('1)', '').replace('2)', '').replace('dBm', '').strip().split(',')
        elif 'Current Input Power' in line:
            need_value_by_slot += line.replace('Current Input Power', '')\
                .replace('1)', '').replace('2)', '').replace('dBm', '').strip().split(',')
        elif 'Tx Capacity - Modulation' in line:
            need_value_by_slot.append(line.split('-')[-1].strip().rstrip('QAM'))

    need_value_by_slot = [i.strip() for i in need_value_by_slot if type(i) is not int]

    if len(need_value_by_slot) == 6:  # 정상 : [slot, Tx(주), Tx(예비), Rx(주), Rx(예비), QAM]
        main_slot = [need_value_by_slot[0], need_value_by_slot[1], need_value_by_slot[3], need_value_by_slot[-1]]
        spare_slot = [str(int(need_value_by_slot[0])+1), need_value_by_slot[2], need_value_by_slot[4], need_value_by_slot[-1]]
    elif len(need_value_by_slot) == 5:  # QAM 미지원 : [slot, Tx(주), Tx(예비), Rx(주), Rx(예비)]
        main_slot = [need_value_by_slot[0], need_value_by_slot[1], need_value_by_slot[3], '-']
        spare_slot = [str(int(need_value_by_slot[0])+1), need_value_by_slot[2], need_value_by_slot[4], '-']
    elif len(need_value_by_slot) == 4:  # 1+0 운용 : [slot, Tx(주), Rx(주), QAM]
        main_slot = [need_value_by_slot[0], need_value_by_slot[1], need_value_by_slot[3], need_value_by_slot[-1]]
        spare_slot = [str(int(need_value_by_slot[0])+1), '-', '-', need_value_by_slot[-1]]
    elif len(need_value_by_slot) == 3:  # 1+0 운용 + QAM 미지원 : [slot, Tx(주), Rx(주)]
        main_slot = [need_value_by_slot[0], need_value_by_slot[1], need_value_by_slot[2], '-']
        spare_slot = [str(int(need_value_by_slot[0])+1), '-', '-', '-']

    slot_info_list = [main_slot, spare_slot]
    return slot_info_list


def make_result_df(slot_level_info_list, local_day, npu_temp, node_name, node_ip, node_type):
    columns_list = ['Date', 'NE Name', 'IPv4', 'NE Type', 'NPU Temp', 'Slot', 'Tx', 'Rx', 'QAM']
    slot_info_df = pd.DataFrame(columns=columns_list)  # 결과 저장할 Dataframe

    for index, slot_info in enumerate(slot_level_info_list):
        slot_info_df.loc[index] = [local_day, node_name, node_ip, node_type, npu_temp] + slot_info
    return slot_info_df


def make_directory(path, filename):
    if os.path.isdir(os.path.join(path, filename)):  # dir가 존재하는 경우 dir 미생성
        return os.path.join(path, filename)
    else:  # dir가 존재하지 않는 경우 dir 생성
        os.mkdir(os.path.join(path, filename))
        return os.path.join(path, filename)


def make_excel(df, path, filename):  # pandas dataframe을 excel로 만듬
    excel_abspath = os.path.join(path, filename)
    df.to_excel(excel_abspath, startrow=1, startcol=1)


def main():
    local_day = time.strftime('%Y%m%d', time.localtime(time.time()))  # 20200101
    # local_hour = time.strftime('%H', time.localtime(time.time()))  # 시간만
    # local_minute = time.strftime('%M', time.localtime(time.time()))  # 분만

    columns_list = ['Date', 'NE Name', 'IPv4', 'NE Type', 'NPU Temp', 'Slot', 'Tx', 'Rx', 'QAM']
    result_df = pd.DataFrame(columns=columns_list)  # 전체 결과 엑셀 파일 만들기 위해 대입
    node_info = get_node_info()  # 서버에서 추출한 node 정보가져오기

    slot_count_start = 0  # CMD 출력문 구성을 위해 result_df에서 하나의 노드만 추출하여 출력하기 위해 사용 예정
    slot_count_end = 0

    # 정상 중 빠름 : 46(LH대청삼각산)
    # 1+0 운용 + QAM : 36(TN대연평도#1)
    # QAM 미지원 : 0(TN모도)
    # STM 장비 : 14
    all_node_num = len(node_info.index)  # 전체 노드 수
    complete_node_count = 0  # 진행률 출력을 위한 변수
    for df_index in range(len(node_info.index)):
        complete_node_count += 1
        each_node_info = node_info.loc[[df_index]]  # 하나의 노드 데이터만 추출
        node_name = each_node_info.loc[df_index, 'NE Name']
        node_ip = each_node_info.loc[df_index, 'IPv4']
        node_type = each_node_info.loc[df_index, 'NE Type']

        # 운용 중인 slots, NPU 온도 정보 담을 dict, {'operating_slots': ['2+3', ...], 'npu_temp': 온도값}
        slots_and_temp_info = get_operating_slots_and_npu_temperature(node_ip, node_type)

        if len(slots_and_temp_info) > 0:  # 장비 접속 가능 경우
            operating_slots = slots_and_temp_info['operating_slots']
            npu_temp = slots_and_temp_info['npu_temp']

            print(node_name + '(' + node_ip + ')', '장비 정보 수집 중...')
            pw = 'ericsson'
            telnet = telnetlib.Telnet(node_ip.rstrip(), timeout=3)
            telnet.read_until(b'Password', 2)
            telnet.write(pw.encode('ascii') + b'\r\n')
            telnet.read_until(b'>', 2)
            for operating_slot in operating_slots:
                slot_count_end += 2
                telnet.write(b'show rl status ' + operating_slot.encode('ascii') + b' near-end' + b'\r\n')
                display_txt = telnet.read_until(b'XPIC Status', 60).decode('ascii')
                slot_level_info_list = get_level_info(display_txt)
                slot_info_df = make_result_df(slot_level_info_list, local_day, npu_temp, node_name, node_ip, node_type)
                result_df = result_df.append(slot_info_df, ignore_index=True)  # 전체 결과 엑셀 파일 만들기 위해 대입
            telnet.write(b'exit' + b'\r\n')
        elif len(slots_and_temp_info) == 0:  # 장비 접속 불가 경우
            slot_count_end += 1
            temp = {'Date': [local_day],
                    'NE Name': [node_name],
                    'IPv4': [node_ip],
                    'NE Type': [node_type],
                    'NPU Temp': ['접속불가'],
                    'Slot': ['접속불가'],
                    'Tx': ['접속불가'],
                    'Rx': ['접속불가'],
                    'QAM': ['접속불가']}
            temp_df = pd.DataFrame(temp)
            result_df = result_df.append(temp_df, ignore_index=True)  # Slot, Tx, Rx 컬럼 접속불가로 표시

        # CMD 출력 화면 구성
        for_print = '========================{0}({1}) 수집 결과========================'.format(node_name, node_ip)
        print(for_print)
        print(result_df.loc[slot_count_start:slot_count_end])
        slot_count_start = slot_count_end
        print('\t*진행률 : {0}/{1}'.format(complete_node_count, all_node_num))
        for i in range(len(for_print) + 3):
            print('=', end='')
        print('\r\n')

    # 필요 파일 생성
    excel_filename = 'E-MW 점검 결과_{0}.xlsx'.format(local_day)  # 저장될 excel 파일명
    download_path = make_directory(desktop_path, directory_name)  # 엑셀 파일 저장할 위치 Path
    make_excel(result_df, download_path, excel_filename)  # 최종 결과 테이블 엑셀 생성


if __name__ == '__main__':
    main()
