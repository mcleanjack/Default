# Vertical lines array: Revit test plan

Formulas under test (array set to fixed spacing, not "fit"):

- `Count = rounddown(Length / 4.2 mm + 0.0001) + 1`
- Spacing parameter locked at `4.2 mm`

The `+ 0.0001` guards against floating-point error: Revit stores lengths in
feet, so a value like 29.4 mm / 4.2 mm can evaluate to 6.9999999 and
`rounddown` would drop a line exactly on the multiples.

## How to run

1. Open the family, select the Length parameter in Family Types.
2. For each row below, type the Length, click Apply, and check:
   - number of lines matches **Lines**
   - every gap between lines is 4.2 mm
   - the space from the last line to the end matches **Remainder**
   - the remainder is always under 4.2 mm (never an oversized last column)
3. Load into a project, place an instance, and drag the end grip across a few
   of the same values to confirm the instance flexes the same way.

| Length (mm) | Lines | Remainder (mm) | Why it's here              |
|-------------|-------|----------------|----------------------------|
| 4.2         | 2     | 0              | smallest valid size        |
| 8.4         | 3     | 0             | exact multiple             |
| 10          | 3     | 1.6           | non-multiple               |
| 12.6        | 4     | 0             | exact multiple             |
| 29.4        | 8     | 0             | float trap: 7 without guard |
| 50          | 12    | 3.8           | gap close to 4.2           |
| 100         | 24    | 3.4           | non-multiple               |
| 100.8       | 25    | 0             | exact multiple             |
| 123.4       | 30    | 1.6           | larger non-multiple        |

## Edge cases to note, not fix

- Length below 4.2 mm gives Count = 1, and Revit arrays need at least 2, so
  the family will error. Either constrain Length >= 4.2 mm or accept it.
- On exact multiples the last line lands on the end reference. If the family
  also draws a separate boundary line there, the two will overlap.
