import streamlit as st
import json
import numpy as np
import pandas as pd
import math
import re
import networkx as nx
from io import BytesIO

# ==========================================
# 設定・定数
# ==========================================
st.set_page_config(page_title="空想鉄道シミュレータ", layout="wide")

# 同一駅とみなす最大距離 (メートル)
SAME_STATION_THRESHOLD = 1000.0

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
# 物理計算・幾何学ロジック
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

# ==========================================
# ネットワーク解析ロジック
# ==========================================
def build_network(map_data):
    G = nx.Graph()
    edge_details = {} 
    known_stations = {}
    lines = map_data.get('line', [])
    station_id_map = {} 
    station_coords = {}

    for line_idx, line in enumerate(lines):
        if line.get('type') == 1: continue 
        line_name = line.get('name', f'路線{line_idx}')
        raw_points = line.get('point', [])
        
        for pt_idx, p in enumerate(raw_points):
            if len(p) >= 4 and p[2] == 's':
                raw_name = p[3]
                lat, lon = p[0], p[1]
                
                if raw_name not in known_stations:
                    known_stations[raw_name] = []
                
                found_id = None
                for entry in known_stations[raw_name]:
                    dist = hubeny_distance(lat, lon, entry['coords'][0], entry['coords'][1])
                    if dist < SAME_STATION_THRESHOLD:
                        found_id = entry['id']
                        break
                
                if found_id:
                    unique_id = found_id
                else:
                    if len(known_stations[raw_name]) == 0:
                        unique_id = raw_name
                    else:
                        unique_id = f"{raw_name} ({line_name})"
                        c = 2
                        base_id = unique_id
                        existing_ids = [e['id'] for e in known_stations[raw_name]]
                        while unique_id in existing_ids:
                            unique_id = f"{base_id} {c}"
                            c += 1
                    
                    known_stations[raw_name].append({'id': unique_id, 'coords': (lat, lon)})
                    station_coords[unique_id] = (lat, lon)
                
                station_id_map[(line_idx, pt_idx)] = unique_id

    for line_idx, line in enumerate(lines):
        if line.get('type') == 1: continue
        line_name = line.get('name', '不明')
        raw_points = line.get('point', [])
        
        line_stations = []
        for i, p in enumerate(raw_points):
            if (line_idx, i) in station_id_map:
                line_stations.append({
                    'id': station_id_map[(line_idx, i)],
                    'raw_idx': i
                })
        
        for i in range(len(line_stations) - 1):
            st1 = line_stations[i]
            st2 = line_stations[i+1]
            u, v = st1['id'], st2['id']
            
            segment_points = []
            for k in range(st1['raw_idx'], st2['raw_idx'] + 1):
                p = raw_points[k]
                segment_points.append((p[0], p[1]))
            
            dist = 0
            for k in range(len(segment_points)-1):
                dist += hubeny_distance(segment_points[k][0], segment_points[k][1],
                                      segment_points[k+1][0], segment_points[k+1][1])
            
            G.add_edge(u, v, weight=dist)
            key = tuple(sorted((u, v)))
            edge_details[key] = {
                'points': segment_points,
                'line_name': line_name
            }

    return G, edge_details, station_coords

# ==========================================
# シミュレーションクラス
# ==========================================
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
        while x < total and t < 3600*5: 
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
st.title("🚆 空想鉄道シミュレータ")
st.markdown("空想別館などの作品データを解析し、直通運転や所要時間シミュレーションを行います。")

# --- ブックマークレット解説 ---
with st.expander("📲 【便利機能】作品データの自動取得ブックマークレット (導入方法はこちら)"):
    st.markdown("""
    ブラウザのブックマーク機能を使って、空想別館のページからワンクリックでデータを取得できます。
    PCの方は以下の手順で登録してください。
    """)
    
    bookmarklet_code = r"""javascript:(function(){const match=location.pathname.match(/\/([^\/]+)\.html/);if(!match){alert('エラー：作品IDが見つかりません。\n作品ページ(ID.html)で実行してください。');return;}const mapId=match[1];const formData=new FormData();formData.append('exec','selectIndex');formData.append('mapno',mapId);formData.append('time',Date.now());fetch('/_Ajax.php',{method:'POST',body:formData}).then(response=>response.text()).then(text=>{if(text.length<50){alert('データ取得に失敗した可能性があります。\n中身: '+text);}else{navigator.clipboard.writeText(text).then(()=>{alert('【成功】作品データをコピーしました！\nID: '+mapId+'\n文字数: '+text.length+'\n\nシミュレータに戻って「Ctrl+V」で貼り付けてください。');}).catch(err=>{window.prompt("自動コピーに失敗しました。Ctrl+Cで以下をコピーしてください:",text);});}}).catch(err=>{alert('通信エラーが発生しました: '+err);});})();"""
    
    st.code(bookmarklet_code, language="javascript")
    
    st.markdown("""
    **【登録手順】**
    1. ブラウザのブックマークバーなどで「右クリック」→「ページを追加」を選択。
    2. 名前を「**空想データ取得**」など分かりやすい名前にする。
    3. URLの欄に、**上の黒いボックス内のコードをすべてコピーして貼り付ける**。
    4. 保存する。
    
    **【使い方】**
    1. 空想鉄道（空想別館）の作品ページを開く。
    2. 登録したブックマークをクリックする。
    3. 「成功」と出たら、このページの入力欄に **Ctrl+V (貼り付け)** する。
    """)

# --- データ入力 ---
raw_text = st.text_area(
    "作品データを貼り付けてください (Ctrl+V)",
    height=150,
    placeholder='ここに {"mapinfo": ... } から始まるデータを貼り付けます'
)

if raw_text:
    try:
        try: data = json.loads(raw_text)
        except:
            idx = raw_text.find('{')
            if idx != -1: data = json.loads(raw_text[idx:])
            else: st.stop()
        
        if isinstance(data.get('mapdata'), str):
            map_data = json.loads(data['mapdata'])
        else:
            map_data = data
            
        map_title = data.get('mapinfo', {}).get('name', '空想鉄道')
        
        # ネットワーク構築 (スマート結合)
        G, edge_details, station_coords = build_network(map_data)
        
        # 全駅リスト（ソート済み）
        all_stations_list = sorted(list(G.nodes()))
        
        st.success(f"ネットワーク構築完了: {len(all_stations_list)}駅 (距離判定閾値: {int(SAME_STATION_THRESHOLD)}m)")
        
        # --- 運転設定 ---
        st.subheader("⚙️ 運転プラン")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            # 出発・到着駅の選択
            dept_st = st.selectbox("出発駅", all_stations_list, index=0)
            dest_st = st.selectbox("到着駅", all_stations_list, index=len(all_stations_list)-1)
            
            # 経路計算
            try:
                route_stations = nx.shortest_path(G, source=dept_st, target=dest_st, weight='weight')
                st.info(f"経路: {' → '.join(route_stations[:5])} ... ({len(route_stations)}駅)")
            except nx.NetworkXNoPath:
                st.error("経路が見つかりませんでした。線路が繋がっていません。")
                st.stop()
            except Exception:
                st.error("出発駅と到着駅を選択してください。")
                st.stop()

            # トグル式停車設定
            st.write("▼ 停車パターン設定")
            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button("全選択"):
                for s in route_stations: st.session_state[f"chk_thru_{s}"] = True
            if btn_col2.button("全解除"):
                for s in route_stations: st.session_state[f"chk_thru_{s}"] = False

            with st.container(height=300):
                selected_names = []
                for s in route_stations:
                    key = f"chk_thru_{s}"
                    if key not in st.session_state: st.session_state[key] = True
                    if st.checkbox(s, key=key):
                        selected_names.append(s)

        with col2:
            vehicle_name = st.selectbox("使用車両", list(VEHICLE_DB.keys()))
            spec = VEHICLE_DB[vehicle_name]
            st.caption(f"{spec['desc']}")
            train_type = st.text_input("種別名", value="直通特急")
            dwell_time = st.slider("停車時間(秒)", 0, 120, 30)

        # --- 実行 ---
        st.write("")
        if st.button("シミュレーション実行", type="primary", use_container_width=True):
            if len(selected_names) < 2:
                st.error("停車駅不足です")
            else:
                final_stops = [s for s in route_stations if s in selected_names]
                if route_stations[0] not in final_stops: final_stops.insert(0, route_stations[0])
                if route_stations[-1] not in final_stops: final_stops.append(route_stations[-1])
                
                # 重複排除・順序維持
                seen = set()
                final_stops_ordered = []
                for x in route_stations:
                    if x in final_stops and x not in seen:
                        final_stops_ordered.append(x)
                        seen.add(x)
                final_stops = final_stops_ordered

                st.divider()
                st.subheader(f"🏁 {dept_st} 発 {dest_st} 行 ({train_type})")
                
                results = []
                progress_bar = st.progress(0)
                
                for i in range(len(final_stops) - 1):
                    progress_bar.progress((i+1)/(len(final_stops)-1))
                    
                    s_start = final_stops[i]
                    s_end = final_stops[i+1]
                    
                    sub_path = nx.shortest_path(G, s_start, s_end, weight='weight')
                    combined_points = []
                    
                    for k in range(len(sub_path)-1):
                        u, v = sub_path[k], sub_path[k+1]
                        key = tuple(sorted((u, v)))
                        details = edge_details[key]
                        pts = details['points']
                        
                        # 向き判定
                        u_coord = station_coords[u]
                        d_start = hubeny_distance(pts[0][0], pts[0][1], u_coord[0], u_coord[1])
                        d_end = hubeny_distance(pts[-1][0], pts[-1][1], u_coord[0], u_coord[1])
                        
                        if d_end < d_start: pts = pts[::-1]
                        
                        if combined_points: combined_points.extend(pts[1:])
                        else: combined_points.extend(pts)
                            
                    track = resample_and_analyze(combined_points, spec)
                    if not track: continue
                    
                    sim = TrainSim(track, spec)
                    run_sec = sim.run()
                    
                    is_last = (i == len(final_stops) - 2)
                    cur_dwell = 0 if is_last else dwell_time
                    total_leg = run_sec + cur_dwell
                    dist_km = track[-1]['dist'] / 1000.0
                    
                    results.append({
                        '出発': s_start, '到着': s_end,
                        '距離(km)': round(dist_km, 2),
                        '走行時間': format_time(run_sec),
                        '停車時間': f"{cur_dwell}秒",
                        '計': format_time(total_leg),
                        '_run': run_sec, '_dwell': cur_dwell
                    })

                progress_bar.progress(100)
                
                if results:
                    df = pd.DataFrame(results)
                    sum_run = df['_run'].sum()
                    sum_dwell = df['_dwell'].sum()
                    total_all = sum_run + sum_dwell
                    
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
                    
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_disp.to_excel(writer, sheet_name=sanitize_filename(train_type), index=False)
                    
                    st.download_button(
                        "Excelファイルをダウンロード",
                        data=output.getvalue(),
                        file_name=f"直通_{sanitize_filename(dept_st)}_{sanitize_filename(dest_st)}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

    except Exception as e:
        st.error(f"エラー: {e}")
