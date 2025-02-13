import asyncio
from smolagents import CodeAgent
from smolagents.models import AzureOpenAIServerModel

async def main():
    # Initialize the Azure OpenAI model
    model = AzureOpenAIServerModel(
        "gpt-4o-mini",
        api_version="2024-02-15-preview",
        azure_endpoint="YOUR_AZURE_ENDPOINT",  # You'll provide this
        api_key="YOUR_API_KEY",  # You'll provide this
    )
    
    # Create the agent with the model
    agent = CodeAgent(tools=[], model=model)
    
    # Basic async execution
    result = await agent.run("What is the result of 2 power 3.7384?")
    print("Result:", result)
    
    # Streaming example
    print("\nStreaming example:")
    async for step in agent.run("Calculate the first 5 prime numbers", stream=True):
        print(f"\nStep {step.step_number}:")
        if hasattr(step, 'action_output'):
            print(f"Output: {step.action_output}")
        if hasattr(step, 'error'):
            print(f"Error: {step.error}")
        print("---")

if __name__ == "__main__":
    asyncio.run(main())