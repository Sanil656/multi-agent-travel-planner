# """
# Tests for agents.py.

# These target the reliability fixes: JSON extraction/retry, defensive
# destination access, and the merged supervisor call. They assume config.py,
# state.py, and mcp_client.py exist in the same project (your real ones —
# these tests only ever touch `agents.llm`, never the real network/LLM).
# """
# import json
# from types import SimpleNamespace

# import pytest

# import agents


# # ---------------------------------------------------------------------------
# # _extract_json: pure function, no mocking needed
# # ---------------------------------------------------------------------------

# def test_extract_json_parses_clean_json():
#     assert agents._extract_json('{"a": 1}') == {"a": 1}


# def test_extract_json_ignores_surrounding_prose():
#     text = 'Sure, here you go:\n{"a": 1, "b": [1, 2]}\nHope that helps!'
#     assert agents._extract_json(text) == {"a": 1, "b": [1, 2]}


# def test_extract_json_raises_on_no_braces():
#     with pytest.raises(ValueError):
#         agents._extract_json("no json here")


# def test_extract_json_raises_on_malformed_json():
#     with pytest.raises(json.JSONDecodeError):
#         agents._extract_json('{"a": 1,}')


# # ---------------------------------------------------------------------------
# # _call_llm_json: retries once on bad JSON instead of crashing
# # ---------------------------------------------------------------------------

# class _ScriptedLLM:
#     """Fake llm.invoke() that returns each response in `replies`, in order."""

#     def __init__(self, replies):
#         self._replies = list(replies)
#         self.calls = 0

#     def invoke(self, messages):
#         self.calls += 1
#         content = self._replies.pop(0)
#         return SimpleNamespace(content=content)


# def test_call_llm_json_succeeds_first_try(monkeypatch):
#     monkeypatch.setattr(agents, "llm", _ScriptedLLM(['{"allowed": true}']))
#     parsed, llm_calls = agents._call_llm_json("sys", "prompt", llm_calls=0)
#     assert parsed == {"allowed": True}
#     assert llm_calls == 1


# def test_call_llm_json_retries_then_succeeds(monkeypatch):
#     fake = _ScriptedLLM(["not json at all", '{"allowed": true}'])
#     monkeypatch.setattr(agents, "llm", fake)
#     parsed, llm_calls = agents._call_llm_json("sys", "prompt", llm_calls=0, max_retries=1)
#     assert parsed == {"allowed": True}
#     assert llm_calls == 2
#     assert fake.calls == 2


# def test_call_llm_json_gives_up_after_max_retries(monkeypatch):
#     fake = _ScriptedLLM(["nope", "still nope"])
#     monkeypatch.setattr(agents, "llm", fake)
#     parsed, llm_calls = agents._call_llm_json("sys", "prompt", llm_calls=0, max_retries=1)
#     assert "error" in parsed
#     assert llm_calls == 2  # doesn't loop forever / doesn't raise


# # ---------------------------------------------------------------------------
# # flight_agent / weather_agent: missing destination no longer KeyErrors
# # ---------------------------------------------------------------------------

# def test_flight_agent_handles_missing_destination():
#     state = {"user_query": "plan a trip", "trip_constraints": {}, "llm_calls": 0}
#     result = agents.flight_agent(state)
#     assert "flight_results" in result
#     assert "destination" in result["flight_results"].lower()
#     assert "llm_calls" not in result  # skipped before any LLM call


# def test_weather_agent_handles_missing_destination():
#     state = {"user_query": "plan a trip", "trip_constraints": {}, "llm_calls": 0}
#     result = agents.weather_agent(state)
#     assert "weather_results" in result
#     assert "destination" in result["weather_results"].lower()


# # ---------------------------------------------------------------------------
# # supervisor_agent: single merged call handles both guardrail + routing
# # ---------------------------------------------------------------------------

# def test_supervisor_agent_blocks_disallowed_request(monkeypatch):
#     reply = json.dumps({
#         "allowed": False,
#         "reason": "Not a travel request.",
#         "selected_agents": [],
#         "trip_constraints": {},
#         "reasoning": "",
#     })
#     monkeypatch.setattr(agents, "llm", _ScriptedLLM([reply]))
#     state = {"user_query": "write me a poem", "llm_calls": 0}
#     result = agents.supervisor_agent(state)
#     assert result["selected_agents"] == []
#     assert result["llm_calls"] == 1  # one call total, not two


# def test_supervisor_agent_routes_valid_request(monkeypatch):
#     reply = json.dumps({
#         "allowed": True,
#         "reason": "",
#         "selected_agents": ["flight_agent", "itinerary_agent"],
#         "trip_constraints": {"destination": "Lisbon"},
#         "reasoning": "Simple trip.",
#     })
#     monkeypatch.setattr(agents, "llm", _ScriptedLLM([reply]))
#     state = {"user_query": "plan a trip to Lisbon", "llm_calls": 0}
#     result = agents.supervisor_agent(state)
#     assert result["selected_agents"] == ["flight_agent", "itinerary_agent"]
#     assert result["trip_constraints"]["destination"] == "Lisbon"
#     assert result["llm_calls"] == 1

