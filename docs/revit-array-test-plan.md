# Vertical lines array: Revit test plan

Formulas under test, as set up in `revit/array-spacing-setup.md` in the
project files (array uses Move To: 2nd, so the spacing is fixed):

- `Spacing = 4.2 mm`
- `Count = if(Length < Spacing, 2, rounddown(Length / Spacing + 0.0001) + 1)`
- `Remainder = Length - (Count - 1) * Spacing`

The `+ 0.0001` guards against floating-point error: Revit stores lengths in
feet, so a value like 29.4 mm / 4.2 mm can evaluate to 6.9999999 and
`rounddown` would drop a line exactly on the multiples. The `if` keeps Count
at 2 or more, since an array of 1 errors.

## How to run

1. Open the family, select the Length parameter in Family Types.
2. For each row below, type the Length, click Apply, and check:
   - number of lines matches **Lines**
   - every gap between lines is 4.2 mm
   - the `Remainder` parameter in Family Types matches **Remainder**
   - the remainder is always under 4.2 mm (never an oversized last column)
   - the last line never passes the `Right` reference plane (except the
     under-4.2 mm guard row)
3. Load into a project, place an instance, and drag the end grip across a few
   of the same values to confirm the instance flexes the same way.

| Length (mm) | Lines | Remainder (mm) | Why it's here                      |
|-------------|-------|----------------|------------------------------------|
| 3           | 2     | -1.2           | guard: second line sits past end   |
| 4.2         | 2     | 0              | smallest exact multiple            |
| 8.4         | 3     | 0              | exact multiple                     |
| 10          | 3     | 1.6            | non-multiple                       |
| 12.6        | 4     | 0              | exact multiple                     |
| 29.4        | 8     | 0              | float trap: 7 without the + 0.0001 |
| 42          | 11    | 0              | float trap, from the setup doc     |
| 44          | 11    | 2              | non-multiple, from the setup doc   |
| 46.2        | 12    | 0              | exact multiple, from the setup doc |
| 50          | 12    | 3.8            | remainder close to 4.2             |
| 100         | 24    | 3.4            | non-multiple                       |
| 100.8       | 25    | 0              | exact multiple                     |
| 123.4       | 30    | 1.6            | larger non-multiple                |

## Edge cases to note, not fix

- Below 4.2 mm the guard keeps 2 lines, so the second line sits past the
  `Right` plane and `Remainder` goes negative. That's expected, not a bug.
- If you use the optional end line (`Show End Line = Remainder > 0.01 mm`),
  check it is hidden on every row with a remainder of 0 and shown on the rest.
