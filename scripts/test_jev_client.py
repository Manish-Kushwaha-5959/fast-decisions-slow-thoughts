from models.jev_client import JevClient, JevClientError


def main():

    state = {
        "user_request": (
            "My internet connection has stopped working. "
            "I restarted my router, but the problem continues."
        ),

        "action_history": [],

        "tool_observations": [],

        "task_status": "in_progress"
    }

    available_tools = {
        "knowledge_search": (
            "Search the support knowledge base "
            "for troubleshooting instructions."
        ),

        "service_status": (
            "Check whether the internet service "
            "is experiencing an outage."
        ),

        "create_ticket": (
            "Create a technical support ticket "
            "for the customer's issue."
        )
    }

    try:

        jev = JevClient()

        result = jev.evaluate_state(
            state=state,
            available_tools=available_tools
        )

        print("\n========== JEV CLIENT TEST ==========")

        print("\n--- Tool Selection ---")
        print("Selected tool:", result.selected_tool)
        print("Probabilities:", result.tool_probabilities)
        print("Confidence:", result.tool_confidence)

        print("\n--- Completion Detection ---")
        print(
            "Completion probability:",
            result.completion_probability
        )

        print("\n--- Loop Detection ---")
        print(
            "Loop probability:",
            result.loop_probability
        )

        print("\n--- Progress Estimation ---")
        print("Progress score:", result.progress_score)

        print("\n--- API Metadata ---")
        print("Model:", result.model)
        print("Input tokens:", result.input_tokens)
        print("Output tokens:", result.output_tokens)
        print("Total tokens:", result.total_tokens)
        print("Latency:", result.latency_seconds, "seconds")

        print("\n========== TEST SUCCESS ==========")

    except (JevClientError, ValueError) as exc:

        print("\nJEV CLIENT TEST FAILED")
        print(exc)


if __name__ == "__main__":
    main()
