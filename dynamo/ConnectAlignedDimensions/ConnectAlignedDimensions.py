"""
Connect Aligned Dimensions  (Dynamo Python node for Revit)

Pick the parallel dimension strings you want to tidy, then press Finish on
the Options Bar. The strings are spaced a set distance apart, moving outward
from the one closest to the building. The Leader box is unticked on every
picked string (and on any string the script rebuilds).

When the same segment (same start and end witness lines) appears
in more than one picked string, it is removed from every string except the
one furthest from the building. Revit cannot delete a segment from the middle
of a string, so the inner string is rebuilt as separate strings either side of
the removed segment, keeping each segment's text overrides.

Inputs
    IN[0]  Remove duplicate segments from the inner strings (bool).
    IN[1]  Max wall thickness, in mm (number). Repeated segments this long
           or shorter are walls (default 240, so 90 and 240 walls): they stay
           on every string, but their number is hidden where a string further
           out shows it. Longer repeats (rooms) are removed. Walls left with
           no room either side after the removal are deleted as well.
    IN[2]  Space the strings this far apart, in mm (number, model size).
           The string closest to the building stays put; the others move
           outward. 0 leaves the strings where they are.
Output
    OUT    Report text.

Works with IronPython 2.7, CPython3 and PythonNet3 engines.
"""
import clr
import uuid

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("RevitServices")
from Autodesk.Revit.DB import (BuiltInParameter, Dimension,
                               ElementTransformUtils, Line, Reference,
                               ReferenceArray)
from Autodesk.Revit.Exceptions import OperationCanceledException
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from System.Collections.Generic import List
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument

REMOVE_DUPES = bool(IN[0]) if len(IN) > 0 and IN[0] is not None else True

MM = 1.0 / 304.8            # Revit internal units are feet
POS_TOL = 0.5 * MM          # witness lines closer than this count as aligned
PARALLEL_TOL = 1e-6
MIN_DUPE_LEN = (float(IN[1]) if len(IN) > 1 and IN[1] is not None else 240.0) * MM
SPACING = (float(IN[2]) if len(IN) > 2 and IN[2] is not None else 600.0) * MM


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
    for a, b, idx in sorted(ivs, key=lambda iv: iv[0]) + [(0.0, 0.0, None)]:
        if idx is None or idx in remove:
            if run and all(is_wall(ra, rb) for ra, rb, _ in run):
                stranded.update(i for _, _, i in run)
            run = []
        else:
            run.append((a, b, idx))
    return stranded


TEXT_PROPS = ("Above", "Below", "Prefix", "Suffix", "ValueOverride")


def copy_segment_text(src, dst):
    """Copy text overrides. The value's position is left to Revit: copying
    TextPosition onto a rebuilt string put values over the wrong segment."""
    for prop in TEXT_PROPS:
        try:
            val = getattr(src, prop)
            if val:
                setattr(dst, prop, val)
        except Exception:
            pass


def match_segments(src_segs, dst_segs, origin, d):
    """Pair each new segment with the old one at the same place on the line."""
    def centre(seg):
        return seg.Origin.Subtract(origin).DotProduct(d)
    src = [(centre(sg), sg.Value, sg) for sg in src_segs]
    pairs = []
    for dst in dst_segs:
        t, v = centre(dst), dst.Value
        for ts, vs, sg in src:
            if (v is not None and vs is not None and abs(t - ts) <= POS_TOL
                    and abs(v - vs) <= POS_TOL):
                pairs.append((sg, dst))
                break
    return pairs


def stable_ref(ref):
    """Fresh copy of a reference taken from an existing dimension.

    Revit sometimes rejects such references in NewDimension; going through
    the stable representation is the usual workaround.
    """
    try:
        return Reference.ParseFromStableRepresentation(
            doc, ref.ConvertToStableRepresentation(doc))
    except Exception:
        return ref


def new_string(view, line, refs, dtype):
    """Create a dimension through refs, trying fresh copies first."""
    error = None
    for convert in (stable_ref, lambda r: r):
        ra = ReferenceArray()
        for r in refs:
            ra.Append(convert(r))
        try:
            return doc.Create.NewDimension(view, line, ra, dtype)
        except Exception as ex:
            error = ex
    raise error


def boundaries(dim, origin, d):
    """Sorted, de-duplicated witness line positions of dim along d."""
    pts = []
    for a, b, _ in segment_intervals(dim, origin, d):
        pts.extend((a, b))
    pts.sort()
    result = []
    for t in pts:
        if not result or t - result[-1] > POS_TOL:
            result.append(t)
    return result


def find(t, positions):
    for i, p in enumerate(positions):
        if p is not None and abs(p - t) <= POS_TOL:
            return i
    return None


def reference_positions(dim, refs, view, line, origin, d):
    """Position along d of each reference.

    Revit doesn't list a dimension's references in order along the line
    (e.g. a witness line added later goes on the end) and can't report where
    a reference is. So each reference is dropped in turn from a temporary
    copy of the string, and the witness line that disappears is its own.
    """
    bounds = boundaries(dim, origin, d)
    positions = []
    for i in range(len(refs)):
        tmp = new_string(view, line, refs[:i] + refs[i + 1:], dim.DimensionType)
        try:
            doc.Regenerate()
            left = boundaries(tmp, origin, d)
        finally:
            doc.Delete(tmp.Id)
        missing = [t for t in bounds if find(t, left) is None]
        if len(missing) != 1:
            raise ValueError("couldn't locate witness line {0} of {1}".format(
                i + 1, len(refs)))
        positions.append(missing[0])
    return positions


def rebuild_without(dim, remove, view):
    """Replace dim by one string per run of kept segments.

    Returns the new dimensions. If anything goes wrong, the pieces made so
    far are deleted, dim is left as it was and the error is raised.
    """
    refs = list(dim.References)
    segs = [dim] if dim.NumberOfSegments == 0 else list(dim.Segments)
    if len(refs) != len(segs) + 1:
        raise ValueError("{0} references for {1} segments".format(
            len(refs), len(segs)))
    d = dim.Curve.Direction.Normalize()
    o = dim.Curve.Origin
    line = Line.CreateBound(o.Subtract(d.Multiply(100.0)), o.Add(d.Multiply(100.0)))

    # Runs of kept segments, walking along the line.
    runs, cur = [], []
    for a, b, idx in sorted(segment_intervals(dim, o, d), key=lambda iv: iv[0]):
        if idx in remove:
            if cur:
                runs.append(cur)
            cur = []
        else:
            cur.append((a, b, idx))
    if cur:
        runs.append(cur)
    if not runs:
        doc.Delete(dim.Id)
        return []

    positions = reference_positions(dim, refs, view, line, o, d)
    created = []
    try:
        for run in runs:
            wanted = [run[0][0]] + [b for _, b, _ in run]
            free = list(positions)
            run_refs = []
            for t in wanted:
                k = find(t, free)
                if k is None:
                    raise ValueError("no witness line at a segment end")
                free[k] = None
                run_refs.append(refs[k])
            new = new_string(view, line, run_refs, dim.DimensionType)
            created.append(new)
            doc.Regenerate()
            got = sorted((a, b) for a, b, _ in segment_intervals(new, o, d))
            if (len(got) != len(run) or any(
                    abs(a - ra) > POS_TOL or abs(b - rb) > POS_TOL
                    for (a, b), (ra, rb, _) in zip(got, run))):
                raise ValueError("rebuilt string didn't match the original")
            new_segs = [new] if new.NumberOfSegments == 0 else list(new.Segments)
            for src, dst in match_segments([segs[i] for _, _, i in run],
                                           new_segs, o, d):
                copy_segment_text(src, dst)
    except Exception:
        for new in created:
            doc.Delete(new.Id)
        raise
    doc.Delete(dim.Id)
    return created


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


def turn_off_leader(dim):
    """Untick the dimension's Leader box. Returns True if it was ticked."""
    p = None
    try:
        p = dim.get_Parameter(BuiltInParameter.DIM_LEADER)
    except Exception:
        pass
    if p is None:
        p = dim.LookupParameter("Leader")
    if p is None or p.IsReadOnly or p.AsInteger() == 0:
        return False
    p.Set(0)
    return True


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
    removed = hidden = spaced = leaders = 0
    TransactionManager.Instance.EnsureInTransaction(doc)
    for dim in dims:
        if turn_off_leader(dim):
            leaders += 1
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
                try:
                    new_dims = rebuild_without(dim, remove, view)
                except Exception as ex:
                    report.append("Couldn't rebuild dimension {0} - left as is "
                                  "({1}).".format(old_id, ex))
                    continue
                removed += len(remove)
                for new in new_dims:
                    turn_off_leader(new)
                g["dims"] = others + new_dims
            if plan:
                doc.Regenerate()
            for seg in plan_hidden_values(g, view):
                if hide_value(seg):
                    hidden += 1
    TransactionManager.Instance.TransactionTaskDone()
    report.insert(0, "{0} dimension(s) picked, {1} row(s) of strings moved, "
                     "{2} duplicate segment(s) removed, "
                     "{3} repeated wall value(s) hidden, "
                     "{4} leader(s) turned off."
                  .format(len(dims), spaced, removed, hidden, leaders))
    OUT = "\n".join(report)

rearm_for_next_run()
