"""
Connect Aligned Dimensions  (Dynamo Python node for Revit)

Pick the parallel dimension strings you want to tie together, then press
Finish on the Options Bar. Each string that shares a witness line position
with a string closer to the building is given its own copy of its dimension
type, set to "Fixed to Dimension Line" with a witness line length that
reaches that inner string. The witness lines are then part of the dimension
and move with it. (Revit's API cannot lengthen individual witness lines, so
every witness line on that string gets the same length.)

Optionally, when the same segment (same start and end witness lines) appears
in more than one picked string, it is removed from every string except the
one furthest from the building. Revit cannot delete a segment from the middle
of a string, so the inner string is rebuilt as separate strings either side of
the removed segment, keeping each segment's text overrides.

Inputs
    IN[0]  Extend the witness lines past the inner string by the dimension
           type's "Witness Line Extension" (bool).
    IN[1]  Remove duplicate segments from the inner strings (bool).
    IN[2]  Only remove duplicates longer than this, in mm (number). The
           default 90 keeps 90 mm walls on every string but removes thicker
           walls (e.g. 240) and rooms. Walls this short that are left with
           no room either side after the removal are deleted as well, and
           the number on the rest is hidden where an outer string shows it.
    IN[3]  Space the strings this far apart, in mm (number, model size).
           The string closest to the building stays put; the others move
           outward. 0 leaves the strings where they are.
Output
    OUT    Report text.

Works with IronPython 2.7, CPython3 and PythonNet3 engines.
"""
import clr
import re
import uuid

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import (BuiltInParameter, Dimension, DimensionType,
                               ElementTransformUtils, FilteredElementCollector,
                               Line, Reference, ReferenceArray)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

EXTEND = bool(IN[0]) if len(IN) > 0 and IN[0] is not None else False
REMOVE_DUPES = bool(IN[1]) if len(IN) > 1 and IN[1] is not None else True

MM = 1.0 / 304.8            # Revit internal units are feet
POS_TOL = 0.5 * MM          # witness lines closer than this count as aligned
PARALLEL_TOL = 1e-6
MIN_DUPE_LEN = (float(IN[2]) if len(IN) > 2 and IN[2] is not None else 90.0) * MM
SPACING = (float(IN[3]) if len(IN) > 3 and IN[3] is not None else 600.0) * MM


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


def witness_extension(dtype):
    """Witness Line Extension of a dimension type, in paper feet."""
    p = None
    try:
        p = dtype.get_Parameter(BuiltInParameter.WITNS_LINE_EXTENSION)
    except Exception:
        pass
    if p is None:
        p = dtype.LookupParameter("Witness Line Extension")
    return p.AsDouble() if p is not None else 2.0 * MM


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


def plan_witness_lengths(group, view):
    """[(dim, paper length)] for each string that shares a witness line with
    a string closer to the building: the length reaching the nearest one."""
    d = group["dir"]
    perp = view.ViewDirection.CrossProduct(d).Normalize()
    base = group["dims"][0].Curve.Origin
    s_bld = building_side(group["dims"], view, base, perp)
    if s_bld is None:
        return None
    info = []
    for dim in group["dims"]:
        off = dim.Curve.Origin.Subtract(base).DotProduct(perp) - s_bld
        ts = [p.Subtract(base).DotProduct(d) for p in witness_points(dim)]
        info.append((dim, off, ts))

    result = []
    for dim, off, ts in info:
        inner = None
        for dim2, off2, ts2 in info:
            if off * off2 <= 0 or abs(off2) >= abs(off) - POS_TOL:
                continue              # other side of the building, or not inside
            if not any(abs(t - t2) <= POS_TOL for t in ts for t2 in ts2):
                continue
            if inner is None or abs(off2) > abs(inner[1]):
                inner = (dim2, off2)
        if inner is None:
            continue
        length = (abs(off) - abs(inner[1])) / view.Scale
        if EXTEND:
            length += witness_extension(inner[0].DimensionType)
        result.append((dim, length))
    return result


# Matches the suffix added by this script (current and older names).
TYPE_SUFFIX = re.compile(r" - [0-9.]+(mm)? Witness( @1:[0-9]+)?$")


def set_fixed_witness_control(dtype):
    """Set Witness Line Control to Fixed to Dimension Line. Returns success."""
    p = dtype.LookupParameter("Witness Line Control")
    if p is None or p.IsReadOnly:
        return False
    for value in (1, 0, 2):
        try:
            p.Set(value)
            if "fixed" in (p.AsValueString() or "").lower():
                return True
        except Exception:
            pass
    return False


def fixed_witness_type(dtype, length, scale):
    """Copy of dtype whose witness lines are fixed at length (paper feet).

    Named after the model length at the view scale, e.g.
    "Standard Dimension - 600 Witness @1:100".
    """
    base_name = TYPE_SUFFIX.sub("", dtype.Name)
    name = "{0} - {1:g} Witness @1:{2}".format(
        base_name, round(length * scale / MM, 1), scale)
    for t in FilteredElementCollector(doc).OfClass(DimensionType):
        if t.Name == name:
            return t
    new = dtype.Duplicate(name)
    if not set_fixed_witness_control(new):
        doc.Delete(new.Id)
        raise ValueError("couldn't set Witness Line Control on '{0}'".format(name))
    p = new.LookupParameter("Witness Line Length")
    if p is None or p.IsReadOnly:
        doc.Delete(new.Id)
        raise ValueError("no Witness Line Length on '{0}'".format(name))
    p.Set(length)
    return new


def space_strings(group, view):
    """Move strings so each sits SPACING beyond the one inside it.

    Strings at the same distance from the building (e.g. pieces of one
    string) count as one row. Returns (rows moved, problems).
    """
    d = group["dir"]
    perp = view.ViewDirection.CrossProduct(d).Normalize()
    base = group["dims"][0].Curve.Origin
    s_bld = building_side(group["dims"], view, base, perp)
    if s_bld is None:
        return 0, ["Couldn't tell which side the building is on - strings not spaced."]
    moved, problems = 0, []
    for side in (1.0, -1.0):
        offs = []
        for dim in group["dims"]:
            off = dim.Curve.Origin.Subtract(base).DotProduct(perp) - s_bld
            if off * side > 0:
                offs.append((abs(off), dim))
        offs.sort(key=lambda o: o[0])
        rows = []
        for off, dim in offs:
            if rows and off - rows[-1][0] <= POS_TOL:
                rows[-1][1].append(dim)
            else:
                rows.append((off, [dim]))
        for k, (off, row) in enumerate(rows):
            if k == 0:
                continue
            delta = rows[0][0] + k * SPACING - off
            if abs(delta) <= POS_TOL:
                continue
            for dim in row:
                try:
                    ElementTransformUtils.MoveElement(
                        doc, dim.Id, perp.Multiply(delta * side))
                except Exception as ex:
                    problems.append("Couldn't move dimension {0}: {1}"
                                    .format(dim.Id.IntegerValue, ex))
            moved += 1
    return moved, problems


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
    retyped = removed = hidden = spaced = 0
    TransactionManager.Instance.EnsureInTransaction(doc)
    for g in group_parallel(dims):
        if len(g["dims"]) < 2:
            continue
        view = doc.GetElement(g["dims"][0].OwnerViewId)
        if SPACING > 0:
            n, problems = space_strings(g, view)
            spaced += n
            report.extend(problems)
            if n:
                doc.Regenerate()
        # Remove duplicates first so witness lines only reach strings that
        # still share a witness line with them.
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
        lengths = plan_witness_lengths(g, view)
        if lengths is None:
            report.append("Couldn't tell which side the building is on - "
                          "witness lines not changed.")
            continue
        for dim, length in lengths:
            try:
                dim.ChangeTypeId(fixed_witness_type(dim.DimensionType, length, view.Scale).Id)
                retyped += 1
            except Exception as ex:
                report.append("Witness lines of dimension {0} not changed: {1}"
                              .format(dim.Id.IntegerValue, ex))
    TransactionManager.Instance.TransactionTaskDone()
    report.insert(0, "{0} dimension(s) picked, {1} row(s) of strings moved, "
                     "{2} string(s) given longer witness lines, "
                     "{3} duplicate segment(s) removed, "
                     "{4} repeated wall value(s) hidden."
                  .format(len(dims), spaced, retyped, removed, hidden))
    OUT = "\n".join(report)

rearm_for_next_run()
