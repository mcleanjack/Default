# -*- coding: utf-8 -*-
"""
Auto Tag Detail Components  (Dynamo Python node)

Workflow
  1. Draw a vertical detail line in the active view where the tag text should align.
  2. Run the graph (Dynamo Player recommended).
  3. Pick the tag type, leader style and placement options in the dialog.
  4. Click the guide line.
  5. Click each detail component to tag, on the exact spot the arrow should land.
     Press ESC (or right-click > Cancel) when finished.
  6. Tags are created with their text aligned to the guide line, and the
     dialog comes back so you can tag the next set (new line, other tag type,
     other side...). Click Finish when you're done. Each set is a separate
     undo step (Ctrl+Z).

Inputs
  IN[0]  Run                            (bool)   False = do nothing
  IN[1]  Minimum tag spacing (mm sheet) (float)  vertical gap kept between tag heads
  IN[2]  Text offset from line (mm)     (float)  0 = text edge sits on the line

Written to run on both the CPython3 and IronPython2 engines (no f-strings).
"""
import clr
import os
import json
import uuid

clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")
clr.AddReference("RevitServices")
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, ElementId, FilteredElementCollector,
    IndependentTag, LeaderEndCondition, Reference, TagMode, TagOrientation,
    Transaction, XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
import Autodesk.Revit.Exceptions as RvtExc

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

from System.Windows.Forms import (
    Button, CheckBox, DialogResult, Form, FormBorderStyle, FormStartPosition,
    GroupBox, Label, RadioButton,
)
from System.Drawing import Point, Size

doc = DocumentManager.Instance.CurrentDBDocument
uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
view = doc.ActiveView

# ---------------------------------------------------------------------------
# Configuration - edit these names if your tag types are called something else.
# "left"  = tag text sits LEFT of the guide line (label right-justified)
# "right" = tag text sits RIGHT of the guide line (label left-justified)
# ---------------------------------------------------------------------------
TAG_OPTIONS = [
    ("Description Tag Align Right", "left"),
    ("Comments Tag Align Right", "left"),
    ("Description Tag", "right"),
    ("Comments Tag", "right"),
]
TAG_CATEGORIES = [BuiltInCategory.OST_MultiCategoryTags,
                  BuiltInCategory.OST_DetailComponentTags]
SETTINGS_FILE = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                             "AutoTagDetailComponents.json")
MM_TO_FT = 1.0 / 304.8
TOL = 1e-6


def _input(index, default):
    try:
        value = IN[index]
        return default if value is None else value
    except (IndexError, NameError):
        return default


run = bool(_input(0, True))
spacing_mm = float(_input(1, 5.0))
offset_mm = float(_input(2, 0.0))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def impl(obj):
    """PythonNet3 returns declared types; unwrap to the runtime type."""
    try:
        return obj.__implementation__
    except Exception:
        return obj


def cat_is(elem, bic):
    cat = elem.Category
    return cat is not None and cat.Id.Equals(ElementId(bic))


def param_str(elem, bip):
    p = elem.get_Parameter(bip)
    return p.AsString() if p is not None else ""


def find_tag_types():
    """Map each configured tag name to an ElementId (matches type or family name)."""
    found = {}
    for bic in TAG_CATEGORIES:
        types = FilteredElementCollector(doc).OfCategory(bic).WhereElementIsElementType()
        for t in types:
            type_name = param_str(t, BuiltInParameter.SYMBOL_NAME_PARAM)
            fam_name = param_str(t, BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
            for name, _side in TAG_OPTIONS:
                if name in found:
                    continue
                if type_name == name or fam_name == name:
                    found[name] = t.Id
    return found


def load_settings():
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------
def show_dialog(available, defaults, status=""):
    form = Form()
    form.Text = "Auto Tag Detail Components"
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.StartPosition = FormStartPosition.CenterScreen
    form.TopMost = True
    form.ClientSize = Size(380, 510)

    def group(text, y, height):
        g = GroupBox()
        g.Text = text
        g.Location = Point(12, y)
        g.Size = Size(356, height)
        form.Controls.Add(g)
        return g

    def label(parent, text, y):
        lbl = Label()
        lbl.Text = text
        lbl.AutoSize = True
        lbl.Location = Point(12, y)
        parent.Controls.Add(lbl)

    def radio(parent, text, y, checked, enabled=True):
        rb = RadioButton()
        rb.Text = text
        rb.AutoSize = True
        rb.Location = Point(24, y)
        rb.Enabled = enabled
        rb.Checked = checked and enabled
        parent.Controls.Add(rb)
        return rb

    # Tag type
    g_tag = group("Tag type", 10, 175)
    tag_radios = []
    y = 22
    for side, heading in (("left", "LEFT of line (text aligned right)"),
                          ("right", "RIGHT of line (text aligned left)")):
        label(g_tag, heading, y)
        y += 22
        for name, s in TAG_OPTIONS:
            if s != side:
                continue
            ok = name in available
            text = name if ok else name + "  (not loaded)"
            tag_radios.append((name, radio(g_tag, text, y, defaults.get("tag") == name, ok)))
            y += 24
        y += 6
    if not any(rb.Checked for _n, rb in tag_radios):
        for _n, rb in tag_radios:
            if rb.Enabled:
                rb.Checked = True
                break

    # Leader style
    g_leader = group("Leader", 195, 80)
    elbow_default = defaults.get("leader", "elbow") == "elbow"
    rb_elbow = radio(g_leader, "Right-angle bend (horizontal, then vertical)", 22, elbow_default)
    rb_straight = radio(g_leader, "Straight leader", 46, not elbow_default)

    # Placement
    g_place = group("Tag height", 285, 80)
    spread_default = defaults.get("placement") == "spread"
    rb_level = radio(g_place, "Level with each picked point", 22, not spread_default)
    rb_spread = radio(g_place, "Spread evenly along the guide line", 46, spread_default)

    cb_delete = CheckBox()
    cb_delete.Text = "Delete guide line after tagging"
    cb_delete.AutoSize = True
    cb_delete.Location = Point(18, 378)
    cb_delete.Checked = bool(defaults.get("delete_line", False))
    form.Controls.Add(cb_delete)

    status_lbl = Label()
    status_lbl.Text = status
    status_lbl.Location = Point(18, 404)
    status_lbl.Size = Size(350, 48)
    form.Controls.Add(status_lbl)

    ok_btn = Button()
    ok_btn.Text = "Pick line && tag"
    ok_btn.Size = Size(120, 30)
    ok_btn.Location = Point(116, 464)
    ok_btn.DialogResult = DialogResult.OK
    form.Controls.Add(ok_btn)
    form.AcceptButton = ok_btn

    cancel_btn = Button()
    cancel_btn.Text = "Finish"
    cancel_btn.Size = Size(120, 30)
    cancel_btn.Location = Point(248, 464)
    cancel_btn.DialogResult = DialogResult.Cancel
    form.Controls.Add(cancel_btn)
    form.CancelButton = cancel_btn

    result = form.ShowDialog()
    if result != DialogResult.OK:
        return None
    chosen = [n for n, rb in tag_radios if rb.Checked]
    if not chosen:
        return None
    return {
        "tag": chosen[0],
        "leader": "elbow" if rb_elbow.Checked else "straight",
        "placement": "spread" if rb_spread.Checked else "level",
        "delete_line": bool(cb_delete.Checked),
    }


# ---------------------------------------------------------------------------
# Selection filters (unique namespace so CPython3 can re-run the node)
# ---------------------------------------------------------------------------
_NS = "AutoTagDetail_" + uuid.uuid4().hex


class GuideLineFilter(ISelectionFilter):
    __namespace__ = _NS

    def AllowElement(self, elem):
        try:
            elem = impl(elem)
            return (cat_is(elem, BuiltInCategory.OST_Lines)
                    and elem.OwnerViewId.Equals(view.Id))
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return False


class DetailItemFilter(ISelectionFilter):
    __namespace__ = _NS

    def AllowElement(self, elem):
        try:
            return cat_is(elem, BuiltInCategory.OST_DetailComponents)
        except Exception:
            return False

    def AllowReference(self, ref, point):
        return False


# ---------------------------------------------------------------------------
# View-plane coordinates (works in drafting, section and plan views)
# ---------------------------------------------------------------------------
V_ORIGIN = view.Origin
V_RIGHT = view.RightDirection
V_UP = view.UpDirection
V_NORMAL = view.ViewDirection


def to_uv(p):
    d = p.Subtract(V_ORIGIN)
    return d.DotProduct(V_RIGHT), d.DotProduct(V_UP)


def to_xyz(u, v, depth):
    return (V_ORIGIN.Add(V_RIGHT.Multiply(u))
            .Add(V_UP.Multiply(v))
            .Add(V_NORMAL.Multiply(depth)))


def pick_point_of(ref, elem):
    p = ref.GlobalPoint
    if p is not None:
        return p
    bb = elem.get_BoundingBox(view)
    return bb.Min.Add(bb.Max).Multiply(0.5)


def spread_heights(picked_vs, top, bottom):
    """Head heights ordered top-down, same order as sorted picked_vs."""
    n = len(picked_vs)
    if n == 1:
        return [min(max(picked_vs[0], bottom), top)]
    step = (top - bottom) / float(n - 1)
    return [top - i * step for i in range(n)]


def level_heights(picked_vs, gap):
    heads = []
    for v in picked_vs:
        if heads and heads[-1] - v < gap:
            v = heads[-1] - gap
        heads.append(v)
    return heads


def set_leader(tag, ref, end, elbow):
    tag.LeaderEndCondition = LeaderEndCondition.Free
    try:
        tag.SetLeaderEnd(ref, end)          # Revit 2022+
    except AttributeError:
        tag.LeaderEnd = end                 # Revit 2021 and earlier
    try:
        tag.SetLeaderElbow(ref, elbow)
    except AttributeError:
        tag.LeaderElbow = elbow


def create_tag(type_id, ref, head):
    try:
        tag = IndependentTag.Create(doc, type_id, view.Id, ref, True,
                                    TagOrientation.Horizontal, head)
    except TypeError:
        tag = IndependentTag.Create(doc, view.Id, ref, True,
                                    TagMode.TM_ADDBY_MULTICATEGORY,
                                    TagOrientation.Horizontal, head)
        tag.ChangeTypeId(type_id)
    return tag


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def tag_batch(options, tag_types):
    """Pick a guide line + components and tag them. Returns (status, tags, errors)."""
    side = dict(TAG_OPTIONS)[options["tag"]]
    type_id = tag_types[options["tag"]]

    # 1. Guide line
    try:
        line_ref = uidoc.Selection.PickObject(
            ObjectType.Element, GuideLineFilter(),
            "Select the vertical guide line (ESC to go back)")
    except RvtExc.OperationCanceledException:
        return "No guide line picked.", [], []
    line_elem = impl(doc.GetElement(line_ref))
    curve = line_elem.GeometryCurve
    p0, p1 = curve.GetEndPoint(0), curve.GetEndPoint(1)
    u0, v0 = to_uv(p0)
    u1, v1 = to_uv(p1)
    if abs(u1 - u0) > abs(v1 - v0):
        return "The guide line must be vertical (it looks horizontal).", [], []
    line_u = (u0 + u1) / 2.0
    top, bottom = max(v0, v1), min(v0, v1)
    depth = p0.Subtract(V_ORIGIN).DotProduct(V_NORMAL)

    # 2. Components - one click each, ESC to finish
    picks = []
    while True:
        prompt = "Click detail component #{0} where the arrow should land (ESC to finish)".format(len(picks) + 1)
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, DetailItemFilter(), prompt)
        except RvtExc.OperationCanceledException:
            break
        elem = doc.GetElement(ref)
        u, v = to_uv(pick_point_of(ref, elem))
        picks.append((v, u, elem))
    if not picks:
        return "No components picked.", [], []

    # 3. Tag head positions (top-down order)
    picks.sort(key=lambda t: -t[0])
    scale = float(view.Scale) if view.Scale else 1.0
    gap = spacing_mm * MM_TO_FT * scale
    offset = offset_mm * MM_TO_FT * scale
    picked_vs = [p[0] for p in picks]
    if options["placement"] == "spread":
        heads_v = spread_heights(picked_vs, top, bottom)
    else:
        heads_v = level_heights(picked_vs, gap)
    head_u = line_u - offset if side == "left" else line_u + offset

    # 4. Create tags - committed per batch so they show up (and undo) straight away
    created, errors = [], []
    t = Transaction(doc, "Auto Tag Detail Components")
    t.Start()
    try:
        for (end_v, end_u, elem), hv in zip(picks, heads_v):
            try:
                ref = Reference(elem)
                head = to_xyz(head_u, hv, depth)
                end = to_xyz(end_u, end_v, depth)
                tag = create_tag(type_id, ref, head)
                if options["leader"] == "elbow" and abs(hv - end_v) > TOL and abs(end_u - head_u) > TOL:
                    elbow = to_xyz(end_u, hv, depth)            # horizontal, then vertical
                else:
                    elbow = to_xyz((head_u + end_u) / 2.0, (hv + end_v) / 2.0, depth)  # straight
                set_leader(tag, ref, end, elbow)
                tag.TagHeadPosition = head
                created.append(tag)
            except Exception as ex:
                errors.append("Could not tag element {0}: {1}".format(elem.Id, ex))
        if options["delete_line"] and created:
            doc.Delete(line_elem.Id)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    uidoc.RefreshActiveView()

    status = "Last run: created {0} '{1}' tag(s) with {2} leaders.".format(
        len(created), options["tag"],
        "right-angle" if options["leader"] == "elbow" else "straight")
    if errors:
        status += " {0} failed (see Dynamo output).".format(len(errors))
    return status, created, errors


def main():
    if not run:
        return ["Set Run to True to start."], []

    tag_types = find_tag_types()
    if not tag_types:
        return ["None of the tag types were found in this project: "
                + ", ".join(n for n, _s in TAG_OPTIONS)], []

    # Close Dynamo's own transaction so each batch can commit on its own.
    TransactionManager.Instance.ForceCloseTransaction()

    all_tags, messages = [], []
    status = "Draw a vertical detail line, then click 'Pick line & tag'."
    options = load_settings()
    while True:
        options = show_dialog(tag_types, options, status)
        if options is None:
            break
        save_settings(options)
        status, created, errors = tag_batch(options, tag_types)
        all_tags.extend(created)
        messages.extend(errors)

    messages.insert(0, "Finished: created {0} tag(s) in total.".format(len(all_tags)))
    return messages, all_tags


def force_rerun_next_time():
    """Dynamo skips nodes whose inputs haven't changed, so the script would only
    run once. Mark this node as modified so the next Run executes it again.
    Skipped in Automatic mode, where it would re-trigger itself endlessly.
    Returns a short status line for the Watch node (helps diagnose re-run issues)."""
    try:
        clr.AddReference("DynamoRevitDS")
        import Dynamo
        workspace = Dynamo.Applications.DynamoRevit().RevitDynamoModel.CurrentWorkspace
        run_type = str(workspace.RunSettings.RunType)
        if "Automatic" in run_type:
            return "Re-run: skipped (graph is in Automatic mode - switch to Manual)."
        marked = 0
        for node in workspace.Nodes:
            code = getattr(node, "Code", None) or ""
            if "force_rerun_next_time" in code:
                node.MarkNodeAsModified(True)
                marked += 1
        return "Re-run: marked {0} node(s) for next run ({1} mode).".format(marked, run_type)
    except Exception as ex:
        return "Re-run: could not mark node - {0}".format(ex)


try:
    OUT = main()
except Exception as ex:
    OUT = ["Error: {0}".format(ex)], []
OUT = [OUT[0] + [force_rerun_next_time()], OUT[1]]
