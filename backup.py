import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import os
import time
import math
import zipfile

# =====================================================================
# BAZA STYLÓW ZNAKÓW UMOWNYCH (MAPA 1:10 000)
# =====================================================================
BDOT10K_STYLES = {
    'Z_ORDER': ['PT', 'TC', 'KU', 'SW', 'SU', 'SK', 'BU', 'AD', 'OI'],
    
    'SKDR_L': {
        'attr': 'klasaDrogi',
        'rules': {
            'A':  {'outline': 'black', 'fill': '#ff5555', 'width_mm': 1.5, 'double': True},
            'S':  {'outline': 'black', 'fill': '#ff5555', 'width_mm': 1.5, 'double': True},
            'GP': {'outline': 'black', 'fill': '#ffaa00', 'width_mm': 1.2, 'double': True},
            'G':  {'outline': 'black', 'fill': '#ffffff', 'width_mm': 1.0, 'double': True},
            'Z':  {'outline': 'black', 'fill': '#ffffff', 'width_mm': 1.0, 'double': True},
            'L':  {'outline': '#555555', 'fill': '#ffffff', 'width_mm': 0.8, 'double': True},
            'D':  {'outline': '#555555', 'fill': '#ffffff', 'width_mm': 0.8, 'double': True},
            'I':  {'outline': '#888888', 'fill': '', 'width_mm': 0.5, 'dash': (4, 4)}
        }
    },
    'BUBD_A': {
        'attr': 'funkcjaOgolnaBudynku',
        'rules': {
            '1110': {'fill': '#f2b6b6', 'outline': 'black'},
            '1251': {'fill': '#cccccc', 'outline': 'black'},
            '1272': {'fill': '#d0b0ff', 'outline': 'black'},
        }
    },
    # Poprawka: Lasy mają domyślny zielony kolor wypełnienia + opcjonalny wzór
    'PTLZ_A': {'default': {'fill': '#2ca25f', 'outline': '#186539'}},
    
    'OIPR_P': {
        'attr': 'rodzaj',
        'rules': {
            'krzyzPrzydrozny': {'shape': 'cross', 'color': 'black', 'size_mm': 2.0},
            'pomnik': {'shape': 'triangle', 'color': '#ff4444', 'size_mm': 2.0},
            'drzewoPomnikPrzyrody': {'shape': 'tree', 'color': 'green', 'size_mm': 3.0}
        }
    }
}

# =====================================================================
# INDEKS PRZESTRZENNY I GEOMETRIA
# =====================================================================
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
                        if not (f_max_x < v_min_x or f_min_x > v_max_x or f_max_y < v_min_y or f_min_y > v_max_y):
                            visible.add(f_id)
        return [self.features[f_id] for f_id in visible]

    def get_global_bbox(self):
        if not self.features: return (0, 100, 0, 100)
        return (min(f['bbox'][0] for f in self.features.values()), max(f['bbox'][1] for f in self.features.values()),
                min(f['bbox'][2] for f in self.features.values()), max(f['bbox'][3] for f in self.features.values()))

def is_point_in_polygon(x, y, poly):
    n, inside = len(poly), False
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y) and y <= max(p1y, p2y) and x <= max(p1x, p2x):
            if p1y != p2y:
                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
            if p1x == p2x or x <= xinters:
                inside = not inside
        p1x, p1y = p2x, p2y
    return inside

def dist_to_segment(px, py, x1, y1, x2, y2):
    l2 = (x1 - x2)**2 + (y1 - y2)**2
    if l2 == 0: return ((px - x1)**2 + (py - y1)**2)**0.5
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2))
    return ((px - (x1 + t * (x2 - x1)))**2 + (py - (y1 + t * (y2 - y1))))**0.5

# =====================================================================
# WBUDOWANY PARSER GML (Niezawodne wykrywanie obiektów OT_...)
# =====================================================================
def process_gml_file_object(file_obj, filename, grid, app_layers, feature_id_counter):
    parts = filename.replace('.xml', '').replace('.gml', '').split('_')
    layer_code = "_".join(parts[-2:]) if len(parts) >= 2 else filename.split('.')[0]
    category = layer_code[:2] if len(layer_code) >= 2 else "IN"
    geom_type = 'polygon' if '_A' in layer_code else ('line' if '_L' in layer_code else 'point')
    
    def_colors = {'BU': '#eebdbd', 'PT': '#2ca25f', 'SW': '#33aaff', 'SK': '#555555', 'TC': '#b2df8a', 'KU': '#ffff99'}
    if layer_code not in app_layers:
        app_layers[layer_code] = {
            'code': layer_code, 'category': category, 'visible': tk.BooleanVar(value=True),
            'type': geom_type, 'color': def_colors.get(category, '#cccccc'), 'width': tk.IntVar(value=1)
        }

    print(f"Przetwarzanie: {filename}...")
    context = ET.iterparse(file_obj, events=('start', 'end'))
    
    current_attrs = {}
    feature_parts = []
    inside_feature = False
    is_interior = False
    
    for event, elem in context:
        tag = elem.tag.split('}')[-1]
        
        if event == 'start':
            if tag.startswith('OT_'):
                inside_feature = True
                current_attrs = {'Klasa': tag}
                feature_parts = []
            elif tag == 'interior':
                is_interior = True
            elif tag == 'exterior':
                is_interior = False
                
        elif event == 'end':
            if tag in ('posList', 'pos') and inside_feature:
                dim = 2
                for k, v in elem.attrib.items():
                    if k.endswith('srsDimension'): dim = int(v)
                
                raw = list(map(float, elem.text.split())) if elem.text else []
                if dim == 2 and len(raw) % 2 != 0 and len(raw) % 3 == 0:
                    dim = 3
                    
                if raw:
                    pts = [(raw[i+1], raw[i]) for i in range(0, len(raw) - dim + 1, dim)]
                    if pts:
                        feature_parts.append({'pts': pts, 'is_interior': is_interior})
                elem.clear()
                
            elif inside_feature and tag not in ('posList', 'pos', 'LinearRing', 'Polygon', 'LineString', 'Point', 'geometria', 'exterior', 'interior', 'MultiSurface', 'surfaceMember', 'featureMember'):
                if elem.text and elem.text.strip() and len(elem.text.strip()) < 100:
                    current_attrs[tag] = elem.text.strip()
                    
            if tag.startswith('OT_') and inside_feature:
                if feature_parts:
                    all_x = [p[0] for part in feature_parts for p in part['pts']]
                    all_y = [p[1] for part in feature_parts for p in part['pts']]
                    if all_x and all_y:
                        grid.add_feature({
                            'id': feature_id_counter[0], 'layer': layer_code, 'category': category,
                            'parts': list(feature_parts),
                            'bbox': (min(all_x), max(all_x), min(all_y), max(all_y)),
                            'attrs': dict(current_attrs)
                        })
                        feature_id_counter[0] += 1
                inside_feature = False
                feature_parts.clear()
                current_attrs.clear()
                elem.clear()

def parse_bdot_data(path, grid, app_layers):
    f_id = [0]
    if os.path.isdir(path):
        for fname in os.listdir(path):
            if fname.lower().endswith(('.gml', '.xml')):
                with open(os.path.join(path, fname), 'rb') as f:
                    process_gml_file_object(f, fname, grid, app_layers, f_id)
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, 'r') as zf:
            for fname in zf.namelist():
                if fname.lower().endswith(('.gml', '.xml')):
                    with zf.open(fname) as f:
                        process_gml_file_object(f, fname.split('/')[-1], grid, app_layers, f_id)
    print(f"Łącznie wczytano obiektów: {f_id[0]}")

# =====================================================================
# GŁÓWNA APLIKACJA GUI
# =====================================================================
class BDOTViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BDOT10k GIS Viewer - Poprawione Tereny")
        self.geometry("1300x800")
        
        self.layers, self.scale, self.view_min_x, self.view_min_y = {}, 1.0, 0.0, 0.0
        self.grid_index, self.is_panning = SpatialGrid(), False
        
        # Pasek Narzędzi
        self.toolbar = tk.Frame(self, bg="#dddddd")
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(self.toolbar, text="Wczytaj Folder GML/XML", command=self.load_dir).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(self.toolbar, text="Wczytaj plik ZIP", command=self.load_zip).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(self.toolbar, text="Widok całości (Powiat)", command=self.reset_view).pack(side=tk.LEFT, padx=5, pady=5)
        
        # Panel Warstw (Lewa strona)
        self.left_panel = tk.Frame(self, width=280, bg="white", bd=1, relief=tk.SUNKEN)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y)
        
        self.layer_canvas = tk.Canvas(self.left_panel, bg="white", highlightthickness=0)
        self.layer_scrollbar = ttk.Scrollbar(self.left_panel, orient="vertical", command=self.layer_canvas.yview)
        self.layer_frame = tk.Frame(self.layer_canvas, bg="white")
        self.layer_frame.bind("<Configure>", lambda e: self.layer_canvas.configure(scrollregion=self.layer_canvas.bbox("all")))
        self.layer_canvas.create_window((0, 0), window=self.layer_frame, anchor="nw")
        self.layer_canvas.configure(yscrollcommand=self.layer_scrollbar.set)
        self.layer_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.layer_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Pasek Stanu (Dół)
        self.statusbar = tk.Label(self, text="Wybierz katalog lub plik ZIP z danymi BDOT10k...", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Płótno Mapy
        self.canvas = tk.Canvas(self, bg="#f5f5f5", cursor="crosshair")
        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # Binds myszy
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Motion>", self.on_mouse_move)

    def load_dir(self):
        if path := filedialog.askdirectory(): self._load(path)
    def load_zip(self):
        if path := filedialog.askopenfilename(filetypes=[("Archiwa ZIP", "*.zip")]): self._load(path)

    def _load(self, path):
        self.grid_index = SpatialGrid()
        parse_bdot_data(path, self.grid_index, self.layers)
        self.build_layers_ui()
        self.reset_view()

    def build_layers_ui(self):
        for w in self.layer_frame.winfo_children(): w.destroy()
        tk.Label(self.layer_frame, text="Zarządzanie Warstwami", font=("Arial", 11, "bold"), bg="white").pack(pady=5)
        
        for cat in BDOT10K_STYLES['Z_ORDER']:
            codes = [c for c in self.layers if self.layers[c]['category'] == cat]
            if not codes: continue
            group = tk.LabelFrame(self.layer_frame, text=f"Kategoria: {cat}", bg="white")
            group.pack(fill=tk.X, padx=5, pady=2)
            for code in codes:
                row = tk.Frame(group, bg="white")
                row.pack(fill=tk.X)
                tk.Checkbutton(row, text=code, variable=self.layers[code]['visible'], bg="white", command=self.draw).pack(side=tk.LEFT)
                btn_color = tk.Button(row, bg=self.layers[code]['color'], width=2, relief=tk.FLAT)
                btn_color.config(command=lambda c=code, b=btn_color: self.change_color(c, b))
                btn_color.pack(side=tk.RIGHT, padx=2)
                tk.Spinbox(row, from_=1, to=10, textvariable=self.layers[code]['width'], width=2, command=self.draw).pack(side=tk.RIGHT, padx=2)

    def change_color(self, layer_code, btn):
        color = colorchooser.askcolor(color=self.layers[layer_code]['color'])[1]
        if color:
            self.layers[layer_code]['color'] = color; btn.config(bg=color); self.draw()

    def reset_view(self):
        if not self.grid_index.features: return
        self.update_idletasks()
        g_min_x, g_max_x, g_min_y, g_max_y = self.grid_index.get_global_bbox()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw > 1:
            self.scale = min(cw/(g_max_x-g_min_x), ch/(g_max_y-g_min_y)) * 0.95 
            self.view_min_x = g_min_x - ((cw - (g_max_x-g_min_x)*self.scale)/2)/self.scale
            self.view_min_y = g_min_y - ((ch - (g_max_y-g_min_y)*self.scale)/2)/self.scale
            self.draw()

    def on_mouse_press(self, event):
        self.press_x, self.press_y = event.x, event.y
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        self.is_panning = False

    def on_mouse_drag(self, event):
        dx, dy = event.x - self.last_mouse_x, event.y - self.last_mouse_y
        self.view_min_x -= dx / self.scale
        self.view_min_y += dy / self.scale
        self.canvas.move("all", dx, dy)
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        self.is_panning = True

    def on_mouse_release(self, event):
        if self.is_panning: self.draw()
        elif abs(event.x - self.press_x) < 3 and abs(event.y - self.press_y) < 3:
            self.identify_feature(event.x, event.y)

    def on_mouse_wheel(self, event):
        zoom = 1.3 if getattr(event, 'delta', 0) > 0 else 1/1.3
        self.scale *= zoom
        self.view_min_x = ((event.x / (self.scale/zoom)) + self.view_min_x) - (event.x / self.scale)
        self.view_min_y = (self.view_min_y + (self.canvas.winfo_height() - event.y) / (self.scale/zoom)) - ((self.canvas.winfo_height() - event.y) / self.scale)
        self.draw()
        self.on_mouse_move(event)

    def on_mouse_move(self, event):
        if self.scale > 0:
            east = (event.x / self.scale) + self.view_min_x
            north = self.view_min_y + (self.canvas.winfo_height() - event.y) / self.scale
            self.statusbar.config(text=f"Współrzędne PL-1992 -> Północ (X): {north:.2f}, Wschód (Y): {east:.2f} | Skala: {self.scale:.3f}")

    def identify_feature(self, screen_x, screen_y):
        if not self.grid_index.features: return
        map_x, map_y = (screen_x / self.scale) + self.view_min_x, self.view_min_y + (self.canvas.winfo_height() - screen_y) / self.scale
        tol_map = 5 / self.scale
        
        candidates = self.grid_index.get_features_in_view(map_x-tol_map, map_x+tol_map, map_y-tol_map, map_y+tol_map)
        found = None
        for f in reversed(candidates):
            l_props = self.layers.get(f['layer'])
            if not l_props or not l_props['visible'].get(): continue
            geom_type = l_props['type']
            
            for part in f['parts']:
                pts = part['pts']
                if geom_type == 'polygon' and len(pts) >= 3 and is_point_in_polygon(map_x, map_y, pts): found = f; break
                elif geom_type == 'line' and len(pts) >= 2:
                    if any(dist_to_segment(map_x, map_y, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) <= tol_map for i in range(len(pts)-1)): found = f; break
                elif geom_type == 'point' and ((pts[0][0]-map_x)**2 + (pts[0][1]-map_y)**2)**0.5 <= tol_map: found = f; break
            if found: break
                    
        if found:
            info = "\n".join([f"{k}: {v}" for k, v in found.get('attrs', {}).items()])
            messagebox.showinfo(f"Identyfikacja obiektu: {found['layer']}", info if info else "Brak atrybutów.")

    def mm_to_px(self, mm): return max(1, mm * 10.0 * self.scale)

    def draw_symbol(self, shape, color, px_x, px_y, size_px, angle_deg):
        r = size_px / 2
        if shape == 'cross':
            self.canvas.create_line(px_x, px_y-r, px_x, px_y+r, fill=color, width=2)
            self.canvas.create_line(px_x-r*0.6, px_y-r*0.2, px_x+r*0.6, px_y-r*0.2, fill=color, width=2)
        elif shape == 'triangle':
            self.canvas.create_polygon(px_x, px_y-r, px_x-r, px_y+r, px_x+r, px_y+r, fill=color, outline='black')
        elif shape == 'tree':
            self.canvas.create_line(px_x, px_y, px_x, px_y+r, fill='brown', width=2)
            self.canvas.create_oval(px_x-r, px_y-r*1.5, px_x+r, px_y+r*0.5, fill=color, outline='darkgreen')
        else:
            self.canvas.create_oval(px_x-r, px_y-r, px_x+r, px_y+r, fill=color, outline='black')

    def draw(self):
        t0 = time.time()
        self.canvas.delete("all")
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        
        v_min_x, v_max_x = self.view_min_x, self.view_min_x + (cw / self.scale)
        v_min_y, v_max_y = self.view_min_y, self.view_min_y + (ch / self.scale)
        
        visible_features = self.grid_index.get_features_in_view(v_min_x, v_max_x, v_min_y, v_max_y)
        visible_features.sort(key=lambda f: BDOT10K_STYLES['Z_ORDER'].index(f['category']) if f['category'] in BDOT10K_STYLES['Z_ORDER'] else -1)

        drawn, hidden = 0, 0
        for f in visible_features:
            layer = f['layer']
            l_props = self.layers.get(layer)
            if not l_props or not l_props['visible'].get(): continue
            
            if self.scale < 0.1 and layer in ('BUBD_A', 'OIPR_P'):
                hidden += 1; continue

            style_def = BDOT10K_STYLES.get(layer, {})
            attr_key = style_def.get('attr')
            rule = style_def.get('rules', {}).get(f['attrs'].get(attr_key, ''), style_def.get('default', {}))
            
            ui_color, ui_width = l_props['color'], l_props['width'].get()
            geom_type = l_props['type']
            
            for part in f['parts']:
                screen_coords = []
                for mx, my in part['pts']:
                    screen_coords.extend([(mx - v_min_x) * self.scale, ch - ((my - v_min_y) * self.scale)])

                if geom_type == 'polygon' and len(screen_coords) >= 6:
                    if part['is_interior']:
                        # Otwory w poligonach rysujemy kolorem tła mapy
                        self.canvas.create_polygon(*screen_coords, fill='#f5f5f5', outline='')
                    else:
                        fill = rule.get('fill', ui_color)
                        outline = rule.get('outline', 'black') if self.scale > 0.2 else ''
                        self.canvas.create_polygon(*screen_coords, fill=fill, outline=outline, width=ui_width)
                    drawn += 1
                    
                elif geom_type == 'line' and len(screen_coords) >= 4:
                    w_px = self.mm_to_px(rule.get('width_mm', ui_width))
                    fill, outline = rule.get('fill', ''), rule.get('outline', ui_color)
                    
                    if rule.get('double', False) and fill:
                        self.canvas.create_line(*screen_coords, fill=outline, width=w_px+2, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                        self.canvas.create_line(*screen_coords, fill=fill, width=w_px, capstyle=tk.ROUND, joinstyle=tk.ROUND)
                    else:
                        self.canvas.create_line(*screen_coords, fill=outline, width=w_px, dash=rule.get('dash'))
                    drawn += 1
                    
                elif geom_type == 'point' and len(screen_coords) >= 2:
                    size_px = self.mm_to_px(rule.get('size_mm', 2.0 * ui_width))
                    orient = float(f['attrs'].get('orientacja', 0))
                    self.draw_symbol(rule.get('shape', 'circle'), color=rule.get('color', ui_color), px_x=screen_coords[0], px_y=screen_coords[1], size_px=size_px, angle_deg=orient)
                    drawn += 1

        self.statusbar.config(text=f"Renderowanie: {time.time()-t0:.3f}s | Obiekty w widoku: {drawn} (Ukryte sub-skala: {hidden}) | Skala: {self.scale:.2f}")

if __name__ == "__main__":
    BDOTViewer().mainloop()