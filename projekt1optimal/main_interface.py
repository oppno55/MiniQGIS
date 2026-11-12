import os
import json
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser

from models import SpatialGrid
from parser import BdotParser
from renderer import MapRenderer

class BDOTViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("BDOT10k GIS Viewer - Zaawansowany Wariant")
        self.geometry("1300x800")
        
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            json_path = os.path.join(script_dir, 'styles.json')
            with open(json_path, 'r', encoding='utf-8') as f:
                self.styles_config = json.load(f)
        except Exception as e:
            messagebox.showerror("Błąd", f"Nie można wczytać styles.json: {e}")
            self.styles_config = {}

        self.layers = {}
        self.scale = 1.0
        self.view_min_x = 0.0
        self.view_min_y = 0.0
        self.grid_index = SpatialGrid()
        self.is_panning = False
        
        self.setup_ui()
        self.renderer = MapRenderer(self.canvas, self.styles_config)

    def setup_ui(self):
        self.toolbar = tk.Frame(self, bg="#dddddd")
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        tk.Button(self.toolbar, text="Wczytaj Folder GML/XML", command=self.load_dir).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(self.toolbar, text="Wczytaj plik ZIP", command=self.load_zip).pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(self.toolbar, text="Widok całości (Powiat)", command=self.reset_view).pack(side=tk.LEFT, padx=5, pady=5)
        
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

        self.statusbar = tk.Label(self, text="Gotowy. Wczytaj dane...", bd=1, relief=tk.SUNKEN, anchor=tk.W)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.canvas = tk.Canvas(self, bg="#f5f5f5", cursor="crosshair")
        self.canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
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
        self.statusbar.config(text="Ładowanie danych...")
        self.update()
        self.layers.clear()
        self.grid_index = SpatialGrid()
        parser = BdotParser(self.grid_index, self.layers, self.styles_config)
        count = parser.parse_path(path)
        self.build_layers_ui()
        self.reset_view()
        messagebox.showinfo("Sukces", f"Pomyślnie wczytano obiekty: {count}")

    def build_layers_ui(self):
        for w in self.layer_frame.winfo_children(): w.destroy()
        tk.Label(self.layer_frame, text="Zarządzanie Warstwami", font=("Arial", 11, "bold"), bg="white").pack(pady=5)
        
        all_cats = list(self.styles_config.get('Z_ORDER', []))
        for c_data in self.layers.values():
            if c_data['category'] not in all_cats:
                all_cats.append(c_data['category'])

        for cat in all_cats:
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
            self.layers[layer_code]['color'] = color
            btn.config(bg=color)
            self.draw()

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
        if self.is_panning: 
            self.draw()
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
        map_x = (screen_x / self.scale) + self.view_min_x
        map_y = self.view_min_y + (self.canvas.winfo_height() - screen_y) / self.scale
        tol_map = 5 / self.scale
        
        active = {k for k, v in self.layers.items() if v['visible'].get()}
        candidates = self.grid_index.get_features_in_view(map_x-tol_map, map_x+tol_map, map_y-tol_map, map_y+tol_map, active)
        
        found = None
        for f in reversed(candidates):
            geom_type = self.layers[f.layer]['type']
            if f.contains_point(map_x, map_y, geom_type, tol_map):
                found = f
                break
                    
        if found:
            info = "\n".join([f"{k}: {v}" for k, v in found.attrs.items()])
            messagebox.showinfo(f"Identyfikacja obiektu: {found.layer}", info if info else "Brak atrybutów.")

    def draw(self):
        t0 = time.time()
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        v_min_x, v_max_x = self.view_min_x, self.view_min_x + (cw / self.scale)
        v_min_y, v_max_y = self.view_min_y, self.view_min_y + (ch / self.scale)
        
        active = {k for k, v in self.layers.items() if v['visible'].get()}
        visible_features = self.grid_index.get_features_in_view(v_min_x, v_max_x, v_min_y, v_max_y, active)
        
        self.renderer.render(visible_features, self.layers, self.view_min_x, self.view_min_y, self.scale, cw, ch)
        
        t1 = time.time() - t0
        self.statusbar.config(text=f"Renderowanie: {t1:.3f}s | Obiekty: {self.renderer.drawn_count} (Ukryte sub-skala: {self.renderer.hidden_count}) | Skala: {self.scale:.2f}")

if __name__ == "__main__":
    app = BDOTViewer()
    app.mainloop()