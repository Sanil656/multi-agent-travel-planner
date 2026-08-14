import uuid
import streamlit as st
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from graph import app

# Set page configuration with a modern layout and travel icon
st.set_page_config(
    page_title="Real-World Multi-Agent Travel Planner",
    page_icon=":material/explore:",
    layout="wide"
)

st.markdown("# :material/flight_takeoff: Real-world multi-agent travel planner")

# Preset travel suggestions
SUGGESTIONS = {
    ":material/explore: Japan Budget Trip": "Plan a 7-day Japan trip under Rs. 2 lakh. I prefer budget hotels and no overnight flights.",
    ":material/beach_access: Weekend in Goa": "Plan a 3-day relaxing weekend trip to Goa. Focus on beachside resorts, seafood, and historic forts.",
    ":material/euro_symbol: Europe Explorer": "Plan a 10-day trip to Paris and Rome for a couple. Medium budget, focus on art galleries, history, and local food.",
    ":material/forest: Wildlife Safari": "Plan a 4-day trip to Jim Corbett National Park. Looking for safari rides, luxury resort stays, and bird watching."
}

# Sidebar configuration
with st.sidebar:
    st.markdown("### :material/settings: Session settings")
    user_id = st.text_input("User ID", value="demo_user")
    
    if "thread_id" not in st.session_state:
        st.session_state.thread_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        
    if st.button("New session", icon=":material/add:", type="secondary"):
        st.session_state.thread_id = f"{user_id}_{uuid.uuid4().hex[:8]}"
        st.session_state.pop("waiting_for_approval", None)
        st.session_state.pop("latest_result", None)
        st.session_state.pop("travel_query", None)
        st.rerun()

    st.space("small")
    st.container(border=True).caption(f"**Active Thread ID:**\n`{st.session_state.thread_id}`")

# Initialize session state travel query
if "travel_query" not in st.session_state:
    st.session_state.travel_query = ""

# Suggestion pills (only show if no result exists yet)
if not st.session_state.get("latest_result"):
    st.caption("Need inspiration? Try one of these travel prompts:")
    selected = st.pills(
        "Suggestions",
        list(SUGGESTIONS.keys()),
        selection_mode="single",
        label_visibility="collapsed"
    )
    if selected:
        st.session_state.travel_query = SUGGESTIONS[selected]

# User travel input form
query = st.text_area(
    "Travel request",
    value=st.session_state.travel_query,
    placeholder="Plan a 7-day Japan trip under Rs. 2 lakh. I prefer budget hotels and no overnight flights.",
    height=110,
)

config = {"configurable": {"thread_id": st.session_state.thread_id}}

# Handle form submission
if st.button("Create Draft Plan", type="primary", icon=":material/smart_toy:"):
    if not query.strip():
        st.warning("Please enter a travel request first.")
    else:
        with st.status("Planning your trip...", expanded=True) as status:
            status.write("🤖 Supervisor analyzing request and routing to specialists...")
            
            result = app.invoke(
                {
                    "messages": [HumanMessage(content=query)],
                    "user_id": user_id,
                    "user_query": query,
                    "flight_results": "",
                    "hotel_results": "",
                    "weather_results": "",
                    "budget_results": "",
                    "itinerary": "",
                    "final_response": "",
                    "llm_calls": 0,
                },
                config=config,
            )
            
            status.update(label="Trip plan drafted!", state="complete", expanded=False)

        st.session_state.latest_result = result
        st.session_state.waiting_for_approval = "__interrupt__" in result

# Retrieve execution results from session state
result = st.session_state.get("latest_result")

if result:
    # Set up layout tabs
    tab_itinerary, tab_flights_hotels, tab_weather_budget, tab_logs = st.tabs([
        "🗺️ Itinerary",
        "✈️ Flights & Hotels",
        "🌤️ Weather & Budget",
        "⚙️ Planning Logs"
    ])
    
    # Tab 1: Main Itinerary
    with tab_itinerary:
        if "__interrupt__" in result:
            draft = result["__interrupt__"][0].value.get("draft_itinerary", "")
        else:
            draft = result.get("itinerary", "")
            
        if result.get("final_response"):
            st.markdown("### :material/tour: Final Travel Plan")
            st.markdown(result["final_response"])
            st.download_button(
                label="Download travel plan",
                data=result["final_response"],
                file_name="travel_plan.md",
                mime="text/markdown",
                icon=":material/download:"
            )
        elif draft:
            st.markdown("### :material/edit_note: Draft Itinerary")
            st.markdown(draft)
        else:
            st.info("No itinerary generated yet.")
            
    # Tab 2: Flight & Hotel side-by-side details
    with tab_flights_hotels:
        col_flight, col_hotel = st.columns(2)
        with col_flight:
            with st.container(border=True, height=500):
                st.markdown("### :material/flight_takeoff: Flight Options")
                flight_data = result.get("flight_results", "")
                if flight_data.strip():
                    st.markdown(flight_data)
                else:
                    st.caption("No flight details loaded.")
        with col_hotel:
            with st.container(border=True, height=500):
                st.markdown("### :material/hotel: Hotel Options")
                hotel_data = result.get("hotel_results", "")
                if hotel_data.strip():
                    st.markdown(hotel_data)
                else:
                    st.caption("No hotel details loaded.")

    # Tab 3: Weather & Budget side-by-side details
    with tab_weather_budget:
        col_weather, col_budget = st.columns(2)
        with col_weather:
            with st.container(border=True, height=500):
                st.markdown("### :material/partly_cloudy_day: Weather Forecast")
                weather_data = result.get("weather_results", "")
                if weather_data.strip():
                    st.markdown(weather_data)
                else:
                    st.caption("No weather details loaded.")
        with col_budget:
            with st.container(border=True, height=500):
                st.markdown("### :material/payments: Budget & Expenses")
                budget_data = result.get("budget_results", "")
                if budget_data.strip():
                    st.markdown(budget_data)
                else:
                    st.caption("No budget details loaded.")

    # Tab 4: Diagnostics and routing logs
    with tab_logs:
        with st.container(border=True):
            st.markdown("### :material/history_edu: Multi-agent system diagnostic logs")
            st.markdown(f"**Total LLM calls:** :blue-badge[{result.get('llm_calls', 0)}]")
            
            selected_agents_badges = " ".join([f":green-badge[{agent}]" for agent in result.get("selected_agents", [])])
            st.markdown(f"**Selected agents:** {selected_agents_badges}")
            
            st.markdown("### Supervisor reasoning")
            reasoning = result.get("supervisor_reasoning", "")
            if reasoning:
                st.info(reasoning, icon=":material/smart_toy:")
            else:
                st.caption("No reasoning logs generated.")

# Handle human feedback / approval loop
if st.session_state.get("waiting_for_approval"):
    st.space("medium")
    with st.container(border=True):
        st.markdown("### :material/rate_review: Human approval required")
        st.markdown("Please review the draft itinerary in the **🗺️ Itinerary** tab. You can approve it to generate the final response, or request adjustments.")
        
        approved_action = st.segmented_control(
            "Do you approve this draft?",
            options=["Approve and finalize", "Request adjustments"],
            default="Approve and finalize"
        )
        
        feedback = st.text_area(
            "Adjustment instructions",
            placeholder="e.g., Please choose a cheaper hotel, or add one day in Tokyo...",
            disabled=(approved_action == "Approve and finalize"),
            height=100
        )
        
        if st.button("Submit decision", type="primary", icon=":material/check_circle:"):
            with st.status("Finalizing travel plan...", expanded=True) as status:
                status.write("🤖 Supervisor revising plan based on feedback...")
                
                final_result = app.invoke(
                    Command(
                        resume={
                            "approved": approved_action == "Approve and finalize",
                            "feedback": feedback,
                        }
                    ),
                    config=config,
                )
                status.update(label="Travel plan finalized!", state="complete", expanded=False)
                
            st.session_state.latest_result = final_result
            st.session_state.waiting_for_approval = False
            st.rerun()