import asyncio
import json
import logging

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from config import get_llm
from mcp_client import current_weather, forecast, list_airlines, list_airports, tavily_search
from state import TravelState

llm = get_llm()
logger = logging.getLogger(__name__)

# Rough char guard so long upstream results (itinerary, budget notes, etc.) can't
# silently blow past the model's context window when they're concatenated together.
PROMPT_CHAR_LIMIT = 6000

# Cap on how much raw MCP tool output gets embedded in a specialist prompt.
MCP_DATA_CHAR_LIMIT = 3000


def _llm_text(system: str, prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage(content=system),
            HumanMessage(content=prompt),
        ]
    )
    return response.content


def _truncate(value, max_chars: int = PROMPT_CHAR_LIMIT) -> str:
    """Defensively cap text embedded into downstream prompts."""
    text = str(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def _extract_json(text: str) -> dict:
    """
    Pull the first {...} block out of a string and parse it.
    Pure function, no LLM calls -> trivially unit-testable.
    Raises ValueError (no braces found) or json.JSONDecodeError (bad JSON).
    """
    start = text.index("{")
    end = text.rindex("}") + 1
    return json.loads(text[start:end])


def _call_llm_json(system: str, prompt: str, llm_calls: int, max_retries: int = 1):
    """
    Call the LLM expecting strict JSON back. If the response doesn't parse,
    retry (up to max_retries times) by telling the model its previous reply
    wasn't valid JSON, instead of raising and crashing the whole graph run.

    Returns (parsed_dict, updated_llm_calls). On repeated failure, parsed_dict
    contains an "error" key so callers can degrade gracefully instead of crashing.
    """
    messages = [SystemMessage(content=system), HumanMessage(content=prompt)]

    for attempt in range(max_retries + 1):
        response = llm.invoke(messages)
        llm_calls += 1
        raw = response.content

        try:
            return _extract_json(raw), llm_calls
        except (ValueError, json.JSONDecodeError) as exc:
            if attempt >= max_retries:
                logger.warning(
                    "LLM returned invalid JSON after %d attempt(s): %s", attempt + 1, exc
                )
                return (
                    {"error": f"Failed to parse JSON after {attempt + 1} attempt(s): {exc}"},
                    llm_calls,
                )
            messages.append(AIMessage(content=raw))
            messages.append(
                HumanMessage(
                    content=(
                        "Your last response wasn't valid JSON "
                        f"(parse error: {exc}). Reply again with ONLY valid JSON, "
                        "no commentary and no markdown code fences."
                    )
                )
            )

    # Unreachable (loop always returns), kept for static analyzers / type checkers.
    return {"error": "Failed to parse JSON."}, llm_calls


def supervisor_agent(state: TravelState):
    query = state["user_query"]
    llm_calls = state.get("llm_calls", 0)

    # Guardrail + routing/constraint-extraction merged into a single LLM call
    # (was two separate calls) to halve supervisor latency/cost.
    prompt = f"""
You are the supervisor of a real-world multi-agent travel planning system.

Step 1: Decide whether this is a valid travel planning request.
Step 2: If it is valid, decide which specialist agents are needed and extract trip constraints.

Available agents:
- flight_agent: use when flights, airports, airlines, routes, or airfare guidance are needed
- hotel_agent: use when hotels, stays, neighborhoods, or accommodation are needed
- weather_agent: use when weather, climate, season, packing, or forecast is useful
- budget_agent: use when budget, affordability, cost, or price constraints are mentioned
- itinerary_agent: almost always needed to produce the travel plan

Return only JSON with this exact schema (no markdown fences, no commentary):
{{
  "allowed": true,
  "reason": "",
  "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration": "",
    "budget": "",
    "travel_style": "",
    "special_preferences": []
  }},
  "reasoning": ""
}}

If the request is NOT a valid travel planning request: set "allowed" to false, fill in "reason"
with why, set "selected_agents" to an empty list, and leave "trip_constraints" fields empty.

User request:
{query}
"""

    parsed, llm_calls = _call_llm_json(
        "You are a routing and input-validation guardrail for a travel planner. Return strict JSON only.",
        prompt,
        llm_calls,
    )

    if "error" in parsed:
        reason = "Supervisor could not produce a valid plan (malformed model output)."
        return {
            "selected_agents": [],
            "trip_constraints": {},
            "supervisor_reasoning": parsed["error"],
            "final_response": reason,
            "messages": [AIMessage(content=f"Supervisor error: {parsed['error']}")],
            "llm_calls": llm_calls,
        }

    if not parsed.get("allowed", False):
        reason = parsed.get("reason", "Request rejected by input guardrail.")
        return {
            "selected_agents": [],
            "trip_constraints": {},
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content=f"Guardrail blocked request: {reason}")],
            "llm_calls": llm_calls,
        }

    return {
        "selected_agents": parsed.get("selected_agents", []),
        "trip_constraints": parsed.get("trip_constraints", {}),
        "supervisor_reasoning": parsed.get("reasoning", ""),
        "messages": [AIMessage(content="Supervisor created the agent plan.")],
        "llm_calls": llm_calls,
    }


async def _gather_flight_data(destination: str):
    # Independent MCP calls -> run concurrently instead of two sequential asyncio.run()s.
    return await asyncio.gather(
        list_airports(destination, limit=10),
        list_airlines("", limit=10),
    )


def flight_agent(state: TravelState):
    query = state["user_query"]
    constraints = state.get("trip_constraints", {})
    destination = constraints.get("destination", "")

    if not destination:
        return {
            "flight_results": (
                "No destination was identified for this trip, so flight guidance "
                "could not be generated. Please clarify the destination and try again."
            ),
            "messages": [AIMessage(content="Flight agent skipped: no destination in trip constraints.")],
        }

    airports, airlines = asyncio.run(_gather_flight_data(destination))

    prompt = f"""
Create flight guidance for this trip.

User request:
{query}

Trip constraints:
{json.dumps(constraints, indent=2)}

Airport MCP data:
{_truncate(airports, MCP_DATA_CHAR_LIMIT)}

Airline MCP data:
{_truncate(airlines, MCP_DATA_CHAR_LIMIT)}

Include likely departure/arrival airports, relevant airlines,
estimated duration, fare range, peak season warning,
and booking advice.
"""

    result = _llm_text("You are a flight planning specialist.", prompt)

    return {
        "flight_results": result,
        "messages": [AIMessage(content="Flight agent completed.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def hotel_agent(state: TravelState):
    query = f"Best hotels and areas to stay for: {state['user_query']}"
    result = asyncio.run(tavily_search(query))

    return {
        "hotel_results": str(result),
        "messages": [AIMessage(content="Hotel agent completed.")],
        # No llm_calls increment: this node only calls the Tavily MCP tool, not the LLM,
        # so it doesn't contribute to LLM call/cost tracking. (Same for weather_agent.)
    }


async def _gather_weather_data(city: str):
    return await asyncio.gather(
        current_weather(city),
        forecast(city),
    )


def weather_agent(state: TravelState):
    constraints = state.get("trip_constraints", {})
    city = constraints.get("destination", "")

    if not city:
        return {
            "weather_results": (
                "No destination was identified for this trip, so weather data "
                "could not be retrieved."
            ),
            "messages": [AIMessage(content="Weather agent skipped: no destination in trip constraints.")],
        }

    weather_data, forecast_data = asyncio.run(_gather_weather_data(city))

    result = f"""
Current weather:
{weather_data}

Forecast:
{forecast_data}
"""

    return {
        "weather_results": result,
        "messages": [AIMessage(content="Weather agent completed.")],
        # No llm_calls increment here — see note in hotel_agent.
    }


def budget_agent(state: TravelState):
    prompt = f"""
Analyze whether this trip plan is realistic for the user's budget.

User request:
{state['user_query']}

Constraints:
{json.dumps(state.get('trip_constraints', {}), indent=2)}

Flight results:
{_truncate(state.get('flight_results', ''))}

Hotel results:
{_truncate(state.get('hotel_results', ''))}

Weather results:
{_truncate(state.get('weather_results', ''))}

Return a concise budget assessment with:
1. estimated cost categories
2. risk areas
3. money-saving suggestions
4. whether the plan seems feasible
"""

    result = _llm_text("You are a practical travel budget analyst.", prompt)

    return {
        "budget_results": result,
        "messages": [AIMessage(content="Budget agent completed.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def itinerary_agent(state: TravelState):
    prompt = f"""
Create a clear draft travel itinerary.

User request:
{state['user_query']}

Trip constraints:
{json.dumps(state.get('trip_constraints', {}), indent=2)}

Flight results:
{_truncate(state.get('flight_results', ''))}

Hotel results:
{_truncate(state.get('hotel_results', ''))}

Weather results:
{_truncate(state.get('weather_results', ''))}

Budget results:
{_truncate(state.get('budget_results', ''))}

Make the output structured, practical, and ready for human review.
"""

    result = _llm_text("You are an expert itinerary planner.", prompt)

    approval_request = f"""
Please review this draft travel plan.

{result}

Reply with approval or feedback.
"""

    return {
        "itinerary": result,
        "approval_request": approval_request,
        "messages": [AIMessage(content="Draft itinerary created for human review.")],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }


def human_approval_agent(state: TravelState):
    feedback = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional feedback for revision",
            },
        }
    )

    return {
        "approved": feedback["approved"],
        "human_feedback": feedback["feedback"],
        "messages": [AIMessage(content="Human approval step completed.")],
    }


def final_response_agent(state: TravelState):
    if state["approved"]:
        prompt = f"""
The human approved this draft itinerary.

Produce the final polished travel plan.

Draft itinerary:
{_truncate(state['itinerary'])}

Budget notes:
{_truncate(state['budget_results'])}
"""
    else:
        prompt = f"""
The human did not approve the draft.

Original user request:
{state['user_query']}

Draft itinerary:
{_truncate(state['itinerary'])}

Human feedback:
{_truncate(state['human_feedback'])}

Budget notes:
{_truncate(state['budget_results'])}
"""

    result = _llm_text("You produce final user-ready travel plans.", prompt)

    return {
        "final_response": result,
        "messages": [AIMessage(content=result)],
        "llm_calls": state.get("llm_calls", 0) + 1,
    }