class Feature:
    def __init__(self, f_id, layer, category, parts, bbox, attrs):
        self.id = f_id
        self.layer = layer
        self.category = category
        self.parts = parts
        self.bbox = bbox
        self.attrs = attrs

    def contains_point(self, map_x, map_y, geom_type, tol_map):
        for part in self.parts:
            pts = part['pts']
            if geom_type == 'polygon' and len(pts) >= 3:
                if self._is_point_in_polygon(map_x, map_y, pts):
                    return True
            elif geom_type == 'line' and len(pts) >= 2:
                for i in range(len(pts)-1):
                    if self._dist_to_segment(map_x, map_y, pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1]) <= tol_map:
                        return True
            elif geom_type == 'point' and len(pts) >= 1:
                if ((pts[0][0]-map_x)**2 + (pts[0][1]-map_y)**2)**0.5 <= tol_map:
                    return True
        return False

    @staticmethod
    def _is_point_in_polygon(x, y, poly):
        n = len(poly)
        inside = False
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

    @staticmethod
    def _dist_to_segment(px, py, x1, y1, x2, y2):
        l2 = (x1 - x2)**2 + (y1 - y2)**2
        if l2 == 0: return ((px - x1)**2 + (py - y1)**2)**0.5
        t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / l2))
        return ((px - (x1 + t * (x2 - x1)))**2 + (py - (y1 + t * (y2 - y1))))**0.5


class SpatialGrid:
    def __init__(self, cell_size=1000):
        self.cell_size = cell_size
        self.cells = {}
        self.features = {}

    def add_feature(self, feature):
        self.features[feature.id] = feature
        min_x, max_x, min_y, max_y = feature.bbox
        for col in range(int(min_x // self.cell_size), int(max_x // self.cell_size) + 1):
            for row in range(int(min_y // self.cell_size), int(max_y // self.cell_size) + 1):
                cell_id = (col, row)
                if cell_id not in self.cells:
                    self.cells[cell_id] = []
                self.cells[cell_id].append(feature.id)

    def get_features_in_view(self, v_min_x, v_max_x, v_min_y, v_max_y, active_layers):
        visible = set()
        for col in range(int(v_min_x // self.cell_size), int(v_max_x // self.cell_size) + 1):
            for row in range(int(v_min_y // self.cell_size), int(v_max_y // self.cell_size) + 1):
                if (col, row) in self.cells:
                    for f_id in self.cells[(col, row)]:
                        if f_id in visible: continue
                        f = self.features[f_id]
                        if f.layer not in active_layers: continue
                        
                        f_min_x, f_max_x, f_min_y, f_max_y = f.bbox
                        if not (f_max_x < v_min_x or f_min_x > v_max_x or f_max_y < v_min_y or f_min_y > v_max_y):
                            visible.add(f_id)
        return [self.features[f_id] for f_id in visible]

    def get_global_bbox(self):
        if not self.features: return (0, 100, 0, 100)
        return (
            min(f.bbox[0] for f in self.features.values()), 
            max(f.bbox[1] for f in self.features.values()),
            min(f.bbox[2] for f in self.features.values()), 
            max(f.bbox[3] for f in self.features.values())
        )