const PETAL_PATH = "M 0,-9 C 4,-8 4,-3 1,-1 C -1,-0.3 -1,-0.3 -0.5,-0.5 C -2,-3 -1.5,-7 0,-9 Z";
const STAR_POINTS =
  "0,-1 0.22,-0.31 0.95,-0.31 0.36,0.12 0.59,0.95 0,0.38 -0.59,0.95 -0.36,0.12 -0.95,-0.31 -0.22,-0.31";
const PETAL_ANGLES = [0, 72, 144, 216, 288];

/** A small decorative Hong Kong flag — five bauhinia petals swirling
 * around a center point, each with a red star, on the flag's red field.
 * Purely visual, no semantic meaning beyond "a spot of color". */
export function HongKongFlag() {
  return (
    <svg className="hk-flag" viewBox="0 0 30 20" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <rect width="30" height="20" fill="#de2910" />
      <g transform="translate(15,10)">
        {PETAL_ANGLES.map((angle) => (
          <g key={angle} transform={`rotate(${angle})`}>
            <path d={PETAL_PATH} fill="#ffffff" />
            <g transform="translate(0,-6.2) scale(0.8)">
              <polygon points={STAR_POINTS} fill="#de2910" />
            </g>
          </g>
        ))}
      </g>
    </svg>
  );
}
