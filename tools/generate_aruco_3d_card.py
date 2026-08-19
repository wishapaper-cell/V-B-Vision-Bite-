from __future__ import annotations

import argparse
import struct
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw


CARD_SIZE_MM = 50.0
CARD_HEIGHT_MM = 0.8
RECESS_DEPTH_MM = 0.2
SEAM_HALF_WIDTH_MM = 0.04
MARKER_ID = 23
GRID_SIZE = 7  # 5x5 payload plus a one-cell black border.


def marker_matrix(opencv_path: Path) -> np.ndarray:
    sys.path.insert(0, str(opencv_path))
    import cv2  # type: ignore

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_100)
    image = cv2.aruco.generateImageMarker(dictionary, MARKER_ID, GRID_SIZE, borderBits=1)
    return (image > 127).astype(np.uint8)


def add_quad(vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]], a, b, c, d) -> None:
    start = len(vertices)
    vertices.extend((a, b, c, d))
    faces.extend(((start, start + 1, start + 2), (start, start + 2, start + 3)))


def voxel_mesh(x_edges: list[float], y_edges: list[float], z_edges: list[float], occupied: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Create a boundary mesh from a rectilinear occupied-voxel grid."""
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    nz, ny, nx = occupied.shape
    for iz in range(nz):
        z0, z1 = z_edges[iz], z_edges[iz + 1]
        for iy in range(ny):
            y0, y1 = y_edges[iy], y_edges[iy + 1]
            for ix in range(nx):
                if not occupied[iz, iy, ix]:
                    continue
                x0, x1 = x_edges[ix], x_edges[ix + 1]
                if iz == nz - 1 or not occupied[iz + 1, iy, ix]:
                    add_quad(vertices, faces, (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
                if iz == 0 or not occupied[iz - 1, iy, ix]:
                    add_quad(vertices, faces, (x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0))
                if ix == 0 or not occupied[iz, iy, ix - 1]:
                    add_quad(vertices, faces, (x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1))
                if ix == nx - 1 or not occupied[iz, iy, ix + 1]:
                    add_quad(vertices, faces, (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))
                if iy == ny - 1 or not occupied[iz, iy + 1, ix]:
                    add_quad(vertices, faces, (x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1))
                if iy == 0 or not occupied[iz, iy - 1, ix]:
                    add_quad(vertices, faces, (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))
    return np.asarray(vertices, dtype=np.float32), np.asarray(faces, dtype=np.uint32)


def card_meshes(matrix: np.ndarray) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """Build a manifold white body and black inlays separated by 0.08 mm print seams."""
    cell = CARD_SIZE_MM / GRID_SIZE
    edges = {0.0, CARD_SIZE_MM}
    for index in range(1, GRID_SIZE):
        boundary = index * cell
        edges.add(boundary - SEAM_HALF_WIDTH_MM)
        edges.add(boundary + SEAM_HALF_WIDTH_MM)
    x_edges = sorted(edges)
    y_edges = sorted(edges)
    z_edges = [0.0, CARD_HEIGHT_MM - RECESS_DEPTH_MM, CARD_HEIGHT_MM]
    nx, ny = len(x_edges) - 1, len(y_edges) - 1
    body = np.zeros((2, ny, nx), dtype=bool)
    black = np.zeros((2, ny, nx), dtype=bool)
    body[0, :, :] = True

    boundaries = [index * cell for index in range(1, GRID_SIZE)]
    for iy in range(ny):
        cy = (y_edges[iy] + y_edges[iy + 1]) / 2
        row = GRID_SIZE - 1 - min(GRID_SIZE - 1, int(cy / cell))
        on_y_seam = any(abs(cy - boundary) < SEAM_HALF_WIDTH_MM for boundary in boundaries)
        for ix in range(nx):
            cx = (x_edges[ix] + x_edges[ix + 1]) / 2
            col = min(GRID_SIZE - 1, int(cx / cell))
            on_x_seam = any(abs(cx - boundary) < SEAM_HALF_WIDTH_MM for boundary in boundaries)
            is_black_interior = matrix[row, col] == 0 and not on_x_seam and not on_y_seam
            body[1, iy, ix] = not is_black_interior
            black[1, iy, ix] = is_black_interior
    return voxel_mesh(x_edges, y_edges, z_edges, body), voxel_mesh(x_edges, y_edges, z_edges, black)


def write_binary_stl(path: Path, vertices: np.ndarray, faces: np.ndarray, title: str) -> None:
    header = title.encode("ascii", errors="replace")[:80].ljust(80, b" ")
    with path.open("wb") as stream:
        stream.write(header)
        stream.write(struct.pack("<I", len(faces)))
        for face in faces:
            a, b, c = vertices[face]
            normal = np.cross(b - a, c - a)
            length = float(np.linalg.norm(normal))
            if length:
                normal = normal / length
            stream.write(struct.pack("<12fH", *(normal.tolist() + a.tolist() + b.tolist() + c.tolist()), 0))


def write_3mf(path: Path, meshes: list[tuple[np.ndarray, np.ndarray, int]]) -> None:
    ns = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    ET.register_namespace("", ns)
    model = ET.Element(f"{{{ns}}}model", {"unit": "millimeter", "xml:lang": "zh-CN"})
    resources = ET.SubElement(model, f"{{{ns}}}resources")
    materials = ET.SubElement(resources, f"{{{ns}}}basematerials", {"id": "1"})
    ET.SubElement(materials, f"{{{ns}}}base", {"name": "White PLA", "displaycolor": "#F5F5F5FF"})
    ET.SubElement(materials, f"{{{ns}}}base", {"name": "Black PLA", "displaycolor": "#101010FF"})
    build = ET.SubElement(model, f"{{{ns}}}build")

    for object_id, (vertices, faces, material_index) in enumerate(meshes, start=2):
        obj = ET.SubElement(resources, f"{{{ns}}}object", {
            "id": str(object_id), "type": "model", "pid": "1", "pindex": str(material_index),
            "name": "white_card_body" if material_index == 0 else "black_marker_inlay",
        })
        mesh = ET.SubElement(obj, f"{{{ns}}}mesh")
        verts_xml = ET.SubElement(mesh, f"{{{ns}}}vertices")
        for x, y, z in vertices:
            ET.SubElement(verts_xml, f"{{{ns}}}vertex", {"x": f"{x:.6f}", "y": f"{y:.6f}", "z": f"{z:.6f}"})
        tris_xml = ET.SubElement(mesh, f"{{{ns}}}triangles")
        for v1, v2, v3 in faces:
            ET.SubElement(tris_xml, f"{{{ns}}}triangle", {"v1": str(v1), "v2": str(v2), "v3": str(v3)})
        ET.SubElement(build, f"{{{ns}}}item", {"objectid": str(object_id)})

    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""
    model_xml = ET.tostring(model, encoding="utf-8", xml_declaration=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types)
        package.writestr("_rels/.rels", relationships)
        package.writestr("3D/3dmodel.model", model_xml)


def write_preview(path: Path, matrix: np.ndarray) -> None:
    margin = 140
    marker_px = 700
    cell = marker_px // GRID_SIZE
    image = Image.new("RGB", (marker_px + margin * 2, marker_px + margin * 2), "white")
    draw = ImageDraw.Draw(image)
    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            color = "white" if matrix[row, col] else "black"
            x0, y0 = margin + col * cell, margin + row * cell
            x1 = margin + (col + 1) * cell
            y1 = margin + (row + 1) * cell
            draw.rectangle((x0, y0, x1, y1), fill=color)
    draw.text((margin, 38), "ArUco DICT_5X5_100  ID 23  |  physical marker: 50 x 50 mm", fill="black")
    image.save(path)


def write_scad(path: Path, matrix: np.ndarray) -> None:
    rows = ",\n  ".join("[" + ", ".join(str(int(v)) for v in row) + "]" for row in matrix)
    content = f"""// V&B 50 mm ArUco calibration card, ID 23
card = {CARD_SIZE_MM};
height = {CARD_HEIGHT_MM};
recess = {RECESS_DEPTH_MM};
grid = [
  {rows}
];
cell = card / 7;

// White body; paint the recessed cells matte black.
union() {{
  cube([card, card, height-recess]);
  for (r=[0:6]) for (c=[0:6]) if (grid[r][c] == 1)
    translate([c*cell, (6-r)*cell, height-recess]) cube([cell, cell, recess]);
}}
"""
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opencv-path", type=Path, default=Path(".tmp_opencv"))
    parser.add_argument("--output-dir", type=Path, default=Path("assets/calibration_card_3d"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    matrix = marker_matrix(args.opencv_path)
    (body_v, body_f), (black_v, black_f) = card_meshes(matrix)

    write_binary_stl(args.output_dir / "VB_aruco_ID23_50mm_single_piece_recessed.stl", body_v, body_f, "V&B ArUco ID23 50mm recessed")
    write_binary_stl(args.output_dir / "VB_aruco_ID23_50mm_white_body.stl", body_v, body_f, "V&B ArUco ID23 50mm white body")
    write_binary_stl(args.output_dir / "VB_aruco_ID23_50mm_black_inlay.stl", black_v, black_f, "V&B ArUco ID23 50mm black inlay")
    write_3mf(args.output_dir / "VB_aruco_ID23_50mm_two_color.3mf", [(body_v, body_f, 0), (black_v, black_f, 1)])
    write_preview(args.output_dir / "VB_aruco_ID23_50mm_preview.png", matrix)
    write_scad(args.output_dir / "VB_aruco_ID23_50mm_source.scad", matrix)
    np.savetxt(args.output_dir / "marker_matrix_ID23.txt", matrix, fmt="%d")


if __name__ == "__main__":
    main()
