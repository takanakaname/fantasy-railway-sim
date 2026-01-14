import math
import numpy as np
import networkx as nx
import folium
import streamlit as st
from config import SAME_STATION_THRESHOLD

# ==========================================
# 1. 物理・幾何学計算
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
# 2. ネットワーク解析 (NetworkX)
# ==========================================
@st.cache_data(show_spinner="マップデータを解析中...")
def build_network(map_data):
    G = nx.MultiGraph()
    edge_details = {} 
    known_stations = {}
    lines = map_data.get('line', [])
    station_id_map = {} 
    station_coords = {}
    all_line_names = []
    line_stations_dict = {}

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

    for line_idx, line in enumerate(lines):
        if line.get('type') == 1: continue
        line_name = line.get('name', '不明')
        raw_points = line.get('point', [])
        
        line_stations = []
        for i, p in enumerate(raw_points):
            if (line_idx, i) in station_id_map:
                st_id = station_id_map[(line_idx, i)]
                line_stations.append({'id': st_id, 'raw_idx': i})
        
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
            if key not in edge_details: edge_details[key] = {}
            edge_details[key][line_name] = {'points': segment_points, 'weight': dist, 'line_name': line_name}

    return G, edge_details, station_coords, all_line_names, line_stations_dict

def find_optimal_route(G, dept_st, dest_st, via_st, avoid_lines, prioritize_lines, avoid_revisit=False):
    """
    経路探索を行う関数
    avoid_revisit=Trueの場合、往路(Start->Via)で使用した区間に対し、復路(Via->End)で超高コストを課す
    """
    G_calc = G.copy()
    
    # コスト調整
    for u, v, k, d in G_calc.edges(keys=True, data=True):
        l_name = d.get('line_name', '')
        base_weight = d['weight']
        if l_name in avoid_lines:
            d['weight'] = base_weight * 10.0
        elif l_name in prioritize_lines:
            d['weight'] = base_weight * 0.2
        else:
            d['weight'] = base_weight
    
    try:
        if via_st:
            # 往路
            p1 = nx.shortest_path(G_calc, source=dept_st, target=via_st, weight='weight')
            
            if avoid_revisit:
                # 復路計算前に往路のコストを上げる
                for i in range(len(p1) - 1):
                    u_node = p1[i]
                    v_node = p1[i+1]
                    if G_calc.has_edge(u_node, v_node):
                        for key in G_calc[u_node][v_node]:
                            G_calc[u_node][v_node][key]['weight'] *= 10000.0
            
            # 復路
            p2 = nx.shortest_path(G_calc, source=via_st, target=dest_st, weight='weight')
            return p1 + p2[1:]
        else:
            # 直行
            return nx.shortest_path(G_calc, source=dept_st, target=dest_st, weight='weight')
            
    except nx.NetworkXNoPath:
        return None

# ==========================================
# 3. シミュレーションクラス
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

# ==========================================
# 4. 地図描画・ユーティリティ
# ==========================================
def create_route_map(route_points_list, route_nodes, station_coords, dept_st, dest_st, via_st):
    if not route_points_list: return None
    
    all_lats = [p[0] for segment in route_points_list for p in segment]
    all_lons = [p[1] for segment in route_points_list for p in segment]
    if not all_lats: return None
            
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10)
    
    for segment in route_points_list:
        folium.PolyLine(locations=segment, color="blue", weight=5, opacity=0.7).add_to(m)
        
    for node in route_nodes:
        coord = station_coords.get(node)
        if not coord: continue
        
        icon_color = "blue"
        icon_type = "info-sign"
        if node == dept_st: icon_color, icon_type = "green", "play"
        elif node == dest_st: icon_color, icon_type = "red", "stop"
        elif node == via_st: icon_color, icon_type = "orange", "flag"
        else:
            folium.CircleMarker(location=coord, radius=4, color="blue", fill=True, fill_color="white", tooltip=node).add_to(m)
            continue
        folium.Marker(location=coord, popup=node, tooltip=node, icon=folium.Icon(color=icon_color, icon=icon_type)).add_to(m)
    return m

def format_time(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}分{int(s):02d}秒"

def sanitize_filename(name):
    return re.sub(r'[\\/:*?"<>|]+', '_', name)
