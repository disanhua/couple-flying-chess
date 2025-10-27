"""Example usage and testing of the geometry processor without database connection.

This script demonstrates the core algorithms used in the geometry processor
without requiring a SQL Server connection. It's useful for understanding
how the simplification algorithm works.
"""

from __future__ import annotations

from typing import List, Tuple

Point = Tuple[float, float]


def parse_linestring(wkt: str) -> List[Point]:
    """Parse a WKT LINESTRING into a list of coordinate tuples."""
    if not wkt:
        raise ValueError("WKT data is empty")

    header = "LINESTRING"
    if not wkt.upper().startswith(header):
        raise ValueError(f"Unsupported geometry type: {wkt}")

    if "EMPTY" in wkt.upper():
        raise ValueError("LINESTRING is empty")

    start = wkt.find("(")
    end = wkt.rfind(")")
    if start == -1 or end == -1 or start >= end:
        raise ValueError(f"Invalid WKT format: {wkt}")

    coordinate_text = wkt[start + 1 : end]
    point_strings = [part.strip() for part in coordinate_text.split(",") if part.strip()]

    points: List[Point] = []
    for point_text in point_strings:
        parts = point_text.split()
        if len(parts) < 2:
            raise ValueError(f"Invalid coordinate point format: {point_text}")
        x_str, y_str = parts[:2]
        points.append((float(x_str), float(y_str)))
    return points


def is_colinear(point_a: Point, point_b: Point, point_c: Point, tolerance: float = 1e-6) -> bool:
    """Check if three points are colinear within a given tolerance.
    
    Uses the cross product method: calculates the area of the triangle
    formed by the three points. If the area is close to zero, the points
    are colinear.
    """
    import math

    if point_a == point_c:
        return True

    line_length = math.hypot(point_c[0] - point_a[0], point_c[1] - point_a[1])
    if line_length == 0:
        return True

    # Calculate area of triangle using cross product
    area = abs(
        (point_b[0] - point_a[0]) * (point_c[1] - point_a[1])
        - (point_b[1] - point_a[1]) * (point_c[0] - point_a[0])
    )
    
    # Distance from point B to line AC
    distance = area / line_length
    return distance <= tolerance


def format_linestring(points: List[Point]) -> str:
    """Format a list of points as a WKT LINESTRING."""
    coordinate_parts = [f"{x:.15f} {y:.15f}" for x, y in points]
    return f"LINESTRING ({', '.join(coordinate_parts)})"


def main() -> None:
    # Example from the ticket
    example_wkt = (
        "LINESTRING (119.62988216935716 34.620537548114697, "
        "119.629876104588249 34.620532364502395, "
        "119.629874536459241 34.620533618145117, "
        "119.62987140129546 34.620536124532379, "
        "119.629869834260688 34.620537377276932, "
        "119.629875897939158 34.620542560886214, "
        "119.62988216935716 34.620537548114697)"
    )

    print("=" * 80)
    print("Geometry Processor Example")
    print("=" * 80)
    print()
    
    print("Original WKT:")
    print(example_wkt)
    print()
    
    points = parse_linestring(example_wkt)
    print(f"Number of points: {len(points)}")
    print()
    
    print("Points:")
    for i, (x, y) in enumerate(points, start=1):
        print(f"  {i}. ({x:.15f}, {y:.15f})")
    print()
    
    print("Collinearity Analysis (tolerance=1e-6):")
    for i in range(1, len(points) - 1):
        prev_point = points[i - 1]
        current_point = points[i]
        next_point = points[i + 1]
        
        colinear = is_colinear(prev_point, current_point, next_point, tolerance=1e-6)
        status = "COLINEAR (can be removed)" if colinear else "NOT colinear (keep)"
        print(f"  Point {i + 1}: {status}")
    print()
    
    print("After simplification:")
    # Simple example - in the actual tool this is more sophisticated
    simplified = [points[0]]
    for i in range(1, len(points) - 1):
        prev_point = points[i - 1]
        current_point = points[i]
        next_point = points[i + 1]
        
        if not is_colinear(prev_point, current_point, next_point, tolerance=1e-6):
            simplified.append(current_point)
    simplified.append(points[-1])
    
    print(f"Reduced from {len(points)} to {len(simplified)} points")
    print()
    
    print("Simplified points:")
    for i, (x, y) in enumerate(simplified, start=1):
        print(f"  {i}. ({x:.15f}, {y:.15f})")
    print()
    
    print("Simplified WKT:")
    print(format_linestring(simplified))
    print()


if __name__ == "__main__":
    main()
