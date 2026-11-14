from models.llm_client import GroqLLMClient

def main():
    llm = GroqLLMClient()

    try:
        models = llm.client.models.list()

        print("\nAVAILABLE GROQ MODELS\n")

        for model in models.data:
            print(model.id)

    finally:
        llm.close()


if __name__ == "__main__":
    main()