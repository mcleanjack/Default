"""
Connect Aligned Dimensions  (Dynamo Python node for Revit)

Pick the parallel dimension strings you want to tie together, then press
Finish on the Options Bar. Wherever two or more of the picked strings have a
witness line at the same position, a detail line is drawn that runs from the
outermost string to the opposite outermost string, so the witness lines read
as one continuous line (e.g. both faces of a 90 mm wall running between an
overall string and a room string).

Optionally, when the same segment (same start and end witness lines) appears
in more than one picked string, it is removed from every string except the
one furthest from the building. Revit cannot delete a segment from the middle
of a string, so the inner string is rebuilt as separate strings either side of
the removed segment, keeping each segment's text overrides.

Inputs
    IN[0]  Line style name (string). Blank or not found = Revit default style.
    IN[1]  Extend past the outer strings by the dimension type's
           "Witness Line Extension" (bool).
    IN[2]  Remove duplicate segments from the inner strings (bool).
    IN[3]  Only remove duplicates longer than this, in mm (number). The
           default 90 keeps 90 mm walls on every string but removes thicker
           walls (e.g. 240) and rooms. Walls this short that are left with
           no room either side after the removal are deleted as well, and
           the number on the rest is hidden where an outer string shows it.
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
                               GraphicsStyleType, Line, Reference,
                               ReferenceArray)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

LINE_STYLE = IN[0] if len(IN) > 0 and IN[0] else ""
EXTEND = bool(IN[1]) if len(IN) > 1 and IN[1] is not None else True
REMOVE_DUPES = bool(IN[2]) if len(IN) > 2 and IN[2] is not None else True

MM = 1.0 / 304.8            # Revit internal units are feet
POS_TOL = 0.5 * MM          # witness lines closer than this count as aligned
PARALLEL_TOL = 1e-6
MIN_DUPE_LEN = (float(IN[3]) if len(IN) > 3 and IN[3] is not None else 90.0) * MM


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


def segment_intervals(dim, base, d):
    """[(t_start, t_end, segment_index)] along d for each segment."""
    if dim.NumberOfSegments == 0:
        segs = [(dim.Origin, dim.Value)]
    else:
        segs = [(s.Origin, s.Value) for s in dim.Segments]
    result = []
    for i, (origin, value) in enumerate(segs):
        if value is None:
            continue
        t = origin.Subtract(base).DotProduct(d)
        result.append((t - value / 2.0, t + value / 2.0, i))
    return result


def building_side(dims, view, base, perp):
    """Average position (across the strings) of the dimensioned elements."""
    vals = []
    for dim in dims:
        for r in dim.References:
            el = doc.GetElement(r.ElementId)
            if el is None:
                continue
            bb = el.get_BoundingBox(view) or el.get_BoundingBox(None)
            if bb is None:
                continue
            centre = bb.Min.Add(bb.Max).Multiply(0.5)
            vals.append(centre.Subtract(base).DotProduct(perp))
    return sum(vals) / len(vals) if vals else None


def outer_duplicates(group, view):
    """[(dim, intervals, dup)]: dup holds the indices of dim's segments that
    also appear in a string further from the building. None if the building
    side can't be found."""
    d = group["dir"]
    perp = view.ViewDirection.CrossProduct(d).Normalize()
    base = group["dims"][0].Curve.Origin
    s_bld = building_side(group["dims"], view, base, perp)
    if s_bld is None:
        return None
    info = []
    for dim in group["dims"]:
        s = dim.Curve.Origin.Subtract(base).DotProduct(perp)
        info.append((dim, abs(s - s_bld), segment_intervals(dim, base, d)))

    result = []
    for dim, dist, ivs in info:
        dup = set()
        for a, b, idx in ivs:
            for dim2, dist2, ivs2 in info:
                if dist2 <= dist + POS_TOL:
                    continue          # only defer to strings further out
                if any(abs(a - a2) <= POS_TOL and abs(b - b2) <= POS_TOL
                       for a2, b2, _ in ivs2):
                    dup.add(idx)
                    break
        result.append((dim, ivs, dup))
    return result


def is_wall(a, b):
    return b - a <= MIN_DUPE_LEN + POS_TOL


def plan_duplicate_removal(group, view):
    """[(dim, set(segment indices))] to remove, keeping the outermost copy."""
    info = outer_duplicates(group, view)
    if info is None:
        return None
    removals = []
    for dim, ivs, dup in info:
        remove = set(idx for a, b, idx in ivs if idx in dup and not is_wall(a, b))
        if remove:
            remove |= stranded_walls(ivs, remove)
            removals.append((dim, remove))
    return removals


def plan_hidden_values(group, view):
    """Segments (walls repeated further out) whose number should be hidden."""
    info = outer_duplicates(group, view) or []
    hide = []
    for dim, ivs, dup in info:
        segs = [dim] if dim.NumberOfSegments == 0 else list(dim.Segments)
        hide.extend(segs[idx] for a, b, idx in ivs if idx in dup and is_wall(a, b))
    return hide


# Revit won't accept a blank override; these print as nothing.
HIDDEN_TEXT = (u"\u200e", u"\u200b", u"\u00a0")


def hide_value(seg):
    for text in HIDDEN_TEXT:
        try:
            seg.ValueOverride = text
            return True
        except Exception:
            pass
    return False


def stranded_walls(ivs, remove):
    """Segments left in a run of walls with no room either side.

    After removal a string falls into runs of kept segments; a run made only
    of short segments (walls no longer than MIN_DUPE_LEN) is dropped too.
    """
    stranded, run = set(), []
    for a, b, idx in sorted(ivs, key=lambda iv: iv[2]) + [(0.0, 0.0, None)]:
        if idx is None or idx in remove:
            if run and all(is_wall(ra, rb) for ra, rb, _ in run):
                stranded.update(i for _, _, i in run)
            run = []
        else:
            run.append((a, b, idx))
    return stranded


TEXT_PROPS = ("Above", "Below", "Prefix", "Suffix", "ValueOverride")


def copy_segment_text(src, dst):
    for prop in TEXT_PROPS:
        try:
            val = getattr(src, prop)
            if val:
                setattr(dst, prop, val)
        except Exception:
            pass
    try:
        if src.IsTextPositionAdjustable():
            dst.TextPosition = src.TextPosition
    except Exception:
        pass


def rebuild_without(dim, remove, view):
    """Replace dim by one string per run of kept segments.

    Returns the new dimensions, or None if dim could not be rebuilt.
    """
    refs = list(dim.References)
    segs = [dim] if dim.NumberOfSegments == 0 else list(dim.Segments)
    if len(refs) != len(segs) + 1:
        return None
    runs, cur = [], []
    for i in range(len(segs)):
        if i in remove:
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append(i)
    if cur:
        runs.append(cur)

    d = dim.Curve.Direction.Normalize()
    o = dim.Curve.Origin
    line = Line.CreateBound(o.Subtract(d.Multiply(100.0)), o.Add(d.Multiply(100.0)))
    created = []
    for run in runs:
        ra = ReferenceArray()
        for k in range(run[0], run[-1] + 2):
            ra.Append(refs[k])
        new = doc.Create.NewDimension(view, line, ra, dim.DimensionType)
        new_segs = [new] if new.NumberOfSegments == 0 else list(new.Segments)
        for src, dst in zip([segs[i] for i in run], new_segs):
            copy_segment_text(src, dst)
        created.append(new)
    doc.Delete(dim.Id)
    return created


def rearm_for_next_run():
    """Mark this node as modified so the next Run executes it again.

    Dynamo skips nodes whose inputs have not changed, which would stop the
    picker from appearing a second time.
    """
    try:
        clr.AddReference("DynamoRevitDS")
        import Dynamo
        ws = Dynamo.Applications.DynamoRevit.RevitDynamoModel.CurrentWorkspace
        for node in ws.Nodes:
            if getattr(node, "Script", None) and RERUN_MARKER in node.Script:
                node.MarkNodeAsModified(True)
    except Exception:
        pass


RERUN_MARKER = "ConnectAlignedDims_rerun_marker"

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
    created = skipped = removed = hidden = 0
    TransactionManager.Instance.EnsureInTransaction(doc)
    for g in group_parallel(dims):
        if len(g["dims"]) < 2:
            continue
        view = doc.GetElement(g["dims"][0].OwnerViewId)
        # Remove duplicates first so lines only join witness lines that remain.
        if REMOVE_DUPES:
            plan = plan_duplicate_removal(g, view)
            if plan is None:
                report.append("Couldn't tell which side the building is on - "
                              "no duplicate segments removed.")
                plan = []
            for dim, remove in plan:
                # Read Ids now: touching dim after it is deleted throws.
                old_id = dim.Id.IntegerValue
                others = [x for x in g["dims"] if x.Id.IntegerValue != old_id]
                new_dims = rebuild_without(dim, remove, view)
                if new_dims is None:
                    report.append("Couldn't rebuild dimension {0} - left as is."
                                  .format(old_id))
                    continue
                removed += len(remove)
                g["dims"] = others + new_dims
            if plan:
                doc.Regenerate()
            for seg in plan_hidden_values(g, view):
                if hide_value(seg):
                    hidden += 1
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
                     "{2} already existed, {3} duplicate segment(s) removed, "
                     "{4} repeated wall value(s) hidden."
                  .format(len(dims), created, skipped, removed, hidden))
    OUT = "\n".join(report)

rearm_for_next_run()
