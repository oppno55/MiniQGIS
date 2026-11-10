import sys
import xml.etree.ElementTree as ET
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QFileDialog, QStatusBar
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QPolygonF
from PyQt5.QtCore import Qt, QPointF

class BoundingBox:
    def __init__(self, min_x=float('inf'), min_y=float('inf'), max_x=float('-inf'), max_y=float('-inf')):
        self.min_x = min_x
        self.min_y = min_y
        self.max_x = max_x
        self.max_y = max_y

    def expand(self, x, y):
        if x < self.min_x: self.min_x = x
        if x > self.max_x: self.max_x = x
        if y < self.min_y: self.min_y = y
        if y > self.max_y: self.max_y = y

    def intersects(self, other):
        if self.max_x < other.min_x or self.min_x > other.max_x: return False
        if self.max_y < other.min_y or self.min_y > other.max_y: return False
        return True

class Feature:
    def __init__(self, category, geom_type, coords):
        self.category = category 
        self.geom_type = geom_type
        self.coords = coords
        self.bbox = BoundingBox()
        self._calculate_bbox()

    def _calculate_bbox(self):
        for pt in self.coords:
            if isinstance(pt, list):
                for p in pt:
                    self.bbox.expand(p[0], p[1])
            else:
                self.bbox.expand(pt[0], pt[1])

class SpatialIndex:
    def __init__(self):
        self.objects = []

    def insert(self, feature):
        self.objects.append(feature)

    def query(self, bbox):
        return [f for f in self.objects if f.bbox.intersects(bbox)]

class GMLParser:
    @staticmethod
    def parse_file(filepath):
        features = []
        context = ET.iterparse(filepath, events=('end',))
        
        for event, elem in context:
            if 'posList' in elem.tag or 'pos' in elem.tag:
                if elem.text is None:
                    continue
                    
                coords_raw = elem.text.strip().split()
                coords = []
                for i in range(0, len(coords_raw), 2):
                    if i + 1 < len(coords_raw):
                        x = float(coords_raw[i])     
                        y = float(coords_raw[i+1])   
                        coords.append((x, y))
                
                geom_type = '_A' if 'Polygon' in filepath or len(coords) > 2 else '_L'
                if 'Point' in filepath or len(coords) == 1:
                    geom_type = '_P'
                    
                # Pobranie kategorii z nazwy pliku (np. OT_BUBD_A.xml -> BU)
                filename = filepath.split('/')[-1].split('\\')[-1]
                category = filename[3:5] if len(filename) >= 5 else 'UN'
                
                features.append(Feature(category, geom_type, coords))
                elem.clear()
                
        return features

class MapCanvas(QWidget):
    def __init__(self, status_bar):
        super().__init__()
        self.status_bar = status_bar
        self.spatial_index = SpatialIndex()
        self.features = []
        
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        
        self.drag_start = None
        self.global_bbox = BoundingBox()
        
        self.colors = {
            'BU': QColor(255, 0, 0),    
            'PT': QColor(0, 255, 0),    
            'SW': QColor(0, 0, 255),    
            'SK': QColor(100, 100, 100),
            'default': QColor(150, 150, 150)
        }

    def load_data(self, filepath):
        self.status_bar.showMessage(f"Wczytywanie: {filepath}...")
        QApplication.processEvents()
        
        new_features = GMLParser.parse_file(filepath)
        for f in new_features:
            self.features.append(f)
            self.spatial_index.insert(f)
            self.global_bbox.expand(f.bbox.min_x, f.bbox.min_y)
            self.global_bbox.expand(f.bbox.max_x, f.bbox.max_y)
            
        self.fit_to_screen()
        self.update()
        self.status_bar.showMessage(f"Wczytano {len(new_features)} obiektów.")

    def fit_to_screen(self):
        if not self.features: return
        
        w = self.width()
        h = self.height()
        
        bbox_w = self.global_bbox.max_y - self.global_bbox.min_y
        bbox_h = self.global_bbox.max_x - self.global_bbox.min_x
        
        scale_x = w / bbox_w if bbox_w > 0 else 1
        scale_y = h / bbox_h if bbox_h > 0 else 1
        self.scale = min(scale_x, scale_y) * 0.9 
        
        self.offset_y = -self.global_bbox.min_y * self.scale + (w - bbox_w * self.scale) / 2
        self.offset_x = self.global_bbox.max_x * self.scale + (h - bbox_h * self.scale) / 2

    def to_screen(self, x, y):
        screen_x = y * self.scale + self.offset_y
        screen_y = -x * self.scale + self.offset_x
        return screen_x, screen_y

    def to_map(self, screen_x, screen_y):
        y = (screen_x - self.offset_y) / self.scale
        x = -(screen_y - self.offset_x) / self.scale
        return x, y

    def paintEvent(self, event):
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.white)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Pusty BBox pokrywający wszystko - w wariancie podstawowym rysujemy wszystkie wczytane dane
        view_bbox = BoundingBox(-float('inf'), -float('inf'), float('inf'), float('inf'))
        visible_features = self.spatial_index.query(view_bbox)
        
        for feature in visible_features:
            color = self.colors.get(feature.category, self.colors['default'])
            painter.setPen(QPen(color, 1))
            
            if feature.geom_type == '_P':
                sx, sy = self.to_screen(feature.coords[0][0], feature.coords[0][1])
                painter.setBrush(QBrush(color))
                painter.drawEllipse(QPointF(sx, sy), 3, 3) 
                
            elif feature.geom_type == '_L':
                for i in range(len(feature.coords)-1):
                    sx1, sy1 = self.to_screen(feature.coords[i][0], feature.coords[i][1])
                    sx2, sy2 = self.to_screen(feature.coords[i+1][0], feature.coords[i+1][1])
                    painter.drawLine(QPointF(sx1, sy1), QPointF(sx2, sy2))
                    
            elif feature.geom_type == '_A':
                painter.setBrush(QBrush(color))
                poly = QPolygonF()
                for pt in feature.coords:
                    if isinstance(pt, tuple):
                        sx, sy = self.to_screen(pt[0], pt[1])
                        poly.append(QPointF(sx, sy))
                painter.drawPolygon(poly)
                
        painter.end()
        
        screen_painter = QPainter(self)
        screen_painter.drawPixmap(0, 0, pixmap)

    def wheelEvent(self, event):
        zoom_factor = 1.1 if event.angleDelta().y() > 0 else 0.9
        
        mouse_pos = event.pos()
        map_x, map_y = self.to_map(mouse_pos.x(), mouse_pos.y())
        
        self.scale *= zoom_factor
        
        new_screen_x, new_screen_y = self.to_screen(map_x, map_y)
        self.offset_y -= (new_screen_x - mouse_pos.x())
        self.offset_x -= (new_screen_y - mouse_pos.y())
        
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start = event.pos()

    def mouseMoveEvent(self, event):
        x, y = self.to_map(event.pos().x(), event.pos().y())
        self.status_bar.showMessage(f"X (Północ): {x:.2f} | Y (Wschód): {y:.2f}")

        if self.drag_start is not None:
            delta = event.pos() - self.drag_start
            self.offset_y += delta.x()
            self.offset_x += delta.y()
            self.drag_start = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start = None

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("BDOT10k Viewer")
        self.resize(1024, 768)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.canvas = MapCanvas(self.status_bar)
        self.setCentralWidget(self.canvas)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    
    # Automatyczne otwarcie okna dialogowego do wyboru pliku GML po uruchomieniu aplikacji
    filepath, _ = QFileDialog.getOpenFileName(window, "Wybierz plik GML BDOT10k", "", "GML Files (*.gml *.xml);;All Files (*)")
    if filepath:
        window.canvas.load_data(filepath)
        
    sys.exit(app.exec_())