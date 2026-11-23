from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from ortools.sat.python import cp_model


app = FastAPI(title="FagNoon Timeline Solver", version="1.0.0")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hussammuhamed1.github.io",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


def time_minutes(value: str) -> int:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", str(value or ""))
    if not match:
        raise ValueError(f"Invalid time: {value!r}")
    hour, minute = map(int, match.groups())
    if hour > 23 or minute > 59:
        raise ValueError(f"Invalid time: {value!r}")
    return hour * 60 + minute


def clean_name(value: Any, fallback: str) -> str:
    text = str(value or fallback).strip()
    return text or fallback


def cuttable_duration(model: cp_model.CpModel, name: str, base: int) -> cp_model.IntVar:
    if base < 1:
        raise ValueError(f"{name}: duration must be positive")
    allowed = sorted({base, *[base - cut for cut in (5, 10) if base - cut >= 15]})
    duration = model.NewIntVar(min(allowed), max(allowed), f"duration_{name}")
    model.AddAllowedAssignments([duration], [[value] for value in allowed])
    return duration


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "solver": "OR-Tools CP-SAT"}


@app.get("/", include_in_schema=False)
def planner_page() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "index.html", media_type="text/html")


@app.get("/images.jpg", include_in_schema=False)
def logo_image() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "images.jpg", media_type="image/jpeg")


@app.get("/solver-config.js", include_in_schema=False)
def solver_config() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "solver-config.js", media_type="application/javascript")


@app.post("/api/optimize")
def optimize(payload: dict[str, Any]) -> dict[str, Any]:
    trips = payload.get("trips")
    if not isinstance(trips, list) or not trips:
        raise HTTPException(400, "Send at least one trip.")

    model = cp_model.CpModel()
    trip_specs: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []
    room_events: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    cut_costs: list[cp_model.LinearExpr] = []
    parallel_terms: list[cp_model.IntVar] = []

    def make_event(
        *,
        name: str,
        place: str,
        priority: str,
        trip_index: int,
        trip_name: str,
        date: str,
        group: str,
        stage: str,
        duration: int | cp_model.IntVar,
        travel: int = 0,
        shared: bool = False,
    ) -> dict[str, Any]:
        safe = re.sub(r"\W+", "_", f"e{len(all_events) + 1}_t{trip_index}_{group}_{stage}_{name}")
        start = model.NewIntVar(0, 1440, f"start_{safe}")
        end = model.NewIntVar(0, 1440, f"end_{safe}")
        interval = model.NewIntervalVar(start, duration, end, f"interval_{safe}")
        event = {
            "name": name,
            "place": place,
            "priority": priority,
            "trip": trip_index,
            "tripName": trip_name,
            "date": date,
            "group": group,
            "stage": stage,
            "startVar": start,
            "endVar": end,
            "interval": interval,
            "durationVar": duration,
            "duration": duration if isinstance(duration, int) else None,
            "baseDuration": duration if isinstance(duration, int) else None,
            "travel": travel,
            "shared": shared,
        }
        all_events.append(event)
        room_events[(date, place.strip().casefold())].append(event)
        return event

    try:
        for trip_index, trip in enumerate(trips, start=1):
            trip_name = clean_name(trip.get("name"), f"Trip {trip_index}")
            date = str(trip.get("date") or "")
            earliest, latest, finish = map(
                time_minutes,
                (trip.get("earliest"), trip.get("latest"), trip.get("finish")),
            )
            if earliest > latest or latest >= finish:
                raise ValueError(f"{trip_name}: check its start window and trip end.")
            groups = int(trip.get("groups", 1))
            if groups < 1 or groups > 20:
                raise ValueError(f"{trip_name}: choose between 1 and 20 groups.")
            group_names = [f"Group {group_index}" for group_index in range(1, groups + 1)] if groups > 1 else ["Whole trip"]
            together_label = "Whole trip" if groups == 1 else "Both groups" if groups == 2 else "All groups"

            welcome_data = trip.get("welcome") or {}
            welcome = make_event(
                name="Welcome", place="Reception", priority="Mandatory",
                trip_index=trip_index, trip_name=trip_name, date=date,
                group=together_label,
                stage="welcome", duration=15, shared=True,
            )
            model.Add(welcome["startVar"] >= earliest)
            model.Add(welcome["startVar"] <= latest)

            core_events: dict[str, list[dict[str, Any]]] = {group: [] for group in group_names}
            activities = trip.get("core") or []
            if not activities:
                raise ValueError(f"{trip_name}: add at least one activity besides Welcome and Farewell.")
            for activity_index, activity in enumerate(activities, start=1):
                activity_name = clean_name(activity.get("name"), f"Activity {activity_index}")
                place = clean_name(activity.get("place"), "")
                if not place:
                    raise ValueError(f"{trip_name}, {activity_name}: choose a location.")
                base_duration = int(activity.get("minutes", 0))
                duration = cuttable_duration(model, f"t{trip_index}_a{activity_index}", base_duration)
                priority = clean_name(activity.get("priority"), "Medium")
                priority_weight = {"Mandatory": 10, "High": 5, "Medium": 2, "Optional": 1}.get(priority, 2)
                cut_costs.append((base_duration - duration) * priority_weight)
                sessions: dict[str, dict[str, Any]] = {}
                for group in group_names:
                    event = make_event(
                        name=activity_name, place=place, priority=priority,
                        trip_index=trip_index, trip_name=trip_name, date=date,
                        group=group, stage="activity", duration=duration,
                        travel=int(activity.get("travel", 0)),
                    )
                    event["baseDuration"] = base_duration
                    core_events[group].append(event)
                    sessions[group] = event
                if groups > 1:
                    trip_specs.extend({"parallel_pair": pair} for pair in combinations(sessions.values(), 2))

            lunch_data = trip.get("lunch") or {}
            lunch_duration = int(lunch_data.get("minutes", 30))
            if lunch_duration <= 0:
                raise ValueError(f"{trip_name}: Lunch duration must be positive.")
            lunch = make_event(
                name="Lunch", place="lunch place", priority="Mandatory",
                trip_index=trip_index, trip_name=trip_name, date=date,
                group=together_label,
                stage="lunch", duration=lunch_duration, travel=int(lunch_data.get("travel", 0)), shared=True,
            )

            color_fight = None
            color_data = trip.get("colorFight")
            if color_data:
                color_name = clean_name(color_data.get("name"), "Color Fight")
                color_place = clean_name(color_data.get("place"), "Outdoor Place 3")
                base_duration = int(color_data.get("minutes", 30))
                color_duration = cuttable_duration(model, f"t{trip_index}_color_fight", base_duration)
                cut_costs.append((base_duration - color_duration) * 10)
                color_fight = make_event(
                    name=color_name, place=color_place, priority="Mandatory",
                    trip_index=trip_index, trip_name=trip_name, date=date,
                    group=together_label,
                    stage="colorFight", duration=color_duration,
                    travel=int(color_data.get("travel", 0)), shared=True,
                )
                color_fight["baseDuration"] = base_duration

            farewell = make_event(
                name="Farewell", place="Reception", priority="Mandatory",
                trip_index=trip_index, trip_name=trip_name, date=date,
                group=together_label,
                stage="farewell", duration=15, shared=True,
            )
            model.Add(farewell["endVar"] == finish)

            group_chains: dict[str, list[dict[str, Any]]] = {}
            for group in group_names:
                chain = [welcome, *core_events[group], lunch]
                if color_fight:
                    chain.append(color_fight)
                chain.append(farewell)
                group_chains[group] = chain
                first, last = chain[0], chain[-1]
                arcs: list[tuple[int, int, cp_model.IntVar]] = []
                arc_vars: dict[tuple[int, int], cp_model.IntVar] = {}

                def add_arc(a: int, b: int) -> None:
                    arc = model.NewBoolVar(f"arc_t{trip_index}_{group}_{a}_{b}")
                    arcs.append((a, b, arc))
                    arc_vars[(a, b)] = arc

                count = len(chain)
                first_index, last_index = 1, count
                add_arc(0, first_index)
                add_arc(last_index, 0)
                color_index = count - 1 if color_fight else None
                for a in range(1, count + 1):
                    if a == last_index:
                        continue
                    for b in range(1, count + 1):
                        if b == first_index or a == b:
                            continue
                        if color_index is not None and (a == color_index and b != last_index or b == last_index and a != color_index):
                            continue
                        previous, following = chain[a - 1], chain[b - 1]
                        if (
                            groups == 1
                            and previous["stage"] == following["stage"] == "activity"
                            and previous["place"].strip().casefold() == following["place"].strip().casefold()
                            and any(
                                event["place"].strip().casefold() != previous["place"].strip().casefold()
                                for event in core_events[group]
                            )
                        ):
                            continue
                        add_arc(a, b)
                        model.Add(chain[b - 1]["startVar"] == chain[a - 1]["endVar"] + chain[b - 1]["travel"]).OnlyEnforceIf(arc_vars[(a, b)])
                model.AddCircuit(arcs)

            trip_specs.append({
                "name": trip_name,
                "idx": int(trip.get("idx", trip_index)),
                "date": date,
                "groups": groups,
                "earliest": earliest,
                "latest": latest,
                "finish": finish,
                "welcome": welcome,
                "farewell": farewell,
            })

        # A room has capacity one across all trips and both groups.
        reception_key = "reception"
        for (date, place_key), events in room_events.items():
            if place_key != reception_key:
                if len(events) > 1:
                    model.AddNoOverlap([event["interval"] for event in events])
                continue
            for index, first in enumerate(events):
                for second in events[index + 1 :]:
                    handoff = (
                        first["trip"] != second["trip"]
                        and first["stage"] in {"welcome", "farewell"}
                        and second["stage"] in {"welcome", "farewell"}
                    )
                    if not handoff:
                        model.AddNoOverlap([first["interval"], second["interval"]])

        for spec in trip_specs:
            pair = spec.get("parallel_pair")
            if not pair:
                continue
            first, second = pair
            if first["place"].strip().casefold() == second["place"].strip().casefold():
                continue
            pair_index = len(parallel_terms) + 1
            min_end = model.NewIntVar(0, 1440, f"min_end_{pair_index}")
            max_start = model.NewIntVar(0, 1440, f"max_start_{pair_index}")
            overlap = model.NewIntVar(0, 1440, f"parallel_{pair_index}")
            model.AddMinEquality(min_end, [first["endVar"], second["endVar"]])
            model.AddMaxEquality(max_start, [first["startVar"], second["startVar"]])
            model.AddMaxEquality(overlap, [0, min_end - max_start])
            parallel_terms.append(overlap)

        model.Maximize(sum(parallel_terms) - 1_000_000_000_000 * sum(cut_costs))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 20.0
        solver.parameters.num_search_workers = 8
        status = solver.Solve(model)
    except (ValueError, TypeError, KeyError) as error:
        raise HTTPException(400, str(error)) from error

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        proved = status == cp_model.INFEASIBLE
        return {
            "feasible": False,
            "status": solver.StatusName(status),
            "provenInfeasible": proved,
            "message": (
                "No conflict-free timeline can satisfy all entered constraints, even with allowed 5- or 10-minute activity reductions."
                if proved
                else "The solver did not find a conflict-free timeline before its time limit. Try changing trip windows, durations, or locations."
            ),
        }

    items = []
    for event in all_events:
        duration = solver.Value(event["endVar"]) - solver.Value(event["startVar"])
        items.append({
            "trip": event["trip"],
            "tripName": event["tripName"],
            "date": event["date"],
            "group": event["group"],
            "name": event["name"],
            "place": event["place"],
            "priority": event["priority"],
            "start": solver.Value(event["startVar"]),
            "end": solver.Value(event["endVar"]),
            "duration": duration,
            "travel": event["travel"],
            "stage": event["stage"],
        })

    trip_meta = []
    for spec in (entry for entry in trip_specs if "welcome" in entry):
        trip_meta.append({
            "idx": spec["idx"],
            "name": spec["name"],
            "date": spec["date"],
            "groups": spec["groups"],
            "start": solver.Value(spec["welcome"]["startVar"]),
            "end": solver.Value(spec["farewell"]["endVar"]),
            "finish": spec["finish"],
        })

    duration_cuts = []
    seen_durations: set[int] = set()
    for event in all_events:
        duration_var = event["durationVar"]
        if isinstance(duration_var, int) or id(duration_var) in seen_durations:
            continue
        seen_durations.add(id(duration_var))
        duration = solver.Value(duration_var)
        base = event["baseDuration"]
        if duration < base:
            duration_cuts.append({
                "trip": event["tripName"],
                "activity": event["name"],
                "by": base - duration,
            })

    return {
        "feasible": True,
        "status": solver.StatusName(status),
        "optimal": status == cp_model.OPTIMAL,
        "items": items,
        "tripMeta": trip_meta,
        "durationCuts": duration_cuts,
        "conflicts": [],
        "endMismatches": [],
        "objective": solver.ObjectiveValue(),
    }
