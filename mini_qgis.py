import streamlit as st
import pydeck as pdk
import geopandas as gpd
import os
import json
from shapely import force_2d
from shapely.geometry import Point

st.set_page_config(page_title="QGIS Python - BDOT10k", layout="wide")

# -----------------------------------------------------------------------------
# 1. KONFIGURACJA WARSTW (Zgodnie z nazewnictwem z zadania)
# -----------------------------------------------------------------------------
FOLDER_BAZOWY = "C:\\Users\\Maks\\Documents\\geo_oblicz\\PL.PZGiK.330.1408\\BDOT10k"

# Dodaj tutaj nazwy plików ze swojego powiatu (zwróć uwagę na _A, _L, _P)
KONFIGURACJA = {
    "Budynki (BUBD_A)": {
        "plik": "PL.PZGiK.330.1408__OT_BUBD_A.xml",
        "typ": "poligon",
        "wypelnienie": [120, 144, 156, 200], 
        "linia": [33, 33, 33, 255]
    },
    "Jezdnie Dróg (SKDR_L)": {
        "plik": "PL.PZGiK.330.1408__OT_SKDR_L.xml",
        "typ": "linia",
        "wypelnienie": [0, 0, 0, 0], 
        "linia": [211, 47, 47, 255]  
    },
    "Inne Obiekty (OIKM_P)": {
        "plik": "PL.PZGiK.330.1408__OT_OIKM_P.xml",
        "typ": "punkt",
        "wypelnienie": [46, 125, 50, 255], 
        "linia": [0, 0, 0, 0]
    }
}

# -----------------------------------------------------------------------------
# 2. WCZYTYWANIE DANYCH W UKŁADZIE ORYGINALNYM (EPSG:2180)
# -----------------------------------------------------------------------------
@st.cache_data
def wczytaj_gml_cache(sciezka_pliku):
    """
    Wczytuje surowe dane GML. Zatrzymuje je w układzie PL-1992 (EPSG:2180),
    aby można było korzystać z indeksowania przestrzennego w metrach!
    """
    if not sciezka_pliku or not os.path.exists(sciezka_pliku):
        return None
    try:
        gdf = gpd.read_file(sciezka_pliku)
        if gdf.empty: return None
        
        # Geoportal domyślnie podaje EPSG:2180 (X-północna, Y-wschodnia)
        if gdf.crs is None: 
            gdf.set_crs(epsg=2180, inplace=True)

        # Usunięcie pustych obiektów i geometrii 3D (Wymóg bibliotek webowych)
        gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
        gdf['geometry'] = force_2d(gdf['geometry'])
        
        # Obsługa topologii (wieloczęściowe poligony, otwory z gml:interior)
        maska = gdf.geom_type.isin(['Polygon', 'MultiPolygon'])
        if maska.any():
            gdf.loc[maska, 'geometry'] = gdf.loc[maska, 'geometry'].buffer(0)
            
        # Zamiana danych opisowych na tekst (wymóg konwersji do JSON)
        for kolumna in gdf.columns:
            if kolumna != 'geometry':
                gdf[kolumna] = gdf[kolumna].astype(str)
                
        # ZWRACAMY DANE W PL-1992 (EPSG:2180) - Gotowe do użycia indeksu!
        return gdf
    except Exception as e:
        return None

# -----------------------------------------------------------------------------
# 3. GŁÓWNA LOGIKA PROGRAMU I INDEKS PRZESTRZENNY
# -----------------------------------------------------------------------------
def main():
    st.title("🗺️ BDOT10k - Wariant Rozszerzony (Indeks Przestrzenny)")

    # --- PANEL BOCZNY: WARIANT ROZSZERZONY ---
    st.sidebar.header("👁️ Wybór Warstw")
    aktywne_warstwy = {}
    for nazwa in KONFIGURACJA.keys():
        # Domyślnie ładujemy na start budynki i drogi
        aktywne_warstwy[nazwa] = st.sidebar.checkbox(nazwa, value=True if "BUBD" in nazwa or "SKDR" in nazwa else False)

    st.sidebar.markdown("---")
    st.sidebar.header("🔍 Indeksowanie Przestrzenne")
    st.sidebar.write("Optymalizacja dla skali całego powiatu.")
    
    # Przełącznik i suwak do sterowania R-Tree
    uzyj_indeksu = st.sidebar.checkbox("Użyj R-Tree (Wytnij obszar)", value=True)
    promien_km = st.sidebar.slider("Promień obszaru roboczego (km)", 1, 20, 3)

    st.sidebar.markdown("---")
    tryb_3d = st.sidebar.checkbox("Włącz budynki 3D", value=False)
    wysokosc_3d = st.sidebar.slider("Wysokość", 5, 50, 15) if tryb_3d else 0

    warstwy_mapy = []
    wczytane_geometrie_wgs84 = []

    # --- PRZETWARZANIE DANYCH Z INDEKSEM PRZESTRZENNYM ---
    with st.spinner("Przetwarzanie duży zbiorów BDOT10k..."):
        
        # Krok 1: Wczytujemy wszystkie aktywne dane (z pamięci podręcznej) do słownika
        slownik_gdf = {}
        for nazwa, parametry in KONFIGURACJA.items():
            if aktywne_warstwy[nazwa]:
                sciezka = os.path.join(FOLDER_BAZOWY, parametry["plik"])
                gdf = wczytaj_gml_cache(sciezka)
                if gdf is not None and not gdf.empty:
                    slownik_gdf[nazwa] = gdf

        # Krok 2: Użycie indeksu przestrzennego (Wariant Rozszerzony)
        if slownik_gdf:
            # Ustawiamy środek obszaru poszukiwań na podstawie pierwszej warstwy
            pierwsza_warstwa = list(slownik_gdf.values())[0]
            srodek_y_2180 = pierwsza_warstwa.geometry.centroid.y.mean()
            srodek_x_2180 = pierwsza_warstwa.geometry.centroid.x.mean()
            
            # Tworzymy geometrię bufora (obszar poszukiwań w metrach!)
            punkt_srodkowy = Point(srodek_x_2180, srodek_y_2180)
            obszar_roboczy = punkt_srodkowy.buffer(promien_km * 1000)
            bbox_obszaru = obszar_roboczy.bounds # (minx, miny, maxx, maxy)

            # Aplikowanie indeksu do warstw
            for nazwa, gdf in slownik_gdf.items():
                if uzyj_indeksu:
                    # TUTEJ DZIEJE SIĘ MAGIA INDEKSU R-TREE:
                    # Funkcja .sindex.intersection sprawdza przecięcie bounding boxów w ułamku sekundy
                    indeksy_z_drzewa = list(gdf.sindex.intersection(bbox_obszaru))
                    gdf_filtrowane = gdf.iloc[indeksy_z_drzewa].copy()
                    
                    st.sidebar.write(f"✅ {nazwa}: **{len(gdf_filtrowane)}** / {len(gdf)} ob.")
                else:
                    gdf_filtrowane = gdf.copy()
                    st.sidebar.write(f"⚠️ {nazwa}: **{len(gdf)}** obiektów (Brak R-Tree!)")

                # Krok 3: Dopiero ten mniejszy, przefiltrowany obszar konwertujemy do WGS84
                # dla przeglądarki (oszczędzamy ogromne ilości pamięci)
                if not gdf_filtrowane.empty:
                    gdf_wgs84 = gdf_filtrowane.to_crs(epsg=4326)
                    wczytane_geometrie_wgs84.append(gdf_wgs84)
                    
                    parametry = KONFIGURACJA[nazwa]
                    warstwa = pdk.Layer(
                        "GeoJsonLayer",
                        json.loads(gdf_wgs84.to_json()), 
                        pickable=True,
                        stroked=True,
                        filled=True,
                        extruded=(tryb_3d if parametry["typ"] == "poligon" else False),
                        get_elevation=wysokosc_3d,
                        get_fill_color=parametry["wypelnienie"],
                        get_line_color=parametry["linia"],
                        get_line_width=3 if parametry["typ"] == "linia" else 1.5,
                        get_point_radius=6,
                        point_radius_min_pixels=4
                    )
                    warstwy_mapy.append(warstwa)

    # --- CENTROWANIE MAPY (Na podstawie danych przefiltrowanych) ---
    srodek_lat, srodek_lon = 52.0, 19.0 
    if wczytane_geometrie_wgs84:
        srodek_lat = wczytane_geometrie_wgs84[0].geometry.centroid.y.mean()
        srodek_lon = wczytane_geometrie_wgs84[0].geometry.centroid.x.mean()

    # --- RENDEROWANIE INTERFEJSU (Przesuwanie, powiększanie) ---
    deck_mapa = pdk.Deck(
        layers=warstwy_mapy,
        initial_view_state=pdk.ViewState(
            latitude=srodek_lat, longitude=srodek_lon, zoom=14, pitch=45 if tryb_3d else 0
        ),
        map_style="light",
        tooltip={"text": "Element z bazy BDOT10k"}
    )

    st.pydeck_chart(deck_mapa, use_container_width=True)

if __name__ == "__main__":
    main()