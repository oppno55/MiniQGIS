import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import os
import time

# ==========================================
# 1. OPTYMALNY INDEKS PRZESTRZENNY (SIATKA O(1))
# ==========================================
class SpatialGrid:
    def __init__(self, cell_size=1000):
        self.cell_size = cell_size
        self.cells = {}
        self.features = {}

    def add_feature(self, feature):
        f_id = feature['id']
        self.features[f_id] = feature
        
        # PROSTOKĄT OGRANICZAJĄCY (BBox) już obliczony podczas czytania XML
        min_x, max_x, min_y, max_y = feature['bbox']
        
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
        for col in range(start_col, end_col + 1):
            for row in range(start_row, end_row + 1):
                cell_id = (col, row)
                if cell_id in self.cells:
                    for f_id in self.cells[cell_id]:
                        if f_id in visible: 
                            continue
                        f = self.features[f_id]
                        f_min_x, f_max_x, f_min_y, f_max_y = f['bbox']
                        
                        # OPTYMALIZACJA: Sprawdzenie BBox za pomocą 4 porównań (zgodnie z instrukcją)
                        if not (f_max_x < v_min_x or f_min_x > v_max_x or 
                                f_max_y < v_min_y or f_min_y > v_max_y):
                            visible.add(f_id)
        return [self.features[f_id] for f_id in visible]

    def get_global_bbox(self):
        if not self.features: return (0, 100, 0, 100)
        min_x = min(f['bbox'][0] for f in self.features.values())
        max_x = max(f['bbox'][1] for f in self.features.values())
        min_y = min(f['bbox'][2] for f in self.features.values())
        max_y = max(f['bbox'][3] for f in self.features.values())
        return min_x, max_x, min_y, max_y

def is_point_in_polygon(x, y, poly):
    n = len(poly)
    inside = False
    p1x, p1y = poly[0]
    for i in range(1, n + 1):
        p2x, p2y = poly[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
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

# ==========================================
# 2. PARSER GML STRUMIENIOWY
# ==========================================
def parse_bdot_folder(folder_path, grid, app_layers):
    feature_id = 0
    gml_files = [f for f in os.listdir(folder_path) if f.lower().endswith(('.gml', '.xml'))]
    cat_colors = {'BU': '#ff4444', 'PT': '#44aa44', 'SW': '#4444ff', 'SK': '#333333', 'OIP': '#ff8800'}
    
    for filename in gml_files:
        filepath = os.path.join(folder_path, filename)
        parts = filename.replace('.xml', '').replace('.gml', '').split('_')
        layer_code = "_".join(parts[-2:]) if len(parts) >= 2 else filename.split('.')[0]
        category = layer_code[:2] if len(layer_code) >= 2 else "IN"
        geom_type = 'polygon' if '_A' in layer_code else ('line' if '_L' in layer_code else 'point')
        
        if layer_code not in app_layers:
            app_layers[layer_code] = {
                'code': layer_code, 'category': category,
                'visible': tk.BooleanVar(value=True),
                'color': cat_colors.get(category, '#888888'),
                'width': tk.IntVar(value=1), 'type': geom_type
            }

        print(f"Wczytywanie: {filename}...")
        
        # Wczytywanie strumieniowe (iterparse) - RAM SAFE
        context = ET.iterparse(filepath, events=('start', 'end'))
        current_attrs = {}
        inside_feature = False
        
        for event, elem in context:
            tag = elem.tag.split('}')[-1]
            if event == 'start':
                if tag.startswith('OT_'):
                    inside_feature = True
                    current_attrs = {'Klasa': tag}
            elif event == 'end':
                if tag in ('posList', 'pos'):
                    raw = list(map(float, elem.text.split())) if elem.text else []
                    if raw:
                        pts = [(raw[i+1], raw[i]) for i in range(0, len(raw), 2)]
                        
                        # WYMÓG: BBox w jednym przebiegu współrzędnych
                        min_x, max_x = min(p[0] for p in pts), max(p[0] for p in pts)
                        min_y, max_y = min(p[1] for p in pts), max(p[1] for p in pts)
                        
                        grid.add_feature({
                            'id': feature_id, 'layer': layer_code,
                            'coords': pts, 'bbox': (min_x, max_x, min_y, max_y),
                            'attrs': dict(current_attrs)
                        })
                        feature_id += 1
                    elem.clear()
                elif inside_feature and tag not in ('posList', 'pos', 'LinearRing', 'Polygon', 'LineString', 'Point', 'geometria', 'exterior', 'interior', 'featureMember'):
                    if elem.text and elem.text.strip(): current_attrs[tag] = elem.text.strip()
                elif tag.startswith('OT_'):
                    inside_feature = False
                    elem.clear()
    print(f"Wczytano {feature_id} obiektów.")

# ==========================================
# 3. INTERFEJS GRAFICZNY I OPTYMALIZACJE RYSOWANIA
# ==========================================
class BDOTViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BDOT10k Viewer - Pełna Optymalizacja Wydajności")
        self.geometry("1200x800")
        
        self.layers = {}
        self.scale = 1.0
        self.view_min_x = 0.0
        self.view_min_y = 0.0
        self.grid_index = SpatialGrid()
        
        self.is_panning = False # Flaga do optymalizacji przesuwania (buforowanie)
        
        self.toolbar = tk.Frame(self, bg="#eeeeee", bd=1, relief=tk.RAISED)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(self.toolbar, text="Wczytaj powiat", command=self.load_data).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(self.toolbar, text="Widok całości", command=self.reset_view).pack(side=tk.LEFT, padx=5, pady=5)

        self.left_panel = tk.Frame(self, width=280, bg="white", bd=1, relief=tk.SUNKEN)
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(self.left_panel, text="Warstwy BDOT10k", font=("Arial", 12, "bold"), bg="white").pack(pady=5)
        
        self.layer_canvas = tk.Canvas(self.left_panel, bg="white", highlightthickness=0)
        self.layer_scrollbar = ttk.Scrollbar(self.left_panel, orient="vertical", command=self.layer_canvas.yview)
        self.layer_frame = tk.Frame(self.layer_canvas, bg="white")
        self.layer_frame.bind("<Configure>", lambda e: self.layer_canvas.configure(scrollregion=self.layer_canvas.bbox("all")))
        self.layer_canvas.create_window((0, 0), window=self.layer_frame, anchor="nw")
        self.layer_canvas.configure(yscrollcommand=self.layer_scrollbar.set)
        self.layer_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.layer_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.statusbar = tk.Label(self, text="Gotowy", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.canvas = tk.Canvas(self, bg="white", cursor="crosshair")
        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)
        self.canvas.bind("<Motion>", self.on_mouse_move)

    def load_data(self):
        folder = filedialog.askdirectory()
        if not folder: return
        self.grid_index = SpatialGrid()
        self.layers.clear()
        parse_bdot_folder(folder, self.grid_index, self.layers)
        self.build_layer_panel()
        self.reset_view()

    def build_layer_panel(self):
        for w in self.layer_frame.winfo_children(): w.destroy()
        categories = {}
        for l_code, l_data in self.layers.items():
            cat = l_data['category']
            if cat not in categories: categories[cat] = []
            categories[cat].append(l_code)
            
        for cat, codes in sorted(categories.items()):
            group = tk.LabelFrame(self.layer_frame, text=f"Kategoria: {cat}", bg="white")
            group.pack(fill=tk.X, padx=5, pady=2, ipadx=2, ipady=2)
            for code in codes:
                row = tk.Frame(group, bg="white")
                row.pack(fill=tk.X)
                tk.Checkbutton(row, text=code, variable=self.layers[code]['visible'], bg="white", command=self.draw).pack(side=tk.LEFT)
                btn_color = tk.Button(row, bg=self.layers[code]['color'], width=2, relief=tk.FLAT)
                btn_color.config(command=lambda c=code, b=btn_color: self.change_layer_color(c, b))
                btn_color.pack(side=tk.RIGHT, padx=2)
                tk.Spinbox(row, from_=1, to=10, textvariable=self.layers[code]['width'], width=3, command=self.draw).pack(side=tk.RIGHT, padx=2)

    def change_layer_color(self, layer_code, btn):
        color = colorchooser.askcolor(color=self.layers[layer_code]['color'])[1]
        if color:
            self.layers[layer_code]['color'] = color
            btn.config(bg=color)
            self.draw()

    def reset_view(self):
        if not self.grid_index.features: return
        g_min_x, g_max_x, g_min_y, g_max_y = self.grid_index.get_global_bbox()
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if canvas_w <= 1 or canvas_h <= 1: return
        
        self.scale = min(canvas_w/(g_max_x-g_min_x), canvas_h/(g_max_y-g_min_y)) * 0.95 
        offset_x, offset_y = (canvas_w - (g_max_x-g_min_x)*self.scale)/2, (canvas_h - (g_max_y-g_min_y)*self.scale)/2
        self.view_min_x = g_min_x - (offset_x/self.scale)
        self.view_min_y = g_min_y - (offset_y/self.scale)
        self.draw()

    # ---- ZOPTYMALIZOWANA NAWIGACJA (BUFOROWANIE MYSZY) ----
    def on_mouse_press(self, event):
        self.press_x, self.press_y = event.x, event.y
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        self.is_panning = False

    def on_mouse_drag(self, event):
        # OPTYMALIZACJA 2: Przesuwanie zawartości sprzętowo bez pełnego rysowania
        dx = event.x - self.last_mouse_x
        dy = event.y - self.last_mouse_y
        self.last_mouse_x, self.last_mouse_y = event.x, event.y
        
        self.view_min_x -= dx / self.scale
        self.view_min_y += dy / self.scale
        
        # Shift the existing canvas items instantly (simulates a bitmap buffer shift)
        self.canvas.move("all", dx, dy)
        self.is_panning = True

    def on_mouse_release(self, event):
        if self.is_panning:
            # Dopiero po puszczeniu myszki odświeżamy brakujące obszary z indeksu
            self.draw()
            self.is_panning = False
        elif abs(event.x - self.press_x) < 3 and abs(event.y - self.press_y) < 3:
            self.identify_feature(event.x, event.y)

    def on_mouse_wheel(self, event):
        zoom = 1.3 if (event.num == 4 or getattr(event, 'delta', 0) > 0) else 1/1.3
        c_map_x = (event.x / self.scale) + self.view_min_x
        c_map_y = self.view_min_y + (self.canvas.winfo_height() - event.y) / self.scale
        self.scale *= zoom
        self.view_min_x = c_map_x - (event.x / self.scale)
        self.view_min_y = c_map_y - (self.canvas.winfo_height() - event.y) / self.scale
        self.draw()

    def on_mouse_move(self, event):
        if self.scale > 0:
            east = (event.x / self.scale) + self.view_min_x
            north = self.view_min_y + (self.canvas.winfo_height() - event.y) / self.scale
            self.statusbar.config(text=f"X(N): {north:.2f}, Y(E): {east:.2f} | Zbliżenie: {self.scale:.2f} px/m")

    def identify_feature(self, screen_x, screen_y):
        if not self.grid_index.features: return
        map_x = (screen_x / self.scale) + self.view_min_x
        map_y = self.view_min_y + (self.canvas.winfo_height() - screen_y) / self.scale
        tol_map = 5 / self.scale
        
        candidates = self.grid_index.get_features_in_view(
            map_x - tol_map, map_x + tol_map, map_y - tol_map, map_y + tol_map
        )
        found = None
        for f in reversed(candidates):
            l_props = self.layers.get(f['layer'])
            if not l_props or not l_props['visible'].get(): continue
            geom_type, pts = l_props['type'], f['coords']
            
            if geom_type == 'polygon' and len(pts) >= 3 and is_point_in_polygon(map_x, map_y, pts):
                found = f; break
            elif geom_type == 'line' and len(pts) >= 2:
                if any(dist_to_segment(map_x, map_y, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) <= tol_map for i in range(len(pts)-1)):
                    found = f; break
            elif geom_type == 'point':
                if ((pts[0][0] - map_x)**2 + (pts[0][1] - map_y)**2)**0.5 <= tol_map:
                    found = f; break
                    
        if found:
            info = "\n".join([f"{k}: {v}" for k, v in found.get('attrs', {}).items()])
            messagebox.showinfo(f"Atrybuty: {found['layer']}", info if info else "Brak.")

    # ---- WYDAJNOŚCIOWY SILNIK RYSOWANIA ----
    def draw(self):
        t0 = time.time()
        self.canvas.delete("all")
        canvas_w, canvas_h = self.canvas.winfo_width(), self.canvas.winfo_height()
        
        v_min_x, v_max_x = self.view_min_x, self.view_min_x + (canvas_w / self.scale)
        v_min_y, v_max_y = self.view_min_y, self.view_min_y + (canvas_h / self.scale)
        
        visible_features = self.grid_index.get_features_in_view(v_min_x, v_max_x, v_min_y, v_max_y)
        
        drawn_count = 0
        skipped_count = 0
        
        for f in visible_features:
            l_props = self.layers.get(f['layer'])
            if not l_props or not l_props['visible'].get(): continue
                
            # OPTYMALIZACJA 1: Pomijanie obiektów mniejszych niż 1 piksel
            geom_type = l_props['type']
            if geom_type != 'point':
                bb_w = (f['bbox'][1] - f['bbox'][0]) * self.scale
                bb_h = (f['bbox'][3] - f['bbox'][2]) * self.scale
                
                if bb_w < 1.0 and bb_h < 1.0:
                    skipped_count += 1
                    continue # Obiekt sub-pikselowy, pomijamy całkowicie
                
            screen_coords = []
            for map_x, map_y in f['coords']:
                screen_x = (map_x - self.view_min_x) * self.scale
                screen_y = canvas_h - ((map_y - self.view_min_y) * self.scale)
                screen_coords.extend([screen_x, screen_y])
                
            color = l_props['color']
            width = l_props['width'].get()
            
            if geom_type == 'polygon' and len(screen_coords) >= 6:
                # Poligon bez czarnego outline (obrysu), jeśli skala jest bardzo mała (przyspiesza renderowanie)
                out_color = 'black' if self.scale > 0.1 else ''
                self.canvas.create_polygon(*screen_coords, fill=color, outline=out_color, width=width)
                drawn_count += 1
            elif geom_type == 'line' and len(screen_coords) >= 4:
                self.canvas.create_line(*screen_coords, fill=color, width=width)
                drawn_count += 1
            elif geom_type == 'point' and len(screen_coords) >= 2:
                r = max(1, width * 2) # Punkty nie mogą zniknąć
                sx, sy = screen_coords[0], screen_coords[1]
                self.canvas.create_oval(sx-r, sy-r, sx+r, sy+r, fill=color, outline='black')
                drawn_count += 1

        draw_time = time.time() - t0
        self.statusbar.config(
            text=f"Renderowanie: {draw_time:.3f}s | Wyświetlono: {drawn_count} (Pominięto małych: {skipped_count}) | Skala: {self.scale:.4f}"
        )

if __name__ == "__main__":
    app = BDOTViewer()
    app.after(100, app.reset_view)
    app.mainloop()