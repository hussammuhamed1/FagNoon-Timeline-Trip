// On Vercel, the planner and CP-SAT API share the same origin. GitHub Pages
// continues using the browser planner until a separate API URL is configured.
window.FAGNOON_SOLVER_API_URL = location.hostname.endsWith("github.io") ? "" : location.origin;
