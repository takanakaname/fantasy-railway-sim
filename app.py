import streamlit as st
import json
import numpy as np
import pandas as pd
import math
import re
from io import BytesIO

# ==========================================
# 設定・定数
# ==========================================
st.set_page_config(page_title="空想鉄道シミュレータ", layout="wide")

VEHICLE_DB = {
    "標準的な私鉄車両 (例: ことでん1200形)": {
        "max_speed": 85.0, "acc": 2.5, "dec": 3.5, "curve_factor": 4.0,
        "desc": "地方私鉄でよく見る標準的な性能。最高速は控えめ。"
    },
    "近郊型電車 (例: 国鉄115系)": {
        "max_speed": 110.0, "acc": 2.0, "dec": 3.5, "curve_factor": 3.9,
        "desc": "国鉄時代の代表的な近郊型電車。加速は鈍いが最高速は出る。"
    },
    "高性能通勤電車 (例: JR E233系)": {
        "max_speed": 120.0, "acc": 3.0, "dec": 4.2, "curve_factor": 4.5,
        "desc": "首都圏の主力車両。加減速性能・最高速ともに高水準。"
    },
    "高加速車「ジェットカー」 (例: 阪神5700系)": {
        "max_speed": 110.0, "acc": 4.0, "dec": 4.5, "curve_factor": 4.2,
        "desc": "駅間が短い路線向け。驚異的な加速力。"
    },
    "特急型車両 (例: 683系)": {
        "max_speed": 130.0, "acc": 2.2, "dec": 4.0, "curve_factor": 4.5,
        "desc": "高速走行性能に優れた特急車両。"
    },
    "新幹線 (例: N700S)": {
        "max_speed": 300.0, "acc": 2.6, "dec": 4.5, "curve_factor": 6.0,
        "desc": "直線区間では最強だが、在来線カーブには弱い。"
    }
}

# ==========================================
# 物理計算ロジック
# ==========================================
def hubeny_distance(lat1, lon1, lat2, lon2):
    a, b = 6378137.000, 6356752.314
    e2 = (a**2 - b**2) / a**2
    rad_lat1, rad_lon1 = math.radians(lat1), math.radians(lon1)
    rad_lat2, rad_lon2 = math.radians(lat2), math.radians(lon2)
    avg_lat = (rad_lat1 + rad_lat2) / 2.0
    d_lat, d_lon = rad_lat1 - rad_lat2, rad_lon1 - rad_lon2
    W = math.sqrt(1 - e2 * math.sin(avg_lat)**2)
    M, N = a * (1 - e2) / W**3, a / W
    return math.sqrt((d_lat * M)**2 + (d_lon * N * math.cos(avg_lat))**2)

def calculate_radius(p1, p2, p3):
    d12 = hubeny_distance(p2[0], p2[1], p1[0], p1[1])
    d23 = hubeny_distance(p2[0], p2[1], p3[0], p3[1])
    a = hubeny_distance(p1[0], p1[1], p2[0], p2[1])
    b = hubeny_distance(p2[0], p2[1], p3[0], p3[1])
    c = hubeny_distance(p3[0], p3[1], p1[0], p1[1])
    s = (a+b+c)/2
    val = s*(s-a)*(s-b)*(s-c)
    if val <= 0: return 9999.0
    area = math.sqrt(val)
    if area < 0.01: return 9999.0
    R = (a*b*c)/(4*area)
    return min(R, 6000.0)

def resample_and_analyze(points, spec, interval=25.0):
    if len(points) < 2: return []
    cum_dist = [0.0]
    for i in range(1, len(points)):
        d = hubeny_distance(points[i-1][0], points[i-1][1], points[i][0], points[i][1])
        cum_dist.append(cum_dist[-1] + d)
    
    total = cum_dist[-1]
    if total == 0: return []
    new_dists = np.arange(0, total, interval)
    lats = np.interp(new_dists, cum_dist, [p[0] for p in points])
    lons = np.interp(new_dists, cum_dist, [p[1] for p in points])
    
    track = []
    w = 3 
    for i in range(len(new_dists)):
        if i < w or i >= len(new_dists) - w:
            R = 9999.0
        else:
            R = calculate_radius((lats[i-w], lons[i-w]), (lats[i], lons[i]), (lats[i+w], lons[i+w]))
        
        limit = spec['curve_factor'] * math.sqrt(R)
        limit = max(25.0, min(spec['max_speed'], limit))
        track.append({'dist': new_dists[i], 'limit': limit, 'pattern': 0.0})
    return track

class TrainSim:
    def __init__(self, track, spec):
        self.track = track
        self.spec = spec
        self.dt = 0.5
        self.max_acc = spec['acc'] / 3.6
        self.max_dec = spec['dec'] / 3.6
        self._calc_brake_pattern()
    
    def _calc_brake_pattern(self):
        self.track[-1]['pattern'] = 0.0
        for i in range(len(self.track)-2, -1, -1):
            dd = self.track[i+1]['dist'] - self.track[i]['dist']
            v_next = self.track[i+1]['pattern'] / 3.6
            v_allow = math.sqrt(v_next**2 + 2 * self.max_dec * dd) * 3.6
            self.track[i]['pattern'] = min(v_allow, self.track[i]['limit'])

    def run(self):
        t, x, v = 0.0, 0.0, 0.0
        curr = 0
        total = self.track[-1]['dist']
        while x < total and t < 3600:
            while curr < len(self.track)-1 and self.track[curr+1]['dist'] < x:
                curr += 1
            node = self.track[curr]
            tgt = node['pattern']
            v_ms = v / 3.6
            if v > tgt:
                v_ms -= self.max_dec * self.dt
            elif v < tgt:
                ratio = 1.0
                if v > 35: ratio = 35/v
                if v > 100: ratio *= (100/v)
                v_ms += self.max_acc * ratio * self.dt
            if v_ms < 0: v_ms = 0
            x += v_ms * self.dt
            v = v_ms * 3.6
            t += self.dt
            if x >= total - 2.0 and v < 1.0: break
        return t

def format_time(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}分{int(s):02d}秒"

def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]+', '_', name)

# ==========================================
# アプリUI
# ==========================================
st.title("空想鉄道シミュレータ Web版")
st.markdown("空想鉄道の作品データ(JSON/txt)を読み込み、運転シミュレーションを行います。")

# 1. データ入力
uploaded_file = st.file_uploader("作品データ(.txt)をアップロード", type=['txt', 'json'])

if uploaded_file is not None:
    try:
        # データの読み込み
        stringio = uploaded_file.getvalue().decode("utf-8")
        
        try:
            data = json.loads(stringio)
        except:
            # {の前まで削除してトライ
            idx = stringio.find('{')
            if idx != -1:
                data = json.loads(stringio[idx:])
            else:
                st.error("有効なJSONデータが見つかりませんでした。")
                st.stop()
        
        # マップデータの抽出
        if isinstance(data.get('mapdata'), str):
            map_data = json.loads(data['mapdata'])
        else:
            map_data = data
            
        map_title = data.get('mapinfo', {}).get('name', '空想鉄道')
        
        # 路線抽出
        lines = map_data.get('line', [])
        line_dict = {}
        for i, l in enumerate(lines):
            if l.get('type') != 1: # 計画線除外
                line_dict[l.get('name', f'路線{i}')] = i
        
        if not line_dict:
            st.warning("有効な路線が見つかりませんでした。")
            st.stop()

        st.success(f"読み込み成功: {map_title} ({len(line_dict)}路線)")
        
        # --- 設定エリア ---
        st.subheader("運転設定")
        
        col1, col2 = st.columns(2)
        
        with col1:
            selected_line_name = st.selectbox("対象路線", list(line_dict.keys()))
            line_idx = line_dict[selected_line_name]
            
            # 停車駅の抽出
            target_line = map_data['line'][line_idx]
            points = target_line.get('point', [])
            all_stations = []
            line_points = []
            
            for i, p in enumerate(points):
                line_points.append((p[0], p[1]))
                if len(p)>=4 and p[2]=='s':
                    all_stations.append({'name': p[3], 'idx': i})
            
            # デフォルトですべて選択
            all_station_names = [s['name'] for s in all_stations]
            
            # 停車駅選択UI (マルチセレクト)
            container = st.container()
            all_check = st.checkbox("全駅停車する", value=True)
            
            if all_check:
                selected_names = all_station_names
                st.info("各駅停車で運転します")
            else:
                selected_names = st.multiselect(
                    "停車する駅を選択 (通過する駅は外してください)",
                    all_station_names,
                    default=all_station_names
                )
        
        with col2:
            vehicle_name = st.selectbox(
                "使用車両",
                list(VEHICLE_DB.keys()),
                index=0
            )
            spec = VEHICLE_DB[vehicle_name]
            st.caption(f"解説: {spec['desc']}")
            
            train_type = st.text_input("種別名", value="普通")
            dwell_time = st.slider("停車時間(秒)", 0, 120, 30)

        # 実行ボタン
        if st.button("シミュレーション実行", type="primary"):
            if len(selected_names) < 2:
                st.error("停車駅は2つ以上必要です。")
            else:
                # 選択された駅データの再構築
                selected_stops = [s for s in all_stations if s['name'] in selected_names]
                # 元の並び順を維持
                selected_stops.sort(key=lambda x: x['idx'])
                
                # 始発・終着の強制追加
                if all_stations[0] not in selected_stops:
                    selected_stops.insert(0, all_stations[0])
                if all_stations[-1] not in selected_stops:
                    selected_stops.append(all_stations[-1])
                # 重複除去
                selected_stops = [dict(t) for t in {tuple(d.items()) for d in selected_stops}]
                selected_stops.sort(key=lambda x: x['idx'])

                st.divider()
                st.subheader(f"{selected_line_name} ({train_type})")
                st.write(f"車両: {vehicle_name.split('(')[0]} / 停車駅数: {len(selected_stops)}")

                results = []
                progress_bar = st.progress(0)
                
                for i in range(len(selected_stops) - 1):
                    start_st = selected_stops[i]
                    end_st = selected_stops[i+1]
                    
                    # 進捗更新
                    progress_bar.progress((i + 1) / (len(selected_stops) - 1))
                    
                    # 区間データ抽出
                    seg_points = line_points[start_st['idx'] : end_st['idx'] + 1]
                    track = resample_and_analyze(seg_points, spec)
                    
                    if not track: continue
                    
                    sim = TrainSim(track, spec)
                    run_sec = sim.run()
                    
                    is_last = (i == len(selected_stops) - 2)
                    cur_dwell = 0 if is_last else dwell_time
                    total_leg = run_sec + cur_dwell
                    dist_km = track[-1]['dist'] / 1000.0
                    
                    results.append({
                        '出発': start_st['name'],
                        '到着': end_st['name'],
                        '距離(km)': round(dist_km, 2),
                        '走行時間': format_time(run_sec),
                        '停車時間': f"{cur_dwell}秒",
                        '計': format_time(total_leg),
                        '_run': run_sec, '_dwell': cur_dwell
                    })
                
                progress_bar.empty()
                
                if results:
                    df = pd.DataFrame(results)
                    sum_run = df['_run'].sum()
                    sum_dwell = df['_dwell'].sum()
                    total_all = sum_run + sum_dwell
                    
                    # 合計行
                    sum_row = pd.DataFrame([{
                        '出発': '【合計】', '到着': '',
                        '距離(km)': df['距離(km)'].sum(),
                        '走行時間': format_time(sum_run),
                        '停車時間': format_time(sum_dwell),
                        '計': format_time(total_all)
                    }])
                    
                    df_disp = pd.concat([df, sum_row], ignore_index=True)
                    df_disp = df_disp[['出発', '到着', '距離(km)', '走行時間', '停車時間', '計']]
                    
                    st.dataframe(df_disp, use_container_width=True)
                    
                    # Excelダウンロード
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_disp.to_excel(writer, sheet_name=sanitize_filename(train_type), index=False)
                    
                    file_name = f"{sanitize_filename(map_title)}_{sanitize_filename(selected_line_name)}_{sanitize_filename(train_type)}.xlsx"
                    
                    st.download_button(
                        label="Excelファイルをダウンロード",
                        data=output.getvalue(),
                        file_name=file_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

    except Exception as e:
        st.error(f"エラーが発生しました: {e}")
