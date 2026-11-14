from models.llm_client import GroqLLMClient, GroqClientError

def main():

    llm = GroqLLMClient()

    try:
        response = llm.generate_text(
            system_prompt=(
                "You are an AI agent assistant. "
                "Respond clearly and concisely."
            ),
            user_prompt=(
                "A customer reports that their internet "
                "connection is not working. Give a short "
                "three-step troubleshooting plan."
            )
        )

        print("\n========== GROQ TEST ==========")

        print("\nResponse:")
        print(response.content)

        print("\nModel:", response.model)
        print("Input tokens:", response.input_tokens)
        print("Output tokens:", response.output_tokens)
        print("Total tokens:", response.total_tokens)
        print("Latency:", response.latency_seconds, "seconds")
        print("Finish reason:", response.finish_reason)
        print("Request ID:", response.request_id)

        print("\n========== TEST SUCCESS ==========")

    except GroqClientError as exc:
        print("\nGROQ TEST FAILED")
        print(exc)

    finally:
        llm.close()


if __name__ == "__main__":
    main()
