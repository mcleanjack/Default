# Auto Tag Detail Components (Revit + Dynamo)

Tags detail components in a 2D detail and lines the tag text up against a vertical guide line.

## Files

| File | Purpose |
|---|---|
| `AutoTagDetailComponents.dyn` | Open in Dynamo or run from **Dynamo Player** |
| `AutoTagDetailComponents.py` | The Python node source (the same code is embedded in the `.dyn`) |
| `build_dyn.py` | Rebuilds the `.dyn` after you edit the `.py` (`python build_dyn.py`) |

Requires Revit 2022+ with Dynamo 2.12+ (CPython3 engine). It also runs on the IronPython2 engine.

## How to use

1. In the detail view, draw a **vertical detail line** where the tag text should align.
2. Run the graph from Dynamo Player or the Dynamo editor.
3. In the dialog, choose:
   - **Tag type**
     - Left of the line: `Description Tag Align Right` or `Comments Tag Align Right`
     - Right of the line: `Description Tag` or `Comments Tag`
   - Optionally, **delete the guide line** after tagging.
4. Click the guide line.
5. Click each detail component **on the exact spot where the arrow should land**. You can press **D** (Description tag) or **C** (Comments tag) at any time, and the tag you choose is used for every click after that. When you switch, a small blue notice such as "Tag selected: Comments Tag" appears by the cursor for about 1.5 seconds. No popup appears between clicks. The tag chosen in the dialog sets the side of the line and the tag you start with. Press **ESC** to finish picking. Each picked component turns blue until you click **Finish**.

Each tag sits level with the point you clicked, with a straight horizontal Free End leader running from its text to that point. The text edge sits on the guide line. A tag type that isn't loaded in the project is greyed out in the dialog. Your last choices are remembered.

6. **The dialog comes back** after every batch, so you can keep going: draw another line, pick another tag type or side, and tag again. Click **Finish** when you're done. Each batch is committed straight away and is its own undo step (Ctrl+Z).

To start the script again after clicking Finish, just press **Run** again, in Dynamo Player or the Dynamo editor. Dynamo normally skips a node whose inputs haven't changed, so at the end of each run the script marks its own node as changed. Keep the graph in **Manual** run mode; in Automatic mode it would keep restarting itself, so the script doesn't do this there.

## Inputs (exposed in Dynamo Player)

| Input | Default | Meaning |
|---|---|---|
| Run | True | Set to False to stop the script from running |
| Text offset from guide line (mm on sheet) | 0 | The gap between the line and the text edge |

## Notes

- The script finds tag types by **type name or family name**, in both Multi-Category Tags and Detail Item Tags. To use different names, edit `TAG_OPTIONS` at the top of the `.py` file, then run `build_dyn.py`.
- For the text to finish exactly on the line, the label's origin in the "Align Right" families must be at the right edge of the text. In the left-aligned families, it must be at the left edge.
- Revit starts a leader at the vertical middle of the tag text. The script measures each tag and shifts it so that middle lines up with the leader, which keeps leaders horizontal for one-line and multi-line notes.
- Tags are never moved apart, so click components far enough apart vertically that the notes don't overlap.
- If pressing D or C ends picking early, a Revit keyboard shortcut is probably being triggered. Check *View > User Interface > Keyboard Shortcuts* for any shortcut that is just `D` or `C`.
