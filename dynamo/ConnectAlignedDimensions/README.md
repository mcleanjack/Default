# Connect Aligned Dimensions (Dynamo for Revit)

Joins parallel dimension strings using their own witness lines. When a string
shares a witness line position with a string closer to the building, its
witness lines are lengthened to reach that inner string. They stay part of the
dimension and move with it.

It can also space the strings evenly (600 mm apart by default) and tidy
repeated segments:
- When the same segment (for example 4180 LIVING) appears in more than one picked string, it is kept only in the string furthest from the building and removed from the others.
- Repeated 90 mm walls stay on every string, but their number is hidden on the inner strings.

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
| String Spacing (mm) | `600` | Moves the strings so each is this far (model size) from the one inside it. The string closest to the building stays put. 0 leaves them where they are. |
| Extend Past Inner String | `true` | Witness lines run past the inner string by its type's *Witness Line Extension*. Off, they stop at the inner string. |
| Remove Duplicate Segments | `true` | Removes repeated segments from strings closer to the building, and hides repeated 90 mm wall numbers. |
| Remove Duplicates Longer Than (mm) | `90` | Repeats this long or shorter (90 mm walls) stay on every string. Thicker walls, such as 240, and rooms are removed. Set it to 0 to remove 90 mm walls too. A short wall left with no room either side after the removal is deleted as well. |

## Order of steps
1. Space the strings.
2. Remove repeated segments and hide repeated 90 mm numbers.
3. Lengthen the witness lines to reach the next string in.

Strings at the same distance from the building (such as the pieces of a rebuilt string) count as one row and move together. Strings on opposite sides of the building are spaced separately. Pinned dimensions can't be moved; the report lists them.

## How the witness lines are lengthened
Revit's API can't change the length of individual witness lines. The only control a script has is the dimension type's *Witness Line Control* setting. So:
- Each outer string is given a copy of its dimension type, named like `Linear - 2.5mm Arial - 6mm Witness`. The copy is set to *Fixed to Dimension Line*, with a *Witness Line Length* that reaches the next string in.
- **Every** witness line on that outer string gets that length, including ones with no matching witness line on the inner string.
- Strings with the same type and spacing share one copied type. Running the script again reuses it.
- The length is worked out from the view scale, so the strings will no longer touch if you change the view scale or move a string. Run the script again to update.
- The type settings are found by their English names (*Witness Line Control*, *Witness Line Length*). In a non-English Revit the report will say the witness lines were not changed.

## Notes
- Witness lines are treated as aligned when they are within 0.5 mm of each other (`POS_TOL`).
- The script only joins strings that point the same way and sit in the same view. You can pick horizontal and vertical strings together.
- You can press Run again as many times as you like; each run brings the picker back.
- Revit can't delete a segment from the middle of a string, so the script replaces the inner string with new strings either side of the removed segment. Above/Below text, prefixes, suffixes, value overrides and moved text are copied across. Other instance settings on the old string are not.
- Hidden 90 mm numbers: Revit won't allow a blank override, so the number is replaced with an invisible character. To show it again, clear *Replace With Text* on that segment.
- "Furthest from the building" is worked out from the elements the strings dimension.
- The graph uses the CPython3 engine. If your Dynamo doesn't have that engine (for example, Revit 2025+ uses PythonNet3), pick the engine it has from the Python node's dropdown. The code works on IronPython2, CPython3 and PythonNet3.
