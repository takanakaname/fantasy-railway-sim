import streamlit as st
import json
import numpy as np
import pandas as pd
import math
import re
import networkx as nx
from streamlit_folium import st_folium
import folium
from io import BytesIO

# ==========================================
# 設定・定数
# ==========================================
st.set_page_config(
    page_title="架空鉄道 所要時間シミュレータ",
    page_icon="🚆",
    layout="wide"
)

# 同一駅とみなす最大距離 (メートル)
SAME_STATION_THRESHOLD = 1000.0

# 車両データベース
VEHICLE_DB = {
    "大手私鉄 一般車両 (例: 東急5000系・阪急8000系)": {
        "max_speed": 110.0, "acc": 3.0, "dec": 4.0, "curve_factor": 4.2,
        "desc": "都市部の私鉄で広く使われている標準的な通勤車両。バランスが良い。"
    },
    "JR高性能通勤車 (例: E233系)": {
        "max_speed": 120.0, "acc": 3.0, "dec": 4.2, "curve_factor": 4.5,
        "desc": "首都圏の主要路線を走る車両。最高速度が高く、高速運転に対応。"
    },
    "近郊型電車 (例: 国鉄115系・211系)": {
        "max_speed": 110.0, "acc": 2.0, "dec": 3.5, "curve_factor": 3.9,
        "desc": "少し昔の標準的な電車。加速はのんびりしているが、高速巡航は可能。"
    },
    "高加速車「ジェットカー」 (例: 阪神5700系)": {
        "max_speed": 110.0, "acc": 4.0, "dec": 4.5, "curve_factor": 4.2,
        "desc": "駅間が短い路線向け。驚異的な加速力でタイムを稼ぐ。"
    },
    "特急型車両 (例: 683系・E259系)": {
        "max_speed": 130.0, "acc": 2.2, "dec": 4.0, "curve_factor": 4.5,
        "desc": "高速走行性能に優れた特急車両。加速より最高速重視。"
    },
    "新幹線 (例: N700S)": {
        "max_speed": 300.0, "acc": 2.6, "dec": 4.5, "curve_factor": 6.0,
        "desc": "直線区間では最強だが、在来線の急カーブでは減速を強いられる。"
    },
    "地方私鉄・旧型車 (例: 元京王・元東急譲渡車)": {
        "max_speed": 85.0, "acc": 2.5, "dec": 3.5, "curve_factor": 4.0,
        "desc": "地方路線で活躍する少し古い車両。最高速度は控えめ。"
    },
    "地下鉄車両 (例: 東京メトロ16000系)": {
        "max_speed": 100.0, "acc": 3.3, "dec": 4.0, "curve_factor": 4.5,
        "desc": "加速性能が高く、カーブや勾配に強い地下鉄仕様。"
    },
    "路面電車 / LRT (例: 広電・ライトレール)": {
        "max_speed": 60.0, "acc": 3.5, "dec": 5.0, "curve_factor": 5.0,
        "desc": "最高速度は低いが、信号待ちからの発進などが得意。"
    },
    "貨物列車 (例: EF210形機関車牽引)": {
        "max_speed": 110.0, "acc": 0.8, "dec": 2.5, "curve_factor": 3.5,
        "desc": "非常に重いため、加速に時間がかかる。ダイヤ上の障害物として。"
    },
    "蒸気機関車 SL (例: C57形)": {
        "max_speed": 85.0, "acc": 1.0, "dec": 2.5, "curve_factor": 3.5,
        "desc": "観光列車用。ゆっくり走り、加減速も緩やか。"
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
# ネットワーク解析ロジック (キャッシュ対応)
# ==========================================
@st.cache_data(show_spinner="マップデータを解析中...")
def build_network(map_data):
    G = nx.MultiGraph()
    edge_details = {} 
    known_stations = {}
    lines = map_data.get('line', [])
    station_id_map = {} 
    station_coords = {}
    all_line_names = [] # 順序保持のためにリストを使用
    line_stations_dict = {}

    # 駅ID解決
    for line_idx, line in enumerate(lines):
        if line.get('type') == 1: continue 
        line_name = line.get('name', f'路線{line_idx}')
        if line_name not in all_line_names:
            all_line_names.append(line_name)
        
        raw_points = line.get('point', [])
        
        for pt_idx, p in enumerate(raw_points):
            if len(p) >= 3 and p[2] == 's':
                if len(p) >= 4 and str(p[3]).strip():
                    raw_name = str(p[3])
                else:
                    raw_name = f"未設定駅({line_idx}-{pt_idx})"

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

    # グラフエッジ構築
    for line_idx, line in enumerate(lines):
        if line.get('type') == 1: continue
        line_name = line.get('name', '不明')
        raw_points = line.get('point', [])
        
        line_stations = []
        for i, p in enumerate(raw_points):
            if (line_idx, i) in station_id_map:
                st_id = station_id_map[(line_idx, i)]
                line_stations.append({
                    'id': st_id,
                    'raw_idx': i
                })
        
        line_stations_dict[line_name] = [s['id'] for s in line_stations]
        
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
            
            G.add_edge(u, v, key=line_name, weight=dist, line_name=line_name)
            
            key = tuple(sorted((u, v)))
            if key not in edge_details:
                edge_details[key] = {}
            
            edge_details[key][line_name] = {
                'points': segment_points,
                'weight': dist,
                'line_name': line_name
            }

    return G, edge_details, station_coords, all_line_names, line_stations_dict

# ==========================================
# 地図描画ロジック
# ==========================================
def create_route_map(route_points_list, route_nodes, station_coords, dept_st, dest_st, via_st):
    if not route_points_list:
        return None
    
    all_lats = []
    all_lons = []
    for segment in route_points_list:
        for p in segment:
            all_lats.append(p[0])
            all_lons.append(p[1])
            
    if not all_lats: return None
            
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10)
    
    # 線路描画
    for segment in route_points_list:
        folium.PolyLine(
            locations=segment,
            color="blue",
            weight=5,
            opacity=0.7
        ).add_to(m)
        
    # マーカー描画
    for node in route_nodes:
        coord = station_coords.get(node)
        if not coord: continue
        
        icon_color = "blue"
        icon_type = "info-sign"
        
        if node == dept_st:
            icon_color = "green"
            icon_type = "play"
        elif node == dest_st:
            icon_color = "red"
            icon_type = "stop"
        elif node == via_st:
            icon_color = "orange"
            icon_type = "flag"
        else:
            folium.CircleMarker(
                location=coord,
                radius=4,
                color="blue",
                fill=True,
                fill_color="white",
                tooltip=node
            ).add_to(m)
            continue

        folium.Marker(
            location=coord,
            popup=node,
            tooltip=node,
            icon=folium.Icon(color=icon_color, icon=icon_type)
        ).add_to(m)
        
    return m

# ==========================================
# UIコンポーネント
# ==========================================
def station_selector_widget(label, all_stations, line_stations_dict, all_lines, key_prefix, default_idx=0):
    st.markdown(f"#### {label}")
    
    mode = st.radio(
        f"{label}の選択方法",
        ["路線から絞り込み", "全駅から検索"],
        horizontal=True,
        key=f"{key_prefix}_mode",
        label_visibility="collapsed"
    )
    
    selected_station = None
    
    if mode == "路線から絞り込み":
        c1, c2 = st.columns(2)
        with c1:
            line = st.selectbox(f"{label}: 路線", all_lines, key=f"{key_prefix}_line")
        with c2:
            stations = line_stations_dict[line]
            idx = 0
            if default_idx == -1: idx = len(stations) - 1
            if idx >= len(stations): idx = 0
            selected_station = st.selectbox(f"{label}: 駅", stations, index=idx, key=f"{key_prefix}_st_sub")
    else:
        idx = default_idx
        if idx == -1: idx = len(all_stations) - 1
        if idx >= len(all_stations): idx = 0
        selected_station = st.selectbox(f"{label}: 駅名", all_stations, index=idx, key=f"{key_prefix}_st_all")
        
    return selected_station

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
        while x < total and t < 3600*10:
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

# サイドバー: 開発者情報・規約
with st.sidebar:
    st.header("ℹ️ アプリ情報")
    st.markdown("開発者: **高那**")
    st.markdown("[X (Twitter): @takanakaname](https://x.com/takanakaname)")
    
    st.divider()
    
    st.markdown("### ⚠️ 免責事項・規約")
    with st.expander("利用規約・クレジットを確認"):
        st.markdown("""
        **1. 非公式ツール**
        本ツールは「空想鉄道」シリーズ等の公式運営とは一切関係のない、個人のファンメイドツールです。
        
        **2. データの取り扱い**
        入力された作品データは、ブラウザ上および一時的なメモリ内でのみ処理されます。サーバーへの保存や、制作者によるデータの収集は行っていません。
        
        **3. 免責**
        本ツールの計算結果（所要時間・距離など）の正確性は保証されません。本ツールを使用したことによる損害やトラブルについて、制作者は一切の責任を負いません。
        
        **4. 地図データ出典**
        Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
        """)

# メインコンテンツ
st.title("架空鉄道 所要時間シミュレータ")
st.markdown("空想鉄道シリーズの作品データを解析し、直通運転や所要時間シミュレーションを行います。")

# --- ブックマークレット解説 ---
with st.expander("作品データの自動取得ブックマークレット (使い方)", expanded=False):
    st.markdown("""
    ブラウザのブックマーク機能を利用して、空想鉄道の作品ページからデータを簡単にコピーできます。
    このブックマークレットを使用できるのは「空想鉄道」「空想旧鉄」「空想地図」「空想別館」です。
    """)
    st.markdown("#### 登録手順")
    st.markdown("""
    1. 下記のコードをすべてコピーしてください。
    2. ブラウザのブックマークバーを右クリックし、「ページを追加」を選びます。
    3. 名前に「データ取得」などと入力します。
    4. URLの欄に、コピーしたコードを貼り付けて保存します。
    """)
    bookmarklet_code = r"""javascript:(function(){const match=location.pathname.match(/\/([^\/]+)\.html/);if(!match){alert('エラー：作品IDが見つかりません。\n作品ページ(ID.html)で実行してください。');return;}const mapId=match[1];const formData=new FormData();formData.append('exec','selectIndex');formData.append('mapno',mapId);formData.append('time',Date.now());fetch('/_Ajax.php',{method:'POST',body:formData}).then(response=>response.text()).then(text=>{if(text.length<50){alert('データ取得に失敗した可能性があります。\n中身: '+text);}else{navigator.clipboard.writeText(text).then(()=>{alert('【成功】作品データをコピーしました！\nID: '+mapId+'\n文字数: '+text.length+'\n\nシミュレータに戻って「Ctrl+V」で貼り付けてください。');}).catch(err=>{window.prompt("自動コピーに失敗しました。Ctrl+Cで以下をコピーしてください:",text);});}}).catch(err=>{alert('通信エラーが発生しました: '+err);});})();"""
    st.code(bookmarklet_code, language="javascript")
    st.markdown("#### 使い方")
    st.markdown("""
    1. 各サイトの作品ページを開きます。
    2. 登録したブックマークをクリックします。
    3. 「成功」と表示されたら、この下の入力欄に **Ctrl+V (貼り付け)** してください。
    """)

st.divider()

# --- データ入力 ---
st.subheader("データの入力")
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
        
        # ネットワーク構築
        G, edge_details, station_coords, all_line_names, line_stations_dict = build_network(map_data)
        all_stations_list = sorted(list(G.nodes()))
        
        st.success(f"解析完了: {len(all_stations_list)}駅 / {len(all_line_names)}路線")
        
        # --- 運転プラン ---
        st.subheader("運転プラン")
        
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("#### ルート選択")
            
            # 出発駅
            dept_st = station_selector_widget(
                "出発駅", all_stations_list, line_stations_dict, all_line_names, "dept", default_idx=0
            )
            
            # 優先・回避
            with st.expander("路線ごとの優先度設定", expanded=False):
                avoid_lines = st.multiselect("避ける (コスト増)", all_line_names)
                prioritize_lines = st.multiselect("優先する (コスト減)", all_line_names)

            # 到着駅
            dest_st = station_selector_widget(
                "到着駅", all_stations_list, line_stations_dict, all_line_names, "dest", default_idx=-1
            )
            
            # 経由地
            use_via = st.checkbox("経由駅を指定", value=False)
            via_st = None
            if use_via:
                via_st = station_selector_widget(
                    "経由駅", all_stations_list, line_stations_dict, all_line_names, "via", default_idx=0
                )

            # --- 経路計算 ---
            try:
                G_calc = G.copy()
                for u, v, k, d in G_calc.edges(keys=True, data=True):
                    l_name = d.get('line_name', '')
                    base_weight = d['weight']
                    if l_name in avoid_lines: d['weight'] = base_weight * 10.0
                    elif l_name in prioritize_lines: d['weight'] = base_weight * 0.2
                    else: d['weight'] = base_weight
                
                if use_via and via_st:
                    p1 = nx.shortest_path(G_calc, source=dept_st, target=via_st, weight='weight')
                    p2 = nx.shortest_path(G_calc, source=via_st, target=dest_st, weight='weight')
                    full_route_nodes = p1 + p2[1:]
                else:
                    full_route_nodes = nx.shortest_path(G_calc, source=dept_st, target=dest_st, weight='weight')
                
                actual_dist = 0
                used_lines_list = []
                map_geometry_list = []
                
                for i in range(len(full_route_nodes)-1):
                    u = full_route_nodes[i]
                    v = full_route_nodes[i+1]
                    key = tuple(sorted((u, v)))
                    
                    candidates = edge_details.get(key, {})
                    best_line = None
                    min_cost = float('inf')
                    
                    for l_name, info in candidates.items():
                        cost = info['weight']
                        if l_name in avoid_lines: cost *= 10.0
                        elif l_name in prioritize_lines: cost *= 0.2
                        
                        if cost < min_cost:
                            min_cost = cost
                            best_line = l_name
                    
                    if best_line:
                        # 経由路線のリスト登録（重複連続の排除）
                        if not used_lines_list or used_lines_list[-1] != best_line:
                            used_lines_list.append(best_line)
                            
                        actual_dist += candidates[best_line]['weight']
                        
                        pts = candidates[best_line]['points']
                        u_coord = station_coords[u]
                        d_start = hubeny_distance(pts[0][0], pts[0][1], u_coord[0], u_coord[1])
                        d_end = hubeny_distance(pts[-1][0], pts[-1][1], u_coord[0], u_coord[1])
                        
                        if d_end < d_start:
                            map_geometry_list.append(pts[::-1])
                        else:
                            map_geometry_list.append(pts)
                
                st.info(f"ルート確定: {len(full_route_nodes)}駅 (実距離 約{actual_dist/1000:.1f}km)")
                st.caption(f"経由路線: {', '.join(used_lines_list)}")

                # --- 地図表示 ---
                st.markdown("#### ルートマップ")
                map_obj = create_route_map(map_geometry_list, full_route_nodes, station_coords, dept_st, dest_st, via_st)
                st_folium(map_obj, height=600, use_container_width=True)

            except nx.NetworkXNoPath:
                st.error("経路が見つかりません。")
                st.stop()
            except Exception as e:
                st.error(f"エラー: {e}")
                st.stop()

            # 停車駅設定
            st.markdown("#### 停車パターン")
            btn_col1, btn_col2 = st.columns(2)
            if btn_col1.button("全選択"):
                for i, s in enumerate(full_route_nodes): st.session_state[f"chk_{i}_{s}"] = True
            if btn_col2.button("全解除"):
                for i, s in enumerate(full_route_nodes): st.session_state[f"chk_{i}_{s}"] = False

            with st.container(height=300):
                selected_indices = []
                for i, s_name in enumerate(full_route_nodes):
                    key = f"chk_{i}_{s_name}"
                    if key not in st.session_state: st.session_state[key] = True
                    if st.checkbox(f"{i+1}. {s_name}", key=key):
                        selected_indices.append(i)

        with col2:
            st.markdown("#### 車両・種別")
            vehicle_name = st.selectbox("使用車両", list(VEHICLE_DB.keys()))
            spec = VEHICLE_DB[vehicle_name]
            st.info(f"性能: {spec['desc']}")
            
            train_type = st.text_input("種別名", value="普通")
            dwell_time = st.slider("停車時間(秒)", 0, 120, 20)

        # --- 実行 ---
        st.write("")
        if st.button("シミュレーション実行", type="primary", use_container_width=True):
            if 0 not in selected_indices: selected_indices.append(0)
            last_idx = len(full_route_nodes) - 1
            if last_idx not in selected_indices: selected_indices.append(last_idx)
            selected_indices.sort()
            
            if len(selected_indices) < 2:
                st.error("停車駅が足りません")
            else:
                st.divider()
                st.subheader(f"{dept_st} 発 {dest_st} 行")
                
                results = []
                progress_bar = st.progress(0)
                
                for i in range(len(selected_indices) - 1):
                    progress_bar.progress((i+1)/(len(selected_indices)-1))
                    
                    idx_start = selected_indices[i]
                    idx_end = selected_indices[i+1]
                    s_name_start = full_route_nodes[idx_start]
                    s_name_end = full_route_nodes[idx_end]
                    
                    segment_nodes = full_route_nodes[idx_start : idx_end + 1]
                    combined_points = []
                    
                    for k in range(len(segment_nodes) - 1):
                        u, v = segment_nodes[k], segment_nodes[k+1]
                        key = tuple(sorted((u, v)))
                        
                        candidates = edge_details.get(key, {})
                        best_line = None
                        min_cost = float('inf')
                        for l_name, info in candidates.items():
                            cost = info['weight']
                            if l_name in avoid_lines: cost *= 10.0
                            elif l_name in prioritize_lines: cost *= 0.2
                            if cost < min_cost:
                                min_cost = cost
                                best_line = l_name
                        
                        if not best_line: continue
                        
                        pts = candidates[best_line]['points']
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
                    
                    cur_dwell = 0 if (i == len(selected_indices) - 2) else dwell_time
                    total_leg = run_sec + cur_dwell
                    dist_km = track[-1]['dist'] / 1000.0
                    
                    results.append({
                        '出発': s_name_start, '到着': s_name_end,
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
                        file_name=f"解析_{sanitize_filename(dept_st)}-{sanitize_filename(dest_st)}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

    except Exception as e:
        st.error(f"エラー: {e}")
