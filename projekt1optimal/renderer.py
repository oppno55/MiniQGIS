import tkinter as tk
import math

class MapRenderer:
    def __init__(self, canvas, styles_json):
        self.canvas = canvas
        self.styles = styles_json
        self.drawn_count = 0
        self.hidden_count = 0

    def render(self, features, app_layers, v_min_x, v_min_y, scale, cw, ch):
        self.canvas.delete("all")
        self.drawn_count = 0
        self.hidden_count = 0
        
        z_order = self.styles.get('Z_ORDER', [])
        features.sort(key=lambda f: z_order.index(f.category) if f.category in z_order else -1)

        for f in features:
            l_props = app_layers.get(f.layer)
            if scale < 0.1 and f.layer in ('BUBD_A', 'OIPR_P', 'SUPS_L'):
                self.hidden_count += 1
                continue

            style_def = self.styles.get(f.layer, {})
            attr_key = style_def.get('attr')
            rule = style_def.get('rules', {}).get(f.attrs.get(attr_key, ''), style_def.get('default', {}))
            
            ui_color, ui_width = l_props['color'], l_props['width'].get()
            geom_type = l_props['type']
            
            for part in f.parts:
                screen_coords = []
                for mx, my in part['pts']:
                    screen_coords.extend([(mx - v_min_x) * scale, ch - ((my - v_min_y) * scale)])

                if geom_type == 'polygon' and len(screen_coords) >= 6:
                    self._draw_polygon(screen_coords, part['is_interior'], f.category, rule, ui_color, ui_width, scale)
                elif geom_type == 'line' and len(screen_coords) >= 4:
                    self._draw_line(screen_coords, rule, ui_color, ui_width, scale)
                elif geom_type == 'point' and len(screen_coords) >= 2:
                    self._draw_point(screen_coords, f.attrs, rule, ui_color, ui_width, scale)

    def _draw_polygon(self, coords, is_interior, category, rule, ui_color, ui_width, scale):
        if is_interior:
            self.canvas.create_polygon(*coords, fill='#f5f5f5', outline='')
        else:
            # Granice administracyjne (AD), tereny chronione (TC) i kompleksy (KU) rysujemy bez wypełnienia
            if category in ('AD', 'TC', 'KU'):
                fill = rule.get('fill', '')
                outline = rule.get('outline', ui_color)
            else:
                fill = rule.get('fill', ui_color)
                outline = rule.get('outline', 'black') if scale > 0.2 else ''

            kwargs = {'fill': fill, 'outline': outline, 'width': ui_width}
            if rule.get('stipple'):
                kwargs['stipple'] = rule['stipple']
            if rule.get('dash'):
                kwargs['dash'] = rule['dash']

            self.canvas.create_polygon(*coords, **kwargs)
        self.drawn_count += 1

    def _draw_line(self, coords, rule, ui_color, ui_width, scale):
        w_px = max(1, rule.get('width_mm', ui_width) * 10.0 * scale)
        fill, outline = rule.get('fill', ''), rule.get('outline', ui_color)
        
        if rule.get('double', False) and fill:
            self.canvas.create_line(*coords, fill=outline, width=w_px+2, capstyle=tk.ROUND, joinstyle=tk.ROUND)
            self.canvas.create_line(*coords, fill=fill, width=w_px, capstyle=tk.ROUND, joinstyle=tk.ROUND)
        else:
            kwargs = {'fill': outline, 'width': w_px}
            if rule.get('dash'):
                kwargs['dash'] = rule['dash']
            self.canvas.create_line(*coords, **kwargs)
        
        if 'decoration' in rule and scale > 0.5:
            self._draw_line_decorations(coords, rule['decoration'], rule.get('dec_spacing', 20), outline)
        self.drawn_count += 1

    def _draw_line_decorations(self, coords, dec_type, spacing, color):
        pts = [(coords[i], coords[i+1]) for i in range(0, len(coords), 2)]
        for i in range(len(pts)-1):
            x1, y1 = pts[i]
            x2, y2 = pts[i+1]
            dist = math.hypot(x2 - x1, y2 - y1)
            if dist == 0: continue
            
            steps = int(dist // spacing)
            for j in range(1, steps + 1):
                t = (j * spacing) / dist
                px, py = x1 + t*(x2-x1), y1 + t*(y2-y1)
                if dec_type == 'tick':
                    angle = math.atan2(y2 - y1, x2 - x1)
                    dx, dy = math.sin(angle) * 4, math.cos(angle) * 4
                    self.canvas.create_line(px - dx, py + dy, px + dx, py - dy, fill=color, width=1)

    def _draw_point(self, coords, attrs, rule, ui_color, ui_width, scale):
        size_px = max(3, rule.get('size_mm', 2.0 * ui_width) * 10.0 * scale)
        shape, color = rule.get('shape', 'circle'), rule.get('color', ui_color)
        px_x, px_y, r = coords[0], coords[1], size_px / 2
        
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
        self.drawn_count += 1