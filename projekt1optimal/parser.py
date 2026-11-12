import xml.etree.ElementTree as ET
import os
import re
import zipfile
import tkinter as tk
from models import Feature

class BdotParser:
    def __init__(self, grid, app_layers, styles):
        self.grid = grid
        self.app_layers = app_layers
        self.styles = styles
        self.feature_id_counter = 0

    def parse_path(self, path):
        if os.path.isdir(path):
            for fname in os.listdir(path):
                if fname.lower().endswith(('.gml', '.xml')):
                    with open(os.path.join(path, fname), 'rb') as f:
                        self._process_file(f, fname)
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, 'r') as zf:
                for fname in zf.namelist():
                    if fname.lower().endswith(('.gml', '.xml')):
                        with zf.open(fname) as f:
                            self._process_file(f, fname.split('/')[-1])
        return self.feature_id_counter

    def _process_file(self, file_obj, filename):
        parts = filename.replace('.xml', '').replace('.gml', '').split('_')
        layer_code = "_".join(parts[-2:]) if len(parts) >= 2 else filename.split('.')[0]
        category = layer_code[:2] if len(layer_code) >= 2 else "IN"
        geom_type = 'polygon' if '_A' in layer_code else ('line' if '_L' in layer_code else 'point')
        
        def_colors = {
            'BU': '#e68a8a',
            'PT': '#d9f0d3',
            'SW': '#33aaff',
            'SK': '#555555',
            'SU': '#d95f02',
            'TC': '#238b45',
            'KU': '#df65b0',
            'AD': '#7b3294',
            'OI': '#e7298a',
            'RT': '#a6761d'
        }
        if layer_code not in self.app_layers:
            self.app_layers[layer_code] = {
                'code': layer_code, 'category': category, 'visible': tk.BooleanVar(value=True),
                'type': geom_type, 'color': def_colors.get(category, '#888888'), 'width': tk.IntVar(value=1)
            }

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
                        if pts: feature_parts.append({'pts': pts, 'is_interior': is_interior})
                    elem.clear()
                    
                elif inside_feature and tag not in ('posList', 'pos', 'LinearRing', 'Polygon', 'LineString', 'Point', 'geometria', 'exterior', 'interior', 'MultiSurface', 'surfaceMember', 'featureMember'):
                    val = None
                    if elem.text and elem.text.strip() and len(elem.text.strip()) < 100:
                        val = elem.text.strip()
                    else:
                        for k, v in elem.attrib.items():
                            if k.endswith('href'):
                                val = re.split(r'[:#/]', v)[-1]
                                break
                    if val:
                        current_attrs[tag] = val
                        
                if tag.startswith('OT_') and inside_feature:
                    if feature_parts:
                        all_x = [p[0] for part in feature_parts for p in part['pts']]
                        all_y = [p[1] for part in feature_parts for p in part['pts']]
                        if all_x and all_y:
                            feat = Feature(
                                self.feature_id_counter, layer_code, category, 
                                list(feature_parts),
                                (min(all_x), max(all_x), min(all_y), max(all_y)),
                                dict(current_attrs)
                            )
                            self.grid.add_feature(feat)
                            self.feature_id_counter += 1
                    inside_feature = False
                    feature_parts.clear()
                    current_attrs.clear()
                    elem.clear()