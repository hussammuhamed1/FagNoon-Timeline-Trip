# FagNoon CP-SAT API

The API models each trip group as a continuous activity chain, uses OR-Tools CP-SAT to select activity order and start times, and applies `NoOverlap` constraints to shared locations across groups and trips. Welcome, synchronized lunch, Farewell, Reception handoffs, Color Fight, travel buffers, exact trip ends, and optional 5/10-minute duration cuts are represented in the model.

## Run locally

From the project root:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn solver.main:app --reload --port 8000
```

The health check is `http://localhost:8000/health` and the optimizer is `POST http://localhost:8000/api/optimize`.

## Deploy the website and API together on Vercel

Import this repository into Vercel and deploy it. `pyproject.toml` points Vercel to the FastAPI application. The application serves the planner page and logo alongside `/api/optimize`; on Vercel, `solver-config.js` automatically connects the planner to the same origin. GitHub Pages remains available and continues to use the browser planner.

Vercel's Python runtime installs the packages in `pyproject.toml`. The `vercel.json` file gives the solver function a 60-second maximum duration. The Render Blueprint remains available as an alternate backend deployment.
