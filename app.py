import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime
import cv2
import numpy as np
import plotly.express as px
import os
import time

# === 1. 설정 및 초기화 ===
IMAGE_DIR = "images"
DOC_DIR = "docs"

for d in [IMAGE_DIR, DOC_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

DB_PATH = 'maintenance_v2.db'

def run_query(query, params=(), is_write=False):
    result = None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
        c = conn.cursor()
        c.execute(query, params)
        if is_write:
            conn.commit()
        else:
            result = c.fetchall()
        conn.close()
    except sqlite3.OperationalError:
        time.sleep(1)
        return run_query(query, params, is_write)
    return result

def init_db():
    queries = [
        '''CREATE TABLE IF NOT EXISTS inspection_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_name TEXT, inspection_date TEXT, status TEXT, 
            occurred_at TEXT, finished_at TEXT, failure_type TEXT,
            details TEXT, inspector TEXT, image_path TEXT)''',
        '''CREATE TABLE IF NOT EXISTS equipment_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''',
        '''CREATE TABLE IF NOT EXISTS checklist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT, equipment_name TEXT, check_item TEXT)''',
        '''CREATE TABLE IF NOT EXISTS maintenance_plan (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_name TEXT, task_name TEXT, start_date TEXT, end_date TEXT, task_type TEXT, manager TEXT)''',
        '''CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipment_name TEXT, doc_type TEXT, file_name TEXT, file_path TEXT, upload_date TEXT)'''
    ]
    for q in queries:
        run_query(q, is_write=True)

    cnt = run_query("SELECT count(*) FROM equipment_list")[0][0]
    if cnt == 0:
        default_equips = ["1호기 터보냉동기", "2호기 흡수식냉온수기", "급수 펌프(A)", "공조기(AHU-01)", "비상발전기"]
        for equip in default_equips:
            run_query("INSERT OR IGNORE INTO equipment_list (name) VALUES (?)", (equip,), is_write=True)

# === 2. 기능 함수들 ===
def save_file(uploaded_file, folder):
    if uploaded_file is not None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_name = uploaded_file.name
        saved_filename = f"{timestamp}_{original_name}"
        file_path = os.path.join(folder, saved_filename)
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        return file_path, original_name
    return None, None

def get_equipments():
    rows = run_query("SELECT name FROM equipment_list ORDER BY name")
    return [row[0] for row in rows]

def get_checklist(equip_name):
    rows = run_query("SELECT check_item FROM checklist_items WHERE equipment_name = ?", (equip_name,))
    return [row[0] for row in rows]

def add_log(equipment, status, details, inspector, image_path, occurred_at=None, finished_at=None, failure_type=None):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run_query('''INSERT INTO inspection_logs 
                 (equipment_name, inspection_date, status, details, inspector, image_path, occurred_at, finished_at, failure_type) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
              (equipment, now, status, details, inspector, image_path, occurred_at, finished_at, failure_type), is_write=True)

def view_logs(equip_filter=None):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    query = "SELECT * FROM inspection_logs"
    
    # [수정] 전체 보기가 아니면 WHERE 조건 추가
    if equip_filter and equip_filter != "전체 보기":
        query += f" WHERE equipment_name = '{equip_filter}'"
        
    query += " ORDER BY id DESC"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def delete_log(log_id):
    rows = run_query("SELECT image_path FROM inspection_logs WHERE id = ?", (log_id,))
    if rows and rows[0][0] and os.path.exists(rows[0][0]):
        try: os.remove(rows[0][0])
        except: pass
    run_query('DELETE FROM inspection_logs WHERE id = ?', (log_id,), is_write=True)

def add_plan(equip, task, start, end, type_, manager):
    run_query('INSERT INTO maintenance_plan (equipment_name, task_name, start_date, end_date, task_type, manager) VALUES (?, ?, ?, ?, ?, ?)',
              (equip, task, start, end, type_, manager), is_write=True)

def get_plans():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    df = pd.read_sql_query("SELECT * FROM maintenance_plan ORDER BY start_date", conn)
    conn.close()
    return df

def delete_plan(plan_id):
    run_query('DELETE FROM maintenance_plan WHERE id = ?', (plan_id,), is_write=True)

def add_document(equip, doc_type, file_name, file_path):
    now = datetime.now().strftime("%Y-%m-%d")
    run_query('INSERT INTO documents (equipment_name, doc_type, file_name, file_path, upload_date) VALUES (?, ?, ?, ?, ?)',
              (equip, doc_type, file_name, file_path, now), is_write=True)

def get_documents(equip_filter=None):
    conn = sqlite3.connect(DB_PATH, timeout=10)
    query = "SELECT * FROM documents"
    if equip_filter and equip_filter != "전체":
        query += f" WHERE equipment_name = '{equip_filter}'"
    query += " ORDER BY id DESC"
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

def delete_document(doc_id):
    rows = run_query("SELECT file_path FROM documents WHERE id = ?", (doc_id,))
    if rows and rows[0][0] and os.path.exists(rows[0][0]):
        try: os.remove(rows[0][0])
        except: pass
    run_query('DELETE FROM documents WHERE id = ?', (doc_id,), is_write=True)

def decode_qr_image(image_buffer):
    try:
        file_bytes = np.asarray(bytearray(image_buffer.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(img)
        return data
    except: return None

# === 3. 메인 앱 UI ===

def main():
    st.set_page_config(page_title="스마트 유지관리 시스템", layout="wide", page_icon="🏭")
    init_db()

    if 'scanned_equip' not in st.session_state:
        st.session_state['scanned_equip'] = None

    with st.sidebar:
        st.title("🏭 스마트 유지관리 v10.3")
        st.success("🟢 Server Online (Search UI)")
        
        menu = ["스마트 대시보드", "도면 및 문서 관리", "유지관리 계획 수립", "설비 점검 입력", "점검 이력 조회/관리", "설비 및 항목 관리"]
        choice = st.selectbox("메뉴 선택", menu)
        st.markdown("---")
        st.caption("Developed by Python")

    # --- [메뉴 1] 스마트 대시보드 ---
    if choice == "스마트 대시보드":
        st.subheader("📊 설비 운영 현황 및 KPI")
        
        col_btn1, col_btn2 = st.columns([1, 5])
        if col_btn1.button("🔄 새로고침"): st.rerun()
        
        # 1. D-Day 알림
        df_plan = get_plans()
        if not df_plan.empty:
            today = datetime.now().date()
            upcoming = []
            for _, row in df_plan.iterrows():
                try:
                    s_date = datetime.strptime(row['start_date'], "%Y-%m-%d").date()
                    diff = (s_date - today).days
                    if 0 <= diff <= 7:
                        upcoming.append(f"🔔 [D-{diff}] {row['equipment_name']} - {row['task_name']} ({row['start_date']})")
                except: pass
            if upcoming: st.warning("\n".join(upcoming))
            else: st.success("✅ 7일 내 예정된 정비 일정이 없습니다.")
        
        st.markdown("---")
        
        # 2. KPI 분석
        df_log = view_logs() # 전체 로그 가져오기
        
        if not df_log.empty:
            try:
                df_log['occ_dt'] = pd.to_datetime(df_log['occurred_at'], errors='coerce')
                df_log['fin_dt'] = pd.to_datetime(df_log['finished_at'], errors='coerce')
                df_log['work_hours'] = (df_log['fin_dt'] - df_log['occ_dt']).dt.total_seconds() / 3600
                df_log['work_hours'] = df_log['work_hours'].fillna(0)
            except: 
                df_log['work_hours'] = 0

            # KPI 요약
            total_logs = len(df_log)
            breakdown_logs = df_log[df_log['status'] == '고장'].copy()
            breakdown_cnt = len(breakdown_logs)
            total_downtime = breakdown_logs['work_hours'].sum()
            maintenance_logs = df_log[df_log['status'].isin(['고장', '점검요망'])].copy()
            total_maintenance_hours = maintenance_logs['work_hours'].sum()

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("총 점검 이력", f"{total_logs} 건")
            c2.metric("고장 발생", f"{breakdown_cnt} 건", delta_color="inverse")
            c3.metric("총 다운타임", f"{total_downtime:.1f} Hr", delta_color="inverse")
            c4.metric("총 정비 투입 시간", f"{total_maintenance_hours:.1f} Hr")

            # PM 비율
            pm_count = total_logs - breakdown_cnt
            pm_ratio = (pm_count / total_logs) * 100 if total_logs > 0 else 0
            
            st.markdown("#### 🛡️ 예방 정비(PM) 효율성")
            p_col1, p_col2 = st.columns([1, 3])
            p_col1.metric("예방 정비 비율", f"{pm_ratio:.1f} %")
            pg_color = "green" if pm_ratio >= 80 else ("orange" if pm_ratio >= 50 else "red")
            p_col2.write(f"목표: 80% 이상 (현재 상태: {pg_color.upper()})")
            p_col2.progress(min(pm_ratio / 100, 1.0))

            # 설비별 상세 분석
            st.markdown("---")
            all_equips = get_equipments()
            eq_stats = []
            PLANNED_HOURS = 720

            for eq_name in all_equips:
                eq_logs = df_log[df_log['equipment_name'] == eq_name]
                eq_fails = eq_logs[eq_logs['status'] == '고장']
                fail_cnt = len(eq_fails)
                eq_down = eq_fails['work_hours'].sum()
                
                op_time = max(0, PLANNED_HOURS - eq_down)
                avail = (op_time / PLANNED_HOURS) * 100
                mtbf = op_time / fail_cnt if fail_cnt > 0 else op_time
                mttr = eq_fails['work_hours'].mean() if fail_cnt > 0 else 0
                
                eq_stats.append({
                    "설비명": eq_name,
                    "가동률(%)": round(avail, 2),
                    "MTBF(시간)": round(mtbf, 1),
                    "MTTR(시간)": round(mttr, 2),
                    "고장횟수": fail_cnt,
                    "다운타임": round(eq_down, 1)
                })
            
            df_stats = pd.DataFrame(eq_stats)

            col_avail, col_mtbf, col_mttr = st.columns(3)
            with col_avail:
                st.subheader("⚡ 가동률")
                df_avail = df_stats.sort_values(by="가동률(%)", ascending=True)
                fig_av = px.bar(df_avail, x="가동률(%)", y="설비명", orientation='h', 
                                text="가동률(%)", color="가동률(%)", 
                                color_continuous_scale="RdYlGn", range_color=[80, 100])
                st.plotly_chart(fig_av, use_container_width=True)

            with col_mtbf:
                st.subheader("⏳ MTBF")
                df_mtbf = df_stats.sort_values(by="MTBF(시간)", ascending=True)
                fig_mt = px.bar(df_mtbf, x="MTBF(시간)", y="설비명", orientation='h',
                                text="MTBF(시간)", color="MTBF(시간)", color_continuous_scale="Blues")
                st.plotly_chart(fig_mt, use_container_width=True)

            with col_mttr:
                st.subheader("🔧 MTTR")
                df_mttr = df_stats.sort_values(by="MTTR(시간)", ascending=True)
                fig_mr = px.bar(df_mttr, x="MTTR(시간)", y="설비명", orientation='h',
                                text="MTTR(시간)", color="MTTR(시간)", color_continuous_scale="Reds")
                st.plotly_chart(fig_mr, use_container_width=True)
            
            with st.expander("📋 설비별 상세 데이터 및 다운로드"):
                st.dataframe(df_stats, use_container_width=True)
                csv_stats = df_stats.to_csv(index=False).encode('utf-8-sig')
                st.download_button(label="📥 KPI 다운로드 (CSV)", data=csv_stats, file_name=f"KPI_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")

            # 차트
            st.markdown("---")
            c_chart1, c_chart2 = st.columns(2)
            with c_chart1:
                st.subheader("📉 월별 고장 추이")
                try:
                    df_log['month'] = pd.to_datetime(df_log['inspection_date']).dt.strftime('%Y-%m')
                    monthly_trend = df_log.groupby('month').agg(fail_count=('status', lambda x: (x == '고장').sum())).reset_index().sort_values('month')
                    if not monthly_trend.empty:
                        fig_trend = px.line(monthly_trend, x='month', y='fail_count', markers=True, labels={'month': '월', 'fail_count': '고장 건수'})
                        fig_trend.update_traces(line_color='red', line_width=3)
                        st.plotly_chart(fig_trend, use_container_width=True)
                    else: st.info("데이터 부족")
                except: pass

            with c_chart2:
                st.subheader("🥧 고장/정비 원인 분석")
                if not maintenance_logs.empty and 'failure_type' in maintenance_logs.columns:
                    ft_counts = maintenance_logs['failure_type'].fillna('미지정').value_counts()
                    fig = px.pie(values=ft_counts, names=ft_counts.index, title="고장 및 정비 원인 분포")
                    st.plotly_chart(fig, use_container_width=True)
                else: st.info("정비 데이터가 없습니다.")

        else:
            st.info("데이터가 없습니다. 점검 이력을 등록해주세요.")

    # --- [메뉴 2~3] ---
    elif choice == "도면 및 문서 관리":
        st.subheader("🗂️ 도면 및 보고서 관리")
        tab1, tab2 = st.tabs(["📤 문서 등록", "📥 문서 조회"])
        with tab1:
            with st.form("doc_up"):
                c1, c2 = st.columns(2)
                d_eq = c1.selectbox("설비", get_equipments())
                d_tp = c2.selectbox("종류", ["도면", "매뉴얼", "성적서", "계획서", "기타"])
                up_f = st.file_uploader("파일", type=['pdf','xlsx','xls','docx','hwp','png','jpg'])
                if st.form_submit_button("저장"):
                    if up_f:
                        fp, fn = save_file(up_f, DOC_DIR)
                        add_document(d_eq, d_tp, fn, fp)
                        st.success("저장됨")
        with tab2:
            eq_f = st.selectbox("설비 필터", ["전체"] + get_equipments())
            df_d = get_documents(eq_f)
            if not df_d.empty:
                c1, c2, c3, c4, c5 = st.columns([2, 2, 3, 1, 1])
                c1.write("설비명"); c2.write("구분"); c3.write("파일명"); c4.write("다운"); c5.write("삭제")
                st.markdown("---")
                for _, r in df_d.iterrows():
                    c1, c2, c3, c4, c5 = st.columns([2, 2, 3, 1, 1])
                    c1.write(r['equipment_name'])
                    c2.write(r['doc_type'])
                    c3.write(r['file_name'])
                    with open(r['file_path'], "rb") as f:
                        c4.download_button("💾", f, file_name=r['file_name'], key=f"dl_{r['id']}")
                    if c5.button("🗑️", key=f"del_d_{r['id']}"): delete_document(r['id']); st.rerun()
            else: st.info("문서 없음")

    elif choice == "유지관리 계획 수립":
        st.subheader("📅 연간 계획 수립")
        with st.expander("➕ 계획 등록", expanded=False):
            with st.form("plan_f"):
                c1, c2 = st.columns(2)
                p_eq = c1.selectbox("설비", get_equipments())
                p_tk = c2.text_input("작업명")
                c3, c4 = st.columns(2)
                ps = c3.date_input("시작"); pe = c4.date_input("종료")
                c5, c6 = st.columns(2)
                pt = c5.selectbox("구분", ["자체점검", "법정검사", "외주공사", "예방정비"])
                pm = c6.text_input("담당자")
                if st.form_submit_button("저장"):
                    add_plan(p_eq, p_tk, str(ps), str(pe), pt, pm)
                    st.rerun()
        df_p = get_plans()
        if not df_p.empty:
            st.plotly_chart(px.timeline(df_p, x_start="start_date", x_end="end_date", y="equipment_name", color="task_type"), use_container_width=True)
            for i, r in df_p.iterrows():
                c1, c2, c3, c4 = st.columns([2, 4, 2, 1])
                c1.write(r['start_date'])
                c2.write(f"**{r['equipment_name']}** - {r['task_name']}")
                c3.write(r['manager'])
                if c4.button("삭제", key=f"dp_{r['id']}"): delete_plan(r['id']); st.rerun()
                st.markdown("---")

    # --- [메뉴 4] 설비 점검 입력 ---
    elif choice == "설비 점검 입력":
        st.subheader("📝 일일 점검 및 작업 기록")
        equip_list = get_equipments()
        
        with st.expander("📷 QR 스캔"):
            cam = st.camera_input("QR")
            if cam:
                dec = decode_qr_image(cam)
                if dec and dec in equip_list: st.session_state['scanned_equip'] = dec
        
        idx = 0
        if st.session_state['scanned_equip'] in equip_list: idx = equip_list.index(st.session_state['scanned_equip'])
        
        c1, c2 = st.columns(2)
        sel_eq = c1.selectbox("설비", equip_list, index=idx)
        insp = c2.text_input("점검자", "김세봉")

        st.markdown("##### 1. 설비 상태")
        stt = st.radio("상태", ["양호", "점검요망", "고장"], horizontal=True)
        
        with st.form("insp"):
            occurred = None; finished = None; f_type = None
            if stt != "양호":
                if stt == "고장":
                    st.error(f"⚠️ [{sel_eq}] 고장 발생! 다운타임 집계를 위해 시간을 입력하세요.")
                else:
                    st.warning(f"🔧 [{sel_eq}] 점검/수리 요망! 정비 시간을 입력하세요.")
                k1, k2, k3 = st.columns(3)
                cur_time = datetime.now().strftime("%Y-%m-%d %H:%M")
                occurred = k1.text_input("작업/발생 시작 (YYYY-MM-DD HH:MM)", value=cur_time)
                finished = k2.text_input("작업/조치 종료 (YYYY-MM-DD HH:MM)", value=cur_time)
                f_type = k3.selectbox("원인/유형", ["기계 결함", "전기/제어", "유압/공압", "S/W 오류", "단순 소모품", "사용자 과실", "기타"])

            st.markdown("---")
            st.markdown("##### 2. 점검 항목")
            chk = get_checklist(sel_eq)
            res = []
            if chk:
                cols = st.columns(2)
                for i, itm in enumerate(chk):
                    if cols[i%2].checkbox(itm): res.append(f"[v] {itm}")
                    else: res.append(f"[ ] {itm}")
            det = st.text_area("특이사항 / 조치내용")
            upf = st.file_uploader("현장 사진")
            if st.form_submit_button("저장하기"):
                imp = save_file(upf, IMAGE_DIR)[0]
                chk_s = "\n".join(res)
                fin_d = f"{chk_s}\n\n[내용]: {det}" if chk_s else det
                add_log(sel_eq, stt, fin_d, insp, imp, occurred, finished, f_type)
                st.success(f"✅ [{sel_eq}] 점검 결과가 저장되었습니다!")
                st.session_state['scanned_equip'] = None

    # --- [메뉴 5] 점검 이력 조회 (🔥 기능 개선) ---
    elif choice == "점검 이력 조회/관리":
        st.subheader("📋 이력 조회")
        
        # [수정] 검색바 대신 드롭다운(selectbox) 적용
        col_sch, col_dn = st.columns([4, 1])
        equip_options = ["전체 보기"] + get_equipments()
        selected_eq = col_sch.selectbox("조회할 설비 선택", equip_options)
        
        # 선택된 설비로 필터링된 데이터 가져오기
        df = view_logs(selected_eq)
        
        if not df.empty:
            csv = df.to_csv(index=False).encode('utf-8-sig')
            col_dn.download_button(label="📥 이력 다운로드", data=csv, file_name=f"Log_List_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv")
            
            # 테이블 표시 (필요한 컬럼만)
            st.dataframe(df[['id', 'equipment_name', 'inspection_date', 'status', 'failure_type', 'inspector']], use_container_width=True)
            
            with st.expander("🔍 상세 보기 및 삭제"):
                tid = st.number_input("조회할 ID 입력", min_value=0)
                if tid > 0:
                    r = df[df['id'] == tid]
                    if not r.empty:
                        row = r.iloc[0]
                        st.info(f"[{row['equipment_name']}] - {row['status']}")
                        st.write(f"**점검 일시:** {row['inspection_date']}")
                        if row['status'] in ['고장', '점검요망']:
                            st.warning(f"**[작업/정비 정보]**\n- 시작: {row['occurred_at']}\n- 종료: {row['finished_at']}\n- 유형: {row['failure_type']}")
                        st.text_area("상세 내용", row['details'], disabled=True)
                        p = row['image_path']
                        if p and os.path.exists(p): st.image(p, caption="현장 사진")
                        if st.button("🗑️ 이 기록 삭제"):
                             delete_log(tid); st.rerun()
                    else: st.warning("해당 ID의 기록이 없습니다.")
        else:
            st.info("조회된 이력이 없습니다.")

    # --- [메뉴 6] 설비 및 항목 관리 ---
    elif choice == "설비 및 항목 관리":
        st.subheader("⚙️ 설비 및 항목 설정")
        tab1, tab2, tab3 = st.tabs(["설비 등록/삭제", "체크리스트 항목", "QR코드"])
        with tab1:
            col1, col2 = st.columns(2)
            with col1:
                st.info("➕ 새로운 설비 등록")
                n_eq = st.text_input("설비명 입력", key="new_eq_input")
                if st.button("설비 추가하기"):
                    if n_eq:
                        try:
                            run_query("INSERT INTO equipment_list (name) VALUES (?)", (n_eq,), is_write=True)
                            st.success(f"[{n_eq}] 등록되었습니다.")
                            st.rerun()
                        except: st.error("이미 존재하는 설비명입니다.")
            with col2:
                st.error("🗑️ 등록된 설비 삭제")
                curr_equips = get_equipments()
                if curr_equips:
                    del_eq = st.selectbox("삭제할 설비 선택", curr_equips, key="del_eq_select")
                    if st.button("설비 삭제하기"):
                        run_query("DELETE FROM equipment_list WHERE name = ?", (del_eq,), is_write=True)
                        st.success(f"[{del_eq}] 삭제되었습니다.")
                        st.rerun()
        with tab2:
            eq = st.selectbox("대상 설비", get_equipments())
            items = get_checklist(eq)
            st.write(f"**[{eq}] 점검 항목:**", items)
            c1, c2 = st.columns(2)
            with c1:
                nit = st.text_input("새 항목")
                if st.button("항목 추가"):
                    run_query("INSERT INTO checklist_items (equipment_name, check_item) VALUES (?, ?)", (eq, nit), is_write=True)
                    st.rerun()
            with c2:
                if items:
                    dit = st.selectbox("항목 삭제", items)
                    if st.button("항목 삭제"):
                        run_query("DELETE FROM checklist_items WHERE equipment_name = ? AND check_item = ?", (eq, dit), is_write=True)
                        st.rerun()
        with tab3:
            q_eq = st.selectbox("QR대상", get_equipments())
            if st.button("QR 생성"):
                qr = cv2.QRCodeEncoder.create()
                _, img = qr.encode(q_eq)
                st.image(img, width=200)

if __name__ == '__main__':
    main()
