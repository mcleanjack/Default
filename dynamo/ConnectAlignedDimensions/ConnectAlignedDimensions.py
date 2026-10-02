"""
Connect Aligned Dimensions  (Dynamo Python node for Revit)

Pick the parallel dimension strings you want to tie together, then press
Finish on the Options Bar. Wherever two or more of the picked strings have a
witness line at the same position, a detail line is drawn that runs from the
outermost string to the opposite outermost string, so the witness lines read
as one continuous line (e.g. both faces of a 90 mm wall running between an
overall string and a room string).

Inputs
    IN[0]  Line style name (string). Blank or not found = Revit default style.
    IN[1]  Extend past the outer strings by the dimension type's
           "Witness Line Extension" (bool).
Output
    OUT    Report text.

Works with IronPython 2.7, CPython3 and PythonNet3 engines.
"""
import clr
import uuid

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, CurveElement,
                               Dimension, FilteredElementCollector,
                               GraphicsStyleType, Line, Reference)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

LINE_STYLE = IN[0] if len(IN) > 0 and IN[0] else ""
EXTEND = bool(IN[1]) if len(IN) > 1 and IN[1] is not None else True

MM = 1.0 / 304.8            # Revit internal units are feet
POS_TOL = 0.5 * MM          # witness lines closer than this count as aligned
PARALLEL_TOL = 1e-6


def as_linear_dim(el):
    """Return el if it is a straight (linear/aligned) dimension, else None."""
    if el is None or not isinstance(el, Dimension):
        return None
    try:
        crv = el.Curve
    except Exception:       # spot dimensions etc. have no curve
        return None
    if crv is None or not isinstance(crv, Line):
        return None
    return el


class DimensionFilter(ISelectionFilter):
    # PythonNet needs a unique namespace per run; IronPython ignores it.
    __namespace__ = "ConnectAlignedDims_" + uuid.uuid4().hex

    def AllowElement(self, element):
        return as_linear_dim(element) is not None

    def AllowReference(self, reference, position):
        return False


def pick_dimensions():
    """Let the user pick dimensions; anything already selected is pre-picked."""
    pre = List[Reference]()
    for eid in uidoc.Selection.GetElementIds():
        el = as_linear_dim(doc.GetElement(eid))
        if el is not None:
            pre.Add(Reference(el))
    prompt = "Pick the dimension strings to connect, then click Finish"
    try:
        refs = uidoc.Selection.PickObjects(ObjectType.Element, DimensionFilter(),
                                           prompt, pre)
    except OperationCanceledException:
        return None
    dims, seen = [], set()
    for r in refs:
        el = as_linear_dim(doc.GetElement(r.ElementId))
        if el is not None and el.Id.IntegerValue not in seen:
            seen.add(el.Id.IntegerValue)
            dims.append(el)
    return dims


def witness_points(dim):
    """Points on the dimension line where each witness line meets it."""
    d = dim.Curve.Direction.Normalize()
    if dim.NumberOfSegments == 0:
        segs = [(dim.Origin, dim.Value)]
    else:
        segs = [(s.Origin, s.Value) for s in dim.Segments]
    pts = []
    for origin, value in segs:
        if value is None:
            continue
        half = d.Multiply(value / 2.0)
        pts.append(origin.Subtract(half))
        pts.append(origin.Add(half))
    return pts


def witness_extension(dim, view):
    """Witness Line Extension of the dimension's type, in model units."""
    dtype = doc.GetElement(dim.GetTypeId())
    p = None
    try:
        p = dtype.get_Parameter(BuiltInParameter.WITNS_LINE_EXTENSION)
    except Exception:
        pass
    if p is None:
        p = dtype.LookupParameter("Witness Line Extension")
    paper = p.AsDouble() if p is not None else 2.0 * MM
    return paper * view.Scale


def find_line_style(name):
    if not name:
        return None
    cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    for sub in cat.SubCategories:
        if sub.Name.strip().lower() == name.strip().lower():
            return sub.GetGraphicsStyle(GraphicsStyleType.Projection)
    return None


def group_parallel(dims):
    """Group dimensions by owner view and (anti)parallel direction."""
    groups = []
    for dim in dims:
        d = dim.Curve.Direction.Normalize()
        for g in groups:
            if (g["view"] == dim.OwnerViewId.IntegerValue
                    and abs(abs(g["dir"].DotProduct(d)) - 1.0) < PARALLEL_TOL):
                g["dims"].append(dim)
                break
        else:
            groups.append({"view": dim.OwnerViewId.IntegerValue,
                           "dir": d, "dims": [dim]})
    return groups


def existing_lines(view):
    lines = []
    for ce in FilteredElementCollector(doc, view.Id).OfClass(CurveElement):
        c = ce.GeometryCurve
        if c is not None and c.IsBound and isinstance(c, Line):
            lines.append((c.GetEndPoint(0), c.GetEndPoint(1)))
    return lines


def is_duplicate(p0, p1, lines):
    for a, b in lines:
        if ((a.IsAlmostEqualTo(p0, POS_TOL) and b.IsAlmostEqualTo(p1, POS_TOL)) or
                (a.IsAlmostEqualTo(p1, POS_TOL) and b.IsAlmostEqualTo(p0, POS_TOL))):
            return True
    return False


def plan_connections(group, view):
    """Return [(p0, p1)] for every witness position shared by 2+ strings."""
    d = group["dir"]
    perp = view.ViewDirection.CrossProduct(d).Normalize()
    base = group["dims"][0].Curve.Origin

    entries = []                      # (t along dims, s across dims, dim)
    for dim in group["dims"]:
        s = dim.Curve.Origin.Subtract(base).DotProduct(perp)
        ts = sorted(p.Subtract(base).DotProduct(d) for p in witness_points(dim))
        last = None
        for t in ts:
            if last is None or t - last > POS_TOL:
                entries.append((t, s, dim))
            last = t
    entries.sort(key=lambda e: e[0])

    clusters, current = [], []
    for e in entries:
        if current and e[0] - current[-1][0] > POS_TOL:
            clusters.append(current)
            current = []
        current.append(e)
    if current:
        clusters.append(current)

    result = []
    for cl in clusters:
        if len(set(e[2].Id.IntegerValue for e in cl)) < 2:
            continue
        t = sum(e[0] for e in cl) / len(cl)
        lo = min(cl, key=lambda e: e[1])
        hi = max(cl, key=lambda e: e[1])
        s0, s1 = lo[1], hi[1]
        if s1 - s0 < POS_TOL:         # collinear strings, nothing to join
            continue
        if EXTEND:
            s0 -= witness_extension(lo[2], view)
            s1 += witness_extension(hi[2], view)
        along = base.Add(d.Multiply(t))
        result.append((along.Add(perp.Multiply(s0)), along.Add(perp.Multiply(s1))))
    return result


report = []
dims = pick_dimensions()
if dims is None:
    OUT = "Cancelled - nothing changed."
elif len(dims) < 2:
    OUT = "Pick at least two parallel dimension strings."
else:
    style = find_line_style(LINE_STYLE)
    if LINE_STYLE and style is None:
        report.append("Line style '{0}' not found - default used.".format(LINE_STYLE))
    created = skipped = 0
    TransactionManager.Instance.EnsureInTransaction(doc)
    for g in group_parallel(dims):
        if len(g["dims"]) < 2:
            continue
        view = doc.GetElement(g["dims"][0].OwnerViewId)
        existing = existing_lines(view)
        for p0, p1 in plan_connections(g, view):
            if is_duplicate(p0, p1, existing):
                skipped += 1
                continue
            curve = doc.Create.NewDetailCurve(view, Line.CreateBound(p0, p1))
            if style is not None:
                curve.LineStyle = style
            existing.append((p0, p1))
            created += 1
    TransactionManager.Instance.TransactionTaskDone()
    report.insert(0, "{0} dimension(s) picked, {1} connecting line(s) created, "
                     "{2} already existed.".format(len(dims), created, skipped))
    OUT = "\n".join(report)
