# Connect Aligned Dimensions (Dynamo for Revit)

Tidies parallel dimension strings:
- Unticks **Leader** on every picked string, and on any string the script rebuilds.
- Spaces the strings evenly, 600 mm apart by default.
- When the same segment (for example 4180 LIVING) appears in more than one picked string, keeps it only in the string furthest from the building and removes it from the others.
- Repeated walls (90 and 240 mm by default) stay on every string, but their number is hidden on the inner strings.

The script does not connect the strings' witness lines. Revit's API can't lengthen individual witness lines, so drag them by hand where you want them to join.

## Files
- `ConnectAlignedDimensions.dyn`: ready-to-run graph for Dynamo and Dynamo Player.
- `ConnectAlignedDimensions.py`: the same Python code, for reading or pasting into your own graph.

## Use
1. Open the plan, section or elevation that holds the dimensions.
2. Run the graph from Dynamo Player, or open it in Dynamo and press **Run** (it is set to Manual).
3. Click each dimension string you want to tidy. Only straight dimensions can be picked. Anything you had selected before running is already picked.
4. Click **Finish** on the Options Bar, or **Cancel** / Esc to stop without changing anything.

## Inputs
| Input | Default | Meaning |
|---|---|---|
| Remove Duplicate Segments | `true` | Removes repeated segments from strings closer to the building, and hides repeated wall numbers. |
| Max Wall Thickness (mm) | `240` | Repeats this long or shorter count as walls: they stay on every string, with their number hidden except on the string furthest from the building. Longer repeats (rooms) are removed. A wall left with no room either side after the removal is deleted. Set it to 90 to remove repeated 240 walls instead of hiding them. |
| String Spacing (mm) | `600` | Moves the strings so each is this far (model size) from the one inside it. The string closest to the building stays put. 0 leaves them where they are. |

## Order of steps
1. Untick Leader on the picked strings.
2. Space the strings.
3. Remove repeated rooms and hide repeated wall numbers.

Strings at the same distance from the building (such as the pieces of a rebuilt string) count as one row and move together. Strings on opposite sides of the building are spaced separately. Pinned dimensions can't be moved; the report lists them.

## Notes
- Witness lines are treated as aligned when they are within 0.5 mm of each other (`POS_TOL`).
- The script only compares strings that point the same way and sit in the same view. You can pick horizontal and vertical strings together.
- You can press Run again as many times as you like; each run brings the picker back.
- Revit can't delete a segment from the middle of a string, so the script replaces the inner string with new strings either side of the removed segment. Above/Below text, prefixes, suffixes and value overrides are copied to the segment at the same place on the new string. The numbers go back to Revit's default position above each segment, so any you had dragged by hand need moving again. Other instance settings on the old string are not copied.
- Hidden wall numbers: Revit won't allow a blank override, so the number is replaced with an invisible character. To show it again, clear *Replace With Text* on that segment.
- "Furthest from the building" is worked out from the elements the strings dimension.
- The graph uses the CPython3 engine. If your Dynamo doesn't have that engine (for example, Revit 2025+ uses PythonNet3), pick the engine it has from the Python node's dropdown. The code works on IronPython2, CPython3 and PythonNet3.
