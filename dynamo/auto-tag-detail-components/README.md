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

1. In the detail view, draw a **vertical detail line** where the tag text should align. Draw it from where you want the top tag to where you want the bottom tag.
2. Run the graph. Dynamo Player is the best option because it re-runs every time. In the Dynamo editor, toggle **Run** off and on to run it again.
3. In the dialog, choose:
   - **Tag type**
     - Left of the line: `Description Tag Align Right` or `Comments Tag Align Right`
     - Right of the line: `Description Tag` or `Comments Tag`
   - **Leader**: *Right-angle bend*, which runs horizontally from the text and then vertically to the component, or *Straight horizontal*, which keeps each tag level with the point you clicked so its leader runs dead horizontal. With *Straight horizontal*, the *Tag height* options are greyed out.
   - **Tag height**: *Level with each picked point*, or *Spread evenly along the guide line* (from the top of the line to the bottom).
   - Optionally, **delete the guide line** after tagging.
4. Click the guide line.
5. Click each detail component **on the exact spot where the arrow should land**. Press **ESC** to finish. Each component you pick **turns blue** and stays blue, across batches, until you click **Finish**. Then its original graphics are restored. If Revit ever closes mid-run and leaves a component blue, right-click it and choose *Override Graphics in View > By Element... > Reset*.

The tags are created as Free End leaders, with the tag head on the guide line. A tag type that isn't loaded in the project is greyed out in the dialog. Your last choices are remembered.

6. **The dialog comes back** after every batch, so you can keep going: draw another line, pick another tag type or side, and tag again. Click **Finish** when you're done. Each batch is committed straight away and is its own undo step (Ctrl+Z).

To start the script again after clicking Finish, just press **Run** again, in Dynamo Player or the Dynamo editor. Dynamo normally skips a node whose inputs haven't changed, so at the end of each run the script marks its own node as changed. Keep the graph in **Manual** run mode; in Automatic mode it would keep restarting itself, so the script doesn't do this there.

## Inputs (exposed in Dynamo Player)

| Input | Default | Meaning |
|---|---|---|
| Run | True | Set to False to stop the script from running |
| Minimum tag spacing (mm on sheet) | 5 | The smallest vertical gap allowed between tag heads. Tags that would overlap are pushed down. |
| Text offset from guide line (mm on sheet) | 0 | The gap between the line and the text edge |

## Notes

- The script finds tag types by **type name or family name**, in both Multi-Category Tags and Detail Item Tags. To use different names, edit `TAG_OPTIONS` at the top of the `.py` file, then run `build_dyn.py`.
- For the text to finish exactly on the line, the label's origin in the "Align Right" families must be at the right edge of the text. In the left-aligned families, it must be at the left edge.
- Revit starts a leader at the vertical middle of the tag text. The script measures each tag and shifts it so that middle lines up with the leader, which keeps leaders horizontal for one-line and multi-line notes.
- With *Straight horizontal*, tags are never moved apart, so click components far enough apart vertically that the notes don't overlap.
- If you choose *Right-angle bend* with *Level with each picked point*, a leader only gets a vertical leg when its tag had to be moved to keep the minimum spacing. Otherwise the leader is a straight horizontal line. To get a right-angle leg on every tag, use *Spread evenly*.
