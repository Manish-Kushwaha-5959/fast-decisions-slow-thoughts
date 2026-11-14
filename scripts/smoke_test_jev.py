from dotenv import load_dotenv
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

load_dotenv()

state = {
    "user_request": "My internet connection has stopped working. "
                    "I have restarted my router, but the problem continues.",
    "available_tools": {
        "knowledge_search": "Search the support knowledge base",
        "service_status": "Check whether an internet service is down",
        "create_ticket": "Create a technical support ticket"
    }
}

with TypeSafeClient(model="jev-latest") as client:

    response = client.system_one(
        state=state,
        questions={
            "next_tool": Choice(
                instructions="Which tool should the agent use next "
                             "to make progress on the user's request?",
                criteria={
                    "knowledge_search": "Find troubleshooting instructions",
                    "service_status": "Check for a service outage",
                    "create_ticket": "Create a support ticket"
                }
            ),

            "task_complete": Noul(
                instructions="Has the user's internet connectivity issue "
                             "been resolved based on the available state?"
            ),

            "progress": Score(
                instructions="How much progress has been made "
                             "towards resolving the issue?",
                criteria=[
                    "No progress",
                    "Some information gathered",
                    "Troubleshooting performed",
                    "Issue resolved"
                ]
            )
        }
    )

    print("\n--- JEV RESULTS ---")

    print("Selected tool:",
          response.choices["next_tool"].choice)

    print("Tool probabilities:",
          response.choices["next_tool"].probabilities)

    print("Tool confidence:",
          response.choices["next_tool"].confidence)

    print("Task completion probability:",
          response.nouls["task_complete"].noul)

    print("Progress score:",
          response.scores["progress"].score)

    print("Model:", response.model)

    print("Usage:", response.usage)
