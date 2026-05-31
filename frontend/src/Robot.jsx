import "./Robot.css";

// One little robot, four moods. The base body is identical across every
// state — only the antenna light, eyes/mouth expression, arm motion and the
// little accessory beside his head change. Drive it with the `state` prop:
// "idle" | "thinking" | "working" | "waiting".
export default function Robot({ state = "idle" }) {
  return (
    <svg
      className={`robot robot--${state}`}
      viewBox="0 0 150 120"
      width="72"
      height="58"
      role="img"
      aria-label={`Agent is ${state}`}
    >
      {/* antenna */}
      <line className="robot__stroke" x1="60" y1="20" x2="60" y2="9" strokeWidth="3" strokeLinecap="round" />
      <circle className="robot__antenna" cx="60" cy="6" r="4.5" />

      {/* head */}
      <rect className="robot__head" x="34" y="20" width="52" height="38" rx="11" />
      {/* face screen */}
      <rect className="robot__face" x="40" y="26" width="40" height="26" rx="7" />

      {/* eyes (blink + expression handled in CSS) */}
      <g className="robot__eyes">
        <circle className="robot__eye robot__eye--l" cx="51" cy="39" r="4.5" />
        <circle className="robot__eye robot__eye--r" cx="69" cy="39" r="4.5" />
      </g>
      {/* mouth */}
      <rect className="robot__mouth" x="54" y="47" width="12" height="3" rx="1.5" />

      {/* arms */}
      <rect className="robot__arm robot__arm--l" x="24" y="62" width="8" height="22" rx="4" />
      <rect className="robot__arm robot__arm--r" x="88" y="62" width="8" height="22" rx="4" />

      {/* torso */}
      <rect className="robot__body" x="38" y="60" width="44" height="34" rx="9" />
      <circle className="robot__chest" cx="60" cy="77" r="4.5" />

      {/* legs */}
      <rect className="robot__leg" x="47" y="94" width="8" height="11" rx="3" />
      <rect className="robot__leg" x="65" y="94" width="8" height="11" rx="3" />

      {/* ---- accessories beside his head (one per mood) ---- */}

      {/* thinking: thought bubble with cycling dots */}
      {state === "thinking" && (
        <g className="robot__accessory robot__think">
          <circle className="robot__bubble" cx="100" cy="44" r="3.5" />
          <circle className="robot__bubble" cx="107" cy="36" r="5" />
          <ellipse className="robot__bubble" cx="124" cy="24" rx="16" ry="11" />
          <circle className="robot__dot robot__dot--1" cx="116" cy="24" r="2.4" />
          <circle className="robot__dot robot__dot--2" cx="124" cy="24" r="2.4" />
          <circle className="robot__dot robot__dot--3" cx="132" cy="24" r="2.4" />
        </g>
      )}

      {/* working: spinning gear (heads-down focus).
          Outer group positions; inner group spins — so the CSS rotate
          transform doesn't clobber the SVG translate. */}
      {state === "working" && (
        <g className="robot__accessory" transform="translate(122 28)">
          <g className="robot__gear">
            <path
              className="robot__gear-shape"
              d="M0-13 3-11 6-13 8-10 12-11 11-6 14-4 12 0 14 4 11 6 12 11 8 10 6 13 3 11 0 13 -3 11 -6 13 -8 10 -12 11 -11 6 -14 4 -12 0 -14-4 -11-6 -12-11 -8-10 -6-13 -3-11Z"
            />
            <circle className="robot__gear-hub" cx="0" cy="0" r="5" />
          </g>
        </g>
      )}

      {/* waiting for human: speech bubble with a "?" */}
      {state === "waiting" && (
        <g className="robot__accessory robot__wait">
          <path
            className="robot__speech"
            d="M100 12h36a7 7 0 0 1 7 7v16a7 7 0 0 1-7 7h-19l-9 8 1-8h-9a7 7 0 0 1-7-7V19a7 7 0 0 1 7-7Z"
          />
          <text className="robot__q" x="118" y="34">?</text>
        </g>
      )}

      {/* idle: slow drifting "z z z" */}
      {state === "idle" && (
        <g className="robot__accessory robot__idle">
          <text className="robot__z robot__z--1" x="98" y="40">z</text>
          <text className="robot__z robot__z--2" x="110" y="28">z</text>
          <text className="robot__z robot__z--3" x="124" y="16">z</text>
        </g>
      )}
    </svg>
  );
}
