import sys
import os
import time
import xml.etree.ElementTree as ET
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QFileDialog, 
                             QAction, QStatusBar, QHBoxLayout, QVBoxLayout, 
                             QScrollArea, QCheckBox, QLabel, QSplitter)
from PyQt5.QtGui import QPainter, QColor, QPolygonF, QPixmap, QPen, QBrush
from PyQt5.QtCore import Qt, QPointF, QPoint, QThread, pyqtSignal

# ==========================================
# 1. Struktury Danych i Geometria
# ==========================================

class BoundingBox:
    __slots__ = ('min_x', 'max_x', 'min_y', 'max_y') # Optymalizacja pamięciowa klas w Pythonie
    def __init__(self, min_x, max_x, min_y, max_y):
        self.min_x = min_x
        self.max_x = max_x
        self.min_y = min_y
        self.max_y = max_y

    def intersects(self, other):
        if self.max_x < other.min_x or self.min_x > other.max_x:
            return False
        if self.max_y < other.min_y or self.min_y > other.max_y:
            return False
        return True

class Feature:
    __slots__ = ('id', 'category', 'geometry_type', 'coordinates', 'attributes', 'bbox')
    def __init__(self, feature_id, category, geometry_type, coordinates, attributes):
        self.id = feature_id
        self.category = category
        self.geometry_type = geometry_type # '_P', '_L', '_A'
        self.coordinates = coordinates
        self.attributes = attributes
        self.bbox = self._calculate_bbox()

    def _calculate_bbox(self):
        xs = [pt[0] for pt in self.coordinates]
        ys = [pt[1] for pt in self.coordinates]
        return BoundingBox(min(xs), max(xs), min(ys), max(ys))

# ==========================================
# 2. Indeks Przestrzenny (Siatka Regularna)
# ==========================================

class SpatialGrid:
    def __init__(self, cell_size=1000):
        self.cell_size = cell_size
        self.grid = {}
        self.global_bbox = None
        self.categories = set()

    def insert(self, feature):
        self.categories.add(feature.category)
        if self.global_bbox is None:
            self.global_bbox = BoundingBox(feature.bbox.min_x, feature.bbox.max_x, 
                                           feature.bbox.min_y, feature.bbox.max_y)
        else:
            self.global_bbox.min_x = min(self.global_bbox.min_x, feature.bbox.min_x)
            self.global_bbox.max_x = max(self.global_bbox.max_x, feature.bbox.max_x)
            self.global_bbox.min_y = min(self.global_bbox.min_y, feature.bbox.min_y)
            self.global_bbox.max_y = max(self.global_bbox.max_y, feature.bbox.max_y)

        min_col = int(feature.bbox.min_y // self.cell_size)
        max_col = int(feature.bbox.max_y // self.cell_size)
        min_row = int(feature.bbox.min_x // self.cell_size)
        max_row = int(feature.bbox.max_x // self.cell_size)

        for col in range(min_col, max_col + 1):
            for row in range(min_row, max_row + 1):
                cell_id = (col, row)
                if cell_id not in self.grid:
                    self.grid[cell_id] = []
                self.grid[cell_id].append(feature)

    def query(self, view_bbox, active_categories):
        if not active_categories:
            return []
            
        result = set()
        min_col = int(view_bbox.min_y // self.cell_size)
        max_col = int(view_bbox.max_y // self.cell_size)
        min_row = int(view_bbox.min_x // self.cell_size)
        max_row = int(view_bbox.max_x // self.cell_size)

        for col in range(min_col, max_col + 1):
            for row in range(min_row, max_row + 1):
                cell_id = (col, row)
                if cell_id in self.grid:
                    for feature in self.grid[cell_id]:
                        if feature.category in active_categories and feature.bbox.intersects(view_bbox):
                            result.add(feature)
        return list(result)
    
    def clear(self):
        self.grid.clear()
        self.global_bbox = None
        self.categories.clear()

# ==========================================
# 3. Wątek wczytujący dane
# ==========================================

class DataLoaderThread(QThread):
    finished_signal = pyqtSignal(object)

    def __init__(self, folder_path):
        super().__init__()
        self.folder_path = folder_path

    def run(self):
        spatial_index = SpatialGrid()
        for filename in os.listdir(self.folder_path):
            if filename.lower().endswith(".xml") or filename.lower().endswith(".gml"):
                file_path = os.path.join(self.folder_path, filename)
                
                if '__' in filename:
                    category_name = filename.split('__')[1].split('.')[0]
                else:
                    category_name = filename.split('.')[0]
                
                try:
                    context = ET.iterparse(file_path, events=('end',))
                    for event, elem in context:
                        if elem.tag.endswith(category_name): 
                            geom_type = category_name[-2:]
                            coords = []
                            
                            pos_list = None
                            for subelem in elem.iter():
                                if subelem.tag.endswith('posList'):
                                    pos_list = subelem
                                    break
                            
                            if pos_list is not None and pos_list.text:
                                raw_coords = pos_list.text.strip().split()
                                for i in range(0, len(raw_coords) - 1, 2):
                                    try:
                                        coords.append((float(raw_coords[i]), float(raw_coords[i+1])))
                                    except ValueError:
                                        continue
                            
                            if coords:
                                feature_id = 'unknown'
                                for k, v in elem.attrib.items():
                                    if k.endswith('id'):
                                        feature_id = v
                                        break
                                spatial_index.insert(Feature(feature_id, category_name, geom_type, coords, {}))
                            elem.clear()
                except Exception as e:
                    print(f"Błąd {filename}: {e}")
                    
        self.finished_signal.emit(spatial_index)

# ==========================================
# 4. Zoptymalizowany Widok Mapy (Render Cache)
# ==========================================

class MapCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.spatial_index = SpatialGrid()
        self.scale = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.status_bar = None
        
        self.active_categories = set()
        self.buffer_pixmap = None
        self.is_dirty = True
        
        self.last_mouse_pos = None
        self.is_panning = False
        self.setMouseTracking(True)

        # OPTYMALIZACJA 1: Pamięć podręczna (Cache) stylów graficznych (Pędzli i Piór)
        self.style_cache = {}
        self._init_styles()

    def _init_styles(self):
        # Prefabrykowane kolory
        colors = {
            'BU': QColor(220, 20, 60, 200),
            'PT': QColor(34, 139, 34, 150),
            'SW': QColor(30, 144, 255, 200),
            'SK': QColor(112, 128, 144, 200),
            'DEFAULT': QColor(100, 100, 100, 150)
        }
        for key, color in colors.items():
            self.style_cache[key] = {
                'pen': QPen(color, 1),
                'brush': QBrush(color)
            }

    def get_style(self, category):
        for key in ('BU', 'PT', 'SW', 'SK'):
            if key in category:
                return self.style_cache[key]
        return self.style_cache['DEFAULT']

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.buffer_pixmap = QPixmap(self.size())
        self.buffer_pixmap.fill(Qt.white)
        self.is_dirty = True

    def paintEvent(self, event):
        painter = QPainter(self)
        
        if self.is_panning or not self.is_dirty:
            if self.buffer_pixmap:
                painter.drawPixmap(0, 0, self.buffer_pixmap)
            return

        if self.buffer_pixmap is None or self.buffer_pixmap.size() != self.size():
            self.buffer_pixmap = QPixmap(self.size())

        self.buffer_pixmap.fill(Qt.white)
        buf_painter = QPainter(self.buffer_pixmap)
        
        # Wyłączamy Antialiasing dla bardzo dużych skali w celu dalszego przyspieszenia FPS
        if len(self.active_categories) < 10:
            buf_painter.setRenderHint(QPainter.Antialiasing)

        if not self.spatial_index.grid or not self.spatial_index.global_bbox:
            buf_painter.setPen(Qt.black)
            buf_painter.drawText(self.rect(), Qt.AlignCenter, "Brak wczytanych danych. Użyj Plik -> Wczytaj folder...")
            buf_painter.end()
            painter.drawPixmap(0, 0, self.buffer_pixmap)
            return

        start_time = time.time()
        
        min_t_x, min_t_y = self.to_terrain(0, self.height())
        max_t_x, max_t_y = self.to_terrain(self.width(), 0)
        view_bbox = BoundingBox(min_t_x, max_t_x, min_t_y, max_t_y)
        
        visible_features = self.spatial_index.query(view_bbox, self.active_categories)
        drawn_count = 0
        skipped_count = 0

        # OPTYMALIZACJA 2: Rysowanie obiektów z użyciem pamięci podręcznej Pióra i Pędzla
        for feature in visible_features:
            style = self.get_style(feature.category)
            buf_painter.setPen(style['pen'])
            
            screen_coords = [self.to_screen(pt) for pt in feature.coordinates]
            if not screen_coords:
                continue
            
            # Pomijanie mikroskopijnych obiektów
            if len(screen_coords) > 1:
                p1 = screen_coords[0]
                p2 = screen_coords[-1]
                if abs(p1[0] - p2[0]) < 1 and abs(p1[1] - p2[1]) < 1:
                    skipped_count += 1
                    continue

            if feature.geometry_type == '_A':
                polygon = QPolygonF([QPointF(x, y) for x, y in screen_coords])
                buf_painter.setBrush(style['brush'])
                buf_painter.drawPolygon(polygon)
            elif feature.geometry_type == '_L':
                for i in range(len(screen_coords)-1):
                    buf_painter.drawLine(int(screen_coords[i][0]), int(screen_coords[i][1]), 
                                         int(screen_coords[i+1][0]), int(screen_coords[i+1][1]))
            elif feature.geometry_type == '_P':
                buf_painter.setBrush(style['brush'])
                buf_painter.drawEllipse(int(screen_coords[0][0])-2, int(screen_coords[0][1])-2, 4, 4)
            
            drawn_count += 1
            
        buf_painter.end()
        painter.drawPixmap(0, 0, self.buffer_pixmap)
        self.is_dirty = False
        
        render_time = time.time() - start_time
        if self.status_bar:
            self.status_bar.showMessage(f"Widoczne: {drawn_count} | Pominięto małe: {skipped_count} | Czas renderowania: {render_time:.3f}s")

    def wheelEvent(self, event):
        if not self.spatial_index.global_bbox:
            return
        zoom_factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        
        cursor_x, cursor_y = event.x(), event.y()
        terrain_x, terrain_y = self.to_terrain(cursor_x, cursor_y)
        
        self.scale *= zoom_factor
        
        new_cursor_x, new_cursor_y = self.to_screen((terrain_x, terrain_y))
        self.offset_y -= (new_cursor_x - cursor_x) / self.scale
        self.offset_x += (new_cursor_y - cursor_y) / self.scale

        self.is_dirty = True
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_panning = True
            self.last_mouse_pos = event.pos()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_panning = False
            self.is_dirty = True
            self.update()

    def mouseMoveEvent(self, event):
        terrain_x, terrain_y = self.to_terrain(event.x(), event.y())
        if self.status_bar and not self.is_panning:
            self.status_bar.showMessage(f"X (N): {terrain_x:.2f}, Y (E): {terrain_y:.2f}")

        if self.is_panning and self.last_mouse_pos:
            dx = event.x() - self.last_mouse_pos.x()
            dy = event.y() - self.last_mouse_pos.y()
            
            self.offset_y -= dx / self.scale
            self.offset_x += dy / self.scale
            
            self.last_mouse_pos = event.pos()
            self.update()

    def to_screen(self, terrain_pt):
        screen_x = (terrain_pt[1] - self.offset_y) * self.scale
        screen_y = self.height() - (terrain_pt[0] - self.offset_x) * self.scale
        return (screen_x, screen_y)

    def to_terrain(self, screen_x, screen_y):
        terrain_y = (screen_x / self.scale) + self.offset_y
        terrain_x = ((self.height() - screen_y) / self.scale) + self.offset_x
        return (terrain_x, terrain_y)

    def fit_to_extent(self):
        if not self.spatial_index.global_bbox:
            return
            
        bbox = self.spatial_index.global_bbox
        width_terrain = bbox.max_y - bbox.min_y
        height_terrain = bbox.max_x - bbox.min_x
        
        if width_terrain <= 0 or height_terrain <= 0: 
            return

        w = self.width() if self.width() > 1 else 800
        h = self.height() if self.height() > 1 else 600

        scale_x = w / width_terrain
        scale_y = h / height_terrain
        self.scale = min(scale_x, scale_y) * 0.95 

        self.offset_y = bbox.min_y - (w / self.scale - width_terrain) / 2
        self.offset_x = bbox.min_x - (h / self.scale - height_terrain) / 2
        
        self.is_dirty = True
        self.update()

# ==========================================
# 5. Główne Okno Aplikacji
# ==========================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Przeglądarka BDOT10k GML - Zoptymalizowana")
        self.resize(1200, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        side_panel = QWidget()
        side_layout = QVBoxLayout(side_panel)
        side_layout.addWidget(QLabel("<b>Warstwy GML (wyłączone)</b>"))
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.layers_container = QWidget()
        self.layers_layout = QVBoxLayout(self.layers_container)
        self.layers_layout.setAlignment(Qt.AlignTop)
        self.scroll_area.setWidget(self.layers_container)
        side_layout.addWidget(self.scroll_area)
        
        splitter.addWidget(side_panel)

        self.canvas = MapCanvas()
        splitter.addWidget(self.canvas)
        splitter.setSizes([250, 950])

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.canvas.status_bar = self.status_bar

        self._create_menu()
        self.layer_checkboxes = {}

    def _create_menu(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("Plik")

        load_action = QAction("Wczytaj folder z plikami GML...", self)
        load_action.triggered.connect(self.load_data)
        file_menu.addAction(load_action)
        
        fit_action = QAction("Dopasuj do ekranu", self)
        fit_action.triggered.connect(self.canvas.fit_to_extent)
        file_menu.addAction(fit_action)

    def load_data(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Wybierz folder z rozpakowanym BDOT10k")
        if not folder_path:
            return

        self.status_bar.showMessage("Wczytywanie danych w tle...")
        
        self.loader_thread = DataLoaderThread(folder_path)
        self.loader_thread.finished_signal.connect(self.on_data_loaded)
        self.loader_thread.start()

    def on_data_loaded(self, spatial_index):
        self.canvas.spatial_index = spatial_index
        
        for i in reversed(range(self.layers_layout.count())): 
            widget = self.layers_layout.itemAt(i).widget()
            if widget: widget.setParent(None)
        
        self.layer_checkboxes.clear()
        self.canvas.active_categories.clear()

        for cat in sorted(spatial_index.categories):
            cb = QCheckBox(cat)
            cb.setChecked(False)
            cb.stateChanged.connect(self.update_active_layers)
            self.layers_layout.addWidget(cb)
            self.layer_checkboxes[cat] = cb

        self.status_bar.showMessage(f"Wczytano pliki. Zaznacz wybrane warstwy w panelu po lewej.")
        self.canvas.fit_to_extent()

    def update_active_layers(self):
        self.canvas.active_categories.clear()
        for cat, cb in self.layer_checkboxes.items():
            if cb.isChecked():
                self.canvas.active_categories.add(cat)
        
        self.canvas.is_dirty = True
        self.canvas.update()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())