import streamlit as st
import pydeck as pdk
import geopandas as gpd
import os
import json
from shapely import force_2d

st.set_page_config(page_title="Mini QGIS - BDOT10k", layout="wide")

# -----------------------------------------------------------------------------
# 1. KONFIGURACJA WARSTW (TUTAJ DODAJESZ NOWE PLIKI!)
# -----------------------------------------------------------------------------
# Definiujemy główny folder, żeby nie powtarzać długiej ścieżki:
FOLDER_BAZOWY = "C:\\Users\\Maks\\Documents\\geo_oblicz\\PL.PZGiK.330.1408\\BDOT10k"

# Słownik wszystkich warstw. 
# Jeśli pobierzesz nowy plik (np. rzeki), po prostu dodajesz go tutaj!
KONFIGURACJA = {
    "Budynki": {
        "plik": "PL.PZGiK.330.1408__OT_BUBD_A.xml",
        "typ": "poligon",
        "wypelnienie": [120, 144, 156, 200], # Szaroniebieski
        "linia": [33, 33, 33, 255]
    },
    "Drogi": {
        "plik": "PL.PZGiK.330.1408__OT_SKDR_L.xml",
        "typ": "linia",
        "wypelnienie": [0, 0, 0, 0], # Linie nie mają wypełnienia
        "linia": [211, 47, 47, 255]  # Czerwony
    },
    "Obiekty Komunikacyjne": {
        "plik": "PL.PZGiK.330.1408__OT_OIKM_P.xml",
        "typ": "punkt",
        "wypelnienie": [46, 125, 50, 255], # Zielony
        "linia": [0, 0, 0, 0]
    },
    "Lasy": {
        "plik": "PL.PZGiK.330.1408__OT_PTWZ_A.xml",
        "typ": "poligon",
        "wypelnienie": [34, 139, 34, 150], # Kolor zielony leśny
        "linia": [0, 0, 0, 0]
    },
    "Rzeki": {
        "plik": "PL.PZGiK.330.1408__OT_SWRS_L.xml",
        "typ": "linia",
        "wypelnienie": [0, 0, 0, 0],
        "linia": [0, 100, 255, 255] # Kolor niebieski
    }
}

# -----------------------------------------------------------------------------
# 2. FUNKCJA WCZYTUJĄCA (Bez zmian - działa idealnie)
# -----------------------------------------------------------------------------
@st.cache_data
def wczytaj_gml(sciezka_pliku):
    if not sciezka_pliku or not os.path.exists(sciezka_pliku):
        return None
    try:
        gdf = gpd.read_file(sciezka_pliku)
        if gdf.empty: return None
        if gdf.crs is None: gdf.set_crs(epsg=2180, inplace=True)

        gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
        gdf['geometry'] = force_2d(gdf['geometry'])
        
        maska = gdf.geom_type.isin(['Polygon', 'MultiPolygon'])
        if maska.any():
            gdf.loc[maska, 'geometry'] = gdf.loc[maska, 'geometry'].buffer(0)
            
        for kolumna in gdf.columns:
            if kolumna != 'geometry':
                gdf[kolumna] = gdf[kolumna].astype(str)
                
        return gdf.to_crs(epsg=4326)
    except Exception as e:
        return None

# -----------------------------------------------------------------------------
# 3. GŁÓWNA LOGIKA
# -----------------------------------------------------------------------------
def main():
    st.title("🌍 Mini QGIS - Elastyczna Przeglądarka BDOT10k")

    # --- PANEL BOCZNY ---
    st.sidebar.header("👁️ Drzewo Warstw")
    
    # Automatyczne tworzenie przycisków na podstawie słownika!
    aktywne_warstwy = {}
    for nazwa in KONFIGURACJA.keys():
        aktywne_warstwy[nazwa] = st.sidebar.checkbox(nazwa, value=True)

    st.sidebar.markdown("---")
    tryb_3d = st.sidebar.checkbox("Włącz budynki 3D", value=False)
    wysokosc_3d = st.sidebar.slider("Wysokość", 5, 50, 15) if tryb_3d else 0

    warstwy_mapy = []
    wczytane_geometrie = [] # Zbieramy wszystko, żeby na końcu wyliczyć środek mapy

    # --- AUTOMATYCZNE PRZETWARZANIE W PĘTLI ---
    with st.spinner("Przetwarzanie danych..."):
        for nazwa, parametry in KONFIGURACJA.items():
            if aktywne_warstwy[nazwa]:
                pelna_sciezka = os.path.join(FOLDER_BAZOWY, parametry["plik"])
                gdf = wczytaj_gml(pelna_sciezka)
                
                if gdf is not None and not gdf.empty:
                    st.sidebar.write(f"✅ {nazwa}: **{len(gdf)}** obiektów")
                    wczytane_geometrie.append(gdf)
                    
                    # Uniwersalna definicja warstwy PyDeck
                    warstwa = pdk.Layer(
                        "GeoJsonLayer",
                        json.loads(gdf.to_json()), 
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
                else:
                    st.sidebar.write(f"❌ {nazwa}: Brak pliku lub pusty")

    # --- CENTROWANIE MAPY ---
    srodek_lat, srodek_lon = 52.0, 19.0 
    if wczytane_geometrie:
        # Bierzemy pierwszą załadowaną warstwę, żeby wyśrodkować na niej kamerę
        srodek_lat = wczytane_geometrie[0].geometry.centroid.y.mean()
        srodek_lon = wczytane_geometrie[0].geometry.centroid.x.mean()

    # --- RENDEROWANIE ---
    deck_mapa = pdk.Deck(
        layers=warstwy_mapy,
        initial_view_state=pdk.ViewState(
            latitude=srodek_lat, longitude=srodek_lon, zoom=15, pitch=45 if tryb_3d else 0
        ),
        map_style="light",
        tooltip={"text": "Nazwa warstwy (sprawdź konsolę GIS)"}
    )

    st.pydeck_chart(deck_mapa, use_container_width=True)

if __name__ == "__main__":
    main()