# Connect Aligned Dimensions (Dynamo for Revit)

Joins parallel dimension strings. Wherever two or more of the strings you pick
have a witness line at the same position, the script draws a detail line from
the outermost string to the string on the other side. The witness lines then
read as one continuous line.

## Files
- `ConnectAlignedDimensions.dyn`: ready-to-run graph for Dynamo and Dynamo Player.
- `ConnectAlignedDimensions.py`: the same Python code, for reading or pasting into your own graph.

## Use
1. Open the plan, section or elevation that holds the dimensions.
2. Run the graph from Dynamo Player, or open it in Dynamo and press **Run** (it is set to Manual).
3. Click each dimension string you want to connect. Only straight dimensions can be picked. Anything you had selected before running is already picked.
4. Click **Finish** on the Options Bar, or **Cancel** / Esc to stop without changing anything.

## Inputs
| Input | Default | Meaning |
|---|---|---|
| Line Style | `Thin Lines` | Line style for the new lines. If it is blank or not found, Revit's default is used. |
| Extend Past Outer Strings | `true` | Extends each line past the outer strings by the dimension type's *Witness Line Extension*. |

## Notes
- Witness lines are treated as aligned when they are within 0.5 mm of each other (`POS_TOL`).
- The script only joins strings that point the same way and sit in the same view. You can pick horizontal and vertical strings together.
- You can press Run again as many times as you like; each run brings the picker back. Running it again does not draw a second copy of a line that is already there.
- The lines are ordinary detail lines, so they do not move with the dimensions.
- The graph uses the CPython3 engine. If your Dynamo doesn't have that engine (for example, Revit 2025+ uses PythonNet3), pick the engine it has from the Python node's dropdown. The code works on IronPython2, CPython3 and PythonNet3.
