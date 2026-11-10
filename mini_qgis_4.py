import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox
import os
import time

# ==========================================
# 1. STRUKTURA DANYCH I INDEKS PRZESTRZENNY
# ==========================================

class SpatialGrid:
    def __init__(self, cell_size=1000):
        # Rozmiar komórki w metrach (dla układu PL-1992)
        self.cell_size = cell_size
        self.cells = {}       # Mapa: (col, row) -> lista ID obiektów
        self.features = {}    # Mapa: id_obiektu -> słownik z danymi obiektu

    def add_feature(self, feature):
        f_id = feature['id']
        self.features[f_id] = feature
        min_x, max_x, min_y, max_y = feature['bbox']
        
        # Wyznaczamy zakres komórek siatki, które przecina Bounding Box obiektu
        start_col = int(min_x // self.cell_size)
        end_col = int(max_x // self.cell_size)
        start_row = int(min_y // self.cell_size)
        end_row = int(max_y // self.cell_size)
        
        for col in range(start_col, end_col + 1):
            for row in range(start_row, end_row + 1):
                cell_id = (col, row)
                if cell_id not in self.cells:
                    self.cells[cell_id] = []
                self.cells[cell_id].append(f_id)

    def get_features_in_view(self, v_min_x, v_max_x, v_min_y, v_max_y):
        start_col = int(v_min_x // self.cell_size)
        end_col = int(v_max_x // self.cell_size)
        start_row = int(v_min_y // self.cell_size)
        end_row = int(v_max_y // self.cell_size)
        
        visible = set()
        # Przeszukujemy tylko komórki widoczne na ekranie
        for col in range(start_col, end_col + 1):
            for row in range(start_row, end_row + 1):
                cell_id = (col, row)
                if cell_id in self.cells:
                    for f_id in self.cells[cell_id]:
                        if f_id in visible: 
                            continue
                        f = self.features[f_id]
                        f_min_x, f_max_x, f_min_y, f_max_y = f['bbox']
                        
                        # Test przecięcia Bounding Boxów (4 szybkie porównania z instrukcji)
                        if not (f_max_x < v_min_x or f_min_x > v_max_x or 
                                f_max_y < v_min_y or f_min_y > v_max_y):
                            visible.add(f_id)
                            
        return [self.features[f_id] for f_id in visible]

    def get_global_bbox(self):
        if not self.features:
            return (0, 100, 0, 100)
        # Obliczanie BBOX dla całego wczytanego powiatu (do początkowego wycentrowania)
        min_x = min(f['bbox'][0] for f in self.features.values())
        max_x = max(f['bbox'][1] for f in self.features.values())
        min_y = min(f['bbox'][2] for f in self.features.values())
        max_y = max(f['bbox'][3] for f in self.features.values())
        return min_x, max_x, min_y, max_y


# ==========================================
# 2. WŁASNY PARSER STRUMIENIOWY GML
# ==========================================

def parse_bdot_folder(folder_path, grid):
    feature_id = 0
    
    # Słownik przypisujący styl rysowania na podstawie nazwy pliku
    # 'polygon' (wypełnienie), 'line' (tylko obrys), 'point' (kropka)
    styles = {
        'BUBD': {'color': '#a9a9a9', 'type': 'polygon'}, # Budynki - szare
        'PTLZ': {'color': '#2ca25f', 'type': 'polygon'}, # Lasy - zielone
        'SKDR': {'color': '#000000', 'type': 'line'},    # Drogi - czarne
        'SWRS': {'color': '#2b8cbe', 'type': 'line'},    # Rzeki - niebieskie
        'OIPR': {'color': '#e34a33', 'type': 'point'}    # Punkty (np. pomniki) - czerwone
    }

    gml_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.gml')]
    
    for filename in gml_files:
        filepath = os.path.join(folder_path, filename)
        
        # Ustalanie stylu na podstawie nazwy pliku BDOT
        style = {'color': '#888888', 'type': 'line'} # Domyślny
        for key, s in styles.items():
            if key in filename.upper():
                style = s
                break
                
        print(f"Wczytywanie {filename}...")
        
        # Iterparse zapobiega wczytaniu całego XML do RAMu
        context = ET.iterparse(filepath, events=('end',))
        for event, elem in context:
            tag = elem.tag.split('}')[-1] # Ignorujemy przestrzenie nazw (namespaces)
            
            if tag in ('posList', 'pos'):
                raw_coords = list(map(float, elem.text.split()))
                if not raw_coords:
                    elem.clear()
                    continue
                
                # Zgodnie z EPSG:2180 (PL-1992) pierwsza to X (północ), druga Y (wschód).
                # Aby ułatwić rysowanie (kartezjański układ 2D), mapujemy: 
                # map_x = wschód (oś odciętych), map_y = północ (oś rzędnych)
                pts = [(raw_coords[i+1], raw_coords[i]) for i in range(0, len(raw_coords), 2)]
                
                # Bounding box wyliczany w jednym przebiegu
                min_x = min(p[0] for p in pts)
                max_x = max(p[0] for p in pts)
                min_y = min(p[1] for p in pts)
                max_y = max(p[1] for p in pts)
                
                grid.add_feature({
                    'id': feature_id,
                    'coords': pts,
                    'bbox': (min_x, max_x, min_y, max_y),
                    'color': style['color'],
                    'type': 'point' if tag == 'pos' else style['type']
                })
                feature_id += 1
                
                # KLUCZOWE: Usuwamy element drzewa DOM z pamięci
                elem.clear()
    
    print(f"Zakończono. Wczytano {feature_id} obiektów przestrzennych.")


# ==========================================
# 3. INTERFEJS GRAFICZNY (TKINTER) I RYSOWANIE
# ==========================================

class BDOTViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BDOT10k GML Viewer - Własny Parser i Indeks")
        self.geometry("1000x800")
        
        # Ustawienia płótna
        self.canvas = tk.Canvas(self, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Zmienne widoku mapy (kamera)
        self.scale = 1.0       # Ile pikseli to 1 metr w terenie
        self.view_min_x = 0.0  # Współrzędna map_x lewej krawędzi ekranu
        self.view_min_y = 0.0  # Współrzędna map_y dolnej krawędzi ekranu (ponieważ Y rośnie na północ)
        
        # Zmienne do przesuwania mapy myszką
        self.last_mouse_x = 0
        self.last_mouse_y = 0
        
        self.grid_index = SpatialGrid(cell_size=1000)
        
        # Bindowanie zdarzeń myszy
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel) # Windows
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)   # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)   # Linux scroll down
        
        # Czekamy na ułożenie UI, aby poznać wymiary płótna, potem ładujemy dane
        self.after(100, self.init_load_data)

    def init_load_data(self):
        folder = filedialog.askdirectory(title="Wybierz folder z plikami GML (powiat)")
        if not folder:
            self.destroy()
            return
            
        start_time = time.time()
        parse_bdot_folder(folder, self.grid_index)
        print(f"Czas parsowania i indeksowania: {time.time() - start_time:.2f} s")
        
        if not self.grid_index.features:
            messagebox.showerror("Błąd", "Nie znaleziono poprawnych danych GML w folderze.")
            return
            
        # Obliczenie początkowego przybliżenia, aby cały powiat zmieścił się na ekranie
        g_min_x, g_max_x, g_min_y, g_max_y = self.grid_index.get_global_bbox()
        
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        
        scale_x = canvas_w / (g_max_x - g_min_x)
        scale_y = canvas_h / (g_max_y - g_min_y)
        
        # Margines 5%
        self.scale = min(scale_x, scale_y) * 0.95 
        
        # Wycentrowanie początkowe
        map_w_pixels = (g_max_x - g_min_x) * self.scale
        map_h_pixels = (g_max_y - g_min_y) * self.scale
        
        offset_x_pixels = (canvas_w - map_w_pixels) / 2
        offset_y_pixels = (canvas_h - map_h_pixels) / 2
        
        self.view_min_x = g_min_x - (offset_x_pixels / self.scale)
        self.view_min_y = g_min_y - (offset_y_pixels / self.scale)
        
        self.draw()

    def on_mouse_press(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y

    def on_mouse_drag(self, event):
        dx = event.x - self.last_mouse_x
        dy = event.y - self.last_mouse_y
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        
        # Przesunięcie kamery
        self.view_min_x -= dx / self.scale
        self.view_min_y += dy / self.scale # W odwróconym układzie przesunięcie myszy w dół podnosi Y mapy
        self.draw()

    def on_mouse_wheel(self, event):
        # Rozpoznawanie kierunku scrolla (Windows / Linux)
        if event.num == 4 or getattr(event, 'delta', 0) > 0:
            zoom_factor = 1.3
        else:
            zoom_factor = 1/1.3
            
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        
        # Zapisz środek ekranu w metrach PL-1992
        map_center_x = self.view_min_x + (canvas_w / self.scale) / 2
        map_center_y = self.view_min_y + (canvas_h / self.scale) / 2
        
        # Nowa skala
        self.scale *= zoom_factor
        
        # Wylicz nowy lewy-dolny róg tak, aby środek pozostał w tym samym miejscu
        self.view_min_x = map_center_x - (canvas_w / self.scale) / 2
        self.view_min_y = map_center_y - (canvas_h / self.scale) / 2
        
        self.draw()

    def draw(self):
        # 1. Czyszczenie bufora (płótna)
        self.canvas.delete("all")
        
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        
        # 2. Wyznaczenie zakresu widoczności (prostokąt kamery) w układzie PL-1992
        v_min_x = self.view_min_x
        v_max_x = self.view_min_x + (canvas_w / self.scale)
        v_min_y = self.view_min