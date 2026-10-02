# Connect Aligned Dimensions (Dynamo for Revit)

Joins parallel dimension strings. Wherever two or more of the strings you pick
have a witness line at the same position, the script draws a detail line from
the outermost string to the string on the other side. The witness lines then
read as one continuous line.

It can also remove repeated segments. When the same segment (for example
4180 LIVING) appears in more than one picked string, it is kept only in the
string furthest from the building and removed from the others.

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
| Remove Duplicate Segments | `true` | Removes repeated segments from strings closer to the building. |
| Remove Duplicates Longer Than (mm) | `90` | Repeats this long or shorter (90 mm walls) stay on every string. Thicker walls, such as 240, and rooms are removed. Set it to 0 to remove 90 mm walls too. A short wall left with no room either side after the removal is deleted as well. |

## Notes
- Witness lines are treated as aligned when they are within 0.5 mm of each other (`POS_TOL`).
- The script only joins strings that point the same way and sit in the same view. You can pick horizontal and vertical strings together.
- You can press Run again as many times as you like; each run brings the picker back. Running it again does not draw a second copy of a line that is already there.
- Revit can't delete a segment from the middle of a string, so the script replaces the inner string with new strings either side of the removed segment. Above/Below text, prefixes, suffixes, value overrides and moved text are copied across. Other instance settings on the old string are not.
- A 90 mm wall that is also shown on a string further out keeps its dimension and witness lines, but its number is hidden. Revit won't allow a blank override, so the number is replaced with an invisible character. To show it again, clear *Replace With Text* on that segment.
- "Furthest from the building" is worked out from the elements the strings dimension.
- The lines are ordinary detail lines, so they do not move with the dimensions.
- The graph uses the CPython3 engine. If your Dynamo doesn't have that engine (for example, Revit 2025+ uses PythonNet3), pick the engine it has from the Python node's dropdown. The code works on IronPython2, CPython3 and PythonNet3.
