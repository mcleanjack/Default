# -*- coding: utf-8 -*-
"""
Auto Tag Detail Components  (Dynamo Python node)

Workflow
  1. Draw a vertical detail line in the active view where the tag text should align.
  2. Run the graph (Dynamo Player recommended).
  3. Pick the tag type in the dialog.
  4. Click the guide line.
  5. Click each detail component to tag, on the exact spot the arrow should land.
     Press D (Description tag) or C (Comments tag) at any time to switch the tag
     used for the following clicks - a notice briefly shows the selected tag.
     The tag picked in the dialog sets the side of the line and the starting tag.
     Picked components turn blue until you click Finish.
     Press ESC (or right-click > Cancel) when finished.
  6. Tags are created with their text aligned to the guide line, and the
     dialog comes back so you can tag the next set (new line, other tag type,
     other side...). Click Finish when you're done. Each set is a separate
     undo step (Ctrl+Z).

Inputs
  IN[0]  Run                            (bool)   False = do nothing
  IN[1]  Text offset from line (mm)     (float)  0 = text edge sits on the line

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
    BuiltInCategory, BuiltInParameter, Color, ElementId, FilteredElementCollector,
    IndependentTag, LeaderEndCondition, OverrideGraphicSettings, Reference,
    TagMode, TagOrientation, Transaction, XYZ,
)
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
import Autodesk.Revit.Exceptions as RvtExc

from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

from System.Windows.Forms import (
    Button, CheckBox, Cursor, DialogResult, Form, FormBorderStyle,
    FormStartPosition, GroupBox, Label, Padding, RadioButton,
)
from System.Drawing import Point, Size, Font, FontStyle
from System.Drawing import Color as DrawColor
from System.Windows.Forms import Timer as FormsTimer

try:
    import ctypes
    _user32 = ctypes.windll.user32
    _user32.GetKeyState.restype = ctypes.c_short
    _user32.GetForegroundWindow.restype = ctypes.c_void_p
    _user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
except Exception:
    _user32 = None

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
# Shortcut keys pressed after each component click: D = Description, C = Comments.
# The side (left/right of the line) comes from the tag chosen in the main dialog.
TAG_SHORTCUTS = {
    "left": [("D", "Description Tag Align Right"), ("C", "Comments Tag Align Right")],
    "right": [("D", "Description Tag"), ("C", "Comments Tag")],
}
TAG_CATEGORIES = [BuiltInCategory.OST_MultiCategoryTags,
                  BuiltInCategory.OST_DetailComponentTags]
SETTINGS_FILE = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                             "AutoTagDetailComponents.json")
MM_TO_FT = 1.0 / 304.8
HIGHLIGHT_COLOR = (0, 120, 215)   # blue used to mark picked components until Finish


def _input(index, default):
    try:
        value = IN[index]
        return default if value is None else value
    except (IndexError, NameError):
        return default


run = bool(_input(0, True))
offset_mm = float(_input(1, 0.0))


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
    form.ClientSize = Size(380, 320)

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
    g_tag = group("Side of line + starting tag (press D / C while picking to switch)", 10, 175)
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

    cb_delete = CheckBox()
    cb_delete.Text = "Delete guide line after tagging"
    cb_delete.AutoSize = True
    cb_delete.Location = Point(18, 196)
    cb_delete.Checked = bool(defaults.get("delete_line", False))
    form.Controls.Add(cb_delete)

    status_lbl = Label()
    status_lbl.Text = status
    status_lbl.UseMnemonic = False      # show "&" literally
    status_lbl.Location = Point(18, 222)
    status_lbl.Size = Size(350, 48)
    form.Controls.Add(status_lbl)

    ok_btn = Button()
    ok_btn.Text = "Pick line && tag"
    ok_btn.Size = Size(120, 30)
    ok_btn.Location = Point(116, 276)
    ok_btn.DialogResult = DialogResult.OK
    form.Controls.Add(ok_btn)
    form.AcceptButton = ok_btn

    cancel_btn = Button()
    cancel_btn.Text = "Finish"
    cancel_btn.Size = Size(120, 30)
    cancel_btn.Location = Point(248, 276)
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
        "delete_line": bool(cb_delete.Checked),
    }


# ---------------------------------------------------------------------------
# D / C shortcut keys while picking components
# A WinForms timer keeps ticking while Revit waits for a pick, so it can poll the
# keyboard. Pressing the other key switches the tag and briefly shows a notice.
# ---------------------------------------------------------------------------
VK_CODES = {"D": 0x44, "C": 0x43}
NOTICE_MS = 1500                  # how long the "tag selected" notice stays up
_watch = {"side": None, "current": None, "available": {}, "prev": {},
          "timer": None, "notice": None, "notice_timer": None}


def key_down(key):
    """True while the key is held (Revit's UI thread keyboard state)."""
    if _user32 is not None:
        return bool(_user32.GetKeyState(VK_CODES[key]) & 0x8000)
    try:
        clr.AddReference("PresentationCore")
        from System.Windows.Input import Keyboard, Key
        return bool(Keyboard.IsKeyDown(getattr(Key, key)))
    except Exception:
        return False


def close_notice(sender=None, args=None):
    t = _watch["notice_timer"]
    if t is not None:
        t.Stop()
        t.Dispose()
        _watch["notice_timer"] = None
    f = _watch["notice"]
    if f is not None:
        f.Close()
        f.Dispose()
        _watch["notice"] = None


def show_notice(text):
    """Small borderless notice by the cursor that closes itself after NOTICE_MS."""
    close_notice()
    previous = _user32.GetForegroundWindow() if _user32 is not None else None

    f = Form()
    f.FormBorderStyle = getattr(FormBorderStyle, "None")
    f.StartPosition = FormStartPosition.Manual
    f.TopMost = True
    f.ShowInTaskbar = False
    f.BackColor = DrawColor.FromArgb(*HIGHLIGHT_COLOR)
    f.Padding = Padding(10)
    lbl = Label()
    lbl.Text = text
    lbl.UseMnemonic = False
    lbl.AutoSize = True
    lbl.ForeColor = DrawColor.White
    lbl.Font = Font("Segoe UI", 11.0, FontStyle.Bold)
    lbl.Location = Point(10, 8)
    f.Controls.Add(lbl)
    f.ClientSize = Size(lbl.PreferredWidth + 20, lbl.PreferredHeight + 16)
    pos = Cursor.Position
    f.Location = Point(pos.X + 20, pos.Y + 20)
    f.Show()

    # Hand focus straight back to Revit so picking carries on.
    if previous:
        try:
            _user32.SetForegroundWindow(previous)
        except Exception:
            pass

    t = FormsTimer()
    t.Interval = NOTICE_MS
    t.Tick += close_notice
    t.Start()
    _watch["notice"] = f
    _watch["notice_timer"] = t


def _poll_keys(sender, args):
    try:
        for key, name in TAG_SHORTCUTS[_watch["side"]]:
            down = key_down(key)
            if down and not _watch["prev"].get(key) and name != _watch["current"]:
                if name in _watch["available"]:
                    _watch["current"] = name
                    show_notice("Tag selected: " + name)
                else:
                    show_notice(name + " is not loaded")
            _watch["prev"][key] = down
    except Exception:
        pass


def start_key_watch(side, available, start_name):
    _watch.update(side=side, current=start_name, available=available,
                  prev={k: key_down(k) for k in VK_CODES})
    t = FormsTimer()
    t.Interval = 50
    t.Tick += _poll_keys
    t.Start()
    _watch["timer"] = t


def stop_key_watch():
    t = _watch["timer"]
    if t is not None:
        t.Stop()
        t.Dispose()
        _watch["timer"] = None
    close_notice()


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
    """Create the tag WITHOUT a leader so its text box can be measured."""
    try:
        tag = IndependentTag.Create(doc, type_id, view.Id, ref, False,
                                    TagOrientation.Horizontal, head)
    except TypeError:
        tag = IndependentTag.Create(doc, view.Id, ref, False,
                                    TagMode.TM_ADDBY_MULTICATEGORY,
                                    TagOrientation.Horizontal, head)
        tag.ChangeTypeId(type_id)
    return tag


def v_extent(bb):
    vs = [to_uv(bb.Min)[1], to_uv(bb.Max)[1]]
    return min(vs), max(vs)


def text_centre_offset(tag, elem, head_u, v, depth, scale):
    """Vertical offset from the tag head to the middle of its text, where Revit
    starts the leader.

    A tag's bounding box can also cover part of the tagged element, so it can't
    be read directly. Instead, move the tag well ABOVE the element and read the
    top of the box, then well BELOW and read the bottom. Both readings then come
    from the text alone."""
    span = 0.0
    eb = elem.get_BoundingBox(view)
    if eb is not None:
        lo, hi = v_extent(eb)
        span = hi - lo
    d = span + 200.0 * MM_TO_FT * scale + 1.0

    tag.TagHeadPosition = to_xyz(head_u, v + d, depth)
    doc.Regenerate()
    bb = tag.get_BoundingBox(view)
    if bb is None:
        return 0.0
    top = v_extent(bb)[1] - (v + d)

    tag.TagHeadPosition = to_xyz(head_u, v - d, depth)
    doc.Regenerate()
    bb = tag.get_BoundingBox(view)
    if bb is None:
        return 0.0
    bottom = v_extent(bb)[0] - (v - d)
    return (top + bottom) / 2.0


# ---------------------------------------------------------------------------
# Highlighting picked components (temporary view override, restored on Finish)
# ---------------------------------------------------------------------------
_original_overrides = {}   # element id value -> (ElementId, original OverrideGraphicSettings)


def _id_key(eid):
    try:
        return eid.Value            # Revit 2024+
    except AttributeError:
        return eid.IntegerValue


def highlight(elem):
    key = _id_key(elem.Id)
    if key in _original_overrides:
        return
    original = view.GetElementOverrides(elem.Id)
    ogs = OverrideGraphicSettings(original)
    blue = Color(*HIGHLIGHT_COLOR)
    ogs.SetProjectionLineColor(blue)
    ogs.SetCutLineColor(blue)
    t = Transaction(doc, "Auto Tag - highlight component")
    t.Start()
    view.SetElementOverrides(elem.Id, ogs)
    t.Commit()
    _original_overrides[key] = (elem.Id, original)
    uidoc.RefreshActiveView()


def clear_highlights():
    if not _original_overrides:
        return
    t = Transaction(doc, "Auto Tag - clear highlights")
    t.Start()
    for eid, original in _original_overrides.values():
        try:
            if doc.GetElement(eid) is not None:
                view.SetElementOverrides(eid, original)
        except Exception:
            pass
    t.Commit()
    _original_overrides.clear()
    uidoc.RefreshActiveView()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def tag_batch(options, tag_types):
    """Pick a guide line + components and tag them. Returns (status, tags, errors)."""
    side = dict(TAG_OPTIONS)[options["tag"]]

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
    depth = p0.Subtract(V_ORIGIN).DotProduct(V_NORMAL)

    # 2. Components - click each one; press D or C at any time to switch tag; ESC to finish
    picks = []
    start_key_watch(side, tag_types, options["tag"])
    try:
        while True:
            prompt = "[{0}] Click component #{1} where the arrow should land  (D = Description, C = Comments, ESC = finish)".format(
                _watch["current"], len(picks) + 1)
            try:
                ref = uidoc.Selection.PickObject(ObjectType.Element, DetailItemFilter(), prompt)
            except RvtExc.OperationCanceledException:
                break
            elem = doc.GetElement(ref)
            u, v = to_uv(pick_point_of(ref, elem))
            picks.append((v, u, elem, _watch["current"]))
            highlight(elem)
    finally:
        stop_key_watch()
    if not picks:
        return "No components picked.", [], []

    # 3. Each tag sits level with its click so the leader runs horizontal
    scale = float(view.Scale) if view.Scale else 1.0
    offset = offset_mm * MM_TO_FT * scale
    head_u = line_u - offset if side == "left" else line_u + offset

    # 4. Create tags - committed per batch so they show up (and undo) straight away
    created, errors = [], []
    t = Transaction(doc, "Auto Tag Detail Components")
    t.Start()
    try:
        for end_v, end_u, elem, tag_name in picks:
            hv = end_v
            try:
                ref = Reference(elem)
                end = to_xyz(end_u, end_v, depth)
                # hv is where the leader should leave the text. Place the tag,
                # measure its text, then shift it so the text centre sits on hv.
                tag = create_tag(tag_types[tag_name], ref, to_xyz(head_u, hv, depth))
                head_v = hv - text_centre_offset(tag, elem, head_u, hv, depth, scale)
                head = to_xyz(head_u, head_v, depth)
                tag.TagHeadPosition = head
                tag.HasLeader = True
                elbow = to_xyz((head_u + end_u) / 2.0, hv, depth)  # on the horizontal run
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

    status = "Last run: created {0} tag(s) on the {1} of the line.".format(len(created), side)
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
    status = ("Draw a vertical detail line, then click 'Pick line & tag'. "
              "While picking, press D (Description) or C (Comments) to switch tag.")
    options = load_settings()
    try:
        while True:
            options = show_dialog(tag_types, options, status)
            if options is None:
                break
            save_settings(options)
            status, created, errors = tag_batch(options, tag_types)
            all_tags.extend(created)
            messages.extend(errors)
    finally:
        clear_highlights()      # put picked components back to normal on Finish/error

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
        # CPython3 hands enums back as ints: Manual = 0, Automatic = 1, Periodic = 2
        run_type = str(workspace.RunSettings.RunType)
        run_type = {"0": "Manual", "1": "Automatic", "2": "Periodic"}.get(run_type, run_type)
        if run_type != "Manual":
            return "Re-run: skipped ({0} mode) - switch the graph to Manual.".format(run_type)
        marked = 0
        for node in workspace.Nodes:
            # Read the Python code via reflection so it works whatever type the
            # Python engine wraps the node as.
            prop = node.GetType().GetProperty("Script")
            code = prop.GetValue(node, None) if prop is not None else None
            if code and "def force_rerun_next_time" in str(code):
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
