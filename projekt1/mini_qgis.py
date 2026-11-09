import streamlit as st
import pydeck as pdk
import geopandas as gpd
import os
from shapely import force_2d  # Biblioteka do spłaszczania geometrii 3D

# -----------------------------------------------------------------------------
# 1. KONFIGURACJA STRONY APLIKACJI
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Mini QGIS - BDOT10k", layout="wide")

# Domyślne nazwy plików z paczki BDOT10k (możesz je zmienić w panelu aplikacji)
# Używamy rozszerzenia .xml, ponieważ w takim formacie często pobierają się dane GML.
DEFAULT_POLIGONY = "PL.PZGiK.330.1408\\BDOT10k\\PL.PZGiK.330.1408__OT_ADMS_P.xml" # Budynki (Poligony)
DEFAULT_LINIE = "PL.PZGiK.330.1408\\BDOT10k\\PL.PZGiK.330.1408__OT_SKDR_L.xml" # Drogi (Linie)
DEFAULT_PUNKTY  = "PL.PZGiK.330.1408\\BDOT10k\\PL.PZGiK.330.1408__OT_OIKM_P.xml" # Obiekty użyteczności (Punkty)

# -----------------------------------------------------------------------------
# 2. FUNKCJA WCZYTUJĄCA I PRZETWARZAJĄCA DANE GML/XML
# -----------------------------------------------------------------------------
@st.cache_data
def wczytaj_gml(sciezka_pliku):
    """
    Wczytuje plik wektorowy, usuwa geometrię 3D (Z) i przelicza na układ WGS84.
    """
    if not sciezka_pliku or not os.path.exists(sciezka_pliku):
        return None
    
    try:
        gdf = gpd.read_file(sciezka_pliku)
        if gdf.empty:
            return None
            
        # Zabezpieczenie przed brakiem definicji układu (BDOT10k to PUWG 1992)
        if gdf.crs is None:
            gdf.set_crs(epsg=2180, inplace=True)

        # Usunięcie pustych geometrii (błędy w danych)
        gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
        
        # KLUCZOWA POPRAWKA: Spłaszczenie geometrii 3D (Z) do 2D (X, Y) 
        # Bez tego PyDeck nie wyrenderuje budynków poprawnie!
        gdf['geometry'] = force_2d(gdf['geometry'])
            
        # Transformacja do układu mapy internetowej (WGS84)
        return gdf.to_crs(epsg=4326)
    except Exception as e:
        st.error(f"Błąd odczytu pliku '{sciezka_pliku}': {e}")
        return None

# -----------------------------------------------------------------------------
# 3. GŁÓWNA LOGIKA APLIKACJI
# -----------------------------------------------------------------------------
def main():
    st.title("🌍 Mini QGIS - Przeglądarka Danych BDOT10k")
    st.markdown("Wizualizacja danych wektorowych z Geoportalu. Obsługa geometrii spłaszczonej 2D.")

    # --- PANEL BOCZNY: Ścieżki do plików ---
    st.sidebar.header("📁 Pliki źródłowe (.xml / .gml)")
    st.sidebar.caption("Podaj nazwy plików (jeśli są w folderze z programem):")
    
    path_poligony = st.sidebar.text_input("Budynki (Poligony - _A)", value=DEFAULT_POLIGONY)
    path_linie = st.sidebar.text_input("Drogi (Linie - _L)", value=DEFAULT_LINIE)
    path_punkty = st.sidebar.text_input("Punkty (Obiekty - _P)", value=DEFAULT_PUNKTY)

    # --- PANEL BOCZNY: Drzewo warstw ---
    st.sidebar.markdown("---")
    st.sidebar.header("👁️ Drzewo Warstw")
    pokaz_poligony = st.sidebar.checkbox("🟦 Budynki (Poligony)", value=True)
    pokaz_linie = st.sidebar.checkbox("🟥 Drogi (Linie)", value=True)
    pokaz_punkty = st.sidebar.checkbox("🟢 Punkty", value=True)

    # --- PANEL BOCZNY: Ustawienia widoku ---
    st.sidebar.markdown("---")
    st.sidebar.header("⚙️ Stylizacja i Widok")
    tryb_3d = st.sidebar.checkbox("Włącz budynki 3D", value=False)
    wysokosc_3d = st.sidebar.slider("Wysokość budynków", 5, 50, 15) if tryb_3d else 0

    # --- WCZYTYWANIE WARSTW ---
    with st.spinner("Przetwarzanie plików przestrzennych..."):
        gdf_poligony = wczytaj_gml(path_poligony) if pokaz_poligony else None
        gdf_linie = wczytaj_gml(path_linie) if pokaz_linie else None
        gdf_punkty = wczytaj_gml(path_punkty) if pokaz_punkty else None

    # --- PANEL BOCZNY: Statystyki obiektów ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("📊 Wczytane obiekty:")
    st.sidebar.write(f"Budynki: **{len(gdf_poligony) if gdf_poligony is not None else 0}**")
    st.sidebar.write(f"Drogi: **{len(gdf_linie) if gdf_linie is not None else 0}**")
    st.sidebar.write(f"Punkty: **{len(gdf_punkty) if gdf_punkty is not None else 0}**")

    # Weryfikacja brakujących plików
    brakujace = []
    if pokaz_poligony and path_poligony and gdf_poligony is None: brakujace.append(path_poligony)
    if pokaz_linie and path_linie and gdf_linie is None: brakujace.append(path_linie)
    if pokaz_punkty and path_punkty and gdf_punkty is None: brakujace.append(path_punkty)

    if brakujace:
        st.warning(f"⚠️ Nie udało się wczytać: `{', '.join(brakujace)}`. Sprawdź nazwę pliku.")

    # --- BUDOWANIE WARSTW MAPY ---
    warstwy_mapy = []

    # 1. WARSTWA POLIGONÓW (np. Budynki)
    if gdf_poligony is not None and not gdf_poligony.empty:
        warstwy_mapy.append(
            pdk.Layer(
                "GeoJsonLayer",
                gdf_poligony,
                pickable=True,
                stroked=True,
                filled=True,
                extruded=tryb_3d,
                get_elevation=wysokosc_3d,
                get_fill_color=[120, 144, 156, 200],  # Szaroniebieski
                get_line_color=[33, 33, 33, 255],     # Ciemna obwódka
                get_line_width=1.5,
            )
        )

    # 2. WARSTWA LINII (np. Drogi)
    if gdf_linie is not None and not gdf_linie.empty:
        warstwy_mapy.append(
            pdk.Layer(
                "GeoJsonLayer",
                gdf_linie,
                pickable=True,
                get_line_color=[211, 47, 47, 255],    # Czerwony
                get_line_width=3,
            )
        )

    # 3. WARSTWA PUNKTÓW (np. Obiekty)
    if gdf_punkty is not None and not gdf_punkty.empty:
        warstwy_mapy.append(
            pdk.Layer(
                "GeoJsonLayer",
                gdf_punkty,
                pickable=True,
                get_fill_color=[46, 125, 50, 255],    # Zielony
                get_point_radius=6,
                point_radius_min_pixels=4,
            )
        )

    # --- CENTROWANIE ORAZ NAWIGACJA MAPY ---
    srodek_lat, srodek_lon = 52.0, 19.0  # Środek Polski (awaryjny)
    
    # Automatyczne szukanie środka miejscowości na podstawie wczytanych danych
    dane_do_centrowania = next((g for g in [gdf_poligony, gdf_linie, gdf_punkty] if g is not None and not g.empty), None)
    if dane_do_centrowania is not None:
        srodek_lat = dane_do_centrowania.geometry.centroid.y.mean()
        srodek_lon = dane_do_centrowania.geometry.centroid.x.mean()

    widok_poczatkowy = pdk.ViewState(
        latitude=srodek_lat,
        longitude=srodek_lon,
        zoom=15,
        pitch=45 if tryb_3d else 0,
        bearing=0
    )

    # --- RENDEROWANIE Z SILNIKIEM WEBGL ---
    deck_mapa = pdk.Deck(
        layers=warstwy_mapy,
        initial_view_state=widok_poczatkowy,
        map_style="light", # Możesz zmienić na "road" lub "satellite"
        tooltip={"text": "Geometria załadowana poprawnie"}
    )

    st.pydeck_chart(deck_mapa, use_container_width=True)

if __name__ == "__main__":
    main()