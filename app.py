# app.py
import streamlit as st
import json
import pandas as pd
from streamlit_folium import st_folium
from io import BytesIO

# モジュール読み込み
import config
import core_logic

# ページ設定
st.set_page_config(page_title="架空鉄道 所要時間シミュレータ", page_icon="🚆", layout="wide")

# ==========================================
# UIコンポーネント: 駅選択
# ==========================================
def station_selector_widget(label, all_stations, line_stations_dict, all_lines, key_prefix, default_idx=0):
    st.markdown(f"#### {label}")
    mode = st.radio(f"{label}の選択方法", ["路線から絞り込み", "全駅から検索"], horizontal=True, key=f"{key_prefix}_mode", label_visibility="collapsed")
    
    if mode == "路線から絞り込み":
        c1, c2 = st.columns(2)
        with c1:
            line = st.selectbox(f"{label}: 路線", all_lines, key=f"{key_prefix}_line")
        with c2:
            stations = line_stations_dict[line]
            idx = 0
            if default_idx == -1: idx = len(stations) - 1
            if idx >= len(stations): idx = 0
            return st.selectbox(f"{label}: 駅", stations, index=idx, key=f"{key_prefix}_st_sub")
    else:
        idx = default_idx
        if idx == -1: idx = len(all_stations) - 1
        if idx >= len(all_stations): idx = 0
        return st.selectbox(f"{label}: 駅名", all_stations, index=idx, key=f"{key_prefix}_st_all")

# ==========================================
# サイドバー (情報・規約)
# ==========================================
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
        入力された作品データは、ブラウザ上および一時的なメモリ内でのみ処理されます。サーバーへの保存は行いません。
        **3. 免責**
        計算結果の正確性は保証されません。本ツールを使用したことによる損害について責任を負いません。
        **4. 地図データ出典**
        Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors
        """)

# ==========================================
# メイン画面
# ==========================================
st.title("架空鉄道 所要時間シミュレータ")
st.markdown("空想鉄道シリーズの作品データを解析し、直通運転や所要時間シミュレーションを行います。")

# ブックマークレット解説
with st.expander("作品データの自動取得ブックマークレット (使い方)", expanded=False):
    st.markdown("ブラウザのブックマーク機能を利用して、空想鉄道の作品ページからデータを簡単にコピーできます。")
    st.markdown("#### 登録手順")
    st.markdown("以下のコードをブックマークのURL欄に保存してください。")
    bookmarklet_code = r"""javascript:(function(){const match=location.pathname.match(/\/([^\/]+)\.html/);if(!match){alert('エラー：作品IDが見つかりません。\n作品ページ(ID.html)で実行してください。');return;}const mapId=match[1];const formData=new FormData();formData.append('exec','selectIndex');formData.append('mapno',mapId);formData.append('time',Date.now());fetch('/_Ajax.php',{method:'POST',body:formData}).then(response=>response.text()).then(text=>{if(text.length<50){alert('データ取得に失敗した可能性があります。\n中身: '+text);}else{navigator.clipboard.writeText(text).then(()=>{alert('【成功】作品データをコピーしました！\nID: '+mapId+'\n文字数: '+text.length+'\n\nシミュレータに戻って「Ctrl+V」で貼り付けてください。');}).catch(err=>{window.prompt("自動コピーに失敗しました。Ctrl+Cで以下をコピーしてください:",text);});}}).catch(err=>{alert('通信エラーが発生しました: '+err);});})();"""
    st.code(bookmarklet_code, language="javascript")

st.divider()

# データ入力
st.subheader("データの入力")
raw_text = st.text_area("作品データを貼り付けてください (Ctrl+V)", height=150, placeholder='{"mapinfo": ... }')

if raw_text:
    try:
        try: data = json.loads(raw_text)
        except: 
            idx = raw_text.find('{')
            if idx != -1: data = json.loads(raw_text[idx:])
            else: st.stop()
        
        if isinstance(data.get('mapdata'), str): map_data = json.loads(data['mapdata'])
        else: map_data = data
        
        # ネットワーク構築 (Core Logic呼び出し)
        G, edge_details, station_coords, all_line_names, line_stations_dict = core_logic.build_network(map_data)
        all_stations_list = sorted(list(G.nodes()))
        
        st.success(f"解析完了: {len(all_stations_list)}駅 / {len(all_line_names)}路線")
        
        # 運転プラン
        st.subheader("運転プラン")
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown("#### ルート選択")
            dept_st = station_selector_widget("出発駅", all_stations_list, line_stations_dict, all_line_names, "dept", 0)
            
            with st.expander("路線ごとの優先度設定", expanded=False):
                avoid_lines = st.multiselect("避ける (コスト増)", all_line_names)
                prioritize_lines = st.multiselect("優先する (コスト減)", all_line_names)

            dest_st = station_selector_widget("到着駅", all_stations_list, line_stations_dict, all_line_names, "dest", -1)
            
            use_via = st.checkbox("経由駅を指定", value=False)
            via_st = None
            if use_via:
                via_st = station_selector_widget("経由駅", all_stations_list, line_stations_dict, all_line_names, "via", 0)

            # 経路計算
            full_route_nodes = core_logic.find_optimal_route(G, dept_st, dest_st, via_st, avoid_lines, prioritize_lines)
            
            if not full_route_nodes:
                st.error("経路が見つかりません。")
                st.stop()
            
            # 経路情報の復元と地図データの準備
            actual_dist = 0
            used_lines_list = []
            map_geometry_list = []
            
            for i in range(len(full_route_nodes)-1):
                u, v = full_route_nodes[i], full_route_nodes[i+1]
                key = tuple(sorted((u, v)))
                candidates = edge_details.get(key, {})
                
                # 最適路線の選定 (優先度考慮)
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
                    # 経由路線の記録 (連続重複排除)
                    if not used_lines_list or used_lines_list[-1] != best_line:
                        used_lines_list.append(best_line)
                    
                    actual_dist += candidates[best_line]['weight']
                    pts = candidates[best_line]['points']
                    
                    # 向き判定
                    u_c = station_coords[u]
                    d_start = core_logic.hubeny_distance(pts[0][0], pts[0][1], u_c[0], u_c[1])
                    d_end = core_logic.hubeny_distance(pts[-1][0], pts[-1][1], u_c[0], u_c[1])
                    if d_end < d_start: map_geometry_list.append(pts[::-1])
                    else: map_geometry_list.append(pts)

            st.info(f"ルート確定: {len(full_route_nodes)}駅 (実距離 約{actual_dist/1000:.1f}km)")
            st.caption(f"経由路線: {', '.join(used_lines_list)}")

            # 地図表示
            st.markdown("#### ルートマップ")
            map_obj = core_logic.create_route_map(map_geometry_list, full_route_nodes, station_coords, dept_st, dest_st, via_st)
            st_folium(map_obj, height=600, use_container_width=True)

            # 停車駅設定
            st.markdown("#### 停車パターン")
            c_btn1, c_btn2 = st.columns(2)
            if c_btn1.button("全選択"):
                for i, s in enumerate(full_route_nodes): st.session_state[f"chk_{i}_{s}"] = True
            if c_btn2.button("全解除"):
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
            vehicle_name = st.selectbox("使用車両", list(config.VEHICLE_DB.keys()))
            spec = config.VEHICLE_DB[vehicle_name]
            st.info(f"性能: {spec['desc']}")
            
            train_type = st.text_input("種別名", value="普通")
            dwell_time = st.slider("停車時間(秒)", 0, 120, 20)

        # 実行
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
                    s_start = full_route_nodes[idx_start]
                    s_end = full_route_nodes[idx_end]
                    
                    # 区間結合
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
                        
                        if best_line:
                            pts = candidates[best_line]['points']
                            u_c = station_coords[u]
                            d_s = core_logic.hubeny_distance(pts[0][0], pts[0][1], u_c[0], u_c[1])
                            d_e = core_logic.hubeny_distance(pts[-1][0], pts[-1][1], u_c[0], u_c[1])
                            if d_e < d_s: pts = pts[::-1]
                            
                            if combined_points: combined_points.extend(pts[1:])
                            else: combined_points.extend(pts)
                    
                    # 物理シミュレーション
                    track = core_logic.resample_and_analyze(combined_points, spec)
                    if track:
                        sim = core_logic.TrainSim(track, spec)
                        run_sec = sim.run()
                        cur_dwell = 0 if (i == len(selected_indices) - 2) else dwell_time
                        total_leg = run_sec + cur_dwell
                        dist_km = track[-1]['dist'] / 1000.0
                        
                        results.append({
                            '出発': s_start, '到着': s_end,
                            '距離(km)': round(dist_km, 2),
                            '走行時間': core_logic.format_time(run_sec),
                            '停車時間': f"{cur_dwell}秒",
                            '計': core_logic.format_time(total_leg),
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
                        '走行時間': core_logic.format_time(sum_run),
                        '停車時間': core_logic.format_time(sum_dwell),
                        '計': core_logic.format_time(total_all)
                    }])
                    
                    df_disp = pd.concat([df, sum_row], ignore_index=True)
                    df_disp = df_disp[['出発', '到着', '距離(km)', '走行時間', '停車時間', '計']]
                    
                    st.dataframe(df_disp, use_container_width=True)
                    
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df_disp.to_excel(writer, sheet_name=core_logic.sanitize_filename(train_type), index=False)
                    
                    st.download_button(
                        "Excelファイルをダウンロード",
                        data=output.getvalue(),
                        file_name=f"解析_{core_logic.sanitize_filename(dept_st)}-{core_logic.sanitize_filename(dest_st)}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

    except Exception as e:
        st.error(f"エラー: {e}")
