# FagNoon CP-SAT API

The API models each trip group as a continuous activity chain, uses OR-Tools CP-SAT to select activity order and start times, and applies `NoOverlap` constraints to shared locations across groups and trips. Welcome, synchronized lunch, Farewell, Reception handoffs, Color Fight, travel buffers, exact trip ends, and optional 5/10-minute duration cuts are represented in the model.

## Run locally

From the project root:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn solver.main:app --reload --port 8000
```

The health check is `http://localhost:8000/health` and the optimizer is `POST http://localhost:8000/api/optimize`.

## Deploy the API

The project includes `render.yaml` for a Render web service. Create a Blueprint from this repository. After it deploys, copy the service's HTTPS URL into `solver-config.js` as `window.FAGNOON_SOLVER_API_URL`, then publish that file with the website. The GitHub Pages site remains the team's interface; this Python service runs the CP-SAT model.

The API allows requests from the current GitHub Pages origin and local development. Update the CORS allowlist in `solver/main.py` if the website hostname changes.
