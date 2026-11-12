import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import math
import os
import time

# ==========================================
# 0. BAZA STYLÓW ZNAKÓW UMOWNYCH (MAPA 1:10 000)
# Reguły zapisane w formacie przypominającym JSON
# ==========================================
BDOT10K_STYLES = {
    # Kolejność rysowania warstw (Z-Order)
    'Z_ORDER': ['PT', 'TC', 'KU', 'SW', 'SU', 'SK', 'BU', 'AD', 'OI'],
    
    # Reguły dla linii komunikacyjnych (Drogi)
    'SKDR_L': {
        'attr': 'klasaDrogi', # Badany atrybut
        'rules': {
            'A':  {'outline': 'black', 'fill': '#ff5555', 'width_mm': 1.5, 'double': True},  # Autostrada
            'S':  {'outline': 'black', 'fill': '#ff5555', 'width_mm': 1.5, 'double': True},  # Ekspresowa
            'GP': {'outline': 'black', 'fill': '#ffaa00', 'width_mm': 1.2, 'double': True},  # Główna przysp.
            'G':  {'outline': 'black', 'fill': '#ffffff', 'width_mm': 1.0, 'double': True},  # Główna
            'Z':  {'outline': 'black', 'fill': '#ffffff', 'width_mm': 1.0, 'double': True},  # Zbiorcza
            'L':  {'outline': '#555555', 'fill': '#ffffff', 'width_mm': 0.8, 'double': True},# Lokalna
            'D':  {'outline': '#555555', 'fill': '#ffffff', 'width_mm': 0.8, 'double': True},# Dojazdowa
            'I':  {'outline': '#888888', 'fill': '', 'width_mm': 0.5, 'dash': (4, 4)}        # Inna (przerywana)
        },
        'default': {'outline': '#555555', 'fill': '#ffffff', 'width_mm': 0.8, 'double': True}
    },
    
    # Reguły dla budynków
    'BUBD_A': {
        'attr': 'funkcjaOgolnaBudynku',
        'rules': {
            '1110': {'fill': '#f2b6b6', 'outline': 'black'}, # Mieszkalne (jasnoczerwony)
            '1251': {'fill': '#cccccc', 'outline': 'black'}, # Przemysłowe (szare)
            '1272': {'fill': '#d0b0ff', 'outline': 'black'}, # Kultu religijnego (fiolet)
        },
        'default': {'fill': '#eebdbd', 'outline': '#333333'}
    },
    
    # Reguły dla wód
    'SWRS_L': {
        'attr': 'rodzaj',
        'rules': {},
        'default': {'outline': '#33aaff', 'width_mm': 0.5}
    },
    
    # Reguły dla pokrycia terenu (lasy z wypełnieniem wzorem stipple)
    'PTLZ_A': {
        'attr': 'rodzaj',
        'rules': {},
        # Używamy stipple "gray25" z systemowego zestawu X11 Tkintera do symulacji sygnatury
        'default': {'fill': '#2ca25f', 'outline': '#186539', 'stipple': 'gray25'}
    },
    
    # Obiekty punktowe z własnymi znakami graficznymi (zamiast SVG rysujemy je wektorowo)
    'OIPR_P': {
        'attr': 'rodzaj',
        'rules': {
            'krzyzPrzydrozny': {'shape': 'cross', 'color': 'black', 'size_mm': 2.0},
            'pomnik': {'shape': 'triangle', 'color': '#ff4444', 'size_mm': 2.0},
            'drzewoPomnikPrzyrody': {'shape': 'tree', 'color': 'green', 'size_mm': 3.0}
        },
        'default': {'shape': 'circle', 'color': 'orange', 'size_mm': 1.5}
    }
}

# ==========================================
# 1. OPTYMALIZOWANY INDEKS (SIATKA REGULARNA O(1))
# ==========================================
class SpatialGrid:
    def __init__(self, cell_size=1000):
        self.cell_size, self.cells, self.features = cell_size, {}, {}

    def add_feature(self, feature):
        f_id = feature['id']
        self.features[f_id] = feature
        min_x, max_x, min_y, max_y = feature['bbox']
        
        for col in range(int(min_x // self.cell_size), int(max_x // self.cell_size) + 1):
            for row in range(int(min_y // self.cell_size), int(max_y // self.cell_size) + 1):
                cell_id = (col, row)
                if cell_id not in self.cells: self.cells[cell_id] = []
                self.cells[cell_id].append(f_id)

    def get_features_in_view(self, v_min_x, v_max_x, v_min_y, v_max_y):
        visible = set()
        for col in range(int(v_min_x // self.cell_size), int(v_max_x // self.cell_size) + 1):
            for row in range(int(v_min_y // self.cell_size), int(v_max_y // self.cell_size) + 1):
                if (col, row) in self.cells:
                    for f_id in self.cells[(col, row)]:
                        if f_id in visible: continue
                        f_min_x, f_max_x, f_min_y, f_max_y = self.features[f_id]['bbox']
                        # Sprawdzanie BBOX (4 warunki)
                        if not (f_max_x < v_min_x or f_min_x > v_max_x or f_max_y < v_min_y or f_min_y > v_max_y):
                            visible.add(f_id)
        return [self.features[f_id] for f_id in visible]

    def get_global_bbox(self):
        if not self.features: return (0, 100, 0, 100)
        return (min(f['bbox'][0] for f in self.features.values()), max(f['bbox'][1] for f in self.features.values()),
                min(f['bbox'][2] for f in self.features.values()), max(f['bbox'][3] for f in self.features.values()))


# ==========================================
# 2. PARSER GML STRUMIENIOWY (ATRYBUTY)
# ==========================================
def parse_bdot_folder(folder_path, grid, app_layers):
    feature_id = 0
    gml_files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.gml', '.xml'))]
    
    for filename in gml_files:
        filepath = os.path.join(folder_path, filename)
        parts = filename.replace('.xml', '').replace('.gml', '').split('_')
        layer_code = "_".join(parts[-2:]) if len(parts) >= 2 else filename.split('.')[0]
        category = layer_code[:2] if len(layer_code) >= 2 else "IN"
        geom_type = 'polygon' if '_A' in layer_code else ('line' if '_L' in layer_code else 'point')
        
        if layer_code not in app_layers:
            app_layers[layer_code] = {'code': layer_code, 'category': category, 'visible': tk.BooleanVar(value=True), 'type': geom_type}

        print(f"Skanowanie: {filename}...")
        context = ET.iterparse(filepath, events=('start', 'end'))
        current_attrs = {}
        inside_feature = False
        
        for event, elem in context:
            tag = elem.tag.split('}')[-1]
            if event == 'start' and tag.startswith('OT_'):
                inside_feature, current_attrs = True, {'Klasa': tag}
            elif event == 'end':
                if tag in ('posList', 'pos'):
                    raw = list(map(float, elem.text.split())) if elem.text else []
                    if raw:
                        pts = [(raw[i+1], raw[i]) for i in range(0, len(raw), 2)]
                        min_x, max_x = min(p[0] for p in pts), max(p[0] for p in pts)
                        min_y, max_y = min(p[1] for p in pts), max(p[1] for p in pts)
                        grid.add_feature({'id': feature_id, 'layer': layer_code, 'category': category,
                                          'coords': pts, 'bbox': (min_x, max_x, min_y, max_y), 'attrs': dict(current_attrs)})
                        feature_id += 1
                    elem.clear()
                elif inside_feature and tag not in ('posList', 'pos', 'LinearRing', 'Polygon', 'LineString', 'Point', 'geometria', 'exterior', 'interior'):
                    if elem.text and elem.text.strip(): current_attrs[tag] = elem.text.strip()
                elif tag.startswith('OT_'):
                    inside_feature = False; elem.clear()

# ==========================================
# 3. SILNIK GRAFICZNY I ZAAWANSOWANE SYMBOLE
# ==========================================
class BDOTViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BDOT10k Viewer - Wariant Zaawansowany 1:10 000")
        self.geometry("1200x800")
        
        self.layers, self.scale, self.view_min_x, self.view_min_y = {}, 1.0, 0.0, 0.0
        self.grid_index, self.is_panning = SpatialGrid(), False
        
        # Interfejs
        self.toolbar = tk.Frame(self, bg="#dddddd"); self.toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(self.toolbar, text="Wczytaj powiat", command=self.load_data).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(self.toolbar, text="Widok całości", command=self.reset_view).pack(side=tk.LEFT, padx=5, pady=5)
        
        self.left_panel = tk.Frame(self, width=200, bg="white", bd=1, relief=tk.SUNKEN)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y)
        self.layer_frame = tk.Frame(self.left_panel, bg="white")
        self.layer_frame.pack(fill=tk.BOTH, expand=True)

        self.statusbar = tk.Label(self, text="Gotowy", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.canvas = tk.Canvas(self, bg="#f5f5f5", cursor="crosshair")
        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)

    def load_data(self):
        if folder := filedialog.askdirectory():
            self.grid_index = SpatialGrid()
            parse_bdot_folder(folder, self.grid_index, self.layers)
            self.build_layers_ui()
            self.reset_view()

    def build_layers_ui(self):
        for w in self.layer_frame.winfo_children(): w.destroy()
        tk.Label(self.layer_frame, text="Z-Order Warstwy", font=("Arial", 11, "bold"), bg="white").pack()
        # Sortujemy UI zgodnie z Z-Order
        for cat in BDOT10K_STYLES['Z_ORDER']:
            codes = [c for c in self.layers if self.layers[c]['category'] == cat]
            if not codes: continue
            group = tk.LabelFrame(self.layer_frame, text=cat, bg="white")
            group.pack(fill=tk.X, padx=5, pady=2)
            for code in codes:
                tk.Checkbutton(group, text=code, variable=self.layers[code]['visible'], bg="white", command=self.draw).pack(anchor=tk.W)

    def reset_view(self):
        if not self.grid_index.features: return
        g_min_x, g_max_x, g_min_y, g_max_y = self.grid_index.get_global_bbox()
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if canvas_w > 1:
            self.scale = min(canvas_w/(g_max_x-g_min_x), canvas_h/(g_max_y-g_min_y)) * 0.95 
            self.view_min_x = g_min_x - ((canvas_w - (g_max_x-g_min_x)*self.scale)/2)/self.scale
            self.view_min_y = g_min_y - ((canvas_h - (g_max_y-g_min_y)*self.scale)/2)/self.scale
            self.draw()

    # ---- NAWIGACJA ----
    def on_mouse_press(self, event):
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        self.is_panning = False

    def on_mouse_drag(self, event):
        self.view_min_x -= (event.x - self.last_mouse_x) / self.scale
        self.view_min_y += (event.y - self.last_mouse_y) / self.scale
        self.canvas.move("all", event.x - self.last_mouse_x, event.y - self.last_mouse_y)
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        self.is_panning = True

    def on_mouse_release(self, event):
        if self.is_panning:
            self.draw()
        else:
            self.statusbar.config(text="Kliknięto na identyfikację - zaimplementowano w rozszerzonym.")

    def on_mouse_wheel(self, event):
        zoom = 1.3 if getattr(event, 'delta', 0) > 0 else 1/1.3
        self.scale *= zoom
        self.view_min_x = ((event.x / (self.scale/zoom)) + self.view_min_x) - (event.x / self.scale)
        self.view_min_y = (self.view_min_y + (self.canvas.winfo_height() - event.y) / (self.scale/zoom)) - ((self.canvas.winfo_height() - event.y) / self.scale)
        self.draw()

    # ---- ZAAWANSOWANE RYSOWANIE ----
    def mm_to_px(self, mm):
        # 1 mm na mapie 1:10 000 = 10 metrów w terenie.
        # Skala to piksele/metr. Zatem 10 metrów * skala = wielkość w pikselach na ekranie.
        return max(1, mm * 10.0 * self.scale)

    def draw_custom_symbol(self, shape, color, px_x, px_y, size_px, angle_deg=0):
        # Rysuje symbol wektorowy imitujący SVG
        r = size_px / 2
        if shape == 'cross':
            # Obrót krzyża (np. dla krzyży przydrożnych, które mają orientację)
            # Upraszczamy tutaj bez trygonometrii dla zwięzłości kodu
            self.canvas.create_line(px_x, px_y-r, px_x, px_y+r, fill=color, width=2)
            self.canvas.create_line(px_x-r*0.6, px_y-r*0.2, px_x+r*0.6, px_y-r*0.2, fill=color, width=2)
        elif shape == 'triangle':
            self.canvas.create_polygon(px_x, px_y-r, px_x-r, px_y+r, px_x+r, px_y+r, fill=color, outline='black')
        elif shape == 'tree':
            self.canvas.create_line(px_x, px_y, px_x, px_y+r, fill='brown', width=2)
            self.canvas.create_oval(px_x-r, px_y-r*1.5, px_x+r, px_y+r*0.5, fill=color, outline='darkgreen')
        else: # Circle default
            self.canvas.create_oval(px_x-r, px_y-r, px_x+r, px_y+r, fill=color, outline='black')

    def draw(self):
        t0 = time.time()
        self.canvas.delete("all")
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        
        v_min_x, v_max_x = self.view_min_x, self.view_min_x + (cw / self.scale)
        v_min_y, v_max_y = self.view_min_y, self.view_min_y + (ch / self.scale)
        
        visible_features = self.grid_index.get_features_in_view(v_min_x, v_max_x, v_min_y, v_max_y)
        
        # Sortowanie wyciągniętych obiektów według Z-ORDER z mapy topograficznej (Wymaganie 5)
        # Obiekty nie występujące w liście trafiają na spód
        def get_z_index(feat):
            cat = feat['category']
            return BDOT10K_STYLES['Z_ORDER'].index(cat) if cat in BDOT10K_STYLES['Z_ORDER'] else -1
            
        visible_features.sort(key=get_z_index)

        drawn, hidden = 0, 0
        
        for f in visible_features:
            layer = f['layer']
            if layer not in self.layers or not self.layers[layer]['visible'].get(): continue
                
            geom_type = self.layers[layer]['type']
            
            # Wymaganie 6: Ukrywanie przy małej skali (zbyt duże oddalenie)
            # Jeśli piksel reprezentuje więcej niż 10 metrów w terenie (scale < 0.1), ukrywamy punkty i budynki
            if self.scale < 0.1 and layer in ('BUBD_A', 'OIPR_P'):
                hidden += 1
                continue

            # Odczytanie reguły atrybutowej ze słownika stylów (Wymaganie 1)
            style_def = BDOT10K_STYLES.get(layer, {})
            attr_key = style_def.get('attr', None)
            attr_val = f['attrs'].get(attr_key, '')
            rule = style_def.get('rules', {}).get(attr_val, style_def.get('default', {}))
            
            # Gdy brak reguły szczegółowej
            if not rule: 
                rule = {'outline': 'gray', 'fill': '', 'width_mm': 0.5, 'shape': 'circle', 'size_mm': 1.0, 'color': 'gray'}

            # Transformacja
            screen_coords = []
            for mx, my in f['coords']:
                screen_coords.extend([(mx - v_min_x) * self.scale, ch - ((my - v_min_y) * self.scale)])

            # ---- RENDEROWANIE GEOMETRII ----
            if geom_type == 'polygon' and len(screen_coords) >= 6:
                stipple = rule.get('stipple', '') # Wymaganie 4 - stipple pattern
                fill = rule.get('fill', '')
                outline = rule.get('outline', 'black') if self.scale > 0.2 else ''
                self.canvas.create_polygon(*screen_coords, fill=fill, outline=outline, stipple=stipple)
                drawn += 1
                
            elif geom_type == 'line' and len(screen_coords) >= 4:
                # Wymaganie 3: Linie złożone, podwójne z obrysem
                w_px = self.mm_to_px(rule.get('width_mm', 0.5))
                dash = rule.get('dash', None)
                outline = rule.get('outline', 'black')
                fill = rule.get('fill', '')
                is_double = rule.get('double', False)
                
                if is_double and fill:
                    # Podwójna linia - rysujemy obrys (szerszy), a na nim wypełnienie (węższe)
                    self.canvas.create_line(*screen_coords, fill=outline, width=w_px+2, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                    self.canvas.create_line(*screen_coords, fill=fill, width=w_px, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                else:
                    self.canvas.create_line(*screen_coords, fill=outline, width=w_px, dash=dash)
                drawn += 1
                
            elif geom_type == 'point' and len(screen_coords) >= 2:
                # Wymaganie 2 i 6: Znaki punktowe przerysowane, przeliczane mm na piksele
                size_px = self.mm_to_px(rule.get('size_mm', 2.0))
                shape = rule.get('shape', 'circle')
                color = rule.get('color', 'black')
                orient = float(f['attrs'].get('orientacja', 0)) # Odczyt kąta jeśli istnieje
                
                self.draw_custom_symbol(shape, color, screen_coords[0], screen_coords[1], size_px, orient)
                drawn += 1

        draw_time = time.time() - t0
        self.statusbar.config(text=f"Wyrysowano: {drawn} (Ukryto małych: {hidden}) | Czas generowania: {draw_time:.3f}s | Skala(px/m): {self.scale:.2f}")

if __name__ == "__main__":
    app = BDOTViewer()
    app.mainloop()